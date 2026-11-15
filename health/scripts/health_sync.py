#!/usr/bin/env python3.12
"""Google Health API → repo dati: sync giornaliero dei dati Fitbit.

Per giorno, in data/fitbit/YYYY-MM-DD.json (e nel diario, chiave `fitbit`): sonno, HRV, SpO2, respiro,
FC a riposo, temperatura cutanea, peso e massa grassa (se una bilancia li scrive), FC oraria e per
zone, passi, AZM, intraday; e dal 15/11/2026 calorie (totali, attive, a riposo, per zona di FC),
distanza, piani, minuti attivi per livello, minuti sedentari, minuti per zona e soglie delle zone,
allenamenti (tipo, orari, kcal, FC media), HRV della notte a campioni, ossigeno della notte
(minimo, mediana, campioni sotto 90/88%), respiro per fase del sonno, VO2 max e altezza se presenti.
Cibo, acqua, ECG chiedono permessi in più (nutrition, ecg): non sono negli SCOPES di health_api.

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
                                    extract_steps, extract_steps_intraday,
                                    extract_body, extract_sleep_temperature,
                            extract_active_minutes, extract_calories, extract_count, extract_distance_km,
                            extract_exercises, extract_height_cm, extract_hr_zone_minutes, extract_hr_zones,
                            extract_hrv_samples, extract_respiratory_by_stage, extract_sedentary_min,
                            extract_spo2_summary, extract_vo2_max)

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

    # temperatura cutanea della notte (data = mattina del risveglio, come i tipi Daily)
    temp = try_call("sleep temperature", lambda: client.list_data_points(
        "daily-sleep-temperature-derivations", "daily_sleep_temperature_derivations", start, end, prefer="date"))
    skin = extract_sleep_temperature(temp or [])
    if skin:
        result["skin_temp"] = skin

    # bilancia (Renpho & co., se scrivono su Google Health/Fitbit): ultima misura del giorno
    weight = try_call("weight", lambda: client.list_data_points("weight", "weight", start, end,
                                                                prefer="sample_time"))
    fat = try_call("body-fat", lambda: client.list_data_points("body-fat", "body_fat", start, end,
                                                               prefer="sample_time"))
    result.update(extract_body(weight or [], fat or []))

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

    result.update(fetch_activity(client, start, end, date_str, try_call))

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


def fetch_activity(client: HealthClient, start: str, end: str, date_str: str, try_call) -> dict:
    """Tutto il resto che il Fitbit misura e i permessi già dati consentono di leggere: calorie
    (totali, attive, per zona), distanza, piani, minuti attivi e sedentari, zone di frequenza,
    allenamenti, HRV della notte a campioni, ossigeno della notte, respiro per fase, VO2 max, altezza."""
    out: dict = {}

    def roll(kebab):
        return try_call(kebab, lambda: client.daily_rollup(kebab, start, end)) or {}

    cal = extract_calories(roll("total-calories"), roll("active-energy-burned"), roll("calories-in-heart-rate-zone"))
    if cal:
        out["calories"] = cal
    km = extract_distance_km(roll("distance"))
    if km is not None:
        out["distance_km"] = km
    floors = extract_count(roll("floors"), "floors")
    if floors is not None:
        out["floors"] = floors
    sed = extract_sedentary_min(roll("sedentary-period"))
    if sed is not None:
        out["sedentary_min"] = sed
    am = extract_active_minutes(roll("active-minutes"))
    if am:
        out["active_minutes"] = am
    zm = extract_hr_zone_minutes(roll("time-in-heart-rate-zone"))
    if zm:
        out["hr_zone_minutes"] = zm

    def lst(kebab, snake, prefer):
        return try_call(kebab, lambda: client.list_data_points(kebab, snake, start, end, prefer=prefer)) or []

    zones = extract_hr_zones(lst("daily-heart-rate-zones", "daily_heart_rate_zones", "date"))
    if zones:
        out["hr_zones"] = zones
    vo2 = extract_vo2_max(lst("daily-vo2-max", "daily_vo2_max", "date")) or \
        extract_vo2_max(lst("vo2-max", "vo2_max", "sample_time"))
    if vo2:
        out["vo2_max"] = vo2
    # allenamenti: il tipo `exercise` si filtra solo sull'ora civile di inizio
    day0 = datetime.strptime(date_str, "%Y-%m-%d")
    flt = (f'exercise.interval.civil_start_time >= "{day0:%Y-%m-%dT00:00:00}" AND '
           f'exercise.interval.civil_start_time < "{day0 + timedelta(days=1):%Y-%m-%dT00:00:00}"')
    ex = extract_exercises(try_call("exercise", lambda: client._list_all_pages("exercise", flt)) or [])
    if ex:
        out["exercises"] = ex
    hrv = extract_hrv_samples(lst("heart-rate-variability", "heart_rate_variability", "sample_time"))
    if hrv:
        out["hrv_samples"] = hrv
    spo2 = extract_spo2_summary(lst("oxygen-saturation", "oxygen_saturation", "sample_time"))
    if spo2:
        out["spo2_night"] = spo2
    rr = extract_respiratory_by_stage(lst("respiratory-rate-sleep-summary", "respiratory_rate_sleep_summary", "sample_time"))
    if rr:
        out["respiratory_by_stage"] = rr
    h = extract_height_cm(lst("height", "height", "sample_time"))
    if h:
        out["height_cm"] = h
    return out


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
