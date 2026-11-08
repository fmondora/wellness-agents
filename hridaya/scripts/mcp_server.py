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

SERVER = {"name": "hridaya-telegram", "version": "0.4.0"}
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
        self.yield_to_dedicated = True
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, listening: list[str], yield_to_dedicated: bool = True) -> None:
        self.listening = listening
        self.yield_to_dedicated = yield_to_dedicated
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
                if self.yield_to_dedicated and session_state.dedicated_elsewhere():
                    print("battito: è subentrata la sessione dedicata, smetto", file=sys.stderr)
                    self.on = False
                    return
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
BUTTONS = {"type": "object", "additionalProperties": False, "required": ["options"],
           "description": "Bottoni di risposta sotto il messaggio. options: etichette (max 12, ≤40 caratteri) "
                          "o righe di etichette; multi=true: si accendono più opzioni e si conferma. "
                          "Il tocco torna nella inbox come messaggio di Francesco con il campo `choice`.",
           "properties": {"options": {"type": "array"}, "multi": {"type": "boolean"}}}
# reazioni ammesse ai bot (sottoinsieme di quelle standard di Telegram), scelte per un feedback caldo
# (niente 👊 né 💪: Telegram non li ammette come reazione; vanno nel testo)
REACTIONS = ["👍", "❤", "❤‍🔥", "🥰", "😍", "💘", "😘", "💋", "🔥", "⚡", "🏆", "💯", "👏", "🎉", "🤩", "😎",
             "🙏", "👌", "🤝", "🫡", "🤗", "✍", "🤔", "👀", "😴", "😢", "🕊", "😇"]
VOICE_PROFILE = {"type": "string", "description": "quale voce, se ce n'è più d'una (hridaya_service status le "
                                                "elenca): la sceglie la persona o la suggerisce il Kaula; "
                                                "vuoto = la principale"}
PRACTICE = {"type": "string", "description": "titolo della pratica: sotto il messaggio compaiono «▶️ Inizia» / "
                                           "«⏹ Fine»; il bot registra la finestra e alla fine arriva l'evento "
                                           "practice_done (da leggere sulla FC al minuto). Per meditazioni e "
                                           "pratiche guidate; non insieme a buttons"}
REPLY_TO = {"type": "string", "description": "id di un messaggio di Francesco nella inbox (non di un evento di sistema): "
                                           "di giorno parte subito, di notte passa dal cancello; il messaggio è segnato fatto"}

