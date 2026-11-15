#!/usr/bin/env python3.12
"""Le cose da loggare: il registro di Hṛdaya, con le domande a bottoni e i nudge.

Una voce la decide la persona o la propone il consiglio (un ask, un agente): cosa registrare,
per quanti giorni, in quale momento della giornata, e cosa succede alla fine. Hṛdaya sceglie il
canale e il modo, il meno invasivo possibile:

  - se il dato c'è già (nel registro o nel diario) non chiede
  - chiede quando si apre un momento che c'è comunque: il mattino dopo il messaggio dell'alzata,
    la sera dopo quello della sera; mai di notte; un messaggio solo per momento, che passa da una
    domanda all'altra (ogni tocco registra, «Salta» sempre possibile, mai serie di giorni né colpe)
  - una voce ignorata per tre giorni di fila non insiste: chiede se continuare; se anche quella
    domanda resta senza risposta, la voce va in pausa da sola
  - una proposta (del consiglio) parte all'apertura di un momento, una volta, con Sì / No
  - a fine voce (scaduta, con almeno un giorno registrato) la sessione propone il `followup`

data/hridaya/log_plan.json:
  {"items": {"<id>": {
      "title", "why", "origin", "status": "proposed"|"active"|"paused"|"closed"|"declined",
      "when": "morning"|"evening", "days": 7, "start"?, "end"?,
      "fields": [{"key", "ask", "options": [...] | [[...]], "target": "bowel.bristol",
                  "skip_when"?: {"<altra key>": ["etichetta", ...]}}],
      "followup"?: {"action": "council"|"ask"|"review", "question", "cost"?},
      "asked": {day: ts}, "skipped": {day: [key]}, "answers": {day: {key: valore}},
      "streak_from"?, "continue_asked"?, "paused_at"?, "closed_reason"?, "followup_cued": [day],
      "proposed_at"?, "followup_done"?, "created_at"}},
   "asks": {"<tok>": {"kind": "field"|"continue"|"propose", "item", "field"?, "day", "scope"?}},
   "opened": {"morning": day, "evening": day}}
Le risposte stanno nel registro (`answers`, sotto lock: fonte di verità) e nel diario del giorno
al path `target`; un giro di riconciliazione riscrive nel diario quelle che mancano.
callback_data: "lg:<tok>:<i>".

    log_plan.py list
    log_plan.py add SPEC.json [--active]      # default: proposta
    log_plan.py set ID active|paused|closed
    log_plan.py missing [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import channel_config as cc  # noqa: E402
import telegram_queue as tq  # noqa: E402

WINDOWS = ("morning", "evening")
WHEN_TEXT = {"morning": "la mattina, dopo il messaggio del risveglio",
             "evening": "la sera, dopo il messaggio della sera"}
FOLLOWUP_ACTIONS = ("council", "ask", "review")
IGNORED_DAYS = 3
CONTINUE_WAIT_DAYS = 2      # «continuo?» senza risposta per due giorni → pausa
FOLLOWUP_MAX_CUES = 2
SKIP = "Salta"
CONTINUE = ["Sì, continua", "Pausa", "Basta così"]
PROPOSE = ["Sì", "No"]
MAX_OPTIONS = 11            # + «Salta»
MAX_LABEL = 40
LIMITS = {"title": 80, "why": 240, "origin": 80, "ask": 300}
RESERVED_ROOTS = {"date", "notes", "morning", "goals_tracking", "fitbit", "location"}
EVENING_FROM = "18:00"      # /diario: le domande della sera da quest'ora
ASK_KEEP_DAYS = 14
DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class PlanError(ValueError):
    pass


# --- stato ---------------------------------------------------------------------------

def path() -> Path:
    return cc.data_root().resolve() / "data" / "hridaya" / "log_plan.json"


def load() -> dict:
    try:
        st = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    if not isinstance(st, dict):
        st = {}
    st.setdefault("items", {})
    st.setdefault("asks", {})
    st.setdefault("opened", {})
    return st


def _dump(st: dict) -> str:
    return json.dumps(st, ensure_ascii=False, indent=1) + "\n"


def save(st: dict) -> None:
    cutoff = (date.today() - timedelta(days=ASK_KEEP_DAYS)).isoformat()
    st["asks"] = {k: v for k, v in st["asks"].items() if v.get("day", "") >= cutoff}
    _atomic(path(), _dump(st))


def _atomic(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)


def _update(fn):
    """fn(st) sotto il lock della coda; si salva solo se lo stato è cambiato."""
    with tq.locked():
        st = load()
        before = _dump(st)
        out = fn(st)
        if _dump(st) != before:
            save(st)
    return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(cc.tz()).date().isoformat()


def _day(s: Any) -> str:
    if not (isinstance(s, str) and DAY_RE.fullmatch(s)):
        raise PlanError("data: YYYY-MM-DD")
    try:
        date.fromisoformat(s)
    except ValueError as e:
        raise PlanError("data: YYYY-MM-DD") from e
    return s


def _plus(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


# --- diario --------------------------------------------------------------------------

class Unreadable(PlanError):
    """Il diario del giorno c'è ma non si legge: non si riscrive (si perderebbe la giornata)."""


