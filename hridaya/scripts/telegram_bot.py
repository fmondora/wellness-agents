#!/usr/bin/env python3.12
"""Il bot Telegram di Hṛdaya — long polling, nessun LLM.

Fa solo trasporto e cose deterministiche:
  1. long polling (getUpdates) e menu comandi (setMyCommands)
  2. comandi locali: /log /nota /sonno /allenamento /help
  3. red flag clinici → escalation immediata, sempre
  4. messaggi di Francesco → coda data/telegram/inbox.jsonl (li legge la sessione accesa)
     sessione spenta → una riga sola «Hṛdaya non è attivo adesso…» (una volta per assenza)
  5. bottoni di risposta (callback_query, choices.py) → la scelta va in coda come un suo messaggio
  5b. web_app_data del player → seduta salvata (formato del coach) + evento per la sessione
  6. outbox: risposte scritte via CLI (sent=false) → Telegram; quelle non di risposta
     passano dal cancello come push
  7. a ogni giro il cancello dei push (push_gate.tick): silenzio notturno, alzata, fallback
  8. igiene del canale: 409 Conflict ripetuti (un altro processo legge lo stesso token)
     → un solo avviso, su Telegram e nel log

Repo dati: cwd o WELLNESS_DATA (lo shim del repo dati lo imposta).
    python3.12 telegram_bot.py
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import channel_config as cc  # noqa: E402
import push_gate  # noqa: E402
import session_state  # noqa: E402
import telegram_queue as tq  # noqa: E402
import tg_transport as tt  # noqa: E402

RED_FLAGS = (
    "dolore toracico", "dolore al petto", "difficoltà respiratorie", "difficolta respiratorie",
    "non riesco a respirare", "perdita di coscienza", "svenuto", "sangue nelle urine",
    "sangue nelle feci", "febbre alta",
)

RED_FLAG_REPLY = (
    "Quello che descrivi merita attenzione medica diretta. "
    "Contatta il tuo medico o vai al pronto soccorso. "
    "Sono qui quando vuoi — ma questo non può aspettare."
)

INACTIVE_REPLY = "Hṛdaya non è attivo adesso, ti rispondo appena torna."

CONFLICT_ALERT = (
    "⚠️ Un altro processo sta leggendo i messaggi di questo bot (409 Conflict): "
    "finché resta acceso, alcuni tuoi messaggi possono non arrivarmi. "
    "Va spento l'altro lettore dello stesso token (vedi skill setup di Hṛdaya)."
)
CONFLICT_THRESHOLD = 3          # 409 consecutivi prima dell'avviso
CONFLICT_RESET_OK_POLLS = 20    # giri buoni dopo i quali un nuovo conflitto riavvisa


def now_local() -> datetime:
    return datetime.now(cc.tz())


def today_str() -> str:
    return now_local().strftime("%Y-%m-%d")


def logs_dir() -> Path:
    return cc.data_root() / "data" / "logs"


def today_log_path() -> Path:
    return logs_dir() / f"{today_str()}.json"


def ensure_today_log() -> dict[str, Any]:
    path = today_log_path()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    log = {"date": today_str(), "morning": {}, "notes": f"Log avviato via Telegram {now_local().isoformat()}",
           "goals_tracking": []}
    path.write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return log


def save_log(log: dict[str, Any]) -> None:
    today_log_path().write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_log_note(text: str) -> None:
    log = ensure_today_log()
    prev = log.get("notes") or ""
    line = f"[Telegram {now_local().strftime('%H:%M')}] {text}"
    log["notes"] = f"{prev}\n{line}".strip() if prev else line
    save_log(log)


def parse_hrv_fc(text: str) -> tuple[float | None, int | None]:
    t = text.lower()
    m = re.search(r"(?:hrv|hev|recovery)[:\s]+(?:a\s+)?([\d.]+)", t)
    hrv = float(m.group(1)) if m else None
    m = re.search(r"fc[:\s]+(?:a\s+)?(\d+)", t)
    fc = int(m.group(1)) if m else None
    return hrv, fc


def update_morning_metrics(text: str) -> bool:
    hrv, fc = parse_hrv_fc(text)
    if hrv is None and fc is None:
        return False
    log = ensure_today_log()
    morning = log.setdefault("morning", {})
    if hrv is not None:
        morning["hrv"] = hrv
    if fc is not None:
        morning["heart_rate"] = fc
    save_log(log)
    return True


def check_red_flags(text: str) -> bool:
    low = text.lower()
    return any(flag in low for flag in RED_FLAGS)


def format_log_summary() -> str:
    path = today_log_path()
    if not path.exists():
        return f"Nessun diario per oggi ({today_str()})."
    log = json.loads(path.read_text(encoding="utf-8"))
    morning = log.get("morning") or {}
    lines = [f"📋 Diario {today_str()}", f"HRV: {morning.get('hrv', '—')} | FC: {morning.get('heart_rate', '—')}"]
    if log.get("notes"):
        lines.append(f"Note:\n{str(log['notes'])[:800]}")
    return "\n".join(lines)


def help_text() -> str:
    return """🫀 Hṛdaya

