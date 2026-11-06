#!/usr/bin/env python3.12
"""
Lettura di una seduta di meditazione sui dati Fitbit.

NON dà punteggi e non cerca di indovinare quando hai meditato: glielo dici tu.
Misura la finestra che dichiari e risponde a due domande osservabili:

  piattezza — quanto la frequenza è rimasta ferma durante la seduta
  discesa   — se DOPO la seduta il corpo è scivolato più in basso di dov'era prima

La domanda a cui questo serve nel tempo non è "quanto hai meditato bene". È:
**in quali condizioni la pratica scarica davvero, e in quali stai solo stando
seduto dentro una giornata veloce.** Per questo ogni riga porta con sé l'ora del
giorno, cosa c'era nei 30 minuti prima, e i vitali di quel mattino.

--- Perché la finestra si dichiara e non si rileva ---

Tentato e scartato il 22/9/2026. Su blocchi da 15 minuti, "fermo con la
frequenza piatta dopo essersi mosso" descrive anche sedersi alla scrivania, in
treno, a tavola: sette falsi positivi in una giornata. Di notte è peggio, perché
il sonno quieto è fermo e piatto per definizione. Il segnale per separare
"meditare" da "stare seduto" non esiste a questa risoluzione.
`--scan` resta disponibile ma propone CANDIDATI da confermare, non verdetti.

--- 19/10/2026: al minuto il segnale c'è ---

I 15 minuti erano una nostra scelta (windowSize 900s nel sync), non un limite
dell'API: il rollup accetta 60s e conserva lo storico. Al minuto, sulle sei
sedute confermate, la seduta ha una forma che il sonno e la scrivania non hanno:

  ingresso — un picco di 10-30 bpm per 1-3 minuti (ti tiri su, ti alzi) o passi
             (20/10: tirato su piano, +11 — a 12 la seduta si perdeva)
  plateau  — 12-75′ senza passi, FC stretta in ~5 bpm
  livello  — dal sonno: 3-8 bpm SOPRA il sonno di prima (il sonno è più basso);
             da sveglio: entro FC-riposo + 4 (seduti alla scrivania si sta a 60-75)
  uscita   — un altro picco (ti alzi o ti stendi) o passi. Riaddormentarsi
             invece scivola giù senza picco: è il discriminante col dormiveglia.

`--scan` usa questa firma quando la FC al minuto è scaricabile (cache in
data/fitbit/minute/), altrimenti ricade sui blocchi da 15′. Restano candidati:
`--not HH:MM` scarta un falso positivo, `--eval` misura il rilevatore sulle
sedute confermate. Ogni conferma e ogni scarto lo rendono misurabile.
Mancato noto: 22/9 (trasferta, plateau a 63 su RHR 54) — da sveglio e agitato
la seduta non si distingue dallo stare seduti.

--- Limite dichiarato ---

La FC intraday nel file del giorno arriva a blocchi di 15 minuti. Quindi, senza
la FC al minuto:
  · i confini di lettura sono quantizzati a 15 minuti
  · una seduta sotto i 15 minuti non è leggibile
  · una seduta sul bordo dei dati sincronizzati ha la coda mancante, e la
    discesa — che è il dato che conta — si misura solo dopo il sync successivo
Con la FC al minuto la lettura aggiunge il blocco `minute` (campi additivi).

Uso:
  meditation_detect.py 03:08 03:46                  # oggi
  meditation_detect.py 08:00 08:25 --date 2026-09-22
  meditation_detect.py 03:08 03:46 --note "risveglio notturno"
  meditation_detect.py --list                       # storico
  meditation_detect.py --scan --date 2026-09-21     # candidati, da confermare
  meditation_detect.py --not 22:29 --date 2026-09-21  # scarta un candidato
  meditation_detect.py --eval                       # quanto ci prende
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DATA = Path(os.environ.get("WELLNESS_DATA", Path.cwd()))
FITBIT = DATA / "data" / "fitbit"
MINUTE = FITBIT / "minute"
OUT = DATA / "data" / "insights" / "meditations.jsonl"
REJECTS = DATA / "data" / "insights" / "meditation_rejects.jsonl"
TZ = ZoneInfo("Europe/Rome")

BUCKET = 15  # minuti

# Firma al minuto, tarata sulle sedute confermate 21/9–19/10/2026.
ENTRY_SPIKE = 10   # bpm sopra il plateau che segue: ti siedi / ti alzi
EXIT_SPIKE = 8     # bpm sopra il plateau per >=2 minuti: ti alzi o ti stendi
SETTLE = 5         # bpm sopra il plateau: minuti di assestamento in testa
FROM_SLEEP = 2.5   # se prima eri fermo, il plateau sta sopra di almeno tanto
CALM = 4           # se prima eri in giro, il plateau sta entro RHR + tanto
MIN_LEN, MAX_LEN = 12, 75


def _load(day: str) -> dict | None:
    f = FITBIT / f"{day}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _buckets(d: dict) -> list[dict]:
    steps = {p["time"]: p.get("steps", 0) for p in (d.get("steps_intraday") or [])}
    out = []
    for p in d.get("heart_rate_15min") or []:
        if p.get("avg") is None:
            continue
        out.append({
            "time": p["time"],
            "avg": float(p["avg"]),
            "min": p.get("min"),
            "max": p.get("max"),
            "steps": steps.get(p["time"], 0),
        })
    return sorted(out, key=lambda x: x["time"])


def _mins(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def _part_of_day(hhmm: str) -> str:
    h = int(hhmm[:2])
    return "notte" if h < 5 else "mattina" if h < 12 else "pomeriggio" if h < 18 else "sera"


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 1) if xs else None


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _q(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))]


# --- FC al minuto ------------------------------------------------------------

def _fetch_minutes(day: str) -> dict | None:
    """FC e passi al minuto (ora di Roma), in cache su data/fitbit/minute/.

    Rifà la chiamata finché il giorno non è "chiuso" (12h dopo la mezzanotte
    successiva: l'orologio può sincronizzare in ritardo). Offline o token
    scaduto: torna la cache, o None — e chi chiama ricade sui 15′.
    """
    f = MINUTE / f"{day}.json"
    cached = None
    if f.exists():
        try:
            cached = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            cached = None
    if cached and cached.get("complete"):
        return cached

    start = datetime.fromisoformat(day).replace(tzinfo=TZ)
    end = start + timedelta(days=1)
    utc = lambda x: x.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import health_sync  # fratello nel plugin health
        client = health_sync.HealthClient(DATA)
        hr = client.rollup("heart-rate", utc(start), utc(end), 60).get("rollupDataPoints") or []
        st = client.rollup("steps", utc(start), utc(end), 60).get("rollupDataPoints") or []
    except Exception:  # noqa: BLE001 — rete, token, plugin assente
        return cached

    loc = lambda iso: datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ).strftime("%H:%M")
    now = datetime.now(TZ)
    out = {
        "date": day,
        "fetched_at": now.isoformat(),
        "complete": now >= end + timedelta(hours=12),
        "hr": {loc(p["startTime"]): round(float(p["heartRate"]["beatsPerMinuteAvg"]), 1)
               for p in hr if (p.get("heartRate") or {}).get("beatsPerMinuteAvg") is not None},
        "steps": {loc(p["startTime"]): int(float(p["steps"]["countSum"]))
                  for p in st if float((p.get("steps") or {}).get("countSum") or 0) > 0},
    }
    if not out["hr"]:
        return cached
    MINUTE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, ensure_ascii=False))
    return out


def _series(mins: dict) -> tuple[dict[int, float], dict[int, int]]:
    return ({_mins(t): v for t, v in mins["hr"].items()},
            {_mins(t): v for t, v in mins["steps"].items()})


def _median(hr: dict[int, float], a: int, b: int) -> float | None:
    v = [hr[x] for x in range(a, b) if x in hr]
    return statistics.median(v) if v else None


def _rejected(day: str) -> list[int]:
    if not REJECTS.exists():
        return []
    out = []
    for line in REJECTS.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("date") == day:
            out.append(_mins(r["time"]))
    return out


def _sleep_windows(day: str) -> list[tuple[int, int]]:
    """Intervalli di sonno Fitbit che toccano `day`, in minuti del giorno.

    Un record con start > end è cominciato la sera prima; quello della notte
    successiva (nel file di domani) copre la sera di oggi.
    """
    out = []
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    for d, own in ((_load(day), True), (_load(nxt), False)):
        sl = (d or {}).get("sleep")
        for r in (sl if isinstance(sl, list) else [sl] if isinstance(sl, dict) else []):
            if not isinstance(r, dict) or not r.get("start") or not r.get("end"):
                continue
            s, e = _mins(r["start"]), _mins(r["end"])
            if own:
                out.append((0, e) if s > e else (s, e))
            elif s > e:
                out.append((s, 1440))
    return out


def scan_minutes(day: str, mins: dict, rhr: float | None) -> list[dict]:
    """Candidati sulla firma ingresso → plateau → uscita. Vedi docstring."""
    hr, steps = _series(mins)
    rhr = rhr or 55.0
    sleep = _sleep_windows(day)
    moving = lambda x: steps.get(x, 0) > 0
    out, t = [], 1
    while t < 1440:
        settle = _median(hr, t + 3, t + 11)
        if t not in hr or settle is None or not (hr[t] - settle >= ENTRY_SPIKE or moving(t)):
            t += 1
            continue
        # fine dell'evento d'ingresso
        e = t
        while e + 1 < 1440 and ((e + 1 in hr and hr[e + 1] > settle + 6) or moving(e + 1)):
            e += 1
        s = e + 1
        before = _median(hr, t - 30, t - 1)
        from_bed = (not any(moving(x) for x in range(t - 30, t))
                    or any(a <= t < b for a, b in sleep))
        # "prima" era sonno solo se il plateau ci sta sopra; sveglio a letto a
        # 58 e seduta a 52 (28/9) non deve chiudere al primo minuto
        from_sleep = from_bed and before is not None and before <= settle - 1.5
        # Uscite: passi, picco (ti alzi), o — se venivi dal letto — FC tornata
        # al livello del sonno di prima per 5 minuti (21/9: ti stendi con un
        # solo minuto a 64 e ti riaddormenti a 46). Una discesa che resta SOPRA
        # il sonno non chiude: è la seduta che si approfondisce (10/10, 28/9).
        vals, u, high, back, exit_kind = [], s, 0, 0, None
        while u < 1440:
            if moving(u):
                exit_kind = "passi"
                break
            if u not in hr:
                u += 1
                continue
            base = statistics.median(vals[-15:]) if len(vals) >= 5 else settle
            v = hr[u]
            high = high + 1 if v > base + EXIT_SPIKE else 0
            back = back + 1 if from_sleep and v <= before + 1.5 else 0
            if high >= 2:
                exit_kind, u = "picco", u - 1
                break
            if back >= 5:
                exit_kind, u = "sonno", u - 4
                break
            vals.append(v)
            u += 1
            if u - s > MAX_LEN:
                break
        end = u
        if not (exit_kind and MIN_LEN <= end - s <= MAX_LEN and len(vals) >= 10):
            t = e + 1
            continue

        # assestamento: minuti di testa ancora sopra il plateau
        tail = statistics.median([hr[x] for x in range(s + (end - s) // 3, end) if x in hr])
        p = s
        while p < end and (p not in hr or hr[p] > tail + SETTLE):
            p += 1
        core = [hr[x] for x in range(p, end) if x in hr]
        if end - p < MIN_LEN or len(core) < 10:
            t = end
            continue
        level = statistics.median(core)
        # interquartile, non p10–p90: tre minuti isolati a 59-60 dentro una
        # seduta a 50 (10/10) non sono agitazione
        spread = round(_q(core, .75) - _q(core, .25), 1)
        if any(a < end and p < b for a, b in sleep):
            # dentro il sonno: deve stare SOPRA il sonno di prima, altrimenti è
            # sonno che continua (17/10 05:16: piatto a 49, prima 49)
            level_ok, origin = before is not None and before <= level - FROM_SLEEP, "dal sonno"
        else:
            # fuori dal sonno basta la calma: sveglio a letto a 58 e seduta a 52
            # (28/9) sta SOTTO quello che c'era prima, non sopra
            level_ok, origin = level <= rhr + CALM, "da letto" if from_bed else "da sveglio"
        third = max(1, len(core) // 3)
        arc = round(statistics.median(core[-third:]) - statistics.median(core[:third]), 1)
        if level_ok and spread <= 5:
            strong = spread <= 3.5 and end - p >= 15
            # da sveglio la pratica scende SOTTO la FC a riposo (28/9 −5, 10/10
            # −3.4); stare seduti o sdraiati resta sopra (19/10 +3.9, 20/10 +1.2).
            # 2 contro 2: declassa, non esclude.
            if origin != "dal sonno" and level > rhr:
                strong = False
            if not any(p <= r < end for r in _rejected(day)):
                out.append({
                    "start": _hhmm(p), "end": _hhmm(end), "duration_min": end - p,
                    "settle_min": p - s, "hr_mean": round(level, 1), "flatness_bpm": spread,
                    "arc_bpm": arc, "hr_before": before, "origin": origin, "exit": exit_kind,
                    "confidence": "alta" if strong else "media",
                })
        t = end
    return out


def read_minutes(mins: dict, start: str, end: str) -> dict | None:
    """Lettura al minuto della finestra dichiarata. Campi additivi."""
    hr, steps = _series(mins)
    s, e = _mins(start), _mins(end)
    inside = [hr[x] for x in range(s, e) if x in hr]
    if len(inside) < 5:
        return None
    tail = statistics.median(inside[len(inside) // 3:])
    settle = next((i for i, x in enumerate(range(s, e)) if x in hr and hr[x] <= tail + SETTLE), 0)
    core = [hr[x] for x in range(s + settle, e) if x in hr]
    head = statistics.median(core[:5])
    last = statistics.median(core[-5:])
    # coda: minuti fermi subito dopo, prima del primo passo
    after = []
    for x in range(e, e + 10):
        if steps.get(x, 0):
            break
        if x in hr:
            after.append(hr[x])
    return {
        "hr_mean": round(statistics.mean(core), 1),
        "hr_floor": min(core),
        "flatness_bpm": round(_q(core, .75) - _q(core, .25), 1),
        "settle_min": settle,
        "arc_bpm": round(last - head, 1),
        "hr_before": _median(hr, s - 30, s - 3),
        "still_after_min": len(after),
        "hr_after": round(statistics.median(after), 1) if len(after) >= 5 else None,
        "missing_min": (e - s) - len(inside),
    }


def read_window(day: str, start: str, end: str, note: str = "") -> dict:
    """Misura la finestra dichiarata. Solleva ValueError se i dati non bastano."""
    d = _load(day)
    if not d:
        raise ValueError(f"Nessun dato Fitbit per {day}.")
    b = _buckets(d)
    if not b:
        raise ValueError(f"Nessuna frequenza intraday per {day}.")

    s, e = _mins(start), _mins(end)
    if e <= s:
        raise ValueError("L'orario di fine deve essere dopo quello di inizio.")

    # blocchi il cui centro cade dentro la finestra dichiarata
    inside = [x for x in b if s <= _mins(x["time"]) + BUCKET / 2 <= e]
    if not inside:
        # finestra più corta di un blocco: prendi quello che la contiene
        inside = [x for x in b if _mins(x["time"]) <= s < _mins(x["time"]) + BUCKET]
    if not inside:
        raise ValueError(
            f"Nessun blocco di frequenza copre {start}–{end} del {day}. "
            f"Dati disponibili da {b[0]['time']} a {b[-1]['time']}."
        )

    idx = {x["time"]: i for i, x in enumerate(b)}
    i0, i1 = idx[inside[0]["time"]], idx[inside[-1]["time"]]

    before = b[max(0, i0 - 2):i0]
    after = b[i1 + 1:i1 + 3]
    at_boundary = i1 >= len(b) - 1

    avgs = [x["avg"] for x in inside]
    spread = round(max(avgs) - min(avgs), 1)
    during = _mean(avgs)
    m_before = _mean([x["avg"] for x in before])

    # Lo spread NON ha segno: "mi sono agitato" e "mi sono progressivamente
    # assestato" danno lo stesso numero. Sulle sedute che cominciano appena
    # svegli il primo blocco contiene sempre il passaggio coricato→seduto
    # (ortostatismo, picchi a 85-90), quindi la piattezza è destinata a
    # leggersi "mossa" anche quando la pratica sta scendendo. 6/10/2026.
    # Campo ADDITIVO: dice la direzione dentro la finestra, non ridefinisce
    # flatness_bpm né le sue etichette (lo storico resta confrontabile).
    within = round(avgs[-1] - avgs[0], 1) if len(avgs) >= 2 else None

    # La discesa è misurabile SOLO se dopo la seduta sei rimasto fermo.
    # Se ti alzi e cammini, la frequenza sale per il cammino e il numero non
    # dice più niente sulla pratica: va dichiarato non misurabile, non "salita".
    steps_after = sum(x["steps"] for x in after)
    got_up = steps_after > 50
    m_after = None if (at_boundary or got_up) else _mean([x["avg"] for x in after])
    descent = round(m_after - during, 1) if m_after is not None else None
    if at_boundary:
        unmeasurable = "dati troncati: la coda arriva al prossimo sync"
    elif got_up:
        unmeasurable = f"ti sei alzato subito ({steps_after} passi nei 30′ dopo): la discesa non è leggibile"
    else:
        unmeasurable = None
    floors = [x["min"] for x in inside if x["min"] is not None]

    sl = d.get("sleep")
    if isinstance(sl, list):
        sl = sl[0] if sl and isinstance(sl[0], dict) else {}
    sl = sl if isinstance(sl, dict) else {}
    stages = {x["type"]: x["minutes"] for x in (sl.get("stages") or []) if isinstance(x, dict)}

    mins = _fetch_minutes(day)
    minute = read_minutes(mins, start, end) if mins else None

    return {
        "id": f"med-{day}-{start.replace(':', '')}",
        "date": day,
        "declared": {"start": start, "end": end, "duration_min": e - s},
        "read": {"from": inside[0]["time"], "to": inside[-1]["time"], "buckets": len(inside)},
        "part_of_day": _part_of_day(start),
        "hr_mean": during,
        "hr_floor": min(floors) if floors else None,
        "flatness_bpm": spread,
        "flatness_label": "molto ferma" if spread < 2 else "ferma" if spread <= 4 else "mossa",
        "trend_within_bpm": within,
        "trend_within_label": (
            None if within is None
            else "si è assestata" if within <= -3
            else "si è attivata" if within >= 3
            else "stabile"
        ),
        "bucket_avgs": avgs,
        "hr_before": m_before,
        "hr_after": m_after,
        "descent_bpm": descent,
        "descent_label": (
            None if descent is None
            else "è scesa" if descent <= -3 else "è salita" if descent >= 3 else "invariata"
        ),
        "steps_30min_before": sum(x["steps"] for x in before),
        "steps_30min_after": steps_after,
        "unmeasurable_reason": unmeasurable,
        "steps_in_window": sum(x["steps"] for x in inside),
        "context": {
            "hrv_rmssd": d.get("hrv_rmssd"),
            "resting_hr": d.get("resting_hr"),
            "respiratory_rate": d.get("respiratory_rate"),
            "sleep_min": sl.get("minutes_asleep"),
            "deep_min": stages.get("DEEP"),
        },
        "tail_missing": at_boundary,
        "got_up_after": got_up,
        "minute": minute,
        "note": note,
        "logged_at": datetime.now().astimezone().isoformat(),
    }


def save(ev: dict) -> bool:
    """Appende, sostituendo una riga precedente con lo stesso id."""
    rows = []
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("id") != ev["id"]:
                rows.append(r)
    rows.append(ev)
    rows.sort(key=lambda r: (r.get("date", ""), r.get("declared", {}).get("start", "")))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return True


def scan(day: str) -> list[dict]:
    """CANDIDATI, non verdetti. Al minuto se possibile, altrimenti sui 15′."""
    d = _load(day)
    mins = _fetch_minutes(day)
    if mins:
        return scan_minutes(day, mins, (d or {}).get("resting_hr"))
    if not d:
        return []
    # fallback 15′: >=30' fermi con piattezza <=2 bpm
    b = _buckets(d)
    out, i = [], 0
    while i < len(b):
        if b[i]["steps"] > 5:
            i += 1
            continue
        j = i
        while (j + 1 < len(b) and b[j + 1]["steps"] <= 5
               and max(x["avg"] for x in b[i:j + 2]) - min(x["avg"] for x in b[i:j + 2]) <= 2.0):
            j += 1
        if j - i + 1 >= 2:
            out.append({
                "start": b[i]["time"],
                "end": (datetime.strptime(b[j]["time"], "%H:%M") + timedelta(minutes=BUCKET)).strftime("%H:%M"),
                "hr_mean": _mean([x["avg"] for x in b[i:j + 1]]),
                "flatness_bpm": round(max(x["avg"] for x in b[i:j + 1]) - min(x["avg"] for x in b[i:j + 1]), 1),
            })
        i = j + 1
    return out


def fmt(ev: dict) -> str:
    dec, rd, c = ev["declared"], ev["read"], ev["context"]
    L = [
        f"{ev['date']}  {dec['start']}–{dec['end']}  ({dec['duration_min']}′, {ev['part_of_day']})",
        f"  letto sui blocchi {rd['from']}–{rd['to']}",
        f"  FC media {ev['hr_mean']} · pavimento {ev['hr_floor']} · {ev['flatness_label']} ({ev['flatness_bpm']} bpm di escursione)",
    ]
    if ev.get("trend_within_label"):
        ba = ev.get("bucket_avgs") or []
        arc = " → ".join(str(x) for x in ba) if ba else ""
        L.append(f"  dentro la finestra: {arc}  ·  {ev['trend_within_label']} ({ev['trend_within_bpm']:+} bpm)")
    if ev["descent_label"]:
        L.append(f"  prima {ev['hr_before']} → durante {ev['hr_mean']} → dopo {ev['hr_after']}   ·   {ev['descent_label']} ({ev['descent_bpm']:+} bpm)")
    else:
        L.append(f"  prima {ev['hr_before']} → durante {ev['hr_mean']} → dopo: non misurabile")
        L.append(f"  perché: {ev.get('unmeasurable_reason')}")
    mn = ev.get("minute")
    if mn:
        L.append(f"  al minuto: FC {mn['hr_mean']} · pavimento {mn['hr_floor']} · escursione {mn['flatness_bpm']} bpm"
                 f" · assestamento {mn['settle_min']}′ · arco {mn['arc_bpm']:+} bpm · prima {mn['hr_before']}")
        if mn["hr_after"] is not None:
            L.append(f"  al minuto, dopo: {mn['still_after_min']}′ senza passi a {mn['hr_after']}")
    L.append(f"  nei 30′ prima: {ev['steps_30min_before']} passi")
    L.append(f"  quel mattino: HRV {c.get('hrv_rmssd')} · FC riposo {c.get('resting_hr')} · respiro {c.get('respiratory_rate')} · sonno {c.get('sleep_min')}′ (deep {c.get('deep_min')})")
    if ev.get("note"):
        L.append(f"  nota: {ev['note']}")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Legge una seduta di meditazione dichiarata.")
    ap.add_argument("start", nargs="?", help="HH:MM di inizio")
    ap.add_argument("end", nargs="?", help="HH:MM di fine")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--note", default="")
    ap.add_argument("--list", action="store_true", help="storico registrato")
    ap.add_argument("--scan", action="store_true", help="candidati da confermare")
    ap.add_argument("--dry", action="store_true", help="leggi senza scrivere")
    ap.add_argument("--not", dest="reject", metavar="HH:MM", help="scarta il candidato che contiene quest'ora")
    ap.add_argument("--eval", action="store_true", help="misura il rilevatore sulle sedute confermate")
    a = ap.parse_args()

    if a.reject:
        REJECTS.parent.mkdir(parents=True, exist_ok=True)
        with REJECTS.open("a") as f:
            f.write(json.dumps({"date": a.date, "time": a.reject,
                                "logged_at": datetime.now().astimezone().isoformat()}) + "\n")
        print(f"Scartato: {a.date} {a.reject} non era meditazione.")
        return 0

    if a.eval:
        rows = [json.loads(l) for l in OUT.read_text().splitlines() if l.strip()] if OUT.exists() else []
        hits = 0
        for r in rows:
            s, e = _mins(r["declared"]["start"]), _mins(r["declared"]["end"])
            cs = scan(r["date"])
            # preso: un candidato copre almeno metà della finestra dichiarata
            hit = next((c for c in cs
                        if min(e, _mins(c["end"])) - max(s, _mins(c["start"])) >= (e - s) / 2), None)
            hits += bool(hit)
            other = [c for c in cs if c is not hit]
            print(f"{r['date']}  dichiarata {r['declared']['start']}–{r['declared']['end']}  →  "
                  + (f"presa {hit['start']}–{hit['end']} ({hit['confidence']})" if hit else "MANCATA")
                  + (f"  · altri candidati: {', '.join(c['start'] for c in other)}" if other else ""))
        rej = sum(1 for l in REJECTS.read_text().splitlines() if l.strip()) if REJECTS.exists() else 0
        print(f"\nPrese {hits}/{len(rows)}. Falsi positivi scartati finora: {rej}.")
        return 0

    if a.list:
        if not OUT.exists():
            print("Nessuna seduta registrata.")
            return 0
        rows = [json.loads(l) for l in OUT.read_text().splitlines() if l.strip()]
        print(f"{len(rows)} sedute registrate:\n")
        for r in rows:
            print(fmt(r))
            print()
        misurabili = [r for r in rows if r.get("descent_label")]
        scesa = [r for r in misurabili if r["descent_label"] == "è scesa"]
        if len(rows) >= 3:
            print(f"Su {len(rows)} sedute registrate, {len(misurabili)} hanno una coda misurabile; "
                  f"in {len(scesa)} la frequenza è scesa dopo.")
            if len(rows) - len(misurabili):
                print(f"({len(rows) - len(misurabili)} non misurabili: alzato subito o dati troncati.)")

            # L'arco DENTRO la finestra si legge anche quando la coda non si legge:
            # non dipende dall'essere rimasto fermo dopo. È la lettura che
            # sopravvive al "mi sono alzato subito".
            arc = [r for r in rows if r.get("trend_within_bpm") is not None]
            if arc:
                giu = [r for r in arc if r["trend_within_bpm"] <= -3]
                print(f"\nArco interno — leggibile su {len(arc)} sedute "
                      f"(non richiede di restare fermi dopo): in {len(giu)} la frequenza "
                      f"si assesta dentro la finestra.")
                # Il discriminante emerso il 6/10/2026: da dove parti.
                dal_sonno = [r for r in arc
                             if r.get("hr_before") is not None
                             and (r.get("context") or {}).get("resting_hr") is not None
                             and r["hr_before"] < (r["context"]["resting_hr"] or 0)]
                da_sveglio = [r for r in arc if r not in dal_sonno]
                for nome, gruppo in (("dal pavimento del sonno", dal_sonno),
                                     ("da sveglio", da_sveglio)):
                    if gruppo:
                        m = _mean([r["trend_within_bpm"] for r in gruppo])
                        print(f"  partendo {nome} (n={len(gruppo)}): arco medio {m:+} bpm")
                if len(arc) < 8:
                    print("  (campione troppo piccolo per chiamarlo pattern: è una direzione.)")
        return 0

    if a.scan:
        cs = scan(a.date)
        if not cs:
            print(f"Nessun candidato il {a.date}.")
            return 0
        print(f"Candidati del {a.date} — da confermare, non sono verdetti:\n")
        for c in cs:
            line = f"  {c['start']}–{c['end']}  FC {c['hr_mean']}  escursione {c['flatness_bpm']} bpm"
            if "confidence" in c:
                line += (f"  · {c['duration_min']}′ {c['origin']} (prima {c['hr_before']})"
                         f" · assestamento {c['settle_min']}′ · uscita: {c['exit']} · {c['confidence']}")
            print(line)
        return 0

    if not (a.start and a.end):
        ap.print_help()
        return 1

    try:
        ev = read_window(a.date, a.start, a.end, a.note)
    except ValueError as e:
        print(f"Errore: {e}", file=sys.stderr)
        return 1

    print(fmt(ev))
    if not a.dry:
        save(ev)
        print(f"\nRegistrata in {OUT.relative_to(DATA)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
