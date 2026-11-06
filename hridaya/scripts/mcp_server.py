#!/usr/bin/env python3.12
"""Server MCP del canale di Hṛdaya — stdio, JSON-RPC 2.0, senza dipendenze.

Il protocollo è scritto a mano (initialize, tools/list, tools/call, ping): così gira con
qualunque python3.12 senza SDK. Messaggi uno per riga su stdin/stdout; i log su stderr.
Repo dati: cwd della sessione o WELLNESS_DATA. Bot e tool condividono trasporto
(`tg_transport`), coda (`telegram_queue`) e cancello (`push_gate`).

Regola del cancello: **risposta = subito, iniziativa = cancello.** Un invio con
`in_reply_to` (id di un messaggio della inbox) è una risposta e parte subito; senza,
è un'iniziativa e passa dalla finestra di silenzio notturno.

Test: HRIDAYA_TRANSPORT_LOG=<file> sostituisce la rete con un trasporto finto che
scrive le chiamate su quel file (nessuna chiamata a Telegram).
"""
from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import channel_config as cc  # noqa: E402
import push_gate  # noqa: E402
import session_state  # noqa: E402
import telegram_queue as tq  # noqa: E402
import tg_transport as tt  # noqa: E402

SERVER = {"name": "hridaya-telegram", "version": "0.3.0"}
PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
HEARTBEAT_S = 30


# --- trasporto (vero o finto) ------------------------------------------------------

def _fake_log(kind: str, token: str, method: str, payload: dict) -> dict:
    with open(os.environ["HRIDAYA_TRANSPORT_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": kind, "method": method, "params": payload}, ensure_ascii=False,
                           default=str) + "\n")
    return {"ok": True, "result": {"message_id": 1}}


def transport_call(token: str, method: str, **params: Any) -> dict:
    if os.environ.get("HRIDAYA_TRANSPORT_LOG"):
        params.pop("_timeout", None)
        return _fake_log("call", token, method, params)
    return tt.call(token, method, **params)


def transport_multipart(token: str, method: str, fields: dict, files: dict) -> dict:
    if os.environ.get("HRIDAYA_TRANSPORT_LOG"):
        return _fake_log("multipart", token, method, {**fields, "_files": {k: str(v) for k, v in files.items()}})
    return tt.multipart(token, method, fields, files)


def _sender() -> push_gate.TelegramSender:
    return push_gate.TelegramSender(call=transport_call, multipart=transport_multipart)


# --- servizio (battito) ----------------------------------------------------------------

class Service:
    def __init__(self):
        self.on = False
        self.listening: list[str] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, listening: list[str]) -> None:
        self.listening = listening
        session_state.beat(listening)
        if self._thread and self._thread.is_alive():
            return
        self.on = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(HEARTBEAT_S):
            try:
                session_state.beat(self.listening)
            except OSError as e:
                print(f"battito: {e}", file=sys.stderr)

    def stop(self) -> None:
        self._stop.set()
        if self.on:
            session_state.off()
        self.on = False


SERVICE = Service()


# --- tool ---------------------------------------------------------------------------

def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


KIND = {"type": "string", "enum": ["message", "push", "review", "detector", "evening", "wake"],
        "description": "evening/wake: i due messaggi programmati (uno al giorno, idempotenti)"}
REPLY_TO = {"type": "string", "description": "id del messaggio della inbox a cui si risponde: parte subito"}