Sono Hṛdaya, il cuore del tuo consiglio: ti ascolto, tengo il quadro della giornata e chiamo lo specialista giusto (Coach Longevità, DreamAgent, il Kaula).

Comandi:
/allenamento — riapre l'ultimo allenamento (timer)
/log — il diario di oggi
/nota testo — annota nel diario
/sonno — com'è andata la notte
/meditazione — una meditazione guidata da ascoltare in cuffia (es. /meditazione 30 respiro)
/studio — lo studio tantrico col Kaula (anche: /studio coppia, /studio inquiry, /studio revisione)
/help — questo messaggio

Scrivimi liberamente: come stai, il corpo, il sonno, una domanda. Rispondo quando la sessione è accesa sul Mac; se non lo è, te lo dico e ti rispondo appena torna.
Di notte, dall'ora di letto all'alzata, non ti scrivo io."""


# --- canale -------------------------------------------------------------------------

TYPING_EVERY_S = 4      # Telegram tiene «sta scrivendo…» per ~5 s: si rinnova prima che sparisca
TYPING_MAX_S = 180      # oltre, un messaggio rimasto in coda non è più «in lavorazione»


class Bot:
    def __init__(self, token: str, call: Callable[..., dict] = tt.call,
                 session_active: Callable[[], bool] | None = None):
        self.token = token
        self.call = call
        self.cfg = cc.rhythm()
        self._session_active = session_active or (
            lambda: session_state.is_active(max_age_s=self.cfg["session_heartbeat_max_age_s"]))
        self.conflicts = 0
        self.ok_polls = 0

    def session_active(self) -> bool:
        return self._session_active()

    def typing_tick(self, now: datetime | None = None) -> set[int]:
        """«sta scrivendo…» nelle chat con un messaggio della persona in attesa di risposta, mentre la
        sessione c'è. Di notte no: la risposta passerebbe dal cancello e uscirebbe al mattino."""
        if not self.session_active():
            return set()
        now = now or datetime.now(timezone.utc)
        if push_gate.is_silent(now.astimezone(cc.tz()), cc.rhythm(), push_gate.load_state()):   # ritmo fresco
            return set()
        cutoff = (now - timedelta(seconds=TYPING_MAX_S)).isoformat()
        chats = {int(r["chat_id"]) for r in tq.list_pending(include_system=False)
                 if r.get("chat_id") and r.get("created_at", "") >= cutoff}
        for chat in chats:
            try:
                self.call(self.token, "sendChatAction", chat_id=chat, action="typing")
            except Exception as e:  # noqa: BLE001  (un'azione persa non deve fermare nulla)
                print(f"sendChatAction: {e}", file=sys.stderr)
        return chats

    def typing_loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.typing_tick()
            except Exception as e:  # noqa: BLE001
                print(f"typing: {e}", file=sys.stderr)
            stop.wait(TYPING_EVERY_S)

    def send(self, chat_id: int, text: str, **kw: Any) -> None:
        tt.send_text(self.token, chat_id, text, call=self.call, **kw)

    # comandi e messaggi
    def handle_message(self, chat_id: int, text: str, username: str,
                       reply_to_text: str | None = None, message_id: int | None = None) -> str:
        text = (text or "").strip()
        if not text:
            return "vuoto"
        if check_red_flags(text):
            self.send(chat_id, RED_FLAG_REPLY)
            append_log_note(f"[red flag] {text[:200]}")
            tq.enqueue_system("red_flag", f"Red flag da Telegram: {text[:300]}", {"chat_id": chat_id})
            return "red_flag"
        low = text.lower()
        if low.startswith("/start") or low.startswith("/help"):
            self.send(chat_id, help_text())
            return "help"
        if low.startswith("/log"):
            self.send(chat_id, format_log_summary())
            return "log"
        if low.startswith("/nota"):
            note = text[5:].strip()
            if not note:
                self.send(chat_id, "Uso: /nota testo")
                return "nota-vuota"
            append_log_note(note)
            self.send(chat_id, f"✓ Nota salvata — diario {today_str()}")
            return "nota"
        if low.startswith("/allenamento"):
            self.send_workout_button(chat_id)
            return "allenamento"
        if low.startswith("/sonno") or low.startswith("/sleep"):
            self.send(chat_id, sleep_text())
            return "sonno"

        if update_morning_metrics(text):
            append_log_note(f"Metriche: {text[:120]}")
        self.maybe_wake_from_message()
        msg_id = tq.enqueue(chat_id, text, username, reply_to_text=reply_to_text, tg_message_id=message_id)
        append_log_note(f"[coda {msg_id[:8]}] {text[:200]}")
        if self.session_active():
            try:
                self.call(self.token, "sendChatAction", chat_id=chat_id, action="typing")
            except tt.TelegramError:
                pass
            return "coda"
        self.notify_inactive(chat_id)
        return "coda-inattivo"

    def notify_inactive(self, chat_id: int) -> None:
        """Una riga sola per assenza: non a ogni messaggio."""
        st = push_gate.load_state()
        hb = session_state.read().get("heartbeat_at")
        last = st.get("inactive_notice_at")
        if last and (not hb or hb < last):
            return
        self.send(chat_id, INACTIVE_REPLY)
        push_gate._update_state(lambda s: s.__setitem__("inactive_notice_at",
                                                       datetime.now(timezone.utc).isoformat()))

    def maybe_wake_from_message(self) -> None:
        """Un messaggio di Francesco al mattino, dopo il pavimento, vale come alzata."""
        now = now_local()
        st = push_gate.load_state()
        m = push_gate.morning_of(now, self.cfg)
        if m != now.date() or now.strftime("%H:%M") < self.cfg["wake"]["earliest"]:
            return
        if m.isoformat() in (st.get("wake") or {}):
            return
        rec = {"at": now.strftime("%H:%M"), "source": "messaggio", "recorded_at": now.isoformat()}
        push_gate._update_state(lambda s: s.setdefault("wake", {}).__setitem__(m.isoformat(), rec))
        if self.session_active():
            tq.enqueue_system("wake", f"Francesco ha scritto alle {rec['at']}: è sveglio. "
                                      "Tocca al messaggio del mattino (notte + scadenze 48 h).",
                              {"date": m.isoformat(), **rec}, dedup_key=f"wake-{m.isoformat()}")

    def send_workout_button(self, chat_id: int) -> None:
        import workout_player as wp
        path = wp.latest_player(wp.DAILY)
        base = cc.load_env().get("WORKOUT_PLAYER_URL", "")
        if not path or not base:
            self.send(chat_id, "Non trovo allenamenti da riaprire.")
            return
        try:
            w = json.loads(path.read_text(encoding="utf-8"))
            errs = wp.validate_workout(w)
            if errs:
                self.send(chat_id, "Scheda non valida: " + "; ".join(errs[:3]))
                return
            day = path.name[:10]
            text = (f"🏋️ Riapro l'allenamento del {day[8:10]}/{day[5:7]}: {w.get('title') or 'senza titolo'}"
                    + (" (demo)" if w.get("demo") else "")
                    + "\nSe l'avevi fermato, dentro trovi «Continua da dove eri».")
            wp.send_player_button(self.token, chat_id, w, base, call=self.call, text=text)
        except Exception as e:  # noqa: BLE001
            self.send(chat_id, "Non riesco a mandare il bottone ora.")
            print(f"/allenamento error: {e}", file=sys.stderr)

    def handle_web_app_data(self, chat_id: int, data: str) -> Path | None:
        import workout_player as wp
        path = wp.handle_web_app_data(self.token, chat_id, data, wp.DAILY, call=self.call)
        if path and path.name.endswith(".session.json") and not path.name.endswith(".demo.session.json"):
            tq.enqueue_system("workout_session", f"Seduta registrata dal player: {path.name}. "
                                                 "Coach Longevità può fare il debrief (workout_fitbit).",
                              {"file": str(path.relative_to(cc.data_root())) if path.is_relative_to(cc.data_root())
                               else str(path)})
        return path

    # outbox e cancello
    def flush_outbox(self) -> None:
        inbox_ids = {r.get("id") for r in tq.read_jsonl(tq.inbox_path())}
        for row in tq.list_unsent_outbox():
            chat_id = int(row["chat_id"]) if row.get("chat_id") is not None else cc.primary_chat_id()
            if row.get("in_reply_to") in inbox_ids:
                self.send(chat_id, row.get("text", ""))
                tq.mark_outbox_sent(row["in_reply_to"], row.get("chat_id"))
                tq.mark_done(row["in_reply_to"])     # risposto: anche «sta scrivendo…» si ferma
            else:   # iniziativa scritta in outbox da un vecchio chiamante: passa dal cancello
                push_gate.submit(row.get("text", ""), source=f"outbox:{row.get('in_reply_to')}",
                                 push_id=f"outbox-{row.get('in_reply_to')}")
                tq.mark_outbox_sent(row["in_reply_to"], row.get("chat_id"), routed="gate")

    def gate_tick(self) -> list[str]:
        sender = push_gate.TelegramSender(token=self.token, call=self.call)
        return push_gate.tick(now_local(), sender, self.session_active(), cfg=self.cfg)

    # igiene
    def on_conflict(self) -> bool:
        """Conta i 409; True quando parte l'avviso (una volta per episodio)."""
        self.conflicts += 1
        self.ok_polls = 0
        st = push_gate.load_state()
        if self.conflicts < CONFLICT_THRESHOLD or (st.get("conflict") or {}).get("notified"):
            return False
        msg = f"409 Conflict ripetuti ({self.conflicts}): un altro processo usa questo token"
        print(f"[{now_local().strftime('%H:%M')}] {msg}", file=sys.stderr)
        # l'avviso è un'iniziativa: passa dal cancello (di notte aspetta l'alzata)
        push_gate.submit(CONFLICT_ALERT, source="bot", kind="alert", meta={"alert": True},
                         push_id=f"conflict-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}")
        push_gate._update_state(lambda s: s.__setitem__(
            "conflict", {"notified": True, "since": datetime.now(timezone.utc).isoformat(), "count": self.conflicts}))
        return True

    def on_poll_ok(self) -> None:
        self.conflicts = 0
        self.ok_polls += 1
        if self.ok_polls >= CONFLICT_RESET_OK_POLLS and (push_gate.load_state().get("conflict")):
            push_gate._update_state(lambda s: s.pop("conflict", None))

    def handle_callback(self, cq: dict, allowed: set[int]) -> str:
        """Tocco su un bottone di risposta (choices.py): la scelta va in coda come un suo messaggio.

        Prima la coda, poi Telegram: le chiamate di risposta al tocco sono cosmetiche e un loro
        errore (anche di rete) non deve far perdere la scelta."""
        import choices
        msg = cq.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        if chat_id not in allowed:
            print(f"Ignorato callback da chat_id {chat_id}")
            return "ignorato"
        if (cq.get("data") or "").startswith("pr:"):
            return self.handle_practice(cq, chat_id, msg)
        res = choices.tap(cq.get("data") or "", tap_id=cq.get("id"))
        outcome = f"bottone-{res['action']}"
        if res["action"] == "answer":
            user = (cq.get("from") or {}).get("username", "?")
            text = choices.answer_text(res["selected"])
            print(f"[{now_local().strftime('%H:%M')}] @{user} bottone: {text[:80]}")
            try:
                msg_id = tq.enqueue(chat_id, text, user, reply_to_text=res.get("question") or msg.get("text"),
                                    choice={"id": res["cid"], "question": res.get("question", ""),
                                            "selected": res["selected"], "multi": res.get("multi", False)})
            except Exception:
                choices.reopen(res["cid"])
                raise
            outcome = "bottone"
            try:
                append_log_note(f"[coda {msg_id[:8]}] [bottone] {text[:200]}")
                self.maybe_wake_from_message()
            except Exception as e:  # noqa: BLE001
                print(f"bottone, diario/alzata: {e}", file=sys.stderr)
        self._ack_callback(cq, chat_id, msg, res)
        if outcome == "bottone" and not self.session_active():
            self.notify_inactive(chat_id)
            return "bottone-inattivo"
        return outcome

    def handle_practice(self, cq: dict, chat_id: int, msg: dict) -> str:
        """«Inizia» / «Fine» sotto una pratica: lo registra il bot, senza la sessione, con una riga nel
        diario. L'evento `practice_done` parte dopo, da practice_tick (serve il «dopo» sulla FC)."""
        import practice
        res = practice.tap(cq.get("data") or "", tap_id=cq.get("id"))
        p = res.get("practice") or {}
        try:
            if res["action"] == "started":
                append_log_note(f"[pratica] inizio «{p.get('title', '')}» {now_local():%H:%M}")
            elif res["action"] == "ended":
                _, data = practice.event(p)
                append_log_note(f"[pratica] «{data['title']}» {data['start']}–{data['end']} ({data['minutes']}′)")
        except Exception as e:  # noqa: BLE001 — il tocco è registrato comunque in practices.json
            print(f"pratica, coda/diario: {e}", file=sys.stderr)
        self._ack_callback(cq, chat_id, msg, res)
        return f"pratica-{res['action']}"

    def practice_tick(self, now: datetime | None = None) -> list[str]:
        """Pratiche finite da mezz'ora: evento `practice_done` per la sessione."""
        import practice
        out = []
        for p in practice.due(now):
            text, data = practice.event(p)
            tq.enqueue_system("practice_done", text, data, dedup_key=f"practice_done:{p['id']}")
            out.append(p["id"])
        return out

    def _ack_callback(self, cq: dict, chat_id: int, msg: dict, res: dict) -> None:
        try:
            self.call(self.token, "answerCallbackQuery", callback_query_id=cq.get("id"),
                      text=res.get("toast") or None)
        except Exception as e:  # noqa: BLE001
            print(f"answerCallbackQuery: {e}", file=sys.stderr)
        if res.get("markup") is not None and msg.get("message_id"):
            try:
                self.call(self.token, "editMessageReplyMarkup", chat_id=chat_id,
                          message_id=msg["message_id"], reply_markup=res["markup"])
            except Exception as e:  # noqa: BLE001 — «message is not modified», rete: la scelta vale lo stesso
                print(f"editMessageReplyMarkup: {e}", file=sys.stderr)

    def process_update(self, upd: dict, allowed: set[int]) -> str:
        if upd.get("callback_query"):
            return self.handle_callback(upd["callback_query"], allowed)
        msg = upd.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        if chat_id not in allowed:
            print(f"Ignorato chat_id {chat_id}")
            return "ignorato"
        if msg.get("web_app_data"):
            saved = self.handle_web_app_data(chat_id, msg["web_app_data"].get("data", ""))
            print(f"[{now_local().strftime('%H:%M')}] seduta → {saved}")
            return "seduta"
        text = msg.get("text") or ""
        user = (msg.get("from") or {}).get("username", "?")
        reply_to = (msg.get("reply_to_message") or {}).get("text")
        print(f"[{now_local().strftime('%H:%M')}] @{user}: {text[:80]}")
        return self.handle_message(chat_id, text, user, reply_to_text=reply_to, message_id=msg.get("message_id"))


