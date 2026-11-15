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
    assert b.process_update(upd("/log"), {42}) == "diario"
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


def test_allenamento_non_riapre_una_seduta_vietata(data, fake_call, monkeypatch):
    monkeypatch.setattr(wp, "DAILY", data / "daily")
    wp.DAILY.mkdir()
    (data / "data" / "coach-longevita").mkdir(parents=True)
    (data / "data" / "coach-longevita" / "state.json").write_text(json.dumps(
        {"preference_book": {"no_rules": [{"match": ["run"], "max_min": 30, "why": "ginocchia"}]}}))
    w = {"title": "Z2", "blocks": [{"type": "timed", "name": "Z2", "exercises": [{"name": "Run", "time_s": 3600}]}]}
    (wp.DAILY / "2026-11-06.player.json").write_text(json.dumps(w))
    monkeypatch.setattr(wp, "latest_player", lambda daily: daily / "2026-11-06.player.json")
    make(fake_call).process_update(upd("/allenamento"), {42})
    m, p = fake_call.calls[-1]
    assert not p.get("reply_markup") and "Scheda bloccata" in p["text"] and "ginocchia" in p["text"]


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


def _enqueue_at(text, when):
    mid = tq.enqueue(42, text)
    rows = tq.read_jsonl(tq.inbox_path())
    for r in rows:
        if r["id"] == mid:
            r["created_at"] = when.astimezone(timezone.utc).isoformat()
    tq.inbox_path().write_text("".join(json.dumps(r) + "\n" for r in rows))
    return mid


def test_messaggio_prima_del_pavimento_diventa_alzata_al_pavimento(data, fake_call):
    tz = tb.cc.tz()
    b = make(fake_call, active=True)
    _enqueue_at("Ciao", datetime(2026, 11, 14, 4, 50, tzinfo=tz))        # pavimento di default 05:00
    assert not b.maybe_wake_from_early_message(datetime(2026, 11, 14, 4, 55, tzinfo=tz))   # non ancora
    assert b.maybe_wake_from_early_message(datetime(2026, 11, 14, 5, 0, 30, tzinfo=tz))
    w = pg.load_state()["wake"]["2026-11-14"]
    assert w["at"] == "05:00" and "04:50" in w["source"]
    assert any(r.get("event") == "wake" for r in tq.list_pending())
    assert not b.maybe_wake_from_early_message(datetime(2026, 11, 14, 5, 1, tzinfo=tz))    # una volta sola


def test_messaggio_della_notte_fonda_non_e_alzata(data, fake_call):
    tz = tb.cc.tz()
    b = make(fake_call, active=True)
    _enqueue_at("non dormo", datetime(2026, 11, 14, 2, 40, tzinfo=tz))   # fuori dall'ora prima
    assert not b.maybe_wake_from_early_message(datetime(2026, 11, 14, 5, 10, tzinfo=tz))
    assert "2026-11-14" not in (pg.load_state().get("wake") or {})


def test_messaggio_gia_risposto_prima_del_pavimento_vale_lo_stesso(data, fake_call):
    tz = tb.cc.tz()
    b = make(fake_call, active=True)
    tq.mark_done(_enqueue_at("ciao", datetime(2026, 11, 14, 4, 30, tzinfo=tz)))   # risposta trattenuta
    assert b.maybe_wake_from_early_message(datetime(2026, 11, 14, 5, 0, 20, tzinfo=tz))


def test_bot_ripartito_tardi_lascia_fare_al_cancello(data, fake_call):
    tz = tb.cc.tz()
    b = make(fake_call, active=True)
    _enqueue_at("ciao", datetime(2026, 11, 14, 4, 50, tzinfo=tz))
    assert not b.maybe_wake_from_early_message(datetime(2026, 11, 14, 12, 0, tzinfo=tz))
    assert "2026-11-14" not in (pg.load_state().get("wake") or {})


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


def test_in_coda_l_id_telegram_per_la_reazione(data, fake_call):
    u = upd("fatto il cammino")
    u["message"]["message_id"] = 321
    assert make(fake_call).process_update(u, {42}).startswith("coda")
    assert tq.list_pending(include_system=False)[0]["tg_message_id"] == 321


