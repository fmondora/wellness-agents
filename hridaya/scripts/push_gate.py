#!/usr/bin/env python3.12
"""Il cancello unico dei push di Hṛdaya.

Ogni messaggio d'iniziativa (detector, review dei coach, promemoria, messaggio della
sera, messaggio dopo l'alzata) passa da qui. Le **risposte** a un messaggio di
Francesco non passano dal cancello: lui ha scritto, lui è sveglio.

Regole:
1. **Silenzio** dall'ora di letto (config, `channel_config.rhythm()["bedtime"]`) fino
   all'alzata rilevata (`wake_detect.py`) o, se l'alzata non si vede, fino al fallback
   a orario (rinviato finché i dati al minuto dicono che dorme ancora).
2. **Red flag** (priority "red_flag") sempre subito, anche di notte.
3. **Fusione**: i push in attesa escono in un solo messaggio; quelli trattenuti
   nella notte si fondono col messaggio dopo l'alzata.
4. **Un messaggio della sera e uno dopo l'alzata al giorno** (idempotenti). Li scrive
   la sessione accesa; se non arrivano entro la scadenza parte il fallback
   deterministico di `morning_message.py`, marcato come automatico. Il messaggio
   della sera dopo l'ora di letto non parte più (niente sera al mattino).

File nel repo dati (`data/telegram/`, lock `.lock` condiviso con la coda):
  push.jsonl  richieste: {"id", "created_at", "source", "kind", "priority": "normal"|"red_flag",
              "text", "parse_mode"?, "card"?: {"steps", "base"}, "status": "pending"|"sending"|"sent",
              "meta": {...}, "sent_at"?, "merged_into"?}
              (scrittori esterni: health/scripts/push_request.py — stesso schema)
  gate.json   stato: {"wake": {"YYYY-MM-DD": {"at", "source", "recorded_at"}}, "wake_sent",
              "evening_sent", "evening_skipped", "last_fetch", "deferred"}

CLI:
  push_gate.py submit --text "..." [--source x] [--kind push] [--red-flag] [--card spec.json]
  push_gate.py status
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent))

import channel_config as cc  # noqa: E402
import telegram_queue as tq  # noqa: E402
import wake_detect as wd  # noqa: E402

AUTO_TAG = "🤖 automatico"


class Sender(Protocol):
    def text(self, text: str, parse_mode: str | None = None) -> None: ...
    def card(self, steps: list[dict], base: Path) -> None: ...


# --- file ------------------------------------------------------------------------

def push_path() -> Path:
    return tq.tg_dir() / "push.jsonl"


def state_path() -> Path:
    return tq.tg_dir() / "gate.json"


def load_state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    keep = sorted(st.get("wake", {}))[-14:]
    st["wake"] = {k: st["wake"][k] for k in keep}
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _update_state(fn: Callable[[dict], Any]) -> Any:
    with tq.locked():
        st = load_state()
        out = fn(st)
        save_state(st)
        return out


def submit(text: str, source: str, kind: str = "push", priority: str = "normal",
           meta: dict | None = None, push_id: str | None = None, parse_mode: str | None = None,
           card: dict | None = None, created_at: datetime | None = None) -> str:
    row = {"id": push_id or f"{source}-{uuid.uuid4().hex[:12]}",
           "created_at": (created_at or datetime.now(timezone.utc)).isoformat(), "source": source, "kind": kind,
           "priority": priority, "text": text, "status": "pending", "meta": meta or {}}
    if parse_mode:
        row["parse_mode"] = parse_mode
    if card:
        row["card"] = card
    with tq.locked():
        rows = tq.read_jsonl(push_path())
        if push_id and any(r.get("id") == push_id for r in rows):
            return push_id
        rows.append(row)
        tq.write_jsonl(push_path(), rows)
    return row["id"]


def _claim(pred: Callable[[dict], bool]) -> list[dict]:
    """Segna 'sending' le righe pending che soddisfano pred e le restituisce."""
    with tq.locked():
        rows = tq.read_jsonl(push_path())
        got = []
        for r in rows:
            if r.get("status") == "pending" and pred(r):
                r["status"] = "sending"
                got.append(dict(r))
        if got:
            tq.write_jsonl(push_path(), rows)
    return got


def _finish(ids: list[str], ok: bool, merged_into: str | None = None) -> None:
    with tq.locked():
        rows = tq.read_jsonl(push_path())
        now = datetime.now(timezone.utc).isoformat()
        for r in rows:
            if r.get("id") in ids and r.get("status") == "sending":
                if ok:
                    r.update(status="sent", sent_at=now)
                    if merged_into:
                        r["merged_into"] = merged_into
                else:
                    r["status"] = "pending"
        tq.write_jsonl(push_path(), rows)


# --- tempo ------------------------------------------------------------------------

def _at(d: date, hhmm: str, tzinfo) -> datetime:
    return datetime(d.year, d.month, d.day, int(hhmm[:2]), int(hhmm[3:5]), tzinfo=tzinfo)


def morning_of(now: datetime, cfg: dict) -> date:
    """Il mattino che segue l'ultima ora di letto passata."""
    bed = cfg["bedtime"]
    last = max(t for t in (_at(now.date(), bed, now.tzinfo), _at(now.date() - timedelta(days=1), bed, now.tzinfo))
               if t <= now)
    return last.date() if bed < "12:00" else last.date() + timedelta(days=1)


