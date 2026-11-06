#!/usr/bin/env python3.12
"""Registra/gestisce il subscriber webhook presso Google Health API.

Richiede un Service Account con ruolo Google Health API (Editor) sul progetto,
chiave JSON in data/fitbit/service-account.json (gitignorata).

Configurazione nel .env del repo dati (niente valori personali nel plugin):
  GOOGLE_HEALTH_PROJECT_NUMBER   numero del progetto Google Cloud
  HEALTH_WEBHOOK_URL             endpoint pubblico (es. https://<tuo-dominio>/webhook)
  HEALTH_WEBHOOK_SUBSCRIBER_ID   id del subscriber (default: wellness)
  HEALTH_WEBHOOK_SECRET          secret Bearer (legacy: LUCIA_WEBHOOK_SECRET)

Uso (cwd o WELLNESS_DATA sul repo dati):
  python3.12 register_webhook.py --create   # registra il subscriber
  python3.12 register_webhook.py --list     # elenca i subscriber
  python3.12 register_webhook.py --delete   # rimuove il subscriber

Alla --create Google fa l'handshake di verifica sull'endpoint (deve essere
già vivo e pubblico): POST con auth → 200, POST senza auth → 401.
Il receiver (webhook_receiver.py, stesso plugin) implementa entrambi.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account

import os  # noqa: E402

PROJECT_ROOT = Path(os.environ.get("WELLNESS_DATA", Path.cwd()))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from health_metrics import load_env  # noqa: E402

SA_KEY_FILE = PROJECT_ROOT / "data" / "fitbit" / "service-account.json"
# tipi che l'API supporta in push (steps e sleep sono quelli che ci servono)
DATA_TYPES = ["steps", "sleep"]
SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def settings() -> dict:
    env = load_env()
    missing = [k for k in ("GOOGLE_HEALTH_PROJECT_NUMBER", "HEALTH_WEBHOOK_URL") if not env.get(k)]
    if missing:
        sys.exit("Mancano nel .env del repo dati: " + ", ".join(missing))
    return {
        "base": f"https://health.googleapis.com/v4/projects/{env['GOOGLE_HEALTH_PROJECT_NUMBER']}/subscribers",
        "endpoint": env["HEALTH_WEBHOOK_URL"],
        "subscriber": env.get("HEALTH_WEBHOOK_SUBSCRIBER_ID", "wellness"),
        "secret": env.get("HEALTH_WEBHOOK_SECRET") or env.get("LUCIA_WEBHOOK_SECRET", ""),
    }


def sa_token() -> str:
    if not SA_KEY_FILE.exists():
        sys.exit(f"Manca {SA_KEY_FILE}.\n"
                 "Creala in Google Cloud Console: IAM → Service Accounts → crea SA\n"
                 "con ruolo 'Google Health API Editor' sul progetto, poi scarica la\n"
                 "chiave JSON e salvala lì (è gitignorata con il resto di data/fitbit/).")
    creds = service_account.Credentials.from_service_account_file(
        str(SA_KEY_FILE), scopes=[SCOPE])
    creds.refresh(GoogleRequest())
    return creds.token


def headers() -> dict:
    return {"Authorization": f"Bearer {sa_token()}",
            "Content-Type": "application/json"}


def create() -> None:
    cfg = settings()
    secret = cfg["secret"]
    if not secret:
        sys.exit("HEALTH_WEBHOOK_SECRET mancante in .env")
    body = {
        "endpointUri": cfg["endpoint"],
        "endpointAuthorization": {"secret": f"Bearer {secret}"},
        "subscriberConfigs": [
            {"dataTypes": DATA_TYPES, "subscriptionCreatePolicy": "AUTOMATIC"},
        ],
    }
    resp = requests.post(f"{cfg['base']}?subscriberId={cfg['subscriber']}",
                         headers=headers(), json=body, timeout=60)
    print(resp.status_code)
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False) if resp.text else "")
    if resp.status_code == 400 and "FAILED_PRECONDITION" in resp.text:
        print("\nFAILED_PRECONDITION = handshake di verifica fallito: controlla che\n"
              f"{cfg['endpoint']} risponda 200 con auth e 401 senza.",
              file=sys.stderr)


def list_subscribers() -> None:
    resp = requests.get(settings()["base"], headers=headers(), timeout=60)
    print(resp.status_code)
    print(json.dumps(resp.json(), indent=2, ensure_ascii=False) if resp.text else "")


def delete() -> None:
    cfg = settings()
    resp = requests.delete(f"{cfg['base']}/{cfg['subscriber']}", headers=headers(), timeout=60)
    print(resp.status_code, resp.text[:300])


def main() -> int:
    parser = argparse.ArgumentParser(description="Subscriber webhook Google Health")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--create", action="store_true")
    group.add_argument("--list", action="store_true")
    group.add_argument("--delete", action="store_true")
    args = parser.parse_args()
    if args.create:
        create()
    elif args.list:
        list_subscribers()
    else:
        delete()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