def log_path(day: str) -> Path:
    return cc.data_root() / "data" / "logs" / f"{day}.json"


def read_log(day: str, strict: bool = False) -> dict:
    p = log_path(day)
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        if strict:
            raise Unreadable(f"diario del {day} illeggibile ({e.__class__.__name__})") from e
        return {}
    if not isinstance(d, dict):
        if strict:
            raise Unreadable(f"diario del {day} non è un oggetto")
        return {}
    return d


def _get(d: dict, dotted: str) -> Any:
    for k in dotted.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _set(d: dict, dotted: str, value: Any) -> None:
    ks = dotted.split(".")
    for k in ks[:-1]:
        nxt = d.get(k)
        if not isinstance(nxt, dict):
            nxt = {} if _empty(nxt) else {"nota": nxt}   # un testo libero lì non si perde
            d[k] = nxt
        d = nxt
    d[ks[-1]] = value


def _write_log(day: str, writes: list[tuple[dict, dict, str]]) -> None:
    """Scrive nel diario le risposte che mancano (chiamare sotto tq.locked). Un campo già pieno
    non si tocca; un diario illeggibile non si riscrive (Unreadable)."""
    log = read_log(day, strict=True) or {"date": day, "morning": {}, "goals_tracking": []}
    lines = []
    for it, f, value in writes:
        if not _empty(_get(log, f["target"])):
            continue
        _set(log, f["target"], value)
        lines.append(f"[diario {datetime.now(cc.tz()):%H:%M}] {it['title']}: {f['ask']} → {value}")
    if not lines:
        return
    prev = log.get("notes")
    if _empty(prev) or isinstance(prev, str):
        log["notes"] = "\n".join(([prev] if prev else []) + lines)
    elif isinstance(prev, list):
        prev.extend(lines)
    _atomic(log_path(day), json.dumps(log, indent=2, ensure_ascii=False) + "\n")


def _answer(st: dict, iid: str, key: str, value: str, day: str) -> bool:
    """Registra la risposta (registro + diario). False se c'era già."""
    it = st["items"][iid]
    f = next(f for f in it["fields"] if f["key"] == key)
    ans = it.setdefault("answers", {}).setdefault(day, {})
    if key in ans or not _empty(_get(read_log(day), f["target"])):
        return False
    _write_log(day, [(it, f, value)])          # prima il diario: se è illeggibile, niente di registrato
    ans[key] = value
    return True


def reconcile(st: dict, days: list[str]) -> None:
    """Riscrive nel diario le risposte del registro che mancano (diario riscritto da un altro)."""
    for day in days:
        writes = []
        log = read_log(day)
        for it in st["items"].values():
            for key, value in ((it.get("answers") or {}).get(day) or {}).items():
                f = next((f for f in it["fields"] if f["key"] == key), None)
                if f and _empty(_get(log, f["target"])):
                    writes.append((it, f, value))
        if writes:
            try:
                _write_log(day, writes)
            except (Unreadable, OSError):
                pass