def fallback_at(m: date, cfg: dict, tzinfo, state: dict) -> datetime:
    return _at(m, cfg["wake"]["fallback"], tzinfo)


def is_silent(now: datetime, cfg: dict, state: dict) -> bool:
    m = morning_of(now, cfg)
    if m.isoformat() in (state.get("wake") or {}):
        return False
    if now < fallback_at(m, cfg, now.tzinfo, state):
        return True
    # oltre il fallback: silenzio solo se il tick ha deciso di rinviare (dorme ancora)
    return state.get("deferred") == m.isoformat() and now < _at(m, cfg["wake"]["fallback_max"], now.tzinfo)


def _waiting_wake_message(now: datetime, cfg: dict, state: dict, session_active: bool) -> bool:
    today = now.date().isoformat()
    w = (state.get("wake") or {}).get(today)
    if not w or state.get("wake_sent") == today or not session_active:
        return False
    rec = datetime.fromisoformat(w["recorded_at"])
    return now < rec + timedelta(minutes=cfg["wake_grace_min"])


# --- invio ------------------------------------------------------------------------

def merge(parts: list[tuple[str, str | None]]) -> tuple[str, str | None]:
    parts = [(t, pm) for t, pm in parts if t and t.strip()]
    if any(pm == "HTML" for _, pm in parts):
        return "\n\n".join(t if pm == "HTML" else html.escape(t) for t, pm in parts), "HTML"
    return "\n\n".join(t for t, _ in parts), None


def _send_rows(rows: list[dict], sender: Sender, head: tuple[str, str | None] | None = None) -> str:
    """Testi fusi in un messaggio (con `head` davanti), poi le schede una per una."""
    texts = ([head] if head else []) + [(r["text"], r.get("parse_mode")) for r in rows if not r.get("card")]
    out = ""
    if texts:
        out, pm = merge(texts)
        if out:
            sender.text(out, pm)
    for r in rows:
        if r.get("card"):
            # le foto devono stare nel repo dati o negli asset dei plugin (difesa in profondità:
            # una riga di push.jsonl può averla scritta chiunque)
            base = Path(r["card"].get("base") or cc.data_root())
            try:
                steps = cc.safe_card(r["card"]["steps"], base)
            except cc.PathNotAllowed as e:
                print(f"scheda scartata: {e}", file=sys.stderr)
                continue
            if r.get("text"):
                sender.text(r["text"], r.get("parse_mode"))
            sender.card(steps, base)
    return out


def deliver(text: str, kind: str, sender: Sender, now: datetime | None = None, cfg: dict | None = None,
            parse_mode: str | None = None, urgent: bool = False, source: str = "session",
            card: dict | None = None) -> dict:
    """Un messaggio d'iniziativa. kind: evening | wake | review | detector | push | message.

    → {"status": "sent"|"held"|"duplicate"|"too_late"|"silent", "merged": n}
    """
    cfg = cfg or cc.rhythm()
    now = now or datetime.now(cc.tz())
    today = now.date().isoformat()
    st = load_state()
    if kind in ("evening", "wake") and st.get(f"{kind}_sent") == today:
        return {"status": "duplicate", "note": f"messaggio {kind} di oggi già partito"}
    silent = is_silent(now, cfg, st) and not urgent
    if silent:
        if kind == "evening":
            _update_state(lambda s: s.__setitem__("evening_skipped", today))
            return {"status": "too_late", "note": "è già ora di letto: la sera non parte di notte"}
        if kind == "wake":
            return {"status": "silent", "note": "alzata non ancora vista: niente messaggio del mattino"}
        pid = submit(text, source=source, kind=kind, parse_mode=parse_mode, card=card, created_at=now)
        return {"status": "held", "id": pid, "note": "finestra di silenzio: esce dopo l'alzata"}
    absorbed = _claim(lambda r: r.get("priority") != "red_flag")
    row = {"text": text, "parse_mode": parse_mode}
    if card:
        row["card"] = card
    try:
        sent = _send_rows([row] + absorbed, sender)
    except Exception:
        _finish([r["id"] for r in absorbed], ok=False)
        raise
    mid = f"{kind}-{now.strftime('%Y%m%d-%H%M%S')}"
    _finish([r["id"] for r in absorbed], ok=True, merged_into=mid)
    if kind in ("evening", "wake"):
        _update_state(lambda s: s.__setitem__(f"{kind}_sent", today))
    try:
        tq.record_sent(mid, cc.primary_chat_id(), sent or text, via=f"gate:{source}")
    except OSError:
        pass
    return {"status": "sent", "merged": len(absorbed), "id": mid}


