#!/usr/bin/env python3.12
"""Google Health API → repo dati: sync giornaliero dei dati Fitbit.

Uso:
  python3.12 scripts/health_sync.py --auth                 # prima autorizzazione
  python3.12 scripts/health_sync.py --identity             # verifica connessione
  python3.12 scripts/health_sync.py                        # sync di ieri + oggi
  python3.12 scripts/health_sync.py --date 2026-07-08      # data specifica
  python3.12 scripts/health_sync.py --from 2026-07-01 --to 2026-07-08
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from health_api import AuthError, HealthClient
from health_extract import (extract_azm, extract_daily_value,
                                    extract_hr_hourly, extract_hr_intraday,
                                    extract_hr_stats, extract_sleep,
                                    extract_steps, extract_steps_intraday)

import os
BASE_DIR = Path(os.environ.get("WELLNESS_DATA", Path.cwd()))
TZ = ZoneInfo("Europe/Rome")

# tipi Daily: (chiave output, kebab, snake)
DAILY_TYPES = [
    ("hrv_rmssd", "daily-heart-rate-variability", "daily_heart_rate_variability"),
    ("spo2_avg", "daily-oxygen-saturation", "daily_oxygen_saturation"),
    ("respiratory_rate", "daily-respiratory-rate", "daily_respiratory_rate"),
    ("resting_hr", "daily-resting-heart-rate", "daily_resting_heart_rate"),
]


def day_window(date_str: str) -> tuple[str, str]:
    """[mezzanotte locale, mezzanotte successiva) in ISO con offset Europe/Rome."""
    day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ)
    return day.isoformat(), (day + timedelta(days=1)).isoformat()


def sync_date(client: HealthClient, base_dir: Path, date_str: str) -> dict:
    print(f"Sync {date_str}...")
    start, end = day_window(date_str)
    result = {"date": date_str, "synced_at": datetime.now(TZ).isoformat()}

    def try_call(label, fn):
        try:
            return fn()
        except AuthError:
            raise
        except Exception as e:
            print(f"  {label}: errore ({e})", file=sys.stderr)
            return None

    # Sonno: il tipo `sleep` è filtrabile solo su interval.end_time (Task 2
    # probe); passiamo prefer="end_time" per fissare esplicitamente questa
    # attribuzione (invece di dipendere dal fallback su 400 di start_time,
    # che se Google lo rendesse filtrabile sposterebbe silenziosamente la
    # notte attribuita). La finestra piena [giorno 00:00, giorno+1 00:00)
    # locale cattura quindi la notte che *finisce* la mattina di date_str —
    # nessuna estensione all'indietro (estenderla pescherebbe anche la notte
    # precedente).
    points = try_call("sleep", lambda: client.list_data_points(
        "sleep", "sleep", start, end, prefer="end_time"))
    sessions = extract_sleep(points or [])
    if sessions:
        result["sleep"] = sessions

    for out_key, kebab, snake in DAILY_TYPES:
        points = try_call(kebab, lambda k=kebab, s=snake: client.list_data_points(
            k, s, start, end, prefer="date"))
        value = extract_daily_value(points or [])
        if value is not None:
            result[out_key] = value

    hr_roll = try_call("heart-rate rollup", lambda: client.rollup("heart-rate", start, end, 3600))
    hourly = extract_hr_hourly(hr_roll or {})
    if hourly:
        result["heart_rate_hourly"] = hourly

    hr_daily = try_call("heart-rate daily", lambda: client.daily_rollup("heart-rate", start, end))
    stats = extract_hr_stats(hr_daily or {})
    if stats:
        result["heart_rate"] = stats

    steps_daily = try_call("steps", lambda: client.daily_rollup("steps", start, end))
    steps = extract_steps(steps_daily or {})
    if steps is not None:
        result["steps"] = steps

    # Intraday (chiavi additive, per l'insight engine): bucket 900s + AZM al minuto
    result.update(fetch_intraday(client, start, end, try_call))

    fields = [k for k in result if k not in ("date", "synced_at")]
    if not fields:
        print("  Nessun dato ricevuto: file e log non toccati")
        return result

    out_file = base_dir / "data" / "fitbit" / f"{date_str}.json"
    out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Dati: {', '.join(fields)}")
    print(f"  Salvato: {out_file}")
    return result


def fetch_intraday(client: HealthClient, start: str, end: str, try_call) -> dict:
    """Le 3 chiamate intraday: steps 900s, heart-rate 900s, AZM al minuto.

    Ritorna solo le chiavi con dati (mai None/liste vuote).
    """
    out = {}

    steps_roll = try_call("steps 900s", lambda: client.rollup("steps", start, end, 900))
    steps_intraday = extract_steps_intraday(steps_roll or {})
    if steps_intraday:
        out["steps_intraday"] = steps_intraday

    hr_roll = try_call("heart-rate 900s", lambda: client.rollup("heart-rate", start, end, 900))
    hr_intraday = extract_hr_intraday(hr_roll or {})
    if hr_intraday:
        out["heart_rate_15min"] = hr_intraday

    azm_points = try_call("active-zone-minutes", lambda: client.list_data_points(
        "active-zone-minutes", "active_zone_minutes", start, end, prefer="start_time"))
    azm = extract_azm(azm_points or [])
    if azm:
        out["azm"] = azm

    return out


def sync_intraday(client: HealthClient, base_dir: Path, date_str: str) -> dict:
    """Sync leggero per il polling diurno: SOLO chiavi intraday di oggi.

    Aggiorna il file fitbit esistente senza toccare le altre chiavi
    (sleep, daily, hourly restano quelle del sync completo delle 08:00)
    e fa il merge nel log se esiste.
    """
    print(f"Sync intraday {date_str}...")
    start, end = day_window(date_str)

    def try_call(label, fn):
        try:
            return fn()
        except AuthError:
            raise
        except Exception as e:
            print(f"  {label}: errore ({e})", file=sys.stderr)
            return None

    intraday = fetch_intraday(client, start, end, try_call)
    if not intraday:
        print("  Nessun dato intraday ricevuto: file e log non toccati")
        return {}

    out_file = base_dir / "data" / "fitbit" / f"{date_str}.json"
    if out_file.exists():
        try:
            data = json.loads(out_file.read_text())
        except json.JSONDecodeError:
            data = {"date": date_str}
    else:
        data = {"date": date_str}
    data.update(intraday)
    data["intraday_synced_at"] = datetime.now(TZ).isoformat()
    out_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Dati intraday: {', '.join(intraday)}")
    print(f"  Salvato: {out_file}")

    merge_into_log(base_dir, date_str, data)
    return data


def merge_into_log(base_dir: Path, date_str: str, fitbit_data: dict) -> bool:
    log_file = base_dir / "data" / "logs" / f"{date_str}.json"
    if not log_file.exists():
        return False
    try:
        log = json.loads(log_file.read_text())
    except json.JSONDecodeError as e:
        print(f"  Log {log_file} corrotto ({e}): merge saltato", file=sys.stderr)
        return False
    log["fitbit"] = {k: v for k, v in fitbit_data.items()
                     if k not in ("date", "synced_at", "intraday_synced_at")}
    log_file.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Mergiato in: {log_file}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Google Health API → sync repo dati")
    parser.add_argument("--auth", action="store_true")
    parser.add_argument("--identity", action="store_true")
    parser.add_argument("--date")
    parser.add_argument("--from", dest="from_date")
    parser.add_argument("--to", dest="to_date")
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--intraday", action="store_true",
                        help="sync leggero: solo steps/HR 900s + AZM di oggi (polling diurno)")
    args = parser.parse_args()

    if bool(args.from_date) != bool(args.to_date):
        parser.error("--from e --to vanno usati insieme")

    client = HealthClient(BASE_DIR)

    try:
        if args.auth:
            client.authorize()
            return
        if args.identity:
            print(json.dumps(client.get_identity(), indent=2))
            return
        if args.intraday:
            date_str = args.date or datetime.now(TZ).strftime("%Y-%m-%d")
            sync_intraday(client, BASE_DIR, date_str)
            return

        if args.from_date and args.to_date:
            cursor = datetime.strptime(args.from_date, "%Y-%m-%d")
            stop = datetime.strptime(args.to_date, "%Y-%m-%d")
            dates = []
            while cursor <= stop:
                dates.append(cursor.strftime("%Y-%m-%d"))
                cursor += timedelta(days=1)
        elif args.date:
            dates = [args.date]
        else:
            # Nessuna data specificata (caso launchd 08:00): sincronizza
            # anche ieri, non solo oggi — altrimenti steps/heart_rate di
            # ieri restano congelati ai valori parziali delle 08:00 per
            # sempre (il giorno "chiude" solo il giorno dopo).
            today = datetime.now(TZ).date()
            yesterday = today - timedelta(days=1)
            dates = [yesterday.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")]

        for date_str in dates:
            data = sync_date(client, BASE_DIR, date_str)
            has_data = any(k not in ("date", "synced_at") for k in data)
            if not args.no_merge and has_data:
                merge_into_log(BASE_DIR, date_str, data)
            print()
    except AuthError as e:
        print(f"ERRORE AUTH: {e}", file=sys.stderr)
        sys.exit(1)

    print("Sync completato.")


if __name__ == "__main__":
    main()