# --- voci ----------------------------------------------------------------------------

_KEYCAP = re.compile(r"^(?:[0-9#*]\uFE0F?\u20E3\s*)+")


def _pictograph(c: str) -> bool:
    o = ord(c)
    return (o in (0xFE0F, 0x200D, 0x20E3) or 0x1F3FB <= o <= 0x1F3FF or 0x1F1E6 <= o <= 0x1F1FF
            or (o >= 0x2190 and unicodedata.category(c) == "So"))


def clean(label: str) -> str:
    """L'icona davanti a un'etichetta serve all'occhio, non al diario: «🍌 3-4 formate» → «3-4 formate».
    Toglie solo i pittogrammi in testa: segni e numeri («< 5», «-1», «.5 L») restano."""
    s = _KEYCAP.sub("", str(label).strip())
    i = 0
    while i < len(s) and (s[i].isspace() or _pictograph(s[i])):
        i += 1
    return s[i:].strip() or str(label).strip()


def _rows(options: Any) -> list[list[str]]:
    if not isinstance(options, list) or not options:
        raise PlanError("options: lista non vuota di etichette (o di righe)")
    rows = ([options[i:i + 4] for i in range(0, len(options), 4)] if all(isinstance(o, str) for o in options)
            else options)
    if not all(isinstance(r, list) and r and all(isinstance(o, str) for o in r) for r in rows):
        raise PlanError("options: o tutte stringhe o tutte righe di stringhe")
    flat = [o.strip() for r in rows for o in r]
    if len(flat) > MAX_OPTIONS or len({clean(o) for o in flat}) != len(flat) or SKIP in flat:
        raise PlanError(f"options: al massimo {MAX_OPTIONS}, senza ripetizioni né «{SKIP}» (lo aggiungo io)")
    if any(not o or len(o) > MAX_LABEL for o in flat):
        raise PlanError(f"options: etichette da 1 a {MAX_LABEL} caratteri")
    return [[o.strip() for o in r] for r in rows]


def _text(item: dict, k: str, required: bool = False) -> str:
    v = str(item.get(k) or "").strip()
    if required and not v:
        raise PlanError(f"{k} mancante")
    if len(v) > LIMITS[k]:
        raise PlanError(f"{k}: al massimo {LIMITS[k]} caratteri")
    return v


def validate(item: Any) -> dict:
    """Spec pulita o PlanError."""
    if not isinstance(item, dict):
        raise PlanError("la voce è un oggetto")
    title = _text(item, "title", required=True)
    when = item.get("when", "morning")
    if when not in WINDOWS:
        raise PlanError(f"when: {' | '.join(WINDOWS)}")
    days = item.get("days")
    if not (isinstance(days, int) and not isinstance(days, bool) and 1 <= days <= 120):
        raise PlanError("days: intero da 1 a 120")
    fields = item.get("fields")
    if not isinstance(fields, list) or not fields or len(fields) > 8:
        raise PlanError("fields: da 1 a 8 domande")
    out_f, keys, targets = [], set(), []
    for f in fields:
        if not isinstance(f, dict) or not f.get("key") or not f.get("ask") or not f.get("target"):
            raise PlanError("ogni field vuole key, ask, target")
        key, target = str(f["key"]), str(f["target"])
        if key in keys:
            raise PlanError(f"key ripetuta: {key}")
        if not re.fullmatch(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)+", target):
            raise PlanError(f"target non valido: {target} (path a punti con almeno due livelli, "
                            "es. bowel.bristol)")
        if target.split(".")[0] in RESERVED_ROOTS:
            raise PlanError(f"target: {target.split('.')[0]} è riservato del diario")
        if any(t == target or t.startswith(target + ".") or target.startswith(t + ".") for t in targets):
            raise PlanError(f"target sovrapposti: {target}")
        keys.add(key)
        targets.append(target)
        g = {"key": key, "ask": _text(f, "ask", required=True), "options": _rows(f.get("options")),
             "target": target}
        if f.get("skip_when"):
            sw = f["skip_when"]
            if not isinstance(sw, dict) or not all(isinstance(v, list) for v in sw.values()):
                raise PlanError("skip_when: {key: [etichette]}")
            g["skip_when"] = sw
        out_f.append(g)
    start = item.get("start")
    if start:
        start = _day(start)
    fu = item.get("followup")
    if fu is not None and not (isinstance(fu, dict) and fu.get("action") in FOLLOWUP_ACTIONS and fu.get("question")):
        raise PlanError(f"followup: {{action: {'|'.join(FOLLOWUP_ACTIONS)}, question, cost?}} oppure niente")
    return {"title": title, "why": _text(item, "why"), "origin": _text(item, "origin"),
            "when": when, "days": days, **({"start": start} if start else {}), "fields": out_f,
            **({"followup": fu} if fu else {})}