# --- tick (dal bot, ogni ~25 s) -------------------------------------------------------

def _fallback_texts():
    import morning_message as mm
    return mm.wake_text, mm.evening_text


def tick(now: datetime, sender: Sender, session_active: bool, cfg: dict | None = None,
         minutes_loader: Callable[[str, bool], dict | None] = wd.load_minutes,
         session_loader: Callable[[str], dict | None] = wd.load_sleep_session,
         notify: Callable[..., Any] = tq.enqueue_system,
         texts: tuple[Callable[[str], str], Callable[[str], str]] | None = None) -> list[str]:
    """Un giro del cancello. Ritorna le azioni fatte (per il log del bot)."""
    cfg = cfg or cc.rhythm()
    w = cfg["wake"]
    done: list[str] = []
    today = now.date().isoformat()

    # 1. red flag: subito
    reds = _claim(lambda r: r.get("priority") == "red_flag")
    if reds:
        try:
            _send_rows(reds, sender)
            _finish([r["id"] for r in reds], ok=True)
            done.append(f"red_flag×{len(reds)}")
        except Exception:
            _finish([r["id"] for r in reds], ok=False)
            raise

    st = load_state()
    m = morning_of(now, cfg)

    # 2. alzata (solo nel mattino di oggi)
    if m == now.date() and today not in (st.get("wake") or {}) \
            and now >= _at(m, w["watch_from"], now.tzinfo):
        found = None
        if now >= _at(m, w["fallback_max"], now.tzinfo):
            found = {"at": now.strftime("%H:%M"), "source": "fallback"}   # bot fermo al mattino: niente rilevazioni tardive
        else:
            last = st.get("last_fetch")
            fetch = not last or (now - datetime.fromisoformat(last)) >= timedelta(minutes=w["fetch_every_min"])
            mins = minutes_loader(today, fetch)
            if fetch:
                _update_state(lambda s: s.__setitem__("last_fetch", now.isoformat()))
            found = wd.detect_wake(mins, session_loader(today), now, w)
        if not found and now >= fallback_at(m, cfg, now.tzinfo, st):
            if now < _at(m, w["fallback_max"], now.tzinfo) and wd.still_asleep(mins, now, w):
                _update_state(lambda s: s.__setitem__("deferred", today))
                done.append("fallback rinviato: dorme ancora")
            else:
                found = {"at": now.strftime("%H:%M"), "source": "fallback"}
        if found:
            rec = {**found, "recorded_at": now.isoformat()}
            _update_state(lambda s: (s.setdefault("wake", {}).__setitem__(today, rec), s.pop("deferred", None)))
            st = load_state()
            done.append(f"alzata {found['at']} ({found['source']})")
            if session_active:
                notify("wake", f"Alzata {'rilevata' if found['source'] != 'fallback' else 'non vista: fallback'} "
                               f"alle {found['at']}. Tocca al messaggio del mattino (notte + scadenze 48 h).",
                       {"date": today, **found}, dedup_key=f"wake-{today}")

    # 3. messaggio dopo l'alzata: fallback se la sessione non c'è o non arriva in tempo
    wk = (st.get("wake") or {}).get(today)
    late = now >= _at(now.date(), w["late_cutoff"], now.tzinfo)
    if wk and late and st.get("wake_sent") != today and st.get("wake_skipped") != today:
        _update_state(lambda s: s.__setitem__("wake_skipped", today))
        done.append("mattino saltato: troppo tardi")
        st = load_state()
    elif wk and st.get("wake_sent") != today and not _waiting_wake_message(now, cfg, st, session_active):
        wake_text = (texts or _fallback_texts())[0]
        r = deliver(wake_text(today), "wake", sender, now=now, cfg=cfg, source="fallback")
        done.append(f"mattino fallback: {r['status']}")
        st = load_state()

    # 4. sera: fallback dopo la scadenza, mai dopo l'ora di letto
    ev, bed = cfg["evening_message"], cfg["bedtime"]
    if bed > ev and st.get("evening_sent") != today and st.get("evening_skipped") != today:
        e_at = _at(now.date(), ev, now.tzinfo)
        deadline = min(e_at + timedelta(minutes=cfg["evening_fallback_delay_min"]),
                       _at(now.date(), bed, now.tzinfo) - timedelta(minutes=1))
        if now >= deadline:
            evening_text = (texts or _fallback_texts())[1]
            r = deliver(evening_text(today), "evening", sender, now=now, cfg=cfg, source="fallback")
            done.append(f"sera fallback: {r['status']}")
            st = load_state()

    # 5. push in attesa: fuori dal silenzio, fusi, dopo la finestra di fusione
    if not is_silent(now, cfg, st) and not _waiting_wake_message(now, cfg, st, session_active):
        rows = [r for r in tq.read_jsonl(push_path()) if r.get("status") == "pending"]
        if rows:
            oldest = min(datetime.fromisoformat(r["created_at"]) for r in rows)
            if (now - oldest).total_seconds() >= cfg["merge_window_s"]:
                claimed = _claim(lambda r: True)
                if claimed:
                    try:
                        _send_rows(claimed, sender)
                        _finish([r["id"] for r in claimed], ok=True)
                        done.append(f"push×{len(claimed)}")
                    except Exception:
                        _finish([r["id"] for r in claimed], ok=False)
                        raise
    return done


