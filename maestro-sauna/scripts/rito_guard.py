#!/usr/bin/env python3.12
"""La soglia del rito: una partitura fuori dai limiti non parte.

    python3.12 rito_guard.py data/sauna/riti/YYYY-MM-DD.rito.json      # exit 3 se non passa

Il Maestro scrive la partitura; questo controllo è deterministico e sta fra lui e il telefono
(lo chiama il canale di Hṛdaya prima di mandare il bottone). Guarda tre cose:

1. la forma: la partitura è valida (stesse regole del motore, apps/rito/engine.js: i due test
   condividono `fixtures/cases.json`) e ha l'ordine di un rito — una soglia prima del calore, un
   riposo dopo ogni calore lungo almeno quanto quel calore;
2. i tetti della persona — `data/sauna/rules.json` nel repo dati:
     {"heat_round_max_min": 15, "heat_total_max_min": 25, "rounds_max": 2, "temp_max_c": 70,
      "cold": {"allowed": true, "max_min": 5, "optional": true, "not_after": "19:00"},
      "rest_ratio_min": 1.0, "earliest_start": "07:00", "latest_end": "20:00", "min_hours_between": 20,
      "wod_peak_max_bpm": 165, "hold": {"until": "2026-11-20", "why": "febbre"},
      "judgement": [{"id": "uscita-lunga", "text": "nelle 24-36 h prima nessuna uscita lunga con sudorazione profusa"}]}
   Li cambiano la persona, il consiglio o il medico: il Maestro li rispetta, non li allarga.
   Il file è obbligatorio (lo scrive il `setup` del Maestro) e si legge in modo stretto: un valore
   del tipo sbagliato, o un file che non si legge, **chiude** la soglia invece di spegnere un
   controllo. Le chiavi che mancano prendono i valori prudenti di DEFAULT_RULES. `hold` senza
   `until` è una sospensione senza scadenza.
3. il giorno: la data della partitura, l'ora (il rito deve cominciare dopo `earliest_start` e
   finire entro `latest_end`, contando i massimi del caldo), l'ultima seduta, il picco di frequenza
   dell'allenamento di oggi, un blocco dichiarato. Le condizioni che un programma non sa leggere
   (`judgement`) le verifica il Maestro e le dichiara nella partitura, in `threshold`: senza quella
   dichiarazione il rito non parte.

Il tempo del calore conta dal tocco «Entro» (il passaggio del calore è solo il tempo per stendersi):
`max_s` è quindi il tempo massimo in cabina, e i tetti si confrontano con quello.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TYPES = ("prep", "heat", "air", "cold", "rest", "close")
HOT = ("heat", "cold")          # finiscono solo con un tocco, hanno sempre un massimo
BEDS = ("silenzio", "brace", "bordone", "acqua", "aria", "respiro")
SHOTS = ("gong", "ciotola", "campanella", "legno", "vapore")
LEADS = {"prep": 0, "heat": 0, "air": 15, "cold": 30, "rest": 60, "close": 0}   # come engine.js (il calore conta dal tocco)
LEAD_MAX = {"heat": 60, "cold": 120}
DEFAULT_RULES: dict = {"heat_round_max_min": 12, "heat_total_max_min": 24, "rounds_max": 2, "temp_max_c": 80,
                       "cold": {"allowed": True, "max_min": 2, "optional": True}, "rest_ratio_min": 1.0}
HM = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


class Unreadable(Exception):
    """Regole assenti, illeggibili o scritte male: la soglia non si apre in silenzio."""


def data_root(root: str | Path | None = None) -> Path:
    return Path(root or os.environ.get("WELLNESS_DATA") or os.getcwd())


def tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("WELLNESS_TZ", "Europe/Rome"))


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _len(s: str) -> int:
    """Lunghezza come la conta JavaScript (unità UTF-16): un'emoji vale due."""
    return len(s.encode("utf-16-le")) // 2


def _str(v: Any, limit: int) -> bool:
    return isinstance(v, str) and 0 < _len(v) <= limit