def _new_id(title: str, items: dict) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:32] or "voce"
    i, k = base, 2
    while i in items:
        i, k = f"{base}-{k}", k + 1
    return i


def _activate(it: dict, today: str) -> None:
    start = max(today, it.get("start") or today)
    it.update(status="active", start=start, end=_plus(start, it["days"] - 1), activated_at=_now())


def add(item: Any, proposed: bool = True, today: str | None = None) -> str:
    spec = validate(item)
    today = today or _today()

    def fn(st):
        for iid, it in st["items"].items():
            if it.get("status") in ("proposed", "active", "paused") and \
                    it["title"].casefold() == spec["title"].casefold():
                raise PlanError(f"c'è già una voce «{it['title']}» ({iid}, {it['status']})")
        iid = _new_id(spec["title"], st["items"])
        it = {**spec, "status": "proposed", "asked": {}, "skipped": {}, "answers": {}, "created_at": _now()}
        if not proposed:
            _activate(it, today)
        st["items"][iid] = it
        return iid
    return _update(fn)


def _resume(it: dict, today: str) -> None:
    """Ripresa dopo pausa o chiusura: la fine si sposta dei giorni di stop."""
    since = it.pop("paused_at", None) or it.get("closed_on") or today
    gap = max(0, (date.fromisoformat(today) - date.fromisoformat(min(since, today))).days)
    it["end"] = max(_plus(it["end"], gap), today)
    it.update(status="active", streak_from=today)
    for k in ("continue_asked", "closed_at", "closed_on", "closed_reason", "followup_done"):
        it.pop(k, None)
    it["followup_cued"] = []


def set_status(iid: str, status: str, today: str | None = None) -> dict:
    if status not in ("active", "paused", "closed"):
        raise PlanError("status: active | paused | closed")
    today = today or _today()

    def fn(st):
        it = st["items"].get(iid)
        if not it:
            raise PlanError(f"voce sconosciuta: {iid}")
        if status == "active":
            if it.get("status") in ("proposed", "declined"):
                _activate(it, today)
            elif it.get("status") in ("paused", "closed"):
                _resume(it, today)
        elif status == "paused" and it.get("status") == "active":
            it.update(status="paused", paused_at=today)
        elif status == "closed" and it.get("status") != "closed":
            it.update(status="closed", closed_at=_now(), closed_on=today, closed_reason="manual")
        return it
    return _update(fn)


def record(iid: str, key: str, value: str, day: str) -> bool:
    """Una risposta data a parole (la sessione l'ha letta in un messaggio). False se c'era già."""
    if not str(value).strip():
        raise PlanError("value vuoto")
    day = _day(day)

    def fn(st):
        it = st["items"].get(iid)
        if not it or not any(f["key"] == key for f in it["fields"]):
            raise PlanError(f"voce o key sconosciuta: {iid}.{key}")
        return _answer(st, iid, key, clean(str(value)), day)
    return _update(fn)


def followup_done(iid: str) -> None:
    def fn(st):
        it = st["items"].get(iid)
        if not it:
            raise PlanError(f"voce sconosciuta: {iid}")
        it["followup_done"] = _now()
    _update(fn)


