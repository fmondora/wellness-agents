#!/usr/bin/env python3.12
"""Client Google Health API (health.googleapis.com/v4).

Solo trasporto: OAuth 2.0, refresh token, chiamate REST con paginazione.
Nessuna conoscenza del formato dei log del repo dati (vive in health_sync.py).
"""

import http.server
import json
import socket
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

import requests

API_BASE = "https://health.googleapis.com/v4/users/me"

SCOPES = [
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
]


def token_is_expired(token: dict) -> bool:
    """True se il token è scaduto o scade entro 5 minuti."""
    saved_at = token.get("saved_at")
    if not saved_at:
        return True
    age = (datetime.now() - datetime.fromisoformat(saved_at)).total_seconds()
    return age >= token.get("expires_in", 3600) - 300


class AuthError(RuntimeError):
    """Token assente/revocato: serve rieseguire --auth."""


class _OAuthHandler(http.server.BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" in params:
            _OAuthHandler.result["code"] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Autorizzazione completata. Puoi chiudere.</h2>".encode())
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, *args):
        pass


class HealthClient:
    def __init__(self, base_dir: Path):
        fitbit_dir = base_dir / "data" / "fitbit"
        self.creds_file = fitbit_dir / "credentials.json"
        self.token_file = fitbit_dir / "token.json"
        with open(self.creds_file) as f:
            self.creds = json.load(f)
        self.token = None
        if self.token_file.exists():
            with open(self.token_file) as f:
                self.token = json.load(f)

    # ── OAuth ────────────────────────────────────────────────

    def _save_token(self, token: dict):
        token["saved_at"] = datetime.now().isoformat()
        if "refresh_token" not in token and self.token:
            token["refresh_token"] = self.token.get("refresh_token")
        with open(self.token_file, "w") as f:
            json.dump(token, f, indent=2)
        self.token = token

    def authorize(self):
        """Flusso OAuth completo nel browser. Salva il token."""
        redirect = self.creds["redirect_uri"]
        port = int(urllib.parse.urlparse(redirect).port or 80)
        server = http.server.HTTPServer(("localhost", port), _OAuthHandler)
        server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()

        auth_url = self.creds["auth_uri"] + "?" + urllib.parse.urlencode({
            "client_id": self.creds["client_id"],
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        })
        print(f"Apro il browser per l'autorizzazione...\nSe non si apre: {auth_url}\n")
        webbrowser.open(auth_url)
        thread.join(timeout=180)
        server.server_close()

        code = _OAuthHandler.result.get("code")
        if not code:
            print("Timeout: nessuna autorizzazione ricevuta.", file=sys.stderr)
            sys.exit(1)

        resp = requests.post(self.creds["token_uri"], data={
            "client_id": self.creds["client_id"],
            "client_secret": self.creds["client_secret"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect,
        })
        resp.raise_for_status()
        self._save_token(resp.json())
        print(f"Token salvato in {self.token_file}")

    def _refresh(self):
        resp = requests.post(self.creds["token_uri"], data={
            "client_id": self.creds["client_id"],
            "client_secret": self.creds["client_secret"],
            "refresh_token": self.token["refresh_token"],
            "grant_type": "refresh_token",
        })
        if resp.status_code != 200:
            raise AuthError(f"Refresh fallito ({resp.status_code}): {resp.text}. Riesegui --auth")
        self._save_token(resp.json())

    def _headers(self) -> dict:
        if not self.token or "refresh_token" not in self.token:
            raise AuthError("Nessun token. Esegui prima --auth")
        if token_is_expired(self.token):
            self._refresh()
        return {"Authorization": f"Bearer {self.token['access_token']}",
                "Accept": "application/json"}

    # ── REST ─────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = requests.get(f"{API_BASE}{path}", headers=self._headers(), params=params)
        if resp.status_code == 401:
            raise AuthError(f"401 su {path}: token revocato? Riesegui --auth")
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        headers = {**self._headers(), "Content-Type": "application/json"}
        resp = requests.post(f"{API_BASE}{path}", headers=headers, json=body)
        if resp.status_code == 401:
            raise AuthError(f"401 su {path}: token revocato? Riesegui --auth")
        resp.raise_for_status()
        return resp.json()

    def get_identity(self) -> dict:
        return self._get("/identity")

    def list_data_points(self, kebab: str, snake: str,
                         start_iso: str, end_iso: str,
                         prefer: str | None = None) -> list[dict]:
        """Tutti i dataPoints di un tipo nel range [start, end).

        Ogni data type espone un solo membro filtrabile: prova in sequenza
        `interval.start_time`, `interval.end_time` (sleep: solo end_time è
        filtrabile), poi `date` (tipi Daily); su 400 passa al successivo.

        `prefer` (es. "end_time", "date") sposta in testa alla sequenza il
        filtro corrispondente, mantenendo gli altri come fallback — utile
        quando sappiamo già quale membro è filtrabile e vogliamo evitare
        round-trip a vuoto (400) o blindare l'attribuzione (es. sleep) contro
        futuri cambi lato Google.
        """
        filters_by_key = {
            "start_time": (
                f'{snake}.interval.start_time >= "{start_iso}" AND '
                f'{snake}.interval.start_time < "{end_iso}"'
            ),
            "end_time": (
                f'{snake}.interval.end_time >= "{start_iso}" AND '
                f'{snake}.interval.end_time < "{end_iso}"'
            ),
            "date": (
                f'{snake}.date >= "{start_iso[:10]}" AND {snake}.date < "{end_iso[:10]}"'
            ),
        }
        order = ["start_time", "end_time", "date"]
        if prefer and prefer in filters_by_key:
            order = [prefer] + [k for k in order if k != prefer]
        filters = [filters_by_key[k] for k in order]
        last_error = None
        for flt in filters:
            try:
                return self._list_all_pages(kebab, flt)
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 400:
                    last_error = e
                    continue
                raise
        raise last_error

    def _list_all_pages(self, kebab: str, flt: str) -> list[dict]:
        points, page_token = [], None
        while True:
            params = {"filter": flt, "pageSize": 500}
            if page_token:
                params["pageToken"] = page_token
            data = self._get(f"/dataTypes/{kebab}/dataPoints", params)
            points.extend(data.get("dataPoints", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                return points

    def rollup(self, kebab: str, start_iso: str, end_iso: str,
               window_seconds: int) -> dict:
        return self._post(f"/dataTypes/{kebab}/dataPoints:rollUp", {
            "range": {"startTime": start_iso, "endTime": end_iso},
            "windowSize": f"{window_seconds}s",
        })

    def daily_rollup(self, kebab: str, start_iso: str, end_iso: str) -> dict:
        """Rollup giornaliero: il range è CivilDateTime {"date": {year, month, day}},
        non timestamp (closed-open sui giorni)."""
        def civil(iso: str) -> dict:
            y, m, d = iso[:10].split("-")
            return {"date": {"year": int(y), "month": int(m), "day": int(d)}}
        return self._post(f"/dataTypes/{kebab}/dataPoints:dailyRollUp", {
            "range": {"start": civil(start_iso), "end": civil(end_iso)},
        })
