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
    def text(self, text: str, parse_mode: str | None = None) -> None: ...   # + reply_markup= se ha bottoni
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
           card: dict | None = None, created_at: datetime | None = None,
           reply_markup: dict | None = None) -> str:
    row = {"id": push_id or f"{source}-{uuid.uuid4().hex[:12]}",
           "created_at": (created_at or datetime.now(timezone.utc)).isoformat(), "source": source, "kind": kind,
           "priority": priority, "text": text, "status": "pending", "meta": meta or {}}
    if parse_mode:
        row["parse_mode"] = parse_mode
    if card:
        row["card"] = card
    if reply_markup:
        row["reply_markup"] = reply_markup   # bottoni: la riga parte da sola, mai fusa
    with tq.locked():
        rows = tq.read_jsonl(push_path())
        if push_id and any(r.get("id") == push_id for r in rows):
            return push_id
        rows.append(row)
        tq.write_jsonl(push_path(), rows)
    return row["id"]


MAX_ATTEMPTS = 5


def _due(r: dict, now_utc: str) -> bool:
    return not r.get("next_try_at") or r["next_try_at"] <= now_utc


def _claim(pred: Callable[[dict], bool], fresh_only: bool = False) -> list[dict]:
    """Segna 'sending' le righe pending (pronte, non in backoff) che soddisfano pred."""
    now_utc = datetime.now(timezone.utc).isoformat()
    with tq.locked():
        rows = tq.read_jsonl(push_path())
        got = []
        for r in rows:
            if r.get("status") == "pending" and _due(r, now_utc) and pred(r) \
                    and not (fresh_only and r.get("attempts")):
                r["status"] = "sending"
                got.append(dict(r))
        if got:
            tq.write_jsonl(push_path(), rows)
    return got


def _mark(results: dict[str, tuple[str, Exception | None]], merged_into: str | None = None) -> list[dict]:
    """Chiude riga per riga: sent | failed (scartata, 4xx) | retry (backoff, poi failed) | release.
    Ritorna le righe appena scartate."""
    if not results:
        return []
    now = datetime.now(timezone.utc)
    dead = []
    with tq.locked():
        rows = tq.read_jsonl(push_path())
        for r in rows:
            out = results.get(r.get("id"))
            if not out or r.get("status") != "sending":
                continue
            outcome, err = out
            if outcome == "sent":
                r.update(status="sent", sent_at=now.isoformat())
                if merged_into:
                    r["merged_into"] = merged_into
            elif outcome == "release":
                r["status"] = "pending"
            else:
                r["attempts"] = int(r.get("attempts") or 0) + 1
                r["last_error"] = str(err)[:300] if err else None
                if outcome == "failed" or r["attempts"] >= MAX_ATTEMPTS:
                    r.update(status="failed", failed_at=now.isoformat())
                    dead.append(dict(r))
                else:
                    r["status"] = "pending"
                    r["next_try_at"] = (now + timedelta(minutes=min(60, 2 ** r["attempts"]))).isoformat()
        tq.write_jsonl(push_path(), rows)
    return dead


def _finish(ids: list[str], ok: bool, merged_into: str | None = None) -> None:
    """Compatibilità: tutte sent oppure tutte rimesse in coda senza contare il tentativo."""
    _mark({i: ("sent" if ok else "release", None) for i in ids}, merged_into)


def _alert_dead(dead: list[dict], now: datetime) -> None:
    """Un messaggio scartato: log sempre, un solo avviso al giorno su Telegram (passa dal cancello)."""
    real = [r for r in dead if not (r.get("meta") or {}).get("alert")]
    for r in dead:
        print(f"push scartato {r['id']} ({r.get('source')}): {r.get('last_error')}", file=sys.stderr)
    if real:
        submit("⚠️ Un messaggio d'iniziativa non è partito (Telegram l'ha rifiutato: "
               f"{(real[0].get('last_error') or '')[:120]}). L'ho scartato invece di ripeterlo; "
               "dettagli in data/telegram/push.jsonl.", source="gate", kind="alert",
               meta={"alert": True}, push_id=f"alert-dead-{now.date().isoformat()}")


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


def _outcome(e: Exception) -> str:
    return "failed" if tt_permanent(e) else "retry"


def tt_permanent(e: Exception) -> bool:
    import tg_transport as tt
    return isinstance(e, cc.PathNotAllowed) or tt.is_permanent(e)