def in_range(it: dict, day: str) -> bool:
    return it.get("status") == "active" and it.get("start", "9") <= day <= it.get("end", "0")


def day_of(it: dict, day: str) -> tuple[int, int]:
    return (date.fromisoformat(day) - date.fromisoformat(it["start"])).days + 1, it["days"]


def missing(it: dict, day: str, log: dict | None = None) -> list[int]:
    """Indici dei field ancora senza risposta (registro o diario), salti esclusi."""
    log = read_log(day) if log is None else log
    skipped = set((it.get("skipped") or {}).get(day) or [])
    ans = (it.get("answers") or {}).get(day) or {}
    vals = {f["key"]: ans.get(f["key"], _get(log, f["target"])) for f in it["fields"]}
    out = []
    for i, f in enumerate(it["fields"]):
        if f["key"] in skipped or not _empty(vals[f["key"]]):
            continue
        if any(vals.get(k) is not None and clean(str(vals.get(k))) in {clean(x) for x in labels}
               for k, labels in (f.get("skip_when") or {}).items()):
            continue
        out.append(i)
    return out


def _untouched(it: dict, day: str) -> bool:
    return len(missing(it, day)) == len(it["fields"]) and not (it.get("skipped") or {}).get(day)


def ignored_streak(it: dict, today: str) -> int:
    """Giorni di fila (prima di oggi) in cui la voce è stata chiesta e niente è stato registrato."""
    n, d = 0, date.fromisoformat(today) - timedelta(days=1)
    floor = max(it.get("start", today), it.get("streak_from", ""))
    while d.isoformat() >= floor:
        day = d.isoformat()
        if day not in (it.get("asked") or {}) or not _untouched(it, day):
            break
        n += 1
        d -= timedelta(days=1)
    return n


def recorded_days(it: dict) -> int:
    """Giorni con almeno una risposta (nel registro o nel diario)."""
    if not it.get("start") or not it.get("end"):
        return 0
    n, d = 0, it["start"]
    while d <= it["end"]:
        log, ans = read_log(d), (it.get("answers") or {}).get(d) or {}
        if ans or any(not _empty(_get(log, f["target"])) for f in it["fields"]):
            n += 1
        d = _plus(d, 1)
    return n


def close_expired(st: dict, today: str) -> list[str]:
    """Voci attive o in pausa oltre la fine → chiuse; «continuo?» senza risposta → pausa."""
    out = []
    for iid, it in st["items"].items():
        if it.get("status") in ("active", "paused") and it.get("end") and it["end"] < today:
            it.update(status="closed", closed_at=_now(), closed_on=today, closed_reason="expired")
            out.append(iid)
        elif it.get("status") == "active" and it.get("continue_asked") and \
                _plus(it["continue_asked"], CONTINUE_WAIT_DAYS) <= today:
            it.update(status="paused", paused_at=today)
            it.pop("continue_asked", None)
    return out


def followups_due(st: dict | None = None) -> list[str]:
    st = st or load()
    return [iid for iid, it in st["items"].items()
            if it.get("status") == "closed" and it.get("closed_reason") == "expired" and it.get("followup")
            and not it.get("followup_done") and len(it.get("followup_cued") or []) < FOLLOWUP_MAX_CUES
            and recorded_days(it) > 0]


def followup_cued(iid: str, day: str) -> None:
    def fn(st):
        it = st["items"].get(iid)
        if it and day not in (it.get("followup_cued") or []):
            it.setdefault("followup_cued", []).append(day)
    _update(fn)


# --- messaggi ------------------------------------------------------------------------

def _token(st: dict, **ask) -> str:
    tok = uuid.uuid4().hex[:10]
    st["asks"][tok] = {**ask, "created_at": _now()}
    return tok


def _kb(tok: str, rows: list[list[str]]) -> dict:
    i, kb = 0, []
    for r in rows:
        kb.append([{"text": o, "callback_data": f"lg:{tok}:{j}"} for j, o in enumerate(r, start=i)])
        i += len(r)
    return {"inline_keyboard": kb}