TOOLS = [
    {"name": "telegram_send",
     "description": "Manda un messaggio d'iniziativa a Francesco su Telegram, come Hṛdaya. Passa dal cancello: "
                    "di notte (dall'ora di letto all'alzata) resta in attesa e si fonde col messaggio del mattino; "
                    "urgent=true solo per red flag clinici.",
     "inputSchema": _schema({"text": {"type": "string"}, "kind": KIND,
                             "parse_mode": {"type": "string", "enum": ["HTML"]},
                             "urgent": {"type": "boolean"}, "in_reply_to": REPLY_TO,
                             "done": {"type": "boolean"}, "buttons": BUTTONS, "practice": PRACTICE}, ["text"])},
    {"name": "telegram_send_card",
     "description": "Manda una scheda: testo HTML + album di immagini (es. la scheda del Coach Longevità). "
                    "spec_path = JSON lista di passi {text} | {photos, caption}, foto relative alla spec; "
                    "foto solo .png/.jpg/.jpeg/.webp/.gif dalle cartelle di export o dagli asset dei plugin.",
     "inputSchema": _schema({"spec_path": {"type": "string"}, "steps": {"type": "array"},
                             "base_dir": {"type": "string"}, "kind": KIND, "in_reply_to": REPLY_TO})},
    {"name": "telegram_send_file",
     "description": "Manda un documento (PDF, immagine…) solo da data/coach-longevita/daily/, data/reports/, "
                    "data/reviews/, data/dream-agent/reviews/, data/exports/ (mai segreti, chiavi, log). "
                    "Di notte senza in_reply_to non parte.",
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
     "description": "Risponde a un messaggio di Francesco della inbox e lo segna fatto. Di giorno parte subito; "
                    "nella finestra di silenzio passa dal cancello (esce dopo l'alzata), salvo urgent=true su un "
                    "messaggio con red flag. Agli eventi di sistema (kind=system) non si risponde.",
     "inputSchema": _schema({"id": {"type": "string"}, "text": {"type": "string"},
                             "parse_mode": {"type": "string", "enum": ["HTML"]},
                             "done": {"type": "boolean"}, "urgent": {"type": "boolean"},
                             "buttons": BUTTONS, "practice": PRACTICE}, ["id", "text"])},
    {"name": "telegram_react",
     "description": "Mette una reazione emoji su un messaggio di Francesco della inbox: un feedback leggero "
                    "(dato registrato, seduta fatta, buona notizia), al posto di una risposta di sole parole "
                    "o prima della risposta. Non sempre: quando dice qualcosa. Di notte non parte. "
                    "done=true se la reazione basta come risposta.",
     "inputSchema": _schema({"id": {"type": "string"}, "emoji": {"type": "string", "enum": REACTIONS},
                             "done": {"type": "boolean"}}, ["id", "emoji"])},
    {"name": "telegram_send_voice",
     "description": "Manda un VOCALE (voce sintetica locale, se i vocali sono accesi nel setup). text = la "
                    "versione per l'orecchio scritta da chi parla (frasi brevi; riga vuota = pausa lunga; "
                    "«...» = pausa breve; niente HTML né emoji), non il messaggio scritto. Per pratiche guidate "
                    "da ascoltare a occhi chiusi o se la persona chiede un vocale; mai dati, schede, temi clinici. "
                    "Serve in_reply_to (risposta) oppure after=evening|wake (subito dopo il messaggio della sera "
                    "o del mattino già partito, uno al giorno). Risponde subito «preparing»: sintesi e invio vanno "
                    "in background (se falliscono arriva un evento voice_failed). Di notte non parte.",
     "inputSchema": _schema({"text": {"type": "string"}, "caption": {"type": "string"},
                             "title": {"type": "string", "description": "breve, per il nome del file"},
                             "in_reply_to": REPLY_TO, "voice_profile": VOICE_PROFILE,
                             "practice": {"type": "boolean", "description": "pratica guidata: «Inizia»/«Fine» sotto "
                                          "il vocale (le meditazioni li hanno sempre)"},
                             "after": {"type": "string", "enum": ["evening", "wake"]}}, ["text"])},
    {"name": "telegram_send_meditation",
     "description": "Prepara e manda una MEDITAZIONE LUNGA da ascoltare in cuffia (5-60 minuti): voce sintetica, "
                    "campane, silenzi e musica di sottofondo, come brano audio. script = copione a tempo scritto "
                    "dal Kaula (segmenti che cominciano con «@mm:ss» o «@mm:ss campana», ultima riga «@mm:ss fine»). "
                    "music = parola del nome di un brano delle cartelle musicali (es. tanpura, bansuri), «drone» "
                    "o «nessuna». Solo su richiesta (in_reply_to). Risponde subito «preparing»: il montaggio "
                    "richiede alcuni minuti, l'invio è in background (errore → evento voice_failed).",
     "inputSchema": _schema({"script": {"type": "string"}, "title": {"type": "string"},
                             "music": {"type": "string"}, "caption": {"type": "string"},
                             "as_voice": {"type": "boolean", "description": "come vocale invece che come brano "
                                          "(se la persona lo chiede; default: brano)"},
                             "voice_profile": VOICE_PROFILE,
                             "in_reply_to": REPLY_TO}, ["script", "title", "in_reply_to"])},
    {"name": "hridaya_service",
     "description": "Accende/spegne il servizio nella sessione (battito che dice al bot che Hṛdaya c'è) "
                    "e riporta cosa si sta ascoltando.",
     "inputSchema": _schema({"action": {"type": "string", "enum": ["on", "off", "status"]},
                             "force": {"type": "boolean", "description": "accendi anche se il servizio batte "
                                       "già in un'altra sessione (solo su richiesta esplicita di Francesco)"}},
                            ["action"])},
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


def _reply_target(msg_id: str) -> tuple[int, dict]:
    """Chat e riga del messaggio a cui si risponde. Agli eventi di sistema non si risponde."""
    row = tq.get_message(msg_id)
    if not row:
        raise ToolError(f"messaggio {msg_id} non trovato nella inbox")
    if row.get("kind") == "system":
        raise ToolError(f"{msg_id} è un evento di sistema ({row.get('event')}), non un messaggio di Francesco: "
                        "non si risponde a un evento. Per un'iniziativa usa telegram_send senza in_reply_to "
                        "(passa dal cancello); poi segna l'evento fatto.")
    return int(row.get("chat_id") or cc.primary_chat_id()), row


def _reply_chat(msg_id: str) -> int:
    return _reply_target(msg_id)[0]


def _is_night() -> bool:
    return push_gate.is_silent(datetime.now(cc.tz()), cc.rhythm(), push_gate.load_state())


def _reply_held(row: dict, urgent: bool) -> bool:
    """Di notte anche le risposte passano dal cancello; subito solo una red flag."""
    if not _is_night():
        return False
    if urgent:
        from telegram_bot import check_red_flags
        if check_red_flags(row.get("text") or ""):
            return False
        raise ToolError("urgent vale solo per rispondere a un messaggio con red flag clinico")
    return True


def _practice_markup(title: Any, buttons: Any) -> dict | None:
    if not title:
        return None
    if buttons:
        raise ToolError("practice e buttons insieme no: una sola tastiera per messaggio")
    if not isinstance(title, str):
        raise ToolError("practice: il titolo della pratica (stringa)")
    import practice
    return practice.create(title)[1]


def _buttons(spec: Any, text: str) -> tuple[str | None, dict | None]:
    """Registra la scelta → (cid, reply_markup); (None, None) se non ci sono bottoni."""
    if spec is None:
        return None, None
    import choices
    if not isinstance(spec, dict) or not isinstance(spec.get("multi", False), bool):
        raise ToolError('buttons: {"options": [...], "multi": true|false}')
    if not (text or "").strip():
        raise ToolError("i bottoni stanno sotto un testo: serve text")
    if len(text) > tt.MAX_TEXT:
        # spezzato in più messaggi, i bottoni finirebbero sull'ultimo pezzo e un errore lì li perderebbe
        raise ToolError(f"con i bottoni il testo sta in un messaggio solo (≤ {tt.MAX_TEXT} caratteri): "
                        "accorcia o manda prima il testo lungo e poi la domanda coi bottoni")
    try:
        return choices.create(spec.get("options"), text, multi=spec.get("multi", False))
    except choices.ChoiceError as e:
        raise ToolError(str(e)) from e


def _with_buttons(cid: str | None, fn):
    """Invio con bottoni: se non è partito di sicuro, la scelta non resta aperta.
    Su un errore di rete non definitivo il messaggio può essere arrivato: la scelta resta aperta."""
    try:
        out = fn()
    except Exception as e:
        if cid and (isinstance(e, ToolError) or tt.is_permanent(e)):
            import choices
            choices.discard(cid)
        raise
    if cid:
        if out.get("status") not in ("sent", "held"):
            import choices
            choices.discard(cid)
        else:
            out["choice_id"] = cid
    return out


def _reply_text(msg_id: str, text: str, parse_mode: str | None, urgent: bool, done: bool,
                buttons: dict | None = None, practice_title: str | None = None) -> dict:
    chat, row = _reply_target(msg_id)
    held = _reply_held(row, urgent)
    pm = _practice_markup(practice_title, buttons)
    cid, markup = _buttons(buttons, text) if not pm else (None, pm)

    def go() -> dict:
        if held:
            r = push_gate.deliver(text, "reply", _sender(), parse_mode=parse_mode, source=f"reply:{msg_id}",
                                  reply_markup=markup)
            return {**r, "as": "reply"}
        s = _sender()
        tt.send_text(s.token, chat, text, parse_mode=parse_mode, reply_markup=markup, call=transport_call)
        tq.record_sent(msg_id, chat, text)
        return {"status": "sent", "as": "reply"}

    out = _with_buttons(cid, go)
    if done:
        tq.mark_done(msg_id)
    return {**out, "done": done}


def _voice_line() -> str:
    try:
        import voice_note as vn
        v = vn.config()
        if not v:
            return "vocali: spenti"
        return f"vocali: accesi (voci: {', '.join(vn.profiles(v))}; la prima è la principale)"
    except Exception as e:  # noqa: BLE001 — una funzione facoltativa non deve fermare il servizio
        return f"vocali: config non valida ({e})"


def _voice_job(name: str, args: dict) -> dict:
    """Vocale o meditazione: valida subito, poi un lavoro in background (niente server bloccato,
    niente doppioni se la chiamata si ripete)."""
    import voice_note as vn
    vcfg = vn.config()
    if not vcfg:
        raise ToolError("vocali spenti: si accendono nella skill setup (fase Vocali), "
                        "config/hridaya.json → voice.enabled")
    meditation = name == "telegram_send_meditation"
    reply, after = args.get("in_reply_to"), args.get("after")
    chat = _reply_target(reply)[0] if reply else None
    try:
        vcfg = vn.with_profile(vcfg, args.get("voice_profile"))
        if meditation:
            import meditation as md
            md.parse(args["script"])
            if vcfg.get("engine", "mlx-audio") != "mlx-audio":
                raise vn.VoiceError("le meditazioni lunghe richiedono il motore mlx-audio")
        else:
            vn.spoken(args["text"])
    except vn.VoiceError as e:
        raise ToolError(str(e))
    if _is_night():
        return {"status": "silent", "note": "finestra di silenzio: niente vocali di notte"}
    if reply:
        key = f"reply:{reply}"            # un vocale (o una meditazione) per messaggio a cui si risponde
    elif after and not meditation:
        st = push_gate.status(session_active=session_state.is_active())
        if not st.get(f"{after}_sent"):
            raise ToolError(f"il messaggio «{after}» di oggi non è ancora partito: il vocale viene dopo")
        key = f"{after}:{datetime.now(cc.tz()).date().isoformat()}"
    else:
        raise ToolError("un vocale è una risposta (in_reply_to) oppure segue il messaggio della sera o del "
                        "mattino (after); le meditazioni solo su richiesta (in_reply_to)")
    payload = {"chat_id": chat or _sender().chat_id, "title": args.get("title") or "",
               "practice": meditation or bool(args.get("practice")),
               "voice_profile": args.get("voice_profile") or "",
               "caption": args.get("caption") or "", "reply_to": reply or ""}
    if meditation:
        payload.update(script=args["script"], music=args.get("music") or "", performer="Kaula",
                       as_voice=bool(args.get("as_voice")))
    else:
        payload["text"] = args["text"]
    r = vn.create_job("meditation" if meditation else "voice", key, payload)
    if reply:
        tq.mark_done(reply)
    return {**r, "done": bool(reply)}


def _installed_plugins() -> set[str]:
    from _plugins import plugin_scripts
    return {p for p in ("coach-longevita", "dream-agent") if plugin_scripts(p)}


def call_tool(name: str, args: dict) -> Any:
    if not cc.is_data_repo():
        raise ToolError(f"non sono in un repo dati ({cc.data_root()} senza data/profile.json): "
                        "apri la sessione nel repo dati o imposta WELLNESS_DATA")
    if name == "telegram_send":
        if args.get("in_reply_to"):
            return _reply_text(args["in_reply_to"], args["text"], args.get("parse_mode"),
                               bool(args.get("urgent")), args.get("done", True), args.get("buttons"),
                               args.get("practice"))
        pm = _practice_markup(args.get("practice"), args.get("buttons"))
        cid, markup = _buttons(args.get("buttons"), args["text"]) if not pm else (None, pm)
        return _with_buttons(cid, lambda: push_gate.deliver(
            args["text"], args.get("kind") or "message", _sender(), parse_mode=args.get("parse_mode"),
            urgent=bool(args.get("urgent")), reply_markup=markup))
    if name == "telegram_send_card":
        if args.get("spec_path"):
            spec = cc.safe_path(args["spec_path"], kind="file")
            if spec.suffix != ".json":
                raise ToolError("spec_path deve essere un .json")
            steps, base = json.loads(spec.read_text(encoding="utf-8")), spec.parent
        elif args.get("steps"):
            steps = args["steps"]
            base = (cc.safe_path(args["base_dir"], kind="image", dir_ok=True) if args.get("base_dir")
                    else cc.data_root().resolve() / "data" / "coach-longevita" / "daily")
        else:
            raise ToolError("serve spec_path o steps")
        steps = cc.safe_card(steps, base)
        if args.get("in_reply_to"):
            chat, row = _reply_target(args["in_reply_to"])
            if _reply_held(row, False):
                r = push_gate.deliver("", "reply", _sender(), card={"steps": steps, "base": str(base)},
                                      source=f"reply:{args['in_reply_to']}")
                tq.mark_done(args["in_reply_to"])
                return {**r, "as": "reply", "done": True}
            s = _sender()
            n = tt.send_card(s.token, chat, steps, base, call=transport_call, multipart=transport_multipart)
            tq.mark_done(args["in_reply_to"])
            return {"status": "sent", "as": "reply", "steps": n, "done": True}
        return push_gate.deliver("", args.get("kind") or "message", _sender(),
                                 card={"steps": steps, "base": str(base)})
    if name == "telegram_send_file":
        path = cc.safe_path(args["path"], kind="file")
        if not path.is_file():
            raise ToolError(f"file non trovato: {path}")
        reply = args.get("in_reply_to")
        chat = _reply_target(reply)[0] if reply else None
        if _is_night():   # di notte un file non parte, nemmeno in risposta: si riprova dopo l'alzata
            return {"status": "silent", "note": "finestra di silenzio: riprova dopo l'alzata (messaggio lasciato in coda)"}
        s = _sender()
        tt.send_file(s.token, chat or s.chat_id, path, args.get("caption") or "", multipart=transport_multipart)
        if reply:
            tq.mark_done(reply)
        return {"status": "sent", "file": path.name, "done": bool(reply)}
    if name == "telegram_send_player":
        import workout_player as wp
        path = cc.safe_path(args["player_json"], kind="player")
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
        reply = args.get("in_reply_to")
        chat = _reply_target(reply)[0] if reply else None
        if _is_night():
            return {"status": "silent", "note": "finestra di silenzio: riprova dopo l'alzata (messaggio lasciato in coda)"}
        s = _sender()
        wp.send_player_button(s.token, chat or s.chat_id, w, base, call=transport_call, text=args.get("text"))
        if reply:
            tq.mark_done(reply)
        return {"status": "sent", "url_length": len(url), "done": bool(reply)}
    if name == "telegram_inbox":
        rows = tq.list_pending(include_system=args.get("include_system", True))
        return {"pending": rows, "count": len(rows)}
    if name == "telegram_reply":
        return _reply_text(args["id"], args["text"], args.get("parse_mode"), bool(args.get("urgent")),
                           args.get("done", True), args.get("buttons"), args.get("practice"))
    if name == "telegram_react":
        chat, row = _reply_target(args["id"])
        if args["emoji"] not in REACTIONS:
            raise ToolError(f"reazione non ammessa: {args['emoji']} (ammesse: {' '.join(REACTIONS)})")
        if not row.get("tg_message_id"):
            raise ToolError("il messaggio non ha l'id Telegram (accodato prima delle reazioni, o un bottone): "
                            "rispondi con telegram_reply")
        if _is_night():
            return {"status": "silent", "note": "finestra di silenzio: niente reazioni di notte"}
        transport_call(_sender().token, "setMessageReaction", chat_id=chat, message_id=row["tg_message_id"],
                       reaction=[{"type": "emoji", "emoji": args["emoji"]}])
        if args.get("done"):
            tq.mark_done(args["id"])
        return {"status": "sent", "emoji": args["emoji"], "done": bool(args.get("done"))}
    if name in ("telegram_send_voice", "telegram_send_meditation"):
        return _voice_job(name, args)
    if name == "hridaya_service":
        act = args["action"]
        listening = [f"coda: {tq.inbox_path()}", "cancello: silenzio notturno, alzata, sera",
                     f"review: {', '.join(sorted(_installed_plugins())) or 'nessun coach installato'}",
                     _voice_line()]
        if act == "on":
            why = None if args.get("force") else session_state.guard(cc.rhythm()["session_heartbeat_max_age_s"])
            if why:
                raise ToolError(why + ". Questa è una sessione di lavoro: niente Monitor, niente risposte su Telegram.")
            SERVICE.start(listening, yield_to_dedicated=not args.get("force"))
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

def handle(req: Any) -> dict | list | None:
    if isinstance(req, list):   # batch JSON-RPC (lecito nel protocollo 2025-03-26)
        if not req:
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "batch vuoto"}}
        out = [r for r in (handle(x) for x in req) if r is not None]
        return out or None
    if not isinstance(req, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "richiesta non valida"}}
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
                # PathNotAllowed è un ValueError: il messaggio dice perché, senza inviare nulla
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