def test_studio_va_in_coda_per_il_kaula(data, fake_call):
    assert make(fake_call).process_update(upd("/studio inquiry"), {42}).startswith("coda")
    assert tq.list_pending(include_system=False)[0]["text"] == "/studio inquiry"
    import workout_player as wp
    assert any(c["command"] == "studio" for c in wp.BOT_COMMANDS)


def test_sta_scrivendo_finche_non_ha_risposto(data, fake_call):
    b = make(fake_call, active=True)
    mid = tq.enqueue(42, "come ho dormito?")
    tq.enqueue_system("wake", "alzata")                      # gli eventi di sistema non contano
    assert b.typing_tick() == {42}
    assert fake_call.calls[-1] == ("sendChatAction", {"chat_id": 42, "action": "typing"})
    tq.mark_done(mid)
    assert b.typing_tick() == set()


def test_sta_scrivendo_no_senza_sessione_di_notte_o_se_vecchio(data, fake_call):
    from datetime import datetime, timedelta, timezone
    tq.enqueue(42, "ci sei?")
    assert make(fake_call, active=False).typing_tick() == set()
    later = datetime.now(timezone.utc) + timedelta(seconds=tb.TYPING_MAX_S + 5)
    assert make(fake_call, active=True).typing_tick(now=later) == set()
    (data / "config" / "hridaya.json").write_text(json.dumps(
        {"bedtime": "00:01", "wake": {"fallback": "23:59", "fallback_max": "23:59", "late_cutoff": "23:59"}}))
    assert make(fake_call, active=True).typing_tick() == set()
    assert not [c for c in fake_call.calls if c[0] == "sendChatAction"]


def test_novita_una_volta_per_versione(data):
    import release
    notes = ("## 0.11.0\n- Le canzoni.\n- Le novità\n  su due righe.\n- [canzoni] Solo con ACE-Step.\n\n"
             "## 0.10.0 — 14/11\n- Il registro.\n\n## 0.9\n- Vecchio.\n")
    sent = []

    def send(text):
        sent.append(text)
        return "sent"
    off = {"canzoni": False}
    assert release.announce(send, "0.10.0", notes, off) is None and not sent      # prima installazione
    assert release.announce(send, "0.11.0", notes, off) == "sent"
    assert "Hṛdaya 0.11.0" in sent[0] and "Le novità su due righe." in sent[0]
    assert "Il registro" not in sent[0] and "ACE-Step" not in sent[0]
    assert release.announce(send, "0.11.0", notes, off) is None and len(sent) == 1   # una volta sola
    (data / "data" / "hridaya" / "release.json").write_text('{"announced": "0.9.0"}')
    release.announce(send, "0.11.0", notes, {"canzoni": True})
    assert "<b>0.10.0</b>" in sent[1] and "Solo con ACE-Step." in sent[1] and "Vecchio" not in sent[1]
    assert release.announce(send, "0.12.0", notes, off) is None and len(sent) == 2   # versione senza note


def test_novita_su_repo_gia_in_uso_senza_stato(data):
    import release
    import telegram_queue as tq
    tq.enqueue(42, "ciao")                                # il canale è già stato usato
    sent = []
    release.announce(lambda t: sent.append(t) or "sent", "0.11.0",
                     "## 0.11.0\n- Nuova.\n\n## 0.10.0\n- Vecchia.\n", {})
    assert len(sent) == 1 and "Nuova." in sent[0] and "Vecchia." not in sent[0]


def test_novita_del_plugin_si_leggono():
    import release
    notes = release.parse(release.NOTES.read_text(encoding="utf-8"))
    v = release.version()
    if v.endswith(".0"):                                  # le minor hanno sempre le loro novità
        assert v in notes and notes[v]