def _field_msg(st: dict, iid: str, fi: int, day: str, scope: list[str]) -> dict:
    it = st["items"][iid]
    f = it["fields"][fi]
    k, n = day_of(it, day)
    tok = _token(st, kind="field", item=iid, field=fi, day=day, scope=scope)
    text = f"📋 <b>{html.escape(it['title'])}</b> · giorno {k} di {n}\n{html.escape(f['ask'])}"
    return {"text": text, "markup": _kb(tok, f["options"] + [[SKIP]]), "item": iid, "day": day, "tok": tok}


def _pairs(st: dict, day: str, scope: list[str]) -> list[tuple[str, int]]:
    """(voce, field) ancora da chiedere, per le voci dei momenti in `scope`."""
    log = read_log(day)
    out = []
    for iid, it in st["items"].items():
        if in_range(it, day) and it.get("when") in scope:
            out += [(iid, fi) for fi in missing(it, day, log)]
    return out


def _last_call(cfg: dict) -> str | None:
    """Un minuto prima dell'ora di letto, se l'ora di letto è di sera (come l'ultima chiamata del cancello)."""
    bed = cfg.get("bedtime") or ""
    if not re.fullmatch(r"\d{2}:\d{2}", bed) or bed < "12:00":
        return None
    t = datetime.strptime(bed, "%H:%M") - timedelta(minutes=1)
    return t.strftime("%H:%M")


def window_open(window: str, now: datetime, cfg: dict, gate: dict) -> bool:
    """Il momento è aperto se il messaggio che lo apre è partito (o non partirà più).
    La notte la esclude chi chiama (`silent`)."""
    today, hhmm = now.date().isoformat(), now.strftime("%H:%M")
    if window == "morning":
        return today in (gate.get("wake_sent"), gate.get("wake_skipped")) or hhmm >= cfg["wake"]["late_cutoff"]
    last = _last_call(cfg)
    return today in (gate.get("evening_sent"), gate.get("evening_skipped")) or bool(last and hhmm >= last)


def due_messages(now: datetime, cfg: dict, gate: dict, silent: bool) -> list[dict]:
    """Cosa mandare adesso, solo all'apertura di un momento (primo giro in cui lo si vede aperto):
    proposte, «continuo?», domande. Già segnato come chiesto; chi spedisce, se fallisce, `undo(msg)`."""
    if silent:
        return []
    today = now.date().isoformat()

    def fn(st):
        close_expired(st, today)
        reconcile(st, [_plus(today, -1), today])
        fresh = [w for w in WINDOWS if window_open(w, now, cfg, gate) and st["opened"].get(w) != today]
        for w in fresh:
            st["opened"][w] = today
        if fresh == list(WINDOWS):          # bot fermo tutto il giorno: il mattino è passato
            fresh = ["evening"]
        out = []
        if fresh:
            for iid, it in st["items"].items():
                if it.get("status") == "proposed" and not it.get("proposed_at"):
                    it["proposed_at"] = _now()
                    tok = _token(st, kind="propose", item=iid, day=today)
                    origin = f" ({html.escape(it['origin'])})" if it.get("origin") else ""
                    why = f"\n<i>{html.escape(it['why'])}</i>" if it.get("why") else ""
                    out.append({"text": f"📋 Proposta{origin}: <b>{html.escape(it['title'])}</b> per {it['days']} "
                                        f"giorni.{why}\nTe lo chiedo io {WHEN_TEXT[it['when']]}, con i bottoni. "
                                        "Lo attivo?",
                                "markup": _kb(tok, [PROPOSE]), "item": iid, "kind": "propose", "window": fresh[0],
                                "tok": tok})
        for w in fresh:
            group = [iid for iid, it in st["items"].items()
                     if in_range(it, today) and it.get("when") == w and today not in (it.get("asked") or {})]
            for iid in list(group):
                it = st["items"][iid]
                if not it.get("continue_asked") and ignored_streak(it, today) >= IGNORED_DAYS:
                    it.setdefault("asked", {})[today] = _now()
                    it["continue_asked"] = today
                    group.remove(iid)
                    tok = _token(st, kind="continue", item=iid, day=today)
                    out.append({"text": f"📋 <b>{html.escape(it['title'])}</b>: negli ultimi giorni non l'hai "
                                        "registrato, e va bene. Continuo a chiedertelo?",
                                "markup": _kb(tok, [CONTINUE]), "item": iid, "day": today, "kind": "continue",
                                "window": w, "tok": tok})
                elif it.get("continue_asked"):
                    group.remove(iid)            # in attesa della risposta al «continuo?»
            pairs = [p for p in _pairs(st, today, [w]) if p[0] in group]
            for iid in group:
                st["items"][iid].setdefault("asked", {})[today] = _now()
            if pairs:
                m = _field_msg(st, pairs[0][0], pairs[0][1], today, [w])
                out.append({**m, "group": group, "window": w})
        return out
    return _update(fn)


