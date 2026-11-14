#!/usr/bin/env python3.12
"""Blocco deterministico: una seduta con un esercizio vietato non parte.

    python3.12 workout_guard.py data/coach-longevita/daily/YYYY-MM-DD.player.json   # exit 3 se vietata

Due fonti di divieti, entrambe nel repo dati:
- personali — `data/coach-longevita/state.json` → `preference_book.no_rules`:
    [{"match": ["running", "run"], "max_min": 30, "why": "corsa lunga: dolori alle ginocchia"}]
  `match` = slug del catalogo o nome: scatta se i suoi token compaiono contigui nel nome o nell'`img`
  dell'esercizio (plurali e qualificatori inclusi). Senza `max_min` l'esercizio è vietato sempre; con
  `max_min` oltre quei minuti sommati su tutta la seduta (stima prudente; durata ignota = 0).
  `preference_book.no` resta il testo libero letto dal coach; il blocco legge solo `no_rules`.
- fase di vita — `data/profile.json` → `life_phase`, incrociata con `knowledge/life-phases.json`
  del plugin (limiti di sicurezza: la persona li stringe, non li allarga).

Un file di regole presente ma illeggibile blocca la seduta (prudenza), non spegne il controllo.

Lo chiamano il tool `telegram_send_player` di Hṛdaya e `workout_send.py`: il coach può sbagliare
la scheda, il canale no.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PHASES = HERE.parent / "knowledge" / "life-phases.json"
RUN_MIN_PER_KM = 6.0          # stima prudente per tradurre una distanza di corsa in minuti


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def data_root(root: str | Path | None = None) -> Path:
    return Path(root or os.environ.get("WELLNESS_DATA") or os.getcwd())


class Unreadable(Exception):
    """File di regole presente ma illeggibile: il blocco non si spegne in silenzio."""


def _json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Unreadable(f"{p.name} illeggibile ({e.__class__.__name__})") from e
    if not isinstance(d, dict):
        raise Unreadable(f"{p.name} non è un oggetto JSON")
    return d


ALIASES = {"du": "double-under", "dus": "double-under", "t2b": "toe-to-bar", "ttb": "toe-to-bar",
           "situp": "sit-up", "situps": "sit-up", "jogging": "jog", "burpie": "burpee"}


def _sing(t: str) -> str:
    return t[:-1] if len(t) >= 3 and t.endswith("s") and not t.endswith("ss") else t


def _toks(s: str) -> list[str]:
    out: list[str] = []
    for t in slug(s).split("-"):
        if t:
            out += ALIASES.get(t, t).split("-")
    return [_sing(t) for t in out]


def _contains(hay: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


def matches(ex: dict, tokens: list[str] | str) -> bool:
    """La regola scatta se i token di una voce compaiono contigui nel nome o nello slug `img`
    (plurali, alias e qualificatori inclusi: «Easy Run», «Burpees», «AbMat Sit-up», «T2B»)."""
    if isinstance(tokens, str):
        tokens = [tokens]
    fields = [_toks(str(ex.get(k) or "")) for k in ("img", "name")]
    return any(_contains(f, _toks(t)) for t in tokens if t for f in fields)


def _num(v: Any) -> float | None:
    try:
        return float(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


def _per_occurrence(ex: dict) -> float | None:
    """Minuti di una singola esecuzione: `time_s`, «12 min» nel testo, distanza (anche «2 x 5 km»)."""
    t = _num(ex.get("time_s"))
    if t is not None:
        return t / 60
    text = f"{ex.get('reps', '')} {ex.get('name', '')}"
    mult = re.search(r"(\d+)\s*[x×]\s*\d", text, re.I)
    k = float(mult.group(1)) if mult else 1.0
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:min\b|minut|′|')", text, re.I)
    if m:
        return k * float(m.group(1).replace(",", "."))
    d = re.search(r"(\d+(?:[.,]\d+)?)\s*(km|m)\b", text, re.I)
    if d:
        v = float(d.group(1).replace(",", "."))
        return k * (v if d.group(2).lower() == "km" else v / 1000) * RUN_MIN_PER_KM
    return None


def minutes(ex: dict, block: dict) -> float | None:
    """Stima prudente dei minuti dell'esercizio nel blocco: la più alta fra quelle ricavabili;
    None se non si ricava nulla."""
    exs = [e for e in (block.get("exercises") or []) if isinstance(e, dict)] or [ex]
    k = len(exs)
    n = int(_num(block.get("rounds")) or _num(block.get("sets")) or 1)
    per = _per_occurrence(ex)
    t = block.get("type")
    est: list[float] = []
    if t == "emom" and _num(block.get("minutes")):
        iv = (_num(block.get("interval_s")) or 60) / 60
        occ = _num(block["minutes"]) / iv / k
        est.append(occ * (min(per, iv) if per is not None else iv))
    elif t == "interval" and _num(block.get("work_s")):
        est.append(_num(block["work_s"]) * n / 60)
    elif t in ("amrap", "fortime", "timed"):
        cap = _num(block.get("duration_s") if t != "fortime" else block.get("cap_s"))
        if cap:
            est.append(cap / 60 / k)
    if per is not None:
        est.append(per * (n if t in ("sets", "fortime", "interval") or t is None else 1))
    return max(est) if est else None


def _months_since(iso: str | None, today: date) -> float | None:
    try:
        d = datetime.fromisoformat(str(iso)).date()
    except ValueError:
        return None
    return (today - d).days / 30.44


def _d(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def active_conditions(profile: dict, today: date | None = None) -> set[str]:
    """Condizioni della fase di vita che accendono le regole di knowledge/life-phases.json."""
    lp = profile.get("life_phase")
    if lp is None:
        return set()
    if isinstance(lp, str):
        lp = {"stage": lp}
    if not isinstance(lp, dict):
        raise Unreadable("profile.json → life_phase non leggibile")
    today = today or date.today()
    on: set[str] = set()
    stage = slug(str(lp.get("stage") or ""))
    if any(r in stage for r in ("gravid", "incinta", "pregnan")):
        on.add("pregnancy")
    pf = _d(lp.get("pelvic_floor"))
    cleared = bool(pf.get("cleared_by_physio"))
    if pf.get("symptoms") and not cleared:
        on.add("pelvic_floor_symptoms")
    postpartum = any(r in stage for r in ("postpartum", "post-partum", "postparto", "puerperio"))
    since = lp.get("postpartum_since")
    m = _months_since(since, today) if since else None
    if not cleared and ((m is not None and m < 3) or (postpartum and m is None)):
        on.add("postpartum_lt_12w")          # postparto senza data: prudenza finché non c'è la data
    if _d(lp.get("bone")).get("vertebral_fracture"):
        on.add("vertebral_fracture")
    return on


def rules(root: str | Path | None = None, today: date | None = None) -> list[dict]:
    """Regole attive. Solleva Unreadable se un file di regole c'è ma non si legge."""
    r = data_root(root)
    state = _json(r / "data" / "coach-longevita" / "state.json")
    out = [{**x, "source": "preferenze"} for x in (_d(state.get("preference_book")).get("no_rules") or [])
           if isinstance(x, dict) and x.get("match")]
    on = active_conditions(_json(r / "data" / "profile.json"), today)
    for x in _json(PHASES).get("rules") or []:
        if x.get("condition") in on:
            out.append({**x, "source": f"fase di vita: {x['condition']}"})
    return out