def _opt_str(v: Any, limit: int) -> bool:
    return v is None or (isinstance(v, str) and _len(v) <= limit)


# --- forma --------------------------------------------------------------------------

def validate(r: Any) -> list[str]:
    """Errori di forma: le stesse regole di engine.js (una partitura che passa qui si apre sul telefono)."""
    if not isinstance(r, dict):
        return ["il rito deve essere un oggetto"]
    errs: list[str] = []
    if type(r.get("v")) is not int or r["v"] != 1:
        errs.append("v deve essere 1")
    ms = r.get("moments")
    if not isinstance(ms, list) or not ms:
        return errs + ["moments mancante o vuoto"]
    if len(ms) > 40:
        errs.append("al massimo 40 momenti")
    ids: set[str] = set()
    for k, m in enumerate(ms, 1):
        p = f"momento {k}"
        if not isinstance(m, dict):
            errs.append(f"{p}: deve essere un oggetto")
            continue
        mid = m.get("id")
        if not isinstance(mid, str) or not re.fullmatch(r"[a-z0-9-]{1,24}", mid):
            errs.append(f"{p}: id deve essere uno slug (a-z, 0-9, -)")
        elif mid in ids:
            errs.append(f"{p}: id ripetuto {mid}")
        if isinstance(mid, str):
            ids.add(mid)
        if not _str(m.get("name"), 40):
            errs.append(f"{p}: name mancante o oltre 40 caratteri")
        t = m.get("type")
        if not isinstance(t, str) or t not in TYPES:
            errs.append(f"{p}: type {t!r} non tra {', '.join(TYPES)}")
        hot = t in HOT
        end = "tap" if m.get("end") is None else m.get("end")
        if end not in ("tap", "time"):
            errs.append(f"{p}: end deve essere tap o time")
        elif end == "time" and hot:
            errs.append(f"{p}: caldo e freddo finiscono solo con un tocco (end: tap), mai da soli")
        if m.get("optional") is not None and not isinstance(m["optional"], bool):
            errs.append(f"{p}: optional deve essere true o false")
        if m.get("optional") is True and t == "rest":
            errs.append(f"{p}: il riposo non si salta (niente optional)")
        if m.get("temp_c") is not None and not ((_num(m["temp_c"]) or 0) > 0):
            errs.append(f"{p}: temp_c deve essere un numero")
        if m.get("temp_c") is not None and t != "heat":
            errs.append(f"{p}: temp_c vale solo per il calore")
        if m.get("sound") == "brace" and t != "heat":
            errs.append(f"{p}: il tappeto brace è del calore")
        b = m.get("breath")
        if b is not None and not (isinstance(b, dict) and all(
                _num(b.get(x)) is not None and 2 <= b[x] <= 15 for x in ("in_s", "out_s"))):
            errs.append(f"{p}: breath vuole in_s e out_s fra 2 e 15 secondi")
        for key in ("where", "done_label"):
            if not _opt_str(m.get(key), 40):
                errs.append(f"{p}: {key} è un testo di al massimo 40 caratteri")
        for key in ("min_s", "target_s", "max_s"):
            if m.get(key) is not None and not ((_num(m[key]) or 0) > 0):
                errs.append(f"{p}: {key} deve essere un numero > 0")
        mn, tg, mx = _num(m.get("min_s")), _num(m.get("target_s")), _num(m.get("max_s"))
        if end == "time" and not ((tg or 0) > 0):
            errs.append(f"{p}: un momento a tempo vuole target_s")
        if hot and not ((mx or 0) > 0):
            errs.append(f"{p}: caldo e freddo vogliono max_s (il limite oltre cui si viene richiamati)")
        if mn and tg and mn > tg:
            errs.append(f"{p}: min_s oltre target_s")
        if tg and mx and tg > mx:
            errs.append(f"{p}: target_s oltre max_s")
        if mn and mx and mn > mx:
            errs.append(f"{p}: min_s oltre max_s")
        if m.get("sound") is not None and m["sound"] not in BEDS:
            errs.append(f"{p}: sound non tra {', '.join(BEDS)}")
        if m.get("enter_sound") is not None and m["enter_sound"] is not False and m["enter_sound"] not in SHOTS:
            errs.append(f"{p}: enter_sound non tra {', '.join(SHOTS)}")
        if not _opt_str(m.get("text"), 400):
            errs.append(f"{p}: text è un testo di al massimo 400 caratteri")
        lmax = LEAD_MAX.get(t, 300)
        if m.get("lead_s") is not None and not (_num(m["lead_s"]) is not None and 0 <= m["lead_s"] <= lmax):
            errs.append(f"{p}: lead_s (il passaggio) va da 0 a {lmax} secondi")
        if not _opt_str(m.get("lead_text"), 200):
            errs.append(f"{p}: lead_text è un testo di al massimo 200 caratteri")
        cues = m.get("cues")
        if cues is not None:
            if not isinstance(cues, list) or len(cues) > 12:
                errs.append(f"{p}: cues è una lista di al massimo 12")
                continue
            for j, c in enumerate(cues, 1):
                q = f"{p} richiamo {j}"
                if not isinstance(c, dict) or _num(c.get("at_s")) is None or c["at_s"] < 0:
                    errs.append(f"{q}: at_s mancante")
                    continue
                lim = mx or tg
                if lim and c["at_s"] >= lim:
                    errs.append(f"{q}: at_s oltre la fine del momento")
                if c.get("sound") is not None and c["sound"] not in SHOTS:
                    errs.append(f"{q}: sound non tra {', '.join(SHOTS)}")
                for key in ("say", "text"):
                    if not _opt_str(c.get(key), 200):
                        errs.append(f"{q}: {key} è un testo di al massimo 200 caratteri")
                if c.get("sound") is None and c.get("say") is None and c.get("text") is None:
                    errs.append(f"{q}: serve sound, say o text")
    closing = r.get("closing")
    if closing is not None:
        if not isinstance(closing, list) or len(closing) > 5:
            errs.append("closing è una lista di al massimo 5 domande")
        else:
            for j, c in enumerate(closing, 1):
                q = f"domanda {j}"
                if not isinstance(c, dict) or not isinstance(c.get("id"), str) or \
                        not re.fullmatch(r"[a-z0-9_-]{1,20}", c["id"]):
                    errs.append(f"{q}: id mancante")
                    continue
                if not _str(c.get("q"), 120):
                    errs.append(f"{q}: q mancante o oltre 120 caratteri")
                o = c.get("options")
                if not isinstance(o, list) or not 2 <= len(o) <= 5 or any(not _str(x, 30) for x in o):
                    errs.append(f"{q}: da 2 a 5 opzioni brevi")
    return errs