def ask_scope(now: datetime) -> list[str]:
    """/diario: il mattino sempre (ha scritto lui), la sera dalle 18."""
    return ["morning"] + (["evening"] if now.strftime("%H:%M") >= EVENING_FROM else [])


def ask_now(day: str | None = None, scope: list[str] | None = None) -> dict | None:
    """Domanda su richiesta (/diario, la sessione): le voci di quei momenti ancora aperte oggi.
    Non segna nulla come chiesto: è una sua richiesta, non un nudge."""
    day = day or _today()
    scope = scope or list(WINDOWS)

    def fn(st):
        pairs = _pairs(st, day, scope)
        if not pairs:
            return None
        return _field_msg(st, pairs[0][0], pairs[0][1], day, scope)
    return _update(fn)


def open_count(day: str, scope: list[str]) -> int:
    """Quante domande il registro farebbe adesso (per il bottone «Registra» di /diario)."""
    return len(_pairs(load(), day, scope))


def answered_today(day: str) -> bool:
    return any((it.get("answers") or {}).get(day) for it in load()["items"].values())


def undo(msg: dict) -> None:
    """Il messaggio non è partito: si richiederà al prossimo giro."""
    def fn(st):
        st["asks"].pop(msg.get("tok"), None)
        if msg.get("window"):            # il momento si riapre: riparte solo ciò che non è segnato
            st["opened"].pop(msg["window"], None)
        for iid in msg.get("group") or [msg.get("item")]:
            it = st["items"].get(iid)
            if not it:
                continue
            if msg.get("kind") == "propose":
                it.pop("proposed_at", None)
            elif msg.get("day"):
                (it.get("asked") or {}).pop(msg["day"], None)
                if msg.get("kind") == "continue":
                    it.pop("continue_asked", None)
    _update(fn)


STALE = {"action": "stale", "toast": "Questa domanda non vale più"}