def test_diario_in_ordine_con_i_bottoni(data, fake_call):
    import json as _j
    import journal
    import telegram_queue as tq
    logs = data / "data" / "logs"
    logs.mkdir(parents=True)
    day = tb.today_str()
    (logs / f"{day}.json").write_text(_j.dumps({
        "symptoms": {"acufeni": {"reported": "forti al risveglio"}},
        "energy": {"morning_note": "un po' stanco"},
        "notes": "[Telegram 07:23] [coda 1c] Oggi fischi forti\n[Telegram 07:24] [coda 1d] Oggi fischi forti!\n"
                 "[Telegram 07:30] [coda 2a] /allenamento\n[Telegram 07:31] [coda 2b] [bottone] 6"}))
    text, info = journal.text(day)
    assert "🩺 <b>Corpo</b>" in text and "acufeni: forti al risveglio" in text and "energia: un po' stanco" in text
    assert text.count("Oggi fischi forti") == 1 and "/allenamento" not in text and info["own"]
    b = tb.Bot("123:T", call=fake_call, session_active=lambda: True)
    assert b.process_update(upd("/diario"), {42}) == "diario"
    assert b.process_update(upd("/journal"), {42}) == "diario"
    sent = [p for m, p in fake_call.calls if m == "sendMessage"][-1]
    assert sent["parse_mode"] == "HTML" and sent["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "dj:aggiorna"
    cq = {"id": "q", "data": "dj:aggiorna", "from": {"username": "f"}, "message": {"message_id": 3, "chat": {"id": 42}}}
    assert b.process_update({"callback_query": cq}, {42}) == "diario-aggiorna"
    assert b.process_update({"callback_query": {**cq, "id": "q2"}}, {42}) == "diario-gia-chiesto"
    assert [r["text"] for r in tq.list_pending(include_system=False)] == [journal.UPDATE_TEXT]


def test_diario_forme_strane_e_parole_sue(data):
    import json as _j
    import journal
    logs = data / "data" / "logs"
    logs.mkdir(parents=True)
    (logs / "2026-11-14.json").write_text(_j.dumps({
        "morning": {"tinnitus": {"score": 7, "at": "08:00", "context": "dopo il box"},
                    "meditation": {"start": "05:21", "end": "06:02", "minutes": "<b>41"}},
        "practices": [{"title": "Il buio che guarda", "start": "18:44", "end": "19:15"}, {}, "x"],
        "symptoms": {"acufeni": None, "gola": "un po' secca"}, "fitbit": "rotto", "energy": ["a"],
        "notes": "[Telegram 22:07] [coda 5ddf] hey ciao\n[Telegram 22:07] [coda 5ddf] saluta (riscritto dalla sessione)\n"
                 "[Telegram 14:05] [log] fischi stamattina: 7\n[Telegram 22:14] [coda 77aa] sessione di coppia"}))
    text, info = journal.text("2026-11-14")
    assert "acufeni al mattino: 7" in text and "{'score'" not in text
    assert "Il buio che guarda 18:44–19:15" in text and "&lt;b&gt;41" in text
    assert "acufeni: None" not in text and "gola: un po' secca" in text
    assert "hey ciao" in text and "riscritto dalla sessione" not in text and "[log]" not in text
    assert info["own"] and len(text) < 4096
    (logs / "2026-11-13.json").write_text("[1, 2]")                      # diario che non è un oggetto
    assert "Diario di" in journal.text("2026-11-13")[0]
    (logs / "2026-11-12.json").write_text(_j.dumps({"symptoms": {f"s{i}": "x" for i in range(60)}}))
    t12 = journal.text("2026-11-12")[0]
    assert "… e altre 54" in t12 and len(t12) < 4096
    (logs / "2026-11-11.json").write_text(_j.dumps({"bowel": {"bristol": "3-4 formate"}}))
    assert journal.text("2026-11-11")[1]["own"]                         # registrato coi bottoni: è suo


def test_diario_vuoto_propone_di_scrivere(data):
    import journal
    text, info = journal.text("2026-11-16")
    assert not info["own"] and "non hai ancora registrato" in text
    assert journal.markup(info)["inline_keyboard"][0][0]["text"] == "✍️ Scrivi il diario"


def test_nessun_nome_proprio_nei_plugin():
    """I plugin sono pubblici: chi li usa è «la persona», il nome sta nel repo dati."""
    from pathlib import Path
    root = Path(tb.__file__).resolve().parents[2]
    bad = []
    for f in root.rglob("*"):
        if f.suffix not in (".py", ".md", ".sh") or "docs" in f.relative_to(root).parts[:1] \
                or "node_modules" in f.parts or f.name == "test_bot.py" \
                or any(x.startswith(".") for x in f.relative_to(root).parts):
            continue
        if "Francesco" in f.read_text(encoding="utf-8", errors="ignore"):
            bad.append(str(f.relative_to(root)))
    assert not bad, bad