def _lead(i: int, m: dict) -> float:
    """Il passaggio che ferma l'orologio (per il calore no: conta dal tocco)."""
    if i == 0 or m.get("type") == "heat":
        return 0
    v = _num(m.get("lead_s"))
    return v if v is not None else LEADS.get(m.get("type"), 0)


def planned(r: dict) -> dict:
    ms = [m for m in r.get("moments") or [] if isinstance(m, dict)]

    def tot(t: str, key: str = "target_s") -> float:
        return sum((_num(m.get(key)) or _num(m.get("max_s")) or 0) for m in ms if m.get("type") == t)
    return {"rounds": sum(1 for m in ms if m.get("type") == "heat"),
            "heat_s": tot("heat"), "heat_max_s": tot("heat", "max_s"), "cold_s": tot("cold"), "rest_s": tot("rest"),
            "total_s": sum((_num(m.get("target_s")) or _num(m.get("min_s")) or 0) + _lead(i, m)
                           for i, m in enumerate(ms)),
            # la fine più lontana: caldo e freddo fino al loro massimo
            "longest_s": sum((_num(m.get("max_s")) if m.get("type") in HOT else
                              (_num(m.get("target_s")) or _num(m.get("min_s")))) or 0
                             for m in ms) + sum(_lead(i, m) for i, m in enumerate(ms))}