def check(w: dict, root: str | Path | None = None, today: date | None = None) -> list[str]:
    """Violazioni della seduta (lista vuota = può partire). I limiti di durata valgono sulla
    seduta intera: tre blocchi di Run da 25′ sono 75′ di corsa."""
    try:
        rs = rules(root, today)
    except Unreadable as e:
        return [f"{e}: blocco prudenziale finché non si sistema"]
    out: list[str] = []
    for x in rs:
        if x.get("block_all"):
            out.append(f"{x.get('why', 'seduta non programmabile')} ({x['source']})")
    for x in rs:
        if not x.get("match"):
            continue
        lim = _num(x.get("max_min"))
        total, names = 0.0, []
        for b in w.get("blocks") or []:
            if not isinstance(b, dict):
                continue
            for ex in b.get("exercises") or []:
                if not isinstance(ex, dict) or not matches(ex, x["match"]):
                    continue
                if lim is None:
                    out.append(f"{ex.get('name')} vietato — {x.get('why', '')} ({x['source']})")
                    continue
                total += minutes(ex, b) or 0.0
                if ex.get("name") not in names:
                    names.append(ex.get("name"))
        if lim is not None and total > lim:
            out.append(f"{', '.join(map(str, names))} ~{total:.0f}′ in tutto, oltre {lim:g}′ — "
                       f"{x.get('why', '')} ({x['source']})")
    return out


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 1
    errs = check(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    if errs:
        print("Seduta bloccata:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 3
    print("OK — nessun esercizio vietato")
    return 0


if __name__ == "__main__":
    sys.exit(main())
