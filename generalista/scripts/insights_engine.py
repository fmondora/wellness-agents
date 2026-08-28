#!/usr/bin/env python3.12
"""Insight engine — il detector deterministico della pipeline responsiva.

Regole su dati Fitbit intraday/giornalieri → eventi → notifiche Telegram
(outbox) con dedup, quiet hours e budget. Nessun LLM: testi template.
Le soglie vivono in config/insights.json, mai qui.

Uso:
  python3.12 scripts/insights_engine.py                       # valuta oggi e notifica
  python3.12 scripts/insights_engine.py --date X --dry-run    # valuta senza scrivere
  python3.12 scripts/insights_engine.py --replay --from A --to B   # backtest storico
  python3.12 scripts/insights_engine.py --emit-test long_walk # evento finto end-to-end

Nel daemon: insights_tick(env) — sync intraday ogni N min + valutazione.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import os
PROJECT_ROOT = Path(os.environ.get("WELLNESS_DATA", Path.cwd()))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from health_metrics import (env_flag, fitbit_days_back, load_env,  # noqa: E402
                            load_fitbit_day, main_sleep_session,
                            primary_chat_id, rmssd_or_none, robust_baseline,
                            robust_zscore, sleep_stage_minutes)
from telegram_queue import write_reply  # noqa: E402

TZ = ZoneInfo("Europe/Rome")
CONFIG_FILE = PROJECT_ROOT / "config" / "insights.json"
STATE_FILE = PROJECT_ROOT / "data" / "insights" / "state.json"
EVENTS_DIR = PROJECT_ROOT / "data" / "insights" / "events"

BUCKET_MIN = 15  # granularità intraday (900s)


# ── config / stato / eventi ─────────────────────────────────


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                          encoding="utf-8")


def events_file(date_str: str) -> Path:
    return EVENTS_DIR / f"{date_str}.jsonl"


def load_events(date_str: str) -> list[dict]:
    f = events_file(date_str)
    if not f.exists():
        return []
    rows = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_events(date_str: str, events: list[dict]) -> None:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    with events_file(date_str).open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def append_event(date_str: str, event: dict) -> None:
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    with events_file(date_str).open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ── helpers tempo ────────────────────────────────────────────


def _hhmm_to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _min_to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _now() -> datetime:
    return datetime.now(TZ)


def _in_quiet_hours(cfg: dict, now: datetime) -> bool:
    quiet = cfg.get("quiet_hours") or {}
    start, end = quiet.get("start", "21:00"), quiet.get("end", "07:00")
    hhmm = now.strftime("%H:%M")
    if start <= end:
        return start <= hhmm < end
    return hhmm >= start or hhmm < end  # finestra a cavallo di mezzanotte


def _in_shadow(cfg: dict, now: datetime) -> bool:
    until = cfg.get("shadow_until")
    return bool(until) and now.strftime("%Y-%m-%d") <= until


# ── regole ───────────────────────────────────────────────────
# Ogni detect_* ritorna una lista di eventi candidati (dict).
# `now=None` (replay) salta i check "l'attività è finita?".


def _sequences(buckets: list[dict], active_steps: int, max_gap: int) -> list[list[dict]]:
    """Raggruppa i bucket attivi in sequenze tollerando gap ≤ max_gap bucket."""
    active = [b for b in buckets if b.get("steps", 0) >= active_steps]
    sequences: list[list[dict]] = []
    for b in sorted(active, key=lambda x: _hhmm_to_min(x["time"])):
        if sequences:
            last = sequences[-1][-1]
            gap = (_hhmm_to_min(b["time"]) - _hhmm_to_min(last["time"])) // BUCKET_MIN - 1
            if gap <= max_gap:
                sequences[-1].append(b)
                continue
        sequences.append([b])
    return sequences


def detect_long_walk(fitbit: dict, cfg: dict, date_str: str,
                     now: datetime | None) -> list[dict]:
    rule = cfg["rules"]["long_walk"]
    if not rule.get("enabled"):
        return []
    buckets = (fitbit or {}).get("steps_intraday") or []
    if not buckets:
        return []
    all_buckets_by_min = {_hhmm_to_min(b["time"]): b.get("steps", 0) for b in buckets}

    events = []
    for seq in _sequences(buckets, rule["bucket_active_steps"], rule["max_gap_buckets"]):
        start_min = _hhmm_to_min(seq[0]["time"])
        end_min = _hhmm_to_min(seq[-1]["time"]) + BUCKET_MIN
        duration = end_min - start_min
        # passi totali nella finestra (inclusi i bucket sotto soglia dentro i gap)
        total = sum(v for m, v in all_buckets_by_min.items() if start_min <= m < end_min)
        if duration < rule["min_duration_min"] or total < rule["min_total_steps"]:
            continue
        # fire solo a camminata finita: ora ≥ fine + 2 bucket
        if now is not None and now.strftime("%Y-%m-%d") == date_str:
            now_min = now.hour * 60 + now.minute
            if now_min < end_min + 2 * BUCKET_MIN:
                continue
        start_h, end_h = _min_to_hhmm(start_min), _min_to_hhmm(end_min)
        hours, mins = duration // 60, duration % 60
        dur_txt = (f"{hours}h{mins:02d}" if hours else f"{mins} min")
        events.append({
            "id": f"long_walk-{date_str}-{start_h.replace(':', '')}",
            "rule": "long_walk",
            "date": date_str,
            "severity": "info",
            "deliver": rule["deliver"],
            "data": {"start": start_h, "end": end_h,
                     "duration_min": duration, "steps": total},
            "message": (f"🚶 Ho visto ~{dur_txt} di camminata "
                        f"({total} passi, {start_h}–{end_h}). Com'era? Dove sei andato?"),
            "question": "Com'era la camminata? Dove sei andato?" if rule.get("ask") else None,
            "log_target": rule.get("log_target"),
        })
    return events


def detect_intense_session(fitbit: dict, cfg: dict, date_str: str,
                           now: datetime | None) -> list[dict]:
    rule = cfg["rules"]["intense_session"]
    if not rule.get("enabled"):
        return []
    hr_buckets = (fitbit or {}).get("heart_rate_15min") or []
    if not hr_buckets:
        return []
    steps_by_min = {_hhmm_to_min(b["time"]): b.get("steps", 0)
                    for b in (fitbit or {}).get("steps_intraday") or []}
    azm = (fitbit or {}).get("azm") or []

    hr_sorted = sorted(hr_buckets, key=lambda b: _hhmm_to_min(b["time"]))
    events, run = [], []

    def close_run(run: list[dict], next_bucket: dict | None):
        if len(run) < rule["min_buckets"]:
            return
        start_min = _hhmm_to_min(run[0]["time"])
        end_min = _hhmm_to_min(run[-1]["time"]) + BUCKET_MIN
        duration = end_min - start_min
        if duration > rule["max_duration_min"]:
            return
        peak_avg = max(b["avg"] for b in run)
        peak_max = max((b.get("max") or 0) for b in run)
        if peak_avg < rule["hr_peak_bucket"] and peak_max < rule["hr_max_bucket"]:
            return
        steps_in = sum(v for m, v in steps_by_min.items() if start_min <= m < end_min)
        if steps_in >= rule["max_steps_in_window"]:
            return
        # sessione "finita": FC rientrata o siamo oltre la finestra
        if now is not None and now.strftime("%Y-%m-%d") == date_str:
            now_min = now.hour * 60 + now.minute
            recovered = next_bucket is not None and next_bucket["avg"] < rule["end_below_hr"]
            if not recovered and now_min < end_min + 2 * BUCKET_MIN:
                return
        azm_intense = sum(z.get("minutes", 1) for z in azm
                          if z.get("zone") in ("CARDIO", "PEAK")
                          and start_min <= _hhmm_to_min(z["time"]) < end_min)
        start_h, end_h = _min_to_hhmm(start_min), _min_to_hhmm(end_min)
        azm_txt = f", {azm_intense} min in zona cardio/peak" if azm_intense else ""
        events.append({
            "id": f"intense-{date_str}-{start_h.replace(':', '')}",
            "rule": "intense_session",
            "date": date_str,
            "severity": "info",
            "deliver": rule["deliver"],
            "data": {"start": start_h, "end": end_h, "duration_min": duration,
                     "hr_avg_peak": peak_avg, "hr_max": peak_max or None,
                     "steps_in_window": steps_in, "azm_intense_min": azm_intense},
            "message": (f"🏋️ FC media fino a {peak_avg:.0f}"
                        + (f" (picco {peak_max:.0f})" if peak_max else "")
                        + f" tra le {start_h} e le {end_h} con pochi passi{azm_txt} — "
                          "CrossFit? Com'è andata?"),
            "question": "Sessione intensa rilevata: cos'era e com'è andata?" if rule.get("ask") else None,
            "log_target": rule.get("log_target"),
        })

    for b in hr_sorted:
        if b.get("avg", 0) >= rule["hr_avg_bucket"] and (
                not run or _hhmm_to_min(b["time"]) - _hhmm_to_min(run[-1]["time"]) == BUCKET_MIN):
            run.append(b)
        else:
            if run:
                close_run(run, b)
            run = [b] if b.get("avg", 0) >= rule["hr_avg_bucket"] else []
    if run:
        close_run(run, None)
    return events


def detect_hrv(cfg: dict, date_str: str) -> list[dict]:
    """hrv_low (semaforo) + hrv_two_mornings. Delivery: morning."""
    events = []
    rule = cfg["rules"]["hrv_low"]
    today = load_fitbit_day(date_str)
    rmssd = rmssd_or_none((today or {}).get("hrv_rmssd"))
    if rule.get("enabled") and rmssd is not None and rmssd < rule["rmssd_full"]:
        zone = "recupero" if rmssd < rule["rmssd_recovery"] else "zona2"
        msg = (f"⚠️ HRV {rmssd:.1f} — sotto {rule['rmssd_recovery']}: oggi recupero attivo, niente intensità."
               if zone == "recupero" else
               f"🟡 HRV {rmssd:.1f} — fascia {rule['rmssd_recovery']}–{rule['rmssd_full']}: ok zona 2/camminata, non di più.")
        events.append({
            "id": f"hrv_low-{date_str}",
            "rule": "hrv_low", "date": date_str,
            "severity": "warn" if zone == "recupero" else "info",
            "deliver": rule["deliver"],
            "data": {"rmssd": rmssd, "zone": zone},
            "message": msg,
        })

    rule2 = cfg["rules"]["hrv_two_mornings"]
    if rule2.get("enabled"):
        days = fitbit_days_back(rule2["consecutive"], date_str)
        vals = [rmssd_or_none(d.get("hrv_rmssd")) for d in days]
        if (len(vals) == rule2["consecutive"]
                and all(v is not None and v < rule2["rmssd_threshold"] for v in vals)):
            serie = " → ".join(f"{v:.1f}" for v in vals)
            events.append({
                "id": f"hrv_two_mornings-{date_str}",
                "rule": "hrv_two_mornings", "date": date_str,
                "severity": "high",
                "deliver": rule2["deliver"],
                "data": {"values": vals},
                "message": (f"🔴 Seconda mattina consecutiva con HRV sotto "
                            f"{rule2['rmssd_threshold']} ({serie}): il semaforo del council "
                            "prescrive riposo — oggi niente allenamento, sauna ok."),
            })
    return events


def detect_sleep(cfg: dict, date_str: str) -> list[dict]:
    """sleep_critical (immediate) + sleep_anomaly (morning) sulla notte di date_str."""
    events = []
    today = load_fitbit_day(date_str)
    session = main_sleep_session(today)
    if not session:
        return events
    asleep = session.get("minutes_asleep") or 0

    crit = cfg["rules"]["sleep_critical"]
    if crit.get("enabled") and asleep < crit["min_asleep_min"]:
        events.append({
            "id": f"sleep_critical-{date_str}",
            "rule": "sleep_critical", "date": date_str,
            "severity": "high", "deliver": crit["deliver"],
            "data": {"minutes_asleep": asleep},
            "message": (f"🔴 Stanotte solo {asleep // 60}h{asleep % 60:02d} di sonno: "
                        "giornata da tenere bassa, recupero stasera."),
        })
        return events  # la critical assorbe l'anomaly

    rule = cfg["rules"]["sleep_anomaly"]
    if not rule.get("enabled"):
        return events
    awake = sleep_stage_minutes(session, "AWAKE")
    deep = sleep_stage_minutes(session, "DEEP")
    history = fitbit_days_back(8, date_str)[:-1]  # 7 giorni precedenti
    baseline = robust_baseline([
        (main_sleep_session(d) or {}).get("minutes_asleep")
        for d in history
        if main_sleep_session(d)])
    z = robust_zscore(asleep, baseline) if baseline else None

    reasons = []
    if asleep < rule["min_asleep_min"]:
        reasons.append(f"corta ({asleep // 60}h{asleep % 60:02d})")
    if awake is not None and awake >= rule["max_awake_min"]:
        reasons.append(f"frammentata ({awake} min svegli)")
    if deep is not None and deep < rule["min_deep_min"]:
        reasons.append(f"poco sonno profondo ({deep} min)")
    if z is not None and z < rule["zscore_vs_7d"]:
        reasons.append(f"molto sotto la tua media 7gg (z={z})")
    if reasons:
        events.append({
            "id": f"sleep_anomaly-{date_str}",
            "rule": "sleep_anomaly", "date": date_str,
            "severity": "warn", "deliver": rule["deliver"],
            "data": {"minutes_asleep": asleep, "awake": awake, "deep": deep, "z": z},
            "message": "😴 Notte " + ", ".join(reasons) + ".",
        })
    return events


def detect_streak_positive(cfg: dict, date_str: str, state: dict) -> list[dict]:
    rule = cfg["rules"]["streak_positive"]
    if not rule.get("enabled"):
        return []
    cooldowns = state.get("streak_cooldowns") or {}
    last = cooldowns.get("streak_positive")
    if last:
        elapsed = (date.fromisoformat(date_str) - date.fromisoformat(last)).days
        if elapsed < rule["cooldown_days"]:
            return []

    days = fitbit_days_back(rule["days"], date_str)
    rmssd_vals = [rmssd_or_none(d.get("hrv_rmssd")) for d in days]
    hrv_streak = (len(rmssd_vals) == rule["days"]
                  and all(v is not None and v >= rule["rmssd_good"] for v in rmssd_vals))

    week = fitbit_days_back(7, date_str)
    steps_vals = [d.get("steps") for d in week if isinstance(d.get("steps"), (int, float))]
    steps_streak = (len(steps_vals) >= 5
                    and sum(steps_vals) / len(steps_vals) >= rule["steps_avg_7d"])

    if not (hrv_streak or steps_streak):
        return []
    if hrv_streak:
        serie = " · ".join(f"{v:.0f}" for v in rmssd_vals)
        msg = (f"🟢 {rule['days']} mattine di fila con HRV ≥{rule['rmssd_good']} ({serie}): "
               "il sistema sta rispondendo. Continua così, senza strafare.")
    else:
        avg = sum(steps_vals) / len(steps_vals)
        msg = (f"🟢 Media di {avg:,.0f} passi al giorno nell'ultima settimana: "
               "il movimento è tornato una costante.")
    return [{
        "id": f"streak_positive-{date_str}",
        "rule": "streak_positive", "date": date_str,
        "severity": "info", "deliver": rule["deliver"],
        "data": {"hrv": rmssd_vals if hrv_streak else None,
                 "steps_avg": (sum(steps_vals) / len(steps_vals)) if steps_vals else None},
        "message": msg,
    }]


def evaluate(date_str: str, cfg: dict, state: dict,
             now: datetime | None) -> list[dict]:
    """Tutte le regole su un giorno → eventi candidati (senza dedup/delivery)."""
    fitbit = load_fitbit_day(date_str) or {}
    events = []
    events += detect_long_walk(fitbit, cfg, date_str, now)
    events += detect_intense_session(fitbit, cfg, date_str, now)
    events += detect_hrv(cfg, date_str)
    events += detect_sleep(cfg, date_str)
    events += detect_streak_positive(cfg, date_str, state)
    return events


# ── delivery: UNICO punto di scrittura outbox ────────────────


def _already_emitted(event_id: str, date_str: str, state: dict) -> bool:
    if event_id in (state.get("emitted_ids") or {}):
        return True
    return any(e.get("id") == event_id for e in load_events(date_str))


def _prune_emitted(state: dict, keep_days: int = 14) -> None:
    emitted = state.get("emitted_ids") or {}
    cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
    state["emitted_ids"] = {k: v for k, v in emitted.items() if v >= cutoff}


def process_events(events: list[dict], cfg: dict, state: dict,
                   now: datetime | None = None, dry_run: bool = False) -> list[dict]:
    """Dedup → registrazione jsonl → eventuale notifica immediata.

    Guardie hard (budget, quiet hours, shadow) applicate QUI, qualunque
    sia la regola chiamante. Gli eventi `morning` restano nel jsonl con
    delivered=false: li consegna morning_message.
    """
    now = now or _now()
    env = load_env()
    chat_id = primary_chat_id(env)
    today = now.strftime("%Y-%m-%d")

    notified = state.get("notified_today") or {}
    if notified.get("date") != today:
        notified = {"date": today, "count": 0}

    processed = []
    for event in events:
        if _already_emitted(event["id"], event["date"], state):
            continue

        deliver = event.get("deliver", "morning")
        requalified = None
        if deliver == "immediate":
            if _in_shadow(cfg, now):
                deliver, requalified = "morning", "shadow"
            elif _in_quiet_hours(cfg, now):
                deliver, requalified = "morning", "quiet_hours"
            elif notified["count"] >= cfg.get("daily_budget", 3):
                deliver, requalified = "morning", "budget"

        event = {**event,
                 "ts": now.isoformat(),
                 "deliver": deliver,
                 "requalified": requalified,
                 "delivered": False,
                 "delivered_at": None}

        if deliver == "immediate" and not dry_run:
            if chat_id:
                text = event["message"]
                write_reply(f"insight-{event['id']}", chat_id, text)
                event["delivered"] = True
                event["delivered_at"] = now.isoformat()
                notified["count"] += 1
                if event.get("question") and event.get("log_target"):
                    questions = state.setdefault("open_questions", [])
                    questions.append({
                        "event_id": event["id"],
                        "rule": event["rule"],
                        "question": event["question"],
                        "log_target": event["log_target"],
                        "asked_at": now.isoformat(),
                        "chat_id": chat_id,
                    })
            else:
                print("  ALLOWED_CHAT_IDS mancante: notifica saltata", file=sys.stderr)

        if not dry_run:
            append_event(event["date"], event)
            state.setdefault("emitted_ids", {})[event["id"]] = event["date"]
        processed.append(event)

    if not dry_run:
        state["notified_today"] = notified
        _prune_emitted(state)
        save_state(state)
    return processed


# ── goals tracking automatico ────────────────────────────────


def fill_goals_tracking(date_str: str) -> int:
    """Compila goals_tracking nel log di date_str per i goal auto_detect.

    Merge non distruttivo: non tocca entry manuali né entry auto già presenti.
    Se il log non esiste ne crea uno minimo (solo date + goals_tracking):
    il /log conversazionale ci si fonde sopra senza conflitti.
    Ritorna il numero di entry aggiunte.
    """
    goals_file = PROJECT_ROOT / "data" / "active-goals.json"
    if not goals_file.exists():
        return 0
    try:
        goals = json.loads(goals_file.read_text(encoding="utf-8")).get("goals", [])
    except json.JSONDecodeError:
        return 0

    fitbit = load_fitbit_day(date_str)
    events = load_events(date_str)
    entries = []
    for goal in goals:
        if goal.get("status") != "active" or not goal.get("auto_detect"):
            continue
        metric = goal.get("metric")
        value, met = None, None
        if metric == "steps_daily":
            value = (fitbit or {}).get("steps")
            met = value is not None and value >= goal.get("target_value", 0)
        elif metric == "minutes_asleep":
            session = main_sleep_session(fitbit)
            value = (session or {}).get("minutes_asleep")
            met = value is not None and value >= goal.get("target_value", 0)
        elif goal.get("auto_detect") == "intense_session":
            hits = [e for e in events if e.get("rule") == "intense_session"]
            if not hits:
                continue  # nessuna sessione = nessuna entry (l'adherence è settimanale)
            value, met = len(hits), True
        if value is None:
            continue
        entries.append({"goal_id": goal["id"], "date": date_str,
                        "value": value, "met": bool(met), "source": "auto"})

    if not entries:
        return 0

    log_file = PROJECT_ROOT / "data" / "logs" / f"{date_str}.json"
    if log_file.exists():
        try:
            log = json.loads(log_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0
    else:
        log = {"date": date_str,
               "notes": "[insights-engine] log creato per goals_tracking"}

    tracking = log.setdefault("goals_tracking", [])
    existing = {(e.get("goal_id"), e.get("source")) for e in tracking
                if isinstance(e, dict)}
    added = 0
    for entry in entries:
        if (entry["goal_id"], "auto") in existing:
            continue
        tracking.append(entry)
        added += 1
    if added:
        log_file.write_text(json.dumps(log, indent=2, ensure_ascii=False),
                            encoding="utf-8")
    return added


# ── webhook inbox (push da Google Health via webhook_receiver) ──


WEBHOOK_INBOX = PROJECT_ROOT / "data" / "insights" / "webhook-inbox.jsonl"


def consume_webhook_inbox() -> set[str]:
    """Legge le notifiche push non processate, le marca, ritorna i dataType.

    Un dataType nuovo (es. steps, sleep) = i dati sono cambiati ADESSO:
    il tick che ci chiama bypassa il throttle e sincronizza subito.
    """
    if not WEBHOOK_INBOX.exists():
        return set()
    rows, dirty, types = [], False, set()
    for line in WEBHOOK_INBOX.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not row.get("processed"):
            dt = ((row.get("payload") or {}).get("data") or {}).get("dataType")
            if dt:
                types.add(dt)
            row["processed"] = True
            dirty = True
        rows.append(row)
    if dirty:
        with WEBHOOK_INBOX.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return types


# ── daemon hook ──────────────────────────────────────────────


def _minutes_since(state: dict, key: str, now: datetime) -> float:
    raw = state.get(key)
    if not raw:
        return float("inf")
    try:
        prev = datetime.fromisoformat(raw)
    except ValueError:
        return float("inf")
    return (now - prev).total_seconds() / 60


def insights_tick(env: dict[str, str] | None = None) -> None:
    """Chiamata dal daemon a ogni tick: si auto-throttla via stato."""
    env = env or load_env()
    if not env_flag(env, "LUCIA_INSIGHTS"):
        return
    cfg = load_config()
    state = load_state()
    now = _now()
    today = now.strftime("%Y-%m-%d")
    hhmm = now.strftime("%H:%M")

    # Push ricevuti: consumati SEMPRE, anche fuori dalla finestra attiva —
    # un push 'sleep' all'alba deve poter far partire il buongiorno.
    pushed = consume_webhook_inbox()
    if pushed:
        print(f"insights: push webhook per {', '.join(sorted(pushed))}")
        state["last_intraday_sync"] = None  # forza il sync al prossimo giro in-window
        state["last_eval"] = None
        save_state(state)

    # Buongiorno guidato dal push del sonno. Un push 'sleep' (a QUALSIASI ora)
    # marca il buongiorno come 'dovuto' per oggi; poi parte al primo tick dopo
    # 'earliest'. Così un push delle 03:58 non viene sprecato: viene tenuto e
    # consegnato alle 05:30. Il launchd 07:30 resta come fallback se il push non
    # arriva mai (guardia morning_sent condivisa → chi parte primo vince).
    mp = cfg.get("morning_push") or {}
    if mp.get("enabled") and mp.get("trigger_on", "sleep") in pushed:
        state["morning_pending"] = today
        save_state(state)
    if (mp.get("enabled") and state.get("morning_pending") == today
            and hhmm >= mp.get("earliest", "05:30")
            and state.get("morning_sent") != today):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "morning_message.py"),
             "--trigger", "push"],
            capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"insights: buongiorno da push fallito: {result.stderr[-300:]}", file=sys.stderr)
        else:
            print("insights: buongiorno inviato (trigger push, sonno chiuso)")
        state = load_state()  # morning_message ha scritto morning_sent
        state.pop("morning_pending", None)
        save_state(state)

    window = cfg.get("active_window") or {}
    if not (window.get("start", "07:00") <= hhmm < window.get("end", "21:00")):
        return

    if _minutes_since(state, "last_intraday_sync", now) >= cfg.get("intraday_sync_minutes", 30):
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "health_sync.py"), "--intraday"],
            capture_output=True, text=True, timeout=180)
        if result.returncode != 0:
            print(f"insights: sync intraday fallito: {result.stderr[-300:]}", file=sys.stderr)
        state["last_intraday_sync"] = now.isoformat()
        save_state(state)

    # trends + goals di ieri: una volta al giorno, dopo il sync completo delle 08:00
    if state.get("trends_generated") != today and hhmm >= "08:15":
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "trends.py")],
            capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            state["trends_generated"] = today
            save_state(state)
        else:
            print(f"insights: trends falliti: {result.stderr[-200:]}", file=sys.stderr)
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            # non fidarsi del launchd delle 08:00 (Mac in sleep → job saltato):
            # ieri va chiuso con dati definitivi prima di compilare i goal
            fitbit_yesterday = load_fitbit_day(yesterday) or {}
            if fitbit_yesterday.get("synced_at", "") < f"{today}T":
                subprocess.run(
                    [sys.executable, str(PROJECT_ROOT / "scripts" / "health_sync.py"),
                     "--date", yesterday],
                    capture_output=True, text=True, timeout=300)
            added = fill_goals_tracking(yesterday)
            if added:
                print(f"insights: goals_tracking {yesterday}: +{added} entry")
        except Exception as e:
            print(f"insights: goals_tracking fallito: {e}", file=sys.stderr)

    # Nudge serale dell'ora di letto (una volta al giorno, dopo evening_nudge_time)
    circ = cfg.get("circadian") or {}
    nudge_time = circ.get("evening_nudge_time", "21:00")
    if state.get("circadian_nudge_sent") != today and hhmm >= nudge_time:
        try:
            from circadian_plan import evening_plan
            chat_id = primary_chat_id(env)
            if chat_id:
                write_reply(f"bedtime-{today}", chat_id, evening_plan(circ)["text"])
                print("insights: nudge serale ora di letto inviato")
        except Exception as e:
            print(f"insights: nudge serale fallito: {e}", file=sys.stderr)
        state["circadian_nudge_sent"] = today
        save_state(state)

    if _minutes_since(state, "last_eval", now) >= cfg.get("eval_minutes", 15):
        events = evaluate(today, cfg, state, now)
        processed = process_events(events, cfg, state, now)  # salva lo stato internamente
        state["last_eval"] = now.isoformat()
        save_state(state)
        if processed:
            print(f"insights: {len(processed)} eventi ({', '.join(e['rule'] for e in processed)})")


# ── CLI ──────────────────────────────────────────────────────


TEST_EVENTS = {
    "long_walk": {
        "rule": "long_walk", "severity": "info", "deliver": "immediate",
        "data": {"start": "15:00", "end": "17:30", "duration_min": 150, "steps": 12000},
        "message": "🚶 [TEST] Ho visto ~2h30 di camminata (12000 passi, 15:00–17:30). Com'era?",
        "question": "Com'era la camminata? Dove sei andato?",
        "log_target": "movement.walk_note",
    },
    "intense_session": {
        "rule": "intense_session", "severity": "info", "deliver": "immediate",
        "data": {"start": "09:00", "end": "10:00", "hr_avg_peak": 132},
        "message": "🏋️ [TEST] FC media 132 tra le 09:00 e le 10:00 con pochi passi — CrossFit?",
        "question": "Sessione intensa rilevata: cos'era e com'è andata?",
        "log_target": "movement.intense_note",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Insight engine Lucia")
    parser.add_argument("--date", default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="valuta e stampa, senza scrivere eventi/outbox/stato")
    parser.add_argument("--replay", action="store_true",
                        help="backtest: ignora i check 'attività finita' (implica --dry-run se non --write)")
    parser.add_argument("--from", dest="from_date")
    parser.add_argument("--to", dest="to_date")
    parser.add_argument("--write", action="store_true",
                        help="col replay: scrivi comunque gli eventi (mai l'outbox)")
    parser.add_argument("--emit-test", choices=sorted(TEST_EVENTS),
                        help="genera un evento finto e passalo alla delivery reale")
    args = parser.parse_args()

    cfg = load_config()
    state = load_state()
    now = _now()

    if args.emit_test:
        today = now.strftime("%Y-%m-%d")
        event = {**TEST_EVENTS[args.emit_test],
                 "id": f"test-{args.emit_test}-{now.strftime('%H%M%S')}",
                 "date": today}
        # il test bypassa la shadow mode (serve per verificare la delivery)
        cfg = {**cfg, "shadow_until": None}
        processed = process_events([event], cfg, state, now, dry_run=args.dry_run)
        for e in processed:
            print(json.dumps(e, indent=2, ensure_ascii=False))
        return 0

    if args.replay:
        if not (args.from_date and args.to_date):
            parser.error("--replay richiede --from e --to")
        cursor = date.fromisoformat(args.from_date)
        stop = date.fromisoformat(args.to_date)
        dry = not args.write
        total = 0
        while cursor <= stop:
            d = cursor.isoformat()
            events = evaluate(d, cfg, state, now=None)
            for e in events:
                total += 1
                flag = "" if not _already_emitted(e["id"], d, state) else " (già emesso)"
                print(f"{d}  {e['rule']:18s} {e['id']}{flag}")
                print(f"      {e['message']}")
            if args.write and events:
                # registra senza notificare (replay non tocca mai l'outbox)
                for e in events:
                    if not _already_emitted(e["id"], d, state):
                        append_event(d, {**e, "ts": now.isoformat(),
                                         "delivered": False, "delivered_at": None,
                                         "requalified": "replay"})
                        state.setdefault("emitted_ids", {})[e["id"]] = d
                save_state(state)
            cursor += timedelta(days=1)
        print(f"\nTotale eventi: {total}" + (" (dry-run, nulla scritto)" if dry else ""))
        return 0

    date_str = args.date or now.strftime("%Y-%m-%d")
    events = evaluate(date_str, cfg, state, now if not args.date else None)
    processed = process_events(events, cfg, state, now, dry_run=args.dry_run)
    for e in processed:
        status = "→ inviato" if e.get("delivered") else f"→ {e.get('deliver')}" + (
            f" ({e['requalified']})" if e.get("requalified") else "")
        print(f"{e['rule']:18s} {e['id']}  {status}")
        print(f"   {e['message']}")
    if not processed:
        print("Nessun evento nuovo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
