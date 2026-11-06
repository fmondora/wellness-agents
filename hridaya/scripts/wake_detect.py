#!/usr/bin/env python3.12
"""Alzata rilevata sui dati al minuto (FC + passi): dove finisce il silenzio della notte.

Il vincolo che conta (anti-obiettivo del design): **mai un invio prima della fine
del sonno.** Ai risvegli notturni Francesco medita sul cuscino o va in bagno: pochi
passi, FC che sale e poi riscende. Questo non è un'alzata.

Due modi, dal più affidabile:

A. **Sessione di sonno del wearable chiusa** (`data/fitbit/<giorno>.json`): la
   sessione principale è la più lunga fra quelle che **finiscono al mattino** (fine fra
   `session_end_from`, default 04:00, e mezzogiorno). In una notte spezzata (22:30–02:45,
   veglia sul cuscino, 03:45–08:30) il primo pezzo non conta: finisce di notte.
   L'alzata è il primo minuto ≥ fine sessione (e ≥ `earliest`) da cui parte un
   **movimento sostenuto**: nei `sustain_window_min` minuti (30) almeno `sustain_steps`
   passi (40) in almeno `sustain_active_min` minuti distinti (3), con il primo e l'ultimo
   minuto attivo distanti almeno `sustain_span_min` minuti (8). Il bagno (30-40 passi in
   1-3 minuti e poi di nuovo a letto) non basta. Tarato sui 58 mattini di set-nov 2026
   del repo dati (sola lettura): mediana del ritardo dal primo passo dopo la sessione 0′;
   quando il primo passo è isolato (ci si siede a meditare) si aspetta il movimento vero,
   e al limite decide il fallback a orario. Mai prima della fine sessione.
B. **Solo dati al minuto** (la sessione non è ancora arrivata): serve
   1. un blocco quieto prima (`quiet_block_min` minuti con ≤ `quiet_max_steps` passi:
      il bagno delle 3 ci sta, una passeggiata no);
   2. movimento che dura: nei `confirm_min` minuti da lì ≥ `confirm_steps` passi in
      ≥ `confirm_active_min` minuti distinti, di cui ≥ `confirm_tail_active_min` nella
      seconda metà (il bagno finisce in 3-5 minuti, l'alzata continua);
   3. FC della conferma ≥ FC del blocco quieto + `hr_rise_bpm` (se ci sono le due FC).
   Si decide solo quando i dati coprono tutta la finestra di conferma.

In entrambi i modi: mai prima di `earliest`. Dati mancanti (orologio in carica,
sync in ritardo) → nessuna alzata: decide il fallback a orario, con rinvio se i dati
dicono che dorme ancora (`still_asleep`).

I dati al minuto vengono da `meditation_detect._fetch_minutes` del plugin health
(cache `data/fitbit/minute/<giorno>.json`); senza health si legge solo la cache.
"""
from __future__ import annotations

import json
import os
import statistics
from datetime import datetime
from pathlib import Path