def _is_partial(e: Exception) -> bool:
    import tg_transport as tt
    return isinstance(e, tt.PartialSendError)


def _dispatch(rows: list[dict], sender: Sender, head: tuple[str, str | None] | None = None
              ) -> tuple[dict[str, tuple[str, Exception | None]], Exception | None, str]:
    """Invia: testi fusi in un messaggio (con `head` davanti), poi le schede una per una.

    Esito riga per riga (mai tutto il lotto indietro): un invio parziale conta come
    consegnato (ritentare farebbe doppioni); un 4xx sul messaggio fuso fa ripartire i pezzi
    da soli per isolare la riga avvelenata. → (esiti, errore della testa o None, testo fuso)
    """
    res: dict[str, tuple[str, Exception | None]] = {}
    head_err: Exception | None = None
    texts = [r for r in rows if not r.get("card") and not r.get("reply_markup") and (r.get("text") or "").strip()]
    for r in rows:   # righe vuote senza scheda: niente da mandare
        if not r.get("card") and not r.get("reply_markup") and not (r.get("text") or "").strip():
            res[r["id"]] = ("sent", None)
    parts = ([head] if head and (head[0] or "").strip() else []) + [(r["text"], r.get("parse_mode")) for r in texts]
    out = ""
    if parts:
        out, pm = merge(parts)
        try:
            sender.text(out, pm)
            res.update({r["id"]: ("sent", None) for r in texts})
        except Exception as e:  # noqa: BLE001
            if _is_partial(e):
                print(f"invio parziale, non ritento: {e}", file=sys.stderr)
                res.update({r["id"]: ("sent", None) for r in texts})
            elif tt_permanent(e) and len(parts) > 1:
                out = ""
                if head and (head[0] or "").strip():
                    try:
                        sender.text(*head)
                        out = head[0]
                    except Exception as e2:  # noqa: BLE001
                        if not _is_partial(e2):
                            head_err = e2
                for r in texts:
                    try:
                        sender.text(r["text"], r.get("parse_mode"))
                        res[r["id"]] = ("sent", None)
                    except Exception as e3:  # noqa: BLE001
                        res[r["id"]] = ("sent", None) if _is_partial(e3) else (_outcome(e3), e3)
            else:
                if head and (head[0] or "").strip():
                    head_err = e
                res.update({r["id"]: (_outcome(e), e) for r in texts})
    for r in rows:   # con bottoni: un messaggio a sé, i bottoni sotto il suo testo
        if r.get("card") or not r.get("reply_markup"):
            continue
        try:
            sender.text(r.get("text") or "", r.get("parse_mode"), reply_markup=r["reply_markup"])
            res[r["id"]] = ("sent", None)
        except Exception as e:  # noqa: BLE001
            res[r["id"]] = ("sent", None) if _is_partial(e) else (_outcome(e), e)
    for r in rows:
        if not r.get("card"):
            continue
        # le foto devono stare nelle cartelle ammesse (una riga di push.jsonl può averla scritta chiunque)
        base = Path(r["card"].get("base") or cc.data_root())
        try:
            steps = cc.safe_card(r["card"]["steps"], base)
            if (r.get("text") or "").strip():
                sender.text(r["text"], r.get("parse_mode"))
            sender.card(steps, base)
            res[r["id"]] = ("sent", None)
        except Exception as e:  # noqa: BLE001
            res[r["id"]] = ("sent", None) if _is_partial(e) else (_outcome(e), e)
    return res, head_err, out


def _send_rows(rows: list[dict], sender: Sender, head: tuple[str, str | None] | None = None) -> str:
    """Compatibilità: invia e chiude riga per riga."""
    res, head_err, out = _dispatch(rows, sender, head)
    _alert_dead(_mark(res), datetime.now(cc.tz()))
    if head_err:
        raise head_err
    return out


def _sending_recent(st: dict, kind: str, now: datetime) -> bool:
    raw = st.get(f"{kind}_sending")
    if not raw:
        return False
    try:
        return now - datetime.fromisoformat(raw) < timedelta(minutes=5)
    except ValueError:
        return False


