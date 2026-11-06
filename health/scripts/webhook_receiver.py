#!/usr/bin/env python3.12
"""Ricevitore webhook Google Health API — l'UNICO pezzo esposto pubblicamente.

Volutamente minimale: una route, un secret, nessun accesso ai dati.
Riceve la notifica, la accoda in data/insights/webhook-inbox.jsonl e
risponde 204 subito (elaborazione asincrona nel daemon, come da docs).

Protocollo verification (creazione subscriber):
- POST {"type": "verification"} CON Authorization corretta → 200
- Stessa POST SENZA credenziali → 401 (Google verifica entrambe le vie)

Sicurezza a strati:
1. Authorization: Bearer <HEALTH_WEBHOOK_SECRET da .env> — obbligatoria
   (nome legacy accettato: LUCIA_WEBHOOK_SECRET)
2. Firma GOOGLE-HEALTH-API-SIGNATURE (Tink ECDSA P-256): registrata nel
   record per verifica; la verifica crittografica attiva è un TODO dichiarato
   (richiede il keyset gstatic + parsing Tink) — il Bearer secret è il gate.

Porta: 8791 (HEALTH_WEBHOOK_PORT), solo localhost (ci arriva solo il tunnel).
Avvio: python3.12 <plugin health>/scripts/webhook_receiver.py con cwd o
WELLNESS_DATA sul repo dati (launchd del repo dati, via shim).
Dipendenze: fastapi + uvicorn (già richieste dal ricevitore, non dal resto del plugin).
"""

from __future__ import annotations

import hmac
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response

import os  # noqa: E402

PROJECT_ROOT = Path(os.environ.get("WELLNESS_DATA", Path.cwd()))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from health_metrics import load_env  # noqa: E402

INBOX = PROJECT_ROOT / "data" / "insights" / "webhook-inbox.jsonl"
PORT = int(os.environ.get("HEALTH_WEBHOOK_PORT", "8791"))

app = FastAPI(title="Wellness Webhook Receiver", docs_url=None, redoc_url=None,
              openapi_url=None)


def _secret() -> str:
    env = load_env()
    return env.get("HEALTH_WEBHOOK_SECRET") or env.get("LUCIA_WEBHOOK_SECRET", "")


def auth_ok(auth: str | None, secret: str) -> bool:
    """Bearer a tempo costante (hmac.compare_digest): l'endpoint è pubblico via tunnel."""
    if not secret:
        return False  # senza secret configurato non si accetta nulla
    return hmac.compare_digest((auth or "").encode(), f"Bearer {secret}".encode())


def _authorized(request: Request) -> bool:
    return auth_ok(request.headers.get("authorization"), _secret())


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    if not _authorized(request):
        return Response(status_code=401)

    raw = await request.body()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return Response(status_code=400)

    # Handshake di verifica alla creazione del subscriber
    if isinstance(payload, dict) and payload.get("type") == "verification":
        return Response(status_code=200)

    # Google può mandare una notifica (oggetto) o un lotto (lista): una riga per notifica.
    # Prima le liste facevano crashare l'handler (500 → retry infiniti, notifiche perse).
    items = payload if isinstance(payload, list) else [payload]
    now = datetime.now(timezone.utc).isoformat()
    sig = request.headers.get("google-health-api-signature")
    INBOX.parent.mkdir(parents=True, exist_ok=True)
    with INBOX.open("a", encoding="utf-8") as f:
        for item in items:
            record = {"received_at": now, "signature": sig, "payload": item, "processed": False}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return Response(status_code=204)


@app.get("/webhook/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/webhook/circadian")
async def circadian(request: Request):
    """Piano circadiano per le Scorciatoie iOS (bedtime + wake). Gated dal secret."""
    if not _authorized(request):
        return Response(status_code=401)
    try:
        try:
            from circadian_plan import full_plan  # shim del repo dati, se c'è
        except ImportError:
            from _plugins import import_from
            full_plan = import_from("dream-agent", "circadian_plan").full_plan
        plan = full_plan()
        # campi piatti comodi per la Shortcut ("Get Dictionary Value")
        return {"bedtime": plan["evening"]["recommended_bedtime"],
                "wake": plan["morning"]["wake"],
                "target_wake": plan["evening"]["target_wake"],
                "evening_text": plan["evening"]["text"],
                "morning_text": plan["morning"]["text"],
                "full": plan}
    except Exception as e:
        print(f"/webhook/circadian error: {e}", file=sys.stderr)
        return Response(status_code=500)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