def order_errors(r: dict, ratio: float = 1.0) -> list[str]:
    """L'ordine di un rito: soglia, calore, e dopo ogni calore un riposo lungo almeno quanto quel calore."""
    ms = [m for m in r.get("moments") or [] if isinstance(m, dict)]
    types = [m.get("type") for m in ms]
    out = []
    if "heat" in types and "prep" not in types[:types.index("heat")]:
        out.append("prima del calore ci vuole la soglia (un momento prep: doccia, asciugarsi)")
    for i, t in enumerate(types):
        if t != "heat":
            continue
        after = ms[i + 1:]
        nxt = next((k for k, x in enumerate(after) if x.get("type") == "heat"), len(after))
        rests = [x for x in after[:nxt] if x.get("type") == "rest"]
        heat_s = _num(ms[i].get("target_s")) or _num(ms[i].get("max_s")) or 0
        rest_s = sum((_num(x.get("target_s")) or _num(x.get("min_s")) or 0) for x in rests)
        if not rests:
            out.append(f"dopo «{ms[i].get('name')}» manca il riposo: il riposo non si salta")
        elif ratio and rest_s < ratio * heat_s:
            out.append(f"dopo «{ms[i].get('name')}» ({heat_s / 60:g}′) il riposo è di {rest_s / 60:g}′: "
                       "dura almeno quanto il calore")
    return out


# --- tetti --------------------------------------------------------------------------

def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise Unreadable(f"rules.json: {msg}")


