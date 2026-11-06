"""Bot: comandi, red flag, coda, «non attivo», web_app_data, 409, outbox."""
import json
from datetime import datetime, timezone
from pathlib import Path

import push_gate as pg
import session_state
import telegram_bot as tb
import telegram_queue as tq
import tg_transport as tt
import workout_player as wp

FIX = Path(__file__).resolve().parent / "fixtures"


def make(fake_call, active=False):
    return tb.Bot("123:T", call=fake_call, session_active=lambda: active)


def upd(text=None, chat=42, web=None, uid=1):
    msg = {"chat": {"id": chat, "type": "private"}, "from": {"username": "fra"}}
    if text is not None:
        msg["text"] = text
    if web is not None:
        msg["web_app_data"] = {"data": web}
    return {"update_id": uid, "message": msg}


def test_help_e_nota_e_log(data, fake_call):
    b = make(fake_call)
    assert b.process_update(upd("/help"), {42}) == "help"
    assert "Hṛdaya" in fake_call.texts()[-1]
    assert b.process_update(upd("/nota dormito male"), {42}) == "nota"
    assert b.process_update(upd("/log"), {42}) == "log"
    assert "dormito male" in fake_call.texts()[-1]
    assert tq.list_pending() == []           # i comandi non vanno in coda


def test_chat_sconosciuta_ignorata(data, fake_call):
    assert make(fake_call).process_update(upd("ciao", chat=99), {42}) == "ignorato"
    assert fake_call.calls == []


def test_red_flag_escalation_e_evento(data, fake_call):
    assert make(fake_call).process_update(upd("ho un dolore toracico forte"), {42}) == "red_flag"
    assert fake_call.texts() == [tb.RED_FLAG_REPLY]
    sys_rows = [r for r in tq.list_pending() if r.get("kind") == "system"]
    assert sys_rows[0]["event"] == "red_flag"


def test_sessione_spenta_una_riga_sola_per_assenza(data, fake_call):
    b = make(fake_call, active=False)
    assert b.process_update(upd("ciao"), {42}) == "coda-inattivo"
    b.process_update(upd("ci sei?", uid=2), {42})
    assert fake_call.texts() == [tb.INACTIVE_REPLY]
    assert len(tq.list_pending(include_system=False)) == 2
    # la sessione torna e poi si rispegne: nuovo avviso
    session_state.beat(["test"])
    session_state.off()
    b.process_update(upd("e adesso?", uid=3), {42})
    assert fake_call.texts() == [tb.INACTIVE_REPLY, tb.INACTIVE_REPLY]


def test_sessione_accesa_niente_ack_solo_typing(data, fake_call):
    assert make(fake_call, active=True).process_update(upd("ciao"), {42}) == "coda"
    assert fake_call.texts() == []
    assert ("sendChatAction", {"chat_id": 42, "action": "typing"}) in fake_call.calls


def test_web_app_data_salva_la_seduta_e_avvisa_la_sessione(data, fake_call, monkeypatch):
    monkeypatch.setattr(wp, "DAILY", data / "data" / "coach-longevita" / "daily")
    payload = (FIX / "2026-11-06.webappdata.txt").read_text()
    assert make(fake_call).process_update(upd(web=payload), {42}) == "seduta"
    assert (wp.DAILY / "2026-11-06.session.json").exists()
    m, p = fake_call.calls[-1]
    assert m == "sendMessage" and p["reply_markup"] == {"remove_keyboard": True}
    ev = [r for r in tq.list_pending() if r.get("event") == "workout_session"]
    assert ev and ev[0]["data"]["file"].endswith("2026-11-06.session.json")


def test_allenamento_rimanda_il_bottone(data, fake_call, monkeypatch):
    monkeypatch.setattr(wp, "DAILY", data / "daily")
    wp.DAILY.mkdir()
    (wp.DAILY / "2026-11-06.player.json").write_text((FIX / "2026-11-06.player.json").read_text())
    monkeypatch.setattr(wp, "latest_player", lambda daily: daily / "2026-11-06.player.json")
    make(fake_call).process_update(upd("/allenamento"), {42})
    m, p = fake_call.calls[-1]
    assert p["reply_markup"]["keyboard"][0][0]["web_app"]["url"].startswith("https://x.pages.dev/#")


def test_409_ripetuti_un_solo_avviso_dal_cancello(data, fake_call):
    b = make(fake_call)
    fired = [b.on_conflict() for _ in range(6)]
    assert fired == [False, False, True, False, False, False]
    assert fake_call.texts() == []                      # niente invio diretto (di notte aspetterebbe)
    alerts = [r for r in tq.read_jsonl(pg.push_path()) if r.get("kind") == "alert"]
    assert len(alerts) == 1 and alerts[0]["text"] == tb.CONFLICT_ALERT
    assert pg.load_state()["conflict"]["notified"]
    for _ in range(tb.CONFLICT_RESET_OK_POLLS):
        b.on_poll_ok()
    assert "conflict" not in pg.load_state()


def test_outbox_risposte_subito_iniziative_al_cancello(data, fake_call):
    mid = tq.enqueue(42, "domanda")
    tq.write_reply(mid, 42, "risposta")
    tq.write_reply("insight-x", 42, "camminata?")
    make(fake_call).flush_outbox()
    assert fake_call.texts() == ["risposta"]
    rows = tq.read_jsonl(pg.push_path())
    assert [r["text"] for r in rows] == ["camminata?"]
    assert tq.list_unsent_outbox() == []


def test_messaggio_al_mattino_vale_come_alzata(data, fake_call, monkeypatch):
    fixed = datetime(2026, 11, 7, 6, 10, tzinfo=tb.cc.tz())
    monkeypatch.setattr(tb, "now_local", lambda: fixed)
    make(fake_call, active=True).process_update(upd("buongiorno"), {42})
    assert pg.load_state()["wake"]["2026-11-07"]["source"] == "messaggio"
    assert any(r.get("event") == "wake" for r in tq.list_pending())


def test_messaggio_notturno_non_e_alzata(data, fake_call, monkeypatch):
    monkeypatch.setattr(tb, "now_local", lambda: datetime(2026, 11, 7, 3, 10, tzinfo=tb.cc.tz()))
    make(fake_call).process_update(upd("non dormo"), {42})
    assert "2026-11-07" not in (pg.load_state().get("wake") or {})


def test_errore_telegram_porta_il_codice():
    e = tt.TelegramError("getUpdates", 409, "Conflict")
    assert e.code == 409 and "409" in str(e)


def test_testi_lunghi_spezzati():
    parts = tt.chunks("riga\n" * 2000)
    assert all(len(p) <= tt.MAX_TEXT for p in parts) and "".join(parts) == "riga\n" * 2000


def test_menu_dei_comandi(fake_call):
    wp.set_bot_commands("T", call=fake_call)
    m, p = fake_call.calls[0]
    assert m == "setMyCommands" and [c["command"] for c in p["commands"]][0] == "allenamento"


def test_gate_tick_usa_lo_stesso_trasporto(data, fake_call, monkeypatch):
    b = make(fake_call)
    pg.submit("🚨", source="x", priority="red_flag")
    b.gate_tick()
    assert "🚨" in fake_call.texts()
    json.dumps(pg.load_state())
    assert datetime.now(timezone.utc)