def sleep_text() -> str:
    try:
        from _plugins import import_from
        sa = import_from("health", "sleep_analysis")
        a = sa.analyze()
        return sa.format_text(a) if a else "Non ho ancora i dati del sonno di stanotte."
    except Exception as e:  # noqa: BLE001
        print(f"/sonno error: {e}", file=sys.stderr)
        return "Analisi del sonno non disponibile ora."


def main() -> int:
    cc.apply_ca_bundle()
    env = cc.load_env()
    token = cc.bot_token(env)
    if not token:
        print("Manca il token del bot (portachiavi o .env): skill setup di Hṛdaya", file=sys.stderr)
        return 1
    allowed = cc.allowed_chat_ids(env)
    if not allowed:
        print("ALLOWED_CHAT_IDS vuoto: registra il chat_id con la skill setup "
              "(telegram_setup.py wait-start --register)", file=sys.stderr)
        return 1
    bot = Bot(token)
    print(f"Hṛdaya — bot Telegram avviato {now_local().isoformat()} · repo dati {cc.data_root()}")
    print(f"Chat autorizzate: {sorted(allowed)}")
    try:
        import workout_player as wp
        wp.set_bot_commands(token)
    except Exception as e:  # noqa: BLE001
        print(f"setMyCommands: {e}", file=sys.stderr)

    # «sta scrivendo…» finché la sessione lavora a una risposta (il long polling blocca il ciclo)
    threading.Thread(target=bot.typing_loop, args=(threading.Event(),), daemon=True,
                     name="typing").start()
    offset = 0
    while True:
        try:
            bot.flush_outbox()
            for action in bot.gate_tick():
                print(f"[{now_local().strftime('%H:%M')}] cancello: {action}")
            try:
                for pid in bot.practice_tick():
                    print(f"[{now_local().strftime('%H:%M')}] pratica {pid}: lettura in coda")
            except Exception as e:  # noqa: BLE001
                print(f"pratiche: {e}", file=sys.stderr)
            # long polling 25 s: il cancello gira almeno ogni 25 s
            resp = tt.call(token, "getUpdates", _timeout=60, timeout=25, offset=offset,
                           allowed_updates=["message", "callback_query"])
            bot.on_poll_ok()
            for upd in resp.get("result") or []:
                offset = max(offset, upd["update_id"] + 1)
                bot.process_update(upd, allowed)
        except KeyboardInterrupt:
            print("\nBot fermato.")
            return 0
        except tt.TelegramError as e:
            if e.code == 409:
                bot.on_conflict()
                time.sleep(10)
            else:
                print(f"Errore Telegram: {e}", file=sys.stderr)
                time.sleep(5)
        except Exception as e:  # noqa: BLE001
            print(f"Errore: {e}", file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