def _m(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def series(minutes: dict | None) -> tuple[dict[int, float], dict[int, int]]:
    if not minutes:
        return {}, {}
    hr = {_m(k): float(v) for k, v in (minutes.get("hr") or {}).items()}
    st = {_m(k): int(v) for k, v in (minutes.get("steps") or {}).items() if v}
    return hr, st


def _steps(st: dict[int, int], a: int, b: int) -> tuple[int, int]:
    vals = [st[x] for x in range(a, b) if st.get(x)]
    return sum(vals), len(vals)


def _median(hr: dict[int, float], a: int, b: int) -> float | None:
    v = [hr[x] for x in range(a, b) if x in hr]
    return statistics.median(v) if v else None


def _last_minute(hr: dict, st: dict) -> int | None:
    keys = list(hr) + list(st)
    return max(keys) if keys else None


def detect_wake(minutes: dict | None, session: dict | None, now: datetime, cfg: dict) -> dict | None:
    """Alzata del mattino di `now` (stesso giorno dei dati al minuto) o None.

    session: sessione di sonno principale del giorno ({"start","end",...}) o None.
    cfg: la sezione `wake` del ritmo (channel_config.DEFAULTS["wake"]).
    """
    hr, st = series(minutes)
    now_m = now.hour * 60 + now.minute
    earliest = _m(cfg["earliest"])
    if now_m < earliest:
        return None
    last = _last_minute(hr, st)
    if last is None:
        return None
    horizon = min(last, now_m)

    end = None
    if session and session.get("end"):
        end = _m(session["end"])
        # sessione di stanotte = chiusa e finita entro mezzogiorno
        if end > now_m or end > 12 * 60:
            end = None
    if end is not None:
        win, span = cfg["sustain_window_min"], cfg["sustain_span_min"]
        for m in range(max(end, earliest), horizon + 1):
            if not st.get(m):
                continue
            act = [x for x in range(m, min(m + win, horizon + 1)) if st.get(x)]
            if sum(st[x] for x in act) >= cfg["sustain_steps"] and len(act) >= cfg["sustain_active_min"] \
                    and act[-1] - act[0] >= span:
                return {"at": _hhmm(m), "confirmed_at": _hhmm(act[-1]), "source": "sessione+minuto",
                        "sleep_end": session["end"]}
        return None

    q, qmax = cfg["quiet_block_min"], cfg["quiet_max_steps"]
    c = cfg["confirm_min"]
    half = c // 2
    for m in range(earliest, horizon - c + 1):
        if not st.get(m):
            continue
        quiet, _ = _steps(st, max(0, m - q), m)
        if quiet > qmax:
            continue
        # il blocco quieto deve essere coperto da dati (orologio al polso), non solo vuoto
        if _median(hr, max(0, m - q), m) is None:
            continue
        tot, active = _steps(st, m, m + c)
        _, tail = _steps(st, m + half, m + c)
        if tot < cfg["confirm_steps"] or active < cfg["confirm_active_min"] \
                or tail < cfg["confirm_tail_active_min"]:
            continue
        before, after = _median(hr, max(0, m - q), m), _median(hr, m, m + c)
        if before is not None and after is not None and after < before + cfg["hr_rise_bpm"]:
            continue
        return {"at": _hhmm(m), "confirmed_at": _hhmm(m + c), "source": "minuto"}
    return None


def still_asleep(minutes: dict | None, now: datetime, cfg: dict) -> bool:
    """Dati freschi e nessun passo da `asleep_still_min` minuti: rimanda il fallback."""
    hr, st = series(minutes)
    now_m = now.hour * 60 + now.minute
    last_hr = max(hr) if hr else None
    if last_hr is None or now_m - last_hr > cfg["asleep_fresh_min"]:
        return False   # non sappiamo: il fallback non si rimanda al buio
    tot, _ = _steps(st, now_m - cfg["asleep_still_min"], now_m + 1)
    return tot == 0


# --- dati dal repo ---------------------------------------------------------------

def _root() -> Path:
    return Path(os.environ.get("WELLNESS_DATA") or Path.cwd())


def load_minutes(day: str, fetch: bool = True) -> dict | None:
    """FC/passi al minuto: via health (_fetch_minutes, rete + cache) o solo dalla cache."""
    if fetch:
        try:
            from _plugins import import_from
            return import_from("health", "meditation_detect")._fetch_minutes(day)
        except Exception:  # noqa: BLE001 — plugin assente, rete, token: si ricade sulla cache
            pass
    f = _root() / "data" / "fitbit" / "minute" / f"{day}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main_morning_session(sessions: list, end_from: str = "04:00") -> dict | None:
    """La più lunga fra le sessioni che finiscono al mattino (fra end_from e mezzogiorno)."""
    lo, hi = _m(end_from), 12 * 60
    valid = [s for s in sessions or [] if isinstance(s, dict) and s.get("minutes_asleep") and s.get("end")
             and lo <= _m(s["end"]) <= hi]
    return max(valid, key=lambda s: s.get("minutes_asleep") or 0) if valid else None


def load_sleep_session(day: str, end_from: str = "04:00") -> dict | None:
    """Sessione di sonno principale del mattino dal file del wearable del giorno."""
    f = _root() / "data" / "fitbit" / f"{day}.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return main_morning_session(d.get("sleep") or [], end_from)