def tap(data: str) -> dict:
    """Un tocco → {"action": "stale"|"next"|"done", "toast", "text"?, "markup"?}.
    Su stale il messaggio non si tocca (un doppio tocco non deve togliere i bottoni della domanda dopo)."""
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != "lg":
        return dict(STALE)
    tok, arg = parts[1], parts[2]

    def fn(st):
        a = st["asks"].get(tok)
        it = st["items"].get((a or {}).get("item"))
        if not a or not it:
            return dict(STALE)
        try:
            i = int(arg)
        except ValueError:
            return dict(STALE)
        title = html.escape(it["title"])
        if a["kind"] == "propose":
            if it.get("status") != "proposed" or i not in (0, 1):
                return dict(STALE)
            del st["asks"][tok]
            if i == 0:
                _activate(it, _today())
                return {"action": "done", "toast": "✓ Attivato",
                        "text": f"📋 <b>{title}</b>: attivo dal {_dm(it['start'])} al {_dm(it['end'])}. "
                                f"Te lo chiedo {WHEN_TEXT[it['when']]}; puoi anche scrivermelo quando vuoi."}
            it["status"] = "declined"
            return {"action": "done", "toast": "Va bene", "text": f"📋 <b>{title}</b>: non lo attivo."}
        if a["kind"] == "continue":
            if it.get("status") != "active" or i not in (0, 1, 2):
                return dict(STALE)
            del st["asks"][tok]
            it.pop("continue_asked", None)
            if i == 0:
                it["streak_from"] = _plus(a["day"], 1)     # i giorni fino al «continuo?» non contano più
                txt = "continuo, senza fretta."
            elif i == 1:
                it.update(status="paused", paused_at=_today())
                txt = "in pausa. Quando vuoi riprendere, dimmelo."
            else:
                it.update(status="closed", closed_at=_now(), closed_on=_today(), closed_reason="manual")
                txt = "chiuso."
            return {"action": "done", "toast": "✓", "text": f"📋 <b>{title}</b>: {txt}"}
        if not 0 <= a.get("field", -1) < len(it["fields"]):
            return dict(STALE)
        f = it["fields"][a["field"]]
        labels = [o for r in f["options"] for o in r] + [SKIP]
        if not 0 <= i < len(labels):
            return dict(STALE)
        day, scope = a["day"], a.get("scope") or list(WINDOWS)
        if labels[i] == SKIP:
            sk = it.setdefault("skipped", {}).setdefault(day, [])
            if f["key"] not in sk:
                sk.append(f["key"])
            toast = "Saltata"
        else:
            toast = f"✓ {labels[i]}" if _answer(st, a["item"], f["key"], clean(labels[i]), day) else "Già registrato"
        del st["asks"][tok]
        nxt = _pairs(st, day, scope)
        if nxt:
            m = _field_msg(st, nxt[0][0], nxt[0][1], day, scope)
            return {"action": "next", "toast": toast, "text": m["text"], "markup": m["markup"]}
        return {"action": "done", "toast": toast, "text": "📋 Registrato nel diario. Grazie."}
    try:
        return _update(fn)
    except Unreadable:
        return {"action": "stale", "toast": "Non riesco a leggere il diario di oggi: riprova fra poco"}


def _dm(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{x.day}/{x.month}"


def summary(day: str | None = None) -> list[str]:
    """Righe per /diario e per la sessione: le voci attive e cosa manca oggi."""
    day = day or _today()
    out = []
    for iid, it in load()["items"].items():
        if in_range(it, day):
            k, n = day_of(it, day)
            miss = [it["fields"][i]["key"].replace("_", " ") for i in missing(it, day)]
            out.append(f"{it['title']} (giorno {k} di {n}): " + (f"manca {', '.join(miss)}" if miss else "fatto"))
        elif it.get("status") == "proposed":
            out.append(f"{it['title']}: proposta, in attesa del sì")
        elif it.get("status") == "paused":
            out.append(f"{it['title']}: in pausa")
    return out


# --- CLI -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("add")
    a.add_argument("spec", help="file JSON della voce, o - per stdin")
    a.add_argument("--active", action="store_true", help="attiva subito (l'ha deciso la persona)")
    s = sub.add_parser("set")
    s.add_argument("id")
    s.add_argument("status", choices=["active", "paused", "closed"])
    m = sub.add_parser("missing")
    m.add_argument("--date")
    args = ap.parse_args()
    try:
        if args.cmd == "list":
            for iid, it in load()["items"].items():
                print(f"{iid}: {it['title']} — {it['status']}"
                      + (f" ({it['start']} → {it['end']})" if it.get("start") and it.get("end") else ""))
        elif args.cmd == "add":
            raw = sys.stdin.read() if args.spec == "-" else Path(args.spec).read_text(encoding="utf-8")
            print(add(json.loads(raw), proposed=not args.active))
        elif args.cmd == "set":
            set_status(args.id, args.status)
        elif args.cmd == "missing":
            print("\n".join(summary(_day(args.date) if args.date else None)) or "niente da registrare")
    except (PlanError, ValueError, OSError) as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