def load_rules(root: str | Path | None = None) -> dict:
    """I tetti, letti in modo stretto. Solleva Unreadable se il file manca, non si legge o è scritto male."""
    p = data_root(root) / "data" / "sauna" / "rules.json"
    if not p.exists():
        raise Unreadable("manca data/sauna/rules.json: prima il setup del Maestro di sauna (i tetti della persona)")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Unreadable(f"rules.json illeggibile ({e.__class__.__name__})") from e
    _need(isinstance(raw, dict), "deve essere un oggetto")
    ru = {**DEFAULT_RULES, **raw}
    for k in ("heat_round_max_min", "heat_total_max_min", "temp_max_c"):
        _need((_num(ru.get(k)) or 0) > 0, f"{k} deve essere un numero > 0")
    _need(type(ru.get("rounds_max")) is int and ru["rounds_max"] >= 0, "rounds_max deve essere un intero ≥ 0")
    _need(_num(ru.get("rest_ratio_min")) is not None and ru["rest_ratio_min"] >= 0, "rest_ratio_min deve essere un numero ≥ 0")
    for k in ("min_hours_between", "wod_peak_max_bpm"):
        _need(ru.get(k) is None or (_num(ru[k]) or 0) > 0, f"{k} deve essere un numero > 0 (o mancare)")
    for k in ("latest_end", "earliest_start"):
        _need(ru.get(k) is None or (isinstance(ru[k], str) and HM.fullmatch(ru[k])), f"{k} deve essere HH:MM")
    cold = raw.get("cold", {})
    _need(isinstance(cold, dict), "cold deve essere un oggetto")
    cold = {**DEFAULT_RULES["cold"], **cold}                       # i pezzi che mancano restano prudenti
    _need(isinstance(cold.get("allowed"), bool), "cold.allowed deve essere true o false")
    _need(isinstance(cold.get("optional"), bool), "cold.optional deve essere true o false")
    _need((_num(cold.get("max_min")) or 0) > 0, "cold.max_min deve essere un numero > 0")
    _need(cold.get("not_after") is None or (isinstance(cold["not_after"], str) and HM.fullmatch(cold["not_after"])),
          "cold.not_after deve essere HH:MM")
    ru["cold"] = cold
    hold = ru.get("hold")
    if hold in (None, False):
        ru["hold"] = None
    elif hold is True:
        ru["hold"] = {"until": None, "why": ""}
    else:
        _need(isinstance(hold, dict), "hold deve essere un oggetto {until, why}, true o null")
        until = hold.get("until")
        if until is not None:
            try:
                _need(isinstance(until, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", until) is not None, "hold.until deve essere YYYY-MM-DD")
                date.fromisoformat(until)
            except ValueError as e:
                raise Unreadable("rules.json: hold.until deve essere YYYY-MM-DD") from e
        ru["hold"] = {"until": until, "why": str(hold.get("why") or "")}
    js = ru.get("judgement", [])
    _need(isinstance(js, list), "judgement deve essere una lista")
    for j in js:
        _need(isinstance(j, dict) and isinstance(j.get("id"), str) and j["id"] != "", "ogni judgement vuole un id")
    ru["judgement"] = js
    return ru


# --- giorno -------------------------------------------------------------------------

def _hm(t: datetime) -> str:
    return t.strftime("%H:%M")


def _last_session_end(root: Path) -> datetime | None:
    best = None
    for f in sorted((root / "data" / "sauna" / "sessions").glob("*.session.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("demo") or not (d.get("heat_s") or 0):
                continue
            t = datetime.fromisoformat(d["ended_at"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=tz())
        best = t if best is None or t > best else best
    return best


def _wod_peak(root: Path, day: str) -> float | None:
    best = None
    for f in (root / "data" / "coach-longevita" / "daily").glob(f"{day}*.session-hr.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for src in ((d.get("hr_recovery"), d.get("session")) if isinstance(d, dict) else ()):
            p = _num(src.get("peak")) if isinstance(src, dict) else None
            best = p if p is not None and (best is None or p > best) else best
    return best


def check(r: Any, root: str | Path | None = None, now: datetime | None = None, reopen: bool = False) -> list[str]:
    """Perché il rito non può partire (lista vuota = la soglia è aperta).

    `reopen=True`: il bottone di questo rito è già stato mandato oggi e la persona lo sta riaprendo a
    metà. Valgono forma, tetti, data, blocco e soglia dichiarata; non si rifanno i conti dell'ora di
    fine né della distanza dall'ultima seduta, che erano giusti quando il rito è cominciato."""
    errs = validate(r)
    if errs:
        return ["partitura non valida: " + "; ".join(errs[:4])]
    base = data_root(root)
    try:
        ru = load_rules(base)
    except Unreadable as e:
        return [f"{e}: la soglia resta chiusa"]
    now = now or datetime.now(tz())
    today = now.date().isoformat()
    ms = r["moments"]
    p = planned(r)
    out = order_errors(r, ru["rest_ratio_min"])

    if not isinstance(r.get("date"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"]):
        out.append("la partitura non ha la data (date: YYYY-MM-DD): un rito vale per un giorno solo")
    elif r["date"] != today:
        out.append(f"la partitura è del {r['date']}, oggi è il {today}: il Maestro la riscrive per oggi")

    cap, tmax = ru["heat_round_max_min"], ru["temp_max_c"]
    for m in ms:
        if m.get("type") != "heat":
            continue
        if m["max_s"] > cap * 60:
            out.append(f"«{m['name']}»: fino a {m['max_s'] / 60:g}′ nel calore, il tetto è {cap:g}′ a passaggio")
        if m.get("temp_c") is None:
            out.append(f"«{m['name']}»: manca temp_c (il tetto è {tmax:g} °C e va confrontato)")
        elif m["temp_c"] > tmax:
            out.append(f"«{m['name']}»: {m['temp_c']:g} °C, il tetto è {tmax:g} °C")
    if p["heat_max_s"] > ru["heat_total_max_min"] * 60:
        out.append(f"calore in tutto fino a {p['heat_max_s'] / 60:g}′, il tetto è {ru['heat_total_max_min']:g}′ "
                   "(contano i massimi, non i traguardi)")
    if p["rounds"] > ru["rounds_max"]:
        out.append(f"{p['rounds']} passaggi nel calore, il tetto è {ru['rounds_max']}"
                   + (" (oggi nessun calore)" if ru["rounds_max"] == 0 else ""))

    cold = ru["cold"]
    for m in ms:
        if m.get("type") != "cold":
            continue
        if not cold["allowed"]:
            out.append(f"«{m['name']}»: l'acqua fredda non è ammessa")
            continue
        if m["max_s"] > cold["max_min"] * 60:
            out.append(f"«{m['name']}»: fino a {m['max_s'] / 60:g}′ nel freddo, il tetto è {cold['max_min']:g}′")
        if cold["optional"] and m.get("optional") is not True:
            out.append(f"«{m['name']}»: il freddo va scritto facoltativo (optional): lo decide il corpo")
        if cold.get("not_after") and _hm(now) > cold["not_after"]:
            out.append(f"«{m['name']}»: niente freddo dopo le {cold['not_after']}")

    hold = ru["hold"]
    if hold is not None and (hold["until"] is None or hold["until"] >= today):
        out.append(("sauna sospesa" + (f" fino al {hold['until']}" if hold["until"] else " finché non viene tolto il blocco"))
                   + (f": {hold['why']}" if hold["why"] else ""))
    if reopen:
        return out + _judgement_errors(r, ru)
    if ru.get("earliest_start") and _hm(now) < ru["earliest_start"]:
        out.append(f"sono le {_hm(now)}: il rito non comincia prima delle {ru['earliest_start']}")
    latest = ru.get("latest_end")
    if latest:
        end = now + timedelta(seconds=p["longest_s"])
        if _hm(now) > latest:
            out.append(f"sono le {_hm(now)}, oltre le {latest}: oggi il rito non comincia più")
        elif end.date() > now.date() or _hm(end) > latest:
            out.append(f"potrebbe finire alle {_hm(end)}, oltre le {latest}")
    gap = _num(ru.get("min_hours_between"))
    last = _last_session_end(base) if gap else None
    if last is not None and (now - last.astimezone(now.tzinfo)).total_seconds() < gap * 3600:
        out.append(f"l'ultima sauna è finita alle {_hm(last)} del {last.day}/{last.month}: fra una e l'altra almeno {gap:g} ore")
    peak_max = _num(ru.get("wod_peak_max_bpm"))
    peak = _wod_peak(base, today) if peak_max else None
    if peak is not None and peak > peak_max:
        out.append(f"oggi l'allenamento è salito a {peak:g} battiti (oltre {peak_max:g}): stasera niente sauna")

    return out + _judgement_errors(r, ru)


def _judgement_errors(r: dict, ru: dict) -> list[str]:
    out = []
    th = r.get("threshold")
    declared = {str(t.get("id")): t for t in (th if isinstance(th, list) else []) if isinstance(t, dict)}
    for j in ru["judgement"]:
        t = declared.get(j["id"])
        label = j.get("text") or j["id"]
        if not t:
            out.append(f"soglia non dichiarata: «{label}» (il Maestro lo verifica e lo scrive in threshold)")
        elif t.get("ok") is not True:
            out.append(f"soglia non passata: «{label}»" + (f" — {t['note']}" if t.get("note") else ""))
    return out


def _no_constants(name: str) -> float:
    raise ValueError(f"{name} non è un numero ammesso")


def read_rito(path: str | Path) -> Any:
    """Legge una partitura come la leggerà il telefono: niente NaN o Infinity."""
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_no_constants)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 1
    if not (data_root() / "data" / "profile.json").exists():
        print(f"La soglia resta chiusa: {data_root()} non è un repo dati (manca data/profile.json; "
              "lancia dal repo dati o imposta WELLNESS_DATA)", file=sys.stderr)
        return 3
    try:
        r = read_rito(sys.argv[1])
    except (OSError, ValueError) as e:
        print(f"Rito illeggibile: {e}", file=sys.stderr)
        return 3
    errs = check(r)
    if errs:
        print("La soglia resta chiusa:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 3
    p = planned(r)
    print(f"OK — {p['rounds']} passaggi, calore {p['heat_s'] / 60:g}′ (al massimo {p['heat_max_s'] / 60:g}′), "
          f"riposo {p['rest_s'] / 60:g}′, circa {p['total_s'] / 60:.0f}′ in tutto"
          + (" — PROVA A SECCO (demo): non conta come seduta" if r.get("demo") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