def status(now: datetime | None = None, session_active: bool | None = None) -> dict:
    cfg = cc.rhythm()
    now = now or datetime.now(cc.tz())
    st = load_state()
    pend = [r for r in tq.read_jsonl(push_path()) if r.get("status") == "pending"]
    m = morning_of(now, cfg).isoformat()
    return {"now": now.isoformat(timespec="minutes"), "silent": is_silent(now, cfg, st),
            "bedtime": cfg["bedtime"], "evening_message": cfg["evening_message"],
            "wake_fallback": cfg["wake"]["fallback"], "morning": m,
            "wake": (st.get("wake") or {}).get(m), "wake_sent": st.get("wake_sent") == now.date().isoformat(),
            "evening_sent": st.get("evening_sent") == now.date().isoformat(),
            "held": len(pend), "session_active": session_active, "conflict": st.get("conflict")}


# --- invio reale ---------------------------------------------------------------------

class TelegramSender:
    def __init__(self, token: str | None = None, chat_id: int | None = None, call=None, multipart=None):
        import tg_transport as tt
        self.tt = tt
        self.call = call or tt.call
        self.multipart = multipart or tt.multipart
        env = cc.load_env()
        self.token = token or cc.bot_token(env)
        self.chat_id = chat_id or cc.primary_chat_id(env)
        if not self.token or not self.chat_id:
            raise RuntimeError("token del bot o ALLOWED_CHAT_IDS mancanti (vedi skill setup)")

    def text(self, text: str, parse_mode: str | None = None) -> None:
        self.tt.send_text(self.token, self.chat_id, text, parse_mode=parse_mode, call=self.call)

    def card(self, steps: list[dict], base: Path) -> None:
        self.tt.send_card(self.token, self.chat_id, steps, base, call=self.call, multipart=self.multipart)


def main() -> int:
    ap = argparse.ArgumentParser(description="Cancello dei push di Hṛdaya")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit", help="accoda un push (esce quando il cancello lo permette)")
    s.add_argument("--text", default="")
    s.add_argument("--source", default="cli")
    s.add_argument("--kind", default="push")
    s.add_argument("--html", action="store_true")
    s.add_argument("--red-flag", action="store_true")
    s.add_argument("--card", help="spec JSON di una scheda (lista di passi text/photos)")
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "status":
        import session_state
        print(json.dumps(status(session_active=session_state.is_active()), ensure_ascii=False, indent=1))
        return 0
    card = None
    if a.card:
        spec = Path(a.card).resolve()
        card = {"steps": json.loads(spec.read_text(encoding="utf-8")), "base": str(spec.parent)}
    if not a.text and not card:
        ap.error("serve --text o --card")
    pid = submit(a.text, source=a.source, kind=a.kind, priority="red_flag" if a.red_flag else "normal",
                 parse_mode="HTML" if a.html else None, card=card)
    print(f"accodato {pid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