def deliver(text: str, kind: str, sender: Sender, now: datetime | None = None, cfg: dict | None = None,
            parse_mode: str | None = None, urgent: bool = False, source: str = "session",
            card: dict | None = None, reply_markup: dict | None = None) -> dict:
    """Un messaggio d'iniziativa. kind: evening | wake | review | detector | push | message | reply.

    → {"status": "sent"|"held"|"duplicate"|"too_late"|"silent"|"failed", "merged": n}
    Sera e mattino: controllo «già partito / in partenza» sotto lock (due bot, due tick).
    Il mattino ha una scadenza (`wake.late_cutoff`) dopo la quale non parte da nessuna strada.
    """
    cfg = cfg or cc.rhythm()
    now = now or datetime.now(cc.tz())
    today = now.date().isoformat()
    gated = kind in ("evening", "wake")
    verdict: dict | None = None
    hold = False
    with tq.locked():
        st = load_state()
        if gated and st.get(f"{kind}_sent") == today:
            verdict = {"status": "duplicate", "note": f"messaggio {kind} di oggi già partito"}
        elif gated and _sending_recent(st, kind, now):
            verdict = {"status": "duplicate", "note": f"messaggio {kind} già in partenza"}
        elif kind == "wake" and (now >= _at(now.date(), cfg["wake"]["late_cutoff"], now.tzinfo)
                                 or st.get("wake_skipped") == today):
            verdict = {"status": "too_late", "note": "il messaggio del mattino ha passato la scadenza"}
        elif is_silent(now, cfg, st) and not urgent:
            if kind == "evening":
                st["evening_skipped"] = today
                save_state(st)
                verdict = {"status": "too_late", "note": "è già ora di letto: la sera non parte di notte"}
            elif kind == "wake":
                verdict = {"status": "silent", "note": "alzata non ancora vista: niente messaggio del mattino"}
            else:
                hold = True
        elif gated:
            st[f"{kind}_sending"] = now.isoformat()
            save_state(st)
    if verdict:
        return verdict
    if hold:
        pid = submit(text, source=source, kind=kind, parse_mode=parse_mode, card=card, created_at=now,
                     reply_markup=reply_markup)
        return {"status": "held", "id": pid, "note": "finestra di silenzio: esce dopo l'alzata"}

    # nel messaggio si fondono i push in attesa mai tentati (quelli già falliti restano al loro backoff)
    absorbed = _claim(lambda r: r.get("priority") != "red_flag", fresh_only=True)
    mid = f"{kind}-{now.strftime('%Y%m%d-%H%M%S')}"
    alone = bool(card or reply_markup)   # testa con scheda o bottoni: riga a sé, dopo i fusi
    head_card = ({"id": "__head__", "text": text, "parse_mode": parse_mode, "card": card,
                  "reply_markup": reply_markup} if alone else None)
    try:
        res, head_err, sent = _dispatch(absorbed + ([head_card] if head_card else []), sender,
                                        head=(text, parse_mode) if not alone else None)
    except Exception:
        _mark({r["id"]: ("release", None) for r in absorbed})
        if gated:
            _update_state(lambda s: s.pop(f"{kind}_sending", None))
        raise
    if alone:
        out = res.pop("__head__", ("sent", None))
        head_err = out[1] if out[0] != "sent" else None
    if head_err is not None:
        # la testa non è partita: le righe assorbite non fuse tornano in coda senza colpa
        _mark({i: (o if o[0] in ("sent", "failed") else ("release", None)) for i, o in res.items()})
        if gated:
            _update_state(lambda s: s.pop(f"{kind}_sending", None))
        return {"status": "failed", "error": str(head_err)}
    _alert_dead(_mark(res, merged_into=mid), now)
    if gated:
        _update_state(lambda s: (s.__setitem__(f"{kind}_sent", today), s.pop(f"{kind}_sending", None)))
    try:
        tq.record_sent(mid, cc.primary_chat_id(), sent or text, via=f"gate:{source}")
    except OSError:
        pass
    return {"status": "sent", "merged": sum(1 for o in res.values() if o[0] == "sent"), "id": mid}


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
        res, _, _ = _dispatch(reds, sender)
        _alert_dead(_mark(res), now)
        done.append(f"red_flag×{sum(1 for o in res.values() if o[0] == 'sent')}")

    st = load_state()
    m = morning_of(now, cfg)

    # 2. alzata (solo nel mattino di oggi)
    if m == now.date() and today not in (st.get("wake") or {}) \
            and now >= _at(m, w["watch_from"], now.tzinfo):
        found = None
        mins = None
        restarted_late = now >= _at(m, w["fallback_max"], now.tzinfo)
        if restarted_late:
            found = {"at": now.strftime("%H:%M"), "source": "fallback"}   # bot fermo al mattino: niente rilevazioni tardive
        else:
            last = st.get("last_fetch")
            fetch = not last or (now - datetime.fromisoformat(last)) >= timedelta(minutes=w["fetch_every_min"])
            mins = minutes_loader(today, fetch)
            if fetch:
                _update_state(lambda s: s.__setitem__("last_fetch", now.isoformat()))
            try:
                sess = session_loader(today, w.get("session_end_from", "04:00"))
            except TypeError:   # loader iniettato senza il secondo argomento
                sess = session_loader(today)
            found = wd.detect_wake(mins, sess, now, w)
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
            # niente invito alla sessione se il mattino è già passato (bot riavviato tardi)
            if session_active and not restarted_late and now < _at(m, w["late_cutoff"], now.tzinfo):
                notify("wake", f"Alzata {'rilevata' if found['source'] != 'fallback' else 'non vista: fallback'} "
                               f"alle {found['at']}. Tocca al messaggio del mattino (notte + scadenze 48 h).",
                       {"date": today, **found}, dedup_key=f"wake-{today}")

    # 3. messaggio dopo l'alzata: fallback se la sessione non c'è o non arriva in tempo
    wk = (st.get("wake") or {}).get(today)
    late = now >= _at(now.date(), w["late_cutoff"], now.tzinfo)
    skipped = st.get("wake_skipped") == today
    if wk and late and st.get("wake_sent") != today and not skipped:
        _update_state(lambda s: s.__setitem__("wake_skipped", today))
        done.append("mattino saltato: troppo tardi")
        st = load_state()
    elif wk and not late and not skipped and st.get("wake_sent") != today \
            and not _waiting_wake_message(now, cfg, st, session_active):
        wake_text = (texts or _fallback_texts())[0]
        r = deliver(wake_text(today, active=session_active), "wake", sender, now=now, cfg=cfg, source="fallback")
        done.append(f"mattino fallback: {r['status']}")
        st = load_state()

    # 4. sera: fallback dopo la scadenza, mai dopo l'ora di letto. Con la sessione accesa
    #    (il Kaula può metterci minuti) si aspetta fino all'ora di letto meno un minuto.
    ev, bed = cfg["evening_message"], cfg["bedtime"]
    if bed > ev and st.get("evening_sent") != today and st.get("evening_skipped") != today:
        e_at = _at(now.date(), ev, now.tzinfo)
        last_call = _at(now.date(), bed, now.tzinfo) - timedelta(minutes=1)
        deadline = last_call if session_active else \
            min(e_at + timedelta(minutes=cfg["evening_fallback_delay_min"]), last_call)
        if now >= deadline:
            evening_text = (texts or _fallback_texts())[1]
            r = deliver(evening_text(today, active=session_active), "evening", sender, now=now, cfg=cfg,
                        source="fallback")
            done.append(f"sera fallback: {r['status']}")
            st = load_state()

    # 5. push in attesa: fuori dal silenzio, fusi, dopo la finestra di fusione
    if not is_silent(now, cfg, st) and not _waiting_wake_message(now, cfg, st, session_active):
        now_utc = datetime.now(timezone.utc).isoformat()
        rows = [r for r in tq.read_jsonl(push_path()) if r.get("status") == "pending" and _due(r, now_utc)]
        if rows:
            oldest = min(datetime.fromisoformat(r["created_at"]) for r in rows)
            if (now - oldest).total_seconds() >= cfg["merge_window_s"]:
                claimed = _claim(lambda r: True)
                if claimed:
                    res, _, _ = _dispatch(claimed, sender)
                    dead = _mark(res)
                    _alert_dead(dead, now)
                    done.append(f"push×{sum(1 for o in res.values() if o[0] == 'sent')}"
                                + (f" scartati×{len(dead)}" if dead else ""))
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

    def text(self, text: str, parse_mode: str | None = None, reply_markup: dict | None = None) -> None:
        self.tt.send_text(self.token, self.chat_id, text, parse_mode=parse_mode, reply_markup=reply_markup,
                          call=self.call)

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