TOOLS = [
    {"name": "telegram_send",
     "description": "Manda un messaggio d'iniziativa a Francesco su Telegram, come Hṛdaya. Passa dal cancello: "
                    "di notte (dall'ora di letto all'alzata) resta in attesa e si fonde col messaggio del mattino; "
                    "urgent=true solo per red flag clinici.",
     "inputSchema": _schema({"text": {"type": "string"}, "kind": KIND,
                             "parse_mode": {"type": "string", "enum": ["HTML"]},
                             "urgent": {"type": "boolean"}, "in_reply_to": REPLY_TO}, ["text"])},
    {"name": "telegram_send_card",
     "description": "Manda una scheda: testo HTML + album di immagini (es. la scheda del Coach Longevità). "
                    "spec_path = JSON lista di passi {text} | {photos, caption}, foto relative alla spec.",
     "inputSchema": _schema({"spec_path": {"type": "string"}, "steps": {"type": "array"},
                             "base_dir": {"type": "string"}, "kind": KIND, "in_reply_to": REPLY_TO})},
    {"name": "telegram_send_file",
     "description": "Manda un documento (PDF, immagine…). Di notte senza in_reply_to non parte.",
     "inputSchema": _schema({"path": {"type": "string"}, "caption": {"type": "string"},
                             "in_reply_to": REPLY_TO}, ["path"])},
    {"name": "telegram_send_player",
     "description": "Manda il bottone «▶️ Avvia allenamento» (Mini App del Coach Longevità) per un player.json "
                    "(data/coach-longevita/daily/YYYY-MM-DD.player.json). Valida lo schema prima di inviare.",
     "inputSchema": _schema({"player_json": {"type": "string"}, "text": {"type": "string"},
                             "in_reply_to": REPLY_TO, "dry_run": {"type": "boolean"}}, ["player_json"])},
    {"name": "telegram_inbox",
     "description": "Messaggi in attesa nella coda Telegram (di Francesco e, kind=system, eventi per Hṛdaya: "
                    "alzata rilevata, seduta registrata, red flag).",
     "inputSchema": _schema({"include_system": {"type": "boolean"}})},
    {"name": "telegram_reply",
     "description": "Risponde a un messaggio della inbox (parte subito, nessun cancello) e lo segna fatto.",
     "inputSchema": _schema({"id": {"type": "string"}, "text": {"type": "string"},
                             "parse_mode": {"type": "string", "enum": ["HTML"]},
                             "done": {"type": "boolean"}}, ["id", "text"])},
    {"name": "hridaya_service",
     "description": "Accende/spegne il servizio nella sessione (battito che dice al bot che Hṛdaya c'è) "
                    "e riporta cosa si sta ascoltando.",
     "inputSchema": _schema({"action": {"type": "string", "enum": ["on", "off", "status"]}}, ["action"])},
    {"name": "gate_status",
     "description": "Stato del cancello: silenzio, ora di letto, alzata rilevata, messaggi della sera/mattino "
                    "partiti, push trattenuti, conflitti 409.",
     "inputSchema": _schema({})},
    {"name": "reviews_due",
     "description": "Review dei coach dovute adesso (calendario di Hṛdaya in data/hridaya/calendar.json).",
     "inputSchema": _schema({})},
    {"name": "review_done",
     "description": "Segna fatta una review del calendario.",
     "inputSchema": _schema({"job": {"type": "string"}}, ["job"])},
]


class ToolError(Exception):
    pass


def _reply_chat(msg_id: str) -> int:
    row = tq.get_message(msg_id)
    if not row:
        raise ToolError(f"messaggio {msg_id} non trovato nella inbox")
    return int(row.get("chat_id") or cc.primary_chat_id())


def _is_night() -> bool:
    return push_gate.is_silent(datetime.now(cc.tz()), cc.rhythm(), push_gate.load_state())


def _installed_plugins() -> set[str]:
    from _plugins import plugin_scripts
    return {p for p in ("coach-longevita", "dream-agent") if plugin_scripts(p)}


