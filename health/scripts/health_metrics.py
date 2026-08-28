#!/usr/bin/env python3.12
"""Utility condivise per metriche salute (engine, trends, weekly review, morning).

Punto unico di verità per:
- normalize_hrv: distingue la scala HRV4Training (1-10) dal RMSSD Fitbit (ms)
- lettura dei file fitbit giornalieri
- baseline rolling robuste (mediana, IQR, z-score)
- load_env / primary_chat_id (config .env condivisa)
"""

from __future__ import annotations

import json
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

import os
PROJECT_ROOT = Path(os.environ.get("WELLNESS_DATA", Path.cwd()))
ENV_FILE = PROJECT_ROOT / ".env"
FITBIT_DIR = PROJECT_ROOT / "data" / "fitbit"

# Sotto questa soglia un valore HRV non può essere RMSSD in ms:
# HRV4Training usa Recovery Points 1-10, il RMSSD reale di Francesco
# vive tra ~25 e ~70 ms.
HRV_SCALE_CUTOFF = 12.0


def normalize_hrv(value) -> tuple[str, float] | None:
    """Classifica un valore HRV: ("hrv4training", v) se ≤12, ("rmssd_ms", v) se >12.

    Le due scale NON vanno mai mischiate nella stessa serie.
    Ritorna None per valori non numerici o non positivi.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v <= HRV_SCALE_CUTOFF:
        return ("hrv4training", v)
    return ("rmssd_ms", v)


def rmssd_or_none(value) -> float | None:
    """Il valore solo se è RMSSD in ms (scarta la scala HRV4Training)."""
    norm = normalize_hrv(value)
    return norm[1] if norm and norm[0] == "rmssd_ms" else None


# ── file fitbit ──────────────────────────────────────────────


def load_fitbit_day(date_str: str) -> dict | None:
    f = FITBIT_DIR / f"{date_str}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def fitbit_days_back(n: int, end_date: str | None = None) -> list[dict]:
    """Gli ultimi n giorni di file fitbit fino a end_date inclusa (default oggi).

    Ordine cronologico; i giorni senza file sono semplicemente assenti.
    """
    end = date.fromisoformat(end_date) if end_date else date.today()
    days = []
    for offset in range(n - 1, -1, -1):
        d = (end - timedelta(days=offset)).isoformat()
        data = load_fitbit_day(d)
        if data is not None:
            data.setdefault("date", d)
            days.append(data)
    return days


def main_sleep_session(fitbit_day: dict | None) -> dict | None:
    """La sessione di sonno principale (la più lunga) del giorno."""
    if not fitbit_day:
        return None
    sessions = fitbit_day.get("sleep") or []
    valid = [s for s in sessions if isinstance(s, dict) and s.get("minutes_asleep")]
    if not valid:
        return None
    return max(valid, key=lambda s: s.get("minutes_asleep") or 0)


def sleep_stage_minutes(session: dict | None, stage_type: str) -> int | None:
    if not session:
        return None
    for stage in session.get("stages") or []:
        if isinstance(stage, dict) and stage.get("type") == stage_type:
            return stage.get("minutes")
    return None


# ── statistiche robuste ──────────────────────────────────────


def robust_baseline(values: list[float]) -> dict | None:
    """Mediana e IQR di una serie (min 3 valori)."""
    clean = [float(v) for v in values if isinstance(v, (int, float))]
    if len(clean) < 3:
        return None
    q = statistics.quantiles(clean, n=4, method="inclusive")
    return {"median": statistics.median(clean), "p25": q[0], "p75": q[2],
            "iqr": q[2] - q[0], "n": len(clean)}


def robust_zscore(value: float, baseline: dict | None) -> float | None:
    """Z-score robusto: (x − mediana) / (IQR · 0.7413). None se IQR nullo."""
    if baseline is None or not baseline.get("iqr"):
        return None
    return round((value - baseline["median"]) / (baseline["iqr"] * 0.7413), 2)


# ── .env condiviso ───────────────────────────────────────────


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def env_flag(env: dict[str, str], key: str) -> bool:
    return env.get(key, "false").lower() in ("1", "true", "yes")


def primary_chat_id(env: dict[str, str]) -> int | None:
    raw = env.get("ALLOWED_CHAT_IDS", "")
    for part in raw.split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            return int(part)
    return None