def call_tool(name: str, args: dict) -> Any:
    if not cc.is_data_repo():
        raise ToolError(f"non sono in un repo dati ({cc.data_root()} senza data/profile.json): "
                        "apri la sessione nel repo dati o imposta WELLNESS_DATA")
    if name == "telegram_send":
        if args.get("in_reply_to"):
            s = _sender()
            tt.send_text(s.token, _reply_chat(args["in_reply_to"]), args["text"],
                         parse_mode=args.get("parse_mode"), call=transport_call)
            tq.record_sent(args["in_reply_to"], s.chat_id, args["text"])
            return {"status": "sent", "as": "reply"}
        return push_gate.deliver(args["text"], args.get("kind") or "message", _sender(),
                                 parse_mode=args.get("parse_mode"), urgent=bool(args.get("urgent")))
    if name == "telegram_send_card":
        if args.get("spec_path"):
            spec = Path(args["spec_path"])
            spec = spec if spec.is_absolute() else cc.data_root() / spec
            steps, base = json.loads(spec.read_text(encoding="utf-8")), spec.parent
        elif args.get("steps"):
            steps, base = args["steps"], Path(args.get("base_dir") or cc.data_root())
        else:
            raise ToolError("serve spec_path o steps")
        if args.get("in_reply_to"):
            s = _sender()
            n = tt.send_card(s.token, _reply_chat(args["in_reply_to"]), steps, base,
                             call=transport_call, multipart=transport_multipart)
            return {"status": "sent", "as": "reply", "steps": n}
        return push_gate.deliver("", args.get("kind") or "message", _sender(),
                                 card={"steps": steps, "base": str(base)})
    if name == "telegram_send_file":
        path = Path(args["path"])
        path = path if path.is_absolute() else cc.data_root() / path
        if not path.is_file():
            raise ToolError(f"file non trovato: {path}")
        if not args.get("in_reply_to") and _is_night():
            return {"status": "silent", "note": "finestra di silenzio: riprova dopo l'alzata"}
        s = _sender()
        chat = _reply_chat(args["in_reply_to"]) if args.get("in_reply_to") else s.chat_id
        tt.send_file(s.token, chat, path, args.get("caption") or "", multipart=transport_multipart)
        return {"status": "sent", "file": path.name}
    if name == "telegram_send_player":
        import workout_player as wp
        path = Path(args["player_json"])
        path = path if path.is_absolute() else cc.data_root() / path
        w = json.loads(path.read_text(encoding="utf-8"))
        errs = wp.validate_workout(w)
        if errs:
            raise ToolError("player.json non valido: " + "; ".join(errs))
        base = cc.load_env().get("WORKOUT_PLAYER_URL", "")
        if not base:
            raise ToolError("manca WORKOUT_PLAYER_URL nel .env del repo dati")
        url = wp.build_url(base, w)
        if args.get("dry_run"):
            return {"status": "ok", "url_length": len(url)}
        if not args.get("in_reply_to") and _is_night():
            return {"status": "silent", "note": "finestra di silenzio: riprova dopo l'alzata"}
        s = _sender()
        chat = _reply_chat(args["in_reply_to"]) if args.get("in_reply_to") else s.chat_id
        wp.send_player_button(s.token, chat, w, base, call=transport_call, text=args.get("text"))
        return {"status": "sent", "url_length": len(url)}
    if name == "telegram_inbox":
        rows = tq.list_pending(include_system=args.get("include_system", True))
        return {"pending": rows, "count": len(rows)}
    if name == "telegram_reply":
        chat = _reply_chat(args["id"])
        s = _sender()
        tt.send_text(s.token, chat, args["text"], parse_mode=args.get("parse_mode"), call=transport_call)
        tq.record_sent(args["id"], chat, args["text"])
        if args.get("done", True):
            tq.mark_done(args["id"])
        return {"status": "sent", "done": args.get("done", True)}
    if name == "hridaya_service":
        act = args["action"]
        listening = [f"coda: {tq.inbox_path()}", "cancello: silenzio notturno, alzata, sera",
                     f"review: {', '.join(sorted(_installed_plugins())) or 'nessun coach installato'}"]
        if act == "on":
            SERVICE.start(listening)
        elif act == "off":
            SERVICE.stop()
        return {"on": SERVICE.on, "active_for_bot": session_state.is_active(), "listening": listening,
                "inbox": str(tq.inbox_path()), "pending": len(tq.list_pending()),
                "gate": push_gate.status(session_active=session_state.is_active())}
    if name == "gate_status":
        return push_gate.status(session_active=session_state.is_active())
    if name == "reviews_due":
        import hridaya_calendar as hc
        return {"due": hc.due(datetime.now(cc.tz()), plugins=_installed_plugins())}
    if name == "review_done":
        import hridaya_calendar as hc
        if not hc.mark_done(args["job"], datetime.now(cc.tz()).date().isoformat()):
            raise ToolError(f"job sconosciuto: {args['job']}")
        return {"status": "ok"}
    raise ToolError(f"tool sconosciuto: {name}")


# --- JSON-RPC ---------------------------------------------------------------------------

def handle(req: dict) -> dict | None:
    method, rid = req.get("method"), req.get("id")
    if rid is None:   # notifica (es. notifications/initialized): nessuna risposta
        return None
    try:
        if method == "initialize":
            asked = (req.get("params") or {}).get("protocolVersion")
            result = {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                      "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER,
                      "instructions": "Canale Telegram di Hṛdaya: risposta = subito, iniziativa = cancello."}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            p = req.get("params") or {}
            try:
                out = call_tool(p.get("name"), p.get("arguments") or {})
                result = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, default=str)}],
                          "isError": False}
            except (ToolError, tt.TelegramError, RuntimeError, OSError, ValueError, KeyError) as e:
                result = {"content": [{"type": "text", "text": f"Errore: {e}"}], "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"metodo sconosciuto: {method}"}}
        return {"jsonrpc": "2.0", "id": rid, "result": result}
    except Exception as e:  # noqa: BLE001
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": str(e)}}


def main() -> int:
    cc.apply_ca_bundle()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON non valido"}}
            else:
                resp = handle(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    finally:
        SERVICE.stop()   # sessione chiusa: il battito si ferma, il bot lo vede
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
