"""Registro delle cose da loggare: proposta, domande a bottoni dopo il messaggio che apre il momento,
nudge non invasivi, «continuo?» dopo tre giorni ignorati, follow-up a fine voce."""
import json
from datetime import datetime

import pytest

import channel_config as cc
import log_plan as lp

CFG = {"bedtime": "22:15", "evening_message": "22:00", "wake": {"late_cutoff": "14:00"}}

GUT = {"title": "Diario intestinale", "why": "capire aria e feci prima della visita", "origin": "consiglio del 15/11",
       "when": "morning", "days": 7, "start": "2026-11-16",
       "fields": [
           {"key": "forma", "ask": "Le feci di oggi?", "target": "symptoms.feci.tipo",
            "options": [["1-2 dure", "3-4 formate"], ["5 morbide", "6 pastose", "7 liquide"], ["Non sono andato"]]},
           {"key": "aspetto", "ask": "Galleggiavano o restavano attaccate?", "target": "symptoms.feci.aspetto",
            "options": ["Galleggiano", "Attaccate", "Né l'uno né l'altro"],
            "skip_when": {"forma": ["Non sono andato"]}},
           {"key": "aria", "ask": "L'aria da ieri sera?", "target": "symptoms.meteorismo.livello",
            "options": ["Poca", "Tanta", "Tanta e puzzolente"]}],
       "followup": {"action": "council", "question": "Rileggere il quadro col diario", "cost": "~9 dispatch"}}


def at(d, hm):
    h, m = map(int, hm.split(":"))
    y, mo, dd = map(int, d.split("-"))
    return datetime(y, mo, dd, h, m, tzinfo=cc.tz())


def woke(d):
    return {"wake_sent": d}


def log(data, d):
    return json.loads((data / "data" / "logs" / f"{d}.json").read_text())


def tok(m):
    return m["markup"]["inline_keyboard"][0][0]["callback_data"].split(":")[1]


def labels(m):
    return [b["text"] for r in m["markup"]["inline_keyboard"] for b in r]


def press(m, label):
    i = labels(m).index(label)
    return lp.tap(f"lg:{tok(m)}:{i}")


def active(data, monkeypatch, item=None):
    monkeypatch.setattr(lp, "_today", lambda: "2026-11-16")
    return lp.add(item or GUT, proposed=False, today="2026-11-16")


def test_spec_validata():
    with pytest.raises(lp.PlanError):
        lp.validate({**GUT, "days": 0})
    with pytest.raises(lp.PlanError):
        lp.validate({**GUT, "fields": [{"key": "x", "ask": "?", "target": "a b", "options": ["s"]}]})
    with pytest.raises(lp.PlanError):
        lp.validate({**GUT, "fields": [{"key": "x", "ask": "?", "target": "a", "options": ["Salta"]}]})
    with pytest.raises(lp.PlanError):
        lp.validate({**GUT, "when": "notte"})


def test_proposta_dopo_il_mattino_e_si(data, monkeypatch):
    iid = lp.add(GUT)                                         # proposta del consiglio
    assert lp.load()["items"][iid]["status"] == "proposed"
    assert lp.due_messages(at("2026-11-15", "07:00"), CFG, {}, silent=False) == []      # mattino non aperto
    assert lp.due_messages(at("2026-11-15", "09:00"), CFG, woke("2026-11-15"), silent=True) == []
    out = lp.due_messages(at("2026-11-15", "09:00"), CFG, woke("2026-11-15"), silent=False)
    assert len(out) == 1 and "Proposta (consiglio del 15/11)" in out[0]["text"] and labels(out[0]) == ["Sì", "No"]
    assert lp.due_messages(at("2026-11-15", "09:05"), CFG, woke("2026-11-15"), silent=False) == []   # una volta
    monkeypatch.setattr(lp, "_today", lambda: "2026-11-15")
    res = press(out[0], "Sì")
    it = lp.load()["items"][iid]
    assert res["action"] == "done" and it["status"] == "active"
    assert (it["start"], it["end"]) == ("2026-11-16", "2026-11-22")      # parte dal giorno indicato


def test_proposta_rifiutata(data):
    iid = lp.add(GUT)
    m = lp.due_messages(at("2026-11-15", "15:00"), CFG, {}, silent=False)[0]   # oltre late_cutoff: aperto
    press(m, "No")
    assert lp.load()["items"][iid]["status"] == "declined"


def test_domande_in_un_messaggio_che_scorre(data, monkeypatch):
    active(data, monkeypatch)
    assert lp.due_messages(at("2026-11-16", "06:30"), CFG, {}, silent=False) == []   # prima del messaggio del mattino
    out = lp.due_messages(at("2026-11-16", "07:10"), CFG, woke("2026-11-16"), silent=False)
    assert len(out) == 1
    m = out[0]
    assert "giorno 1 di 7" in m["text"] and labels(m)[-1] == "Salta"
    r = press(m, "6 pastose")
    assert r["action"] == "next" and "Galleggiavano" in r["text"]
    r = press(r, "Attaccate")
    assert "aria" in r["text"]
    r = press(r, "Salta")
    assert r["action"] == "done"
    lg = log(data, "2026-11-16")
    assert lg["symptoms"]["feci"] == {"tipo": "6 pastose", "aspetto": "Attaccate"}
    assert "meteorismo" not in lg.get("symptoms", {}) and "Diario intestinale" in lg["notes"]
    assert lp.missing(lp.load()["items"]["diario-intestinale"], "2026-11-16") == []
    assert lp.due_messages(at("2026-11-16", "12:00"), CFG, woke("2026-11-16"), silent=False) == []   # una al giorno
    assert lp.tap(f"lg:{tok(m)}:0")["action"] == "stale"                                        # già usato


def test_non_chiede_quel_che_c_e_gia(data, monkeypatch):
    active(data, monkeypatch)
    p = data / "data" / "logs" / "2026-11-16.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"symptoms": {"feci": "molli, scritto da lui",
                                          "meteorismo": {"livello": "tanta"}}}))
    iid = "diario-intestinale"
    # «feci» testo libero: il campo manca ancora, ma il testo non si perde quando si scrive
    m = lp.due_messages(at("2026-11-16", "07:10"), CFG, woke("2026-11-16"), silent=False)[0]
    assert "Le feci" in m["text"]
    press(m, "Non sono andato")                    # salta «aspetto» da solo; «aria» c'era già
    lg = log(data, "2026-11-16")
    assert lg["symptoms"]["feci"] == {"nota": "molli, scritto da lui", "tipo": "Non sono andato"}
    assert lp.missing(lp.load()["items"][iid], "2026-11-16") == []


def test_tre_giorni_ignorati_chiede_se_continuare(data, monkeypatch):
    iid = active(data, monkeypatch)
    for d in ("2026-11-16", "2026-11-17", "2026-11-18"):
        assert lp.due_messages(at(d, "07:10"), CFG, woke(d), silent=False)
    out = lp.due_messages(at("2026-11-19", "07:10"), CFG, woke("2026-11-19"), silent=False)
    assert len(out) == 1 and "Continuo" in out[0]["text"]
    press(out[0], "Pausa")
    assert lp.load()["items"][iid]["status"] == "paused"
    assert lp.due_messages(at("2026-11-20", "07:10"), CFG, woke("2026-11-20"), silent=False) == []


def test_continua_azzera_il_conto(data, monkeypatch):
    active(data, monkeypatch)
    for d in ("2026-11-16", "2026-11-17", "2026-11-18"):
        lp.due_messages(at(d, "07:10"), CFG, woke(d), silent=False)
    press(lp.due_messages(at("2026-11-19", "07:10"), CFG, woke("2026-11-19"), silent=False)[0], "Sì, continua")
    out = lp.due_messages(at("2026-11-20", "07:10"), CFG, woke("2026-11-20"), silent=False)
    assert len(out) == 1 and "Le feci" in out[0]["text"]


def test_sera_e_notte(data, monkeypatch):
    active(data, monkeypatch, {**GUT, "title": "Frutta secca", "when": "evening",
                               "fields": [{"key": "fs", "ask": "Frutta secca oggi?", "target": "food.frutta_secca",
                                           "options": ["Sì", "No"]}]})
    assert lp.due_messages(at("2026-11-16", "21:00"), CFG, woke("2026-11-16"), silent=False) == []
    assert lp.due_messages(at("2026-11-16", "22:01"), CFG, {"evening_sent": "2026-11-16"}, silent=False)
    assert lp.due_messages(at("2026-11-17", "22:20"), CFG, {"evening_sent": "2026-11-17"}, silent=True) == []
    assert lp.due_messages(at("2026-11-17", "22:10"), CFG, woke("2026-11-17"), silent=False) == []   # sera non partita
    assert lp.due_messages(at("2026-11-17", "22:14"), CFG, woke("2026-11-17"), silent=False)         # ultima chiamata


def test_fine_voce_e_followup(data, monkeypatch):
    iid = active(data, monkeypatch)
    lp.record(iid, "aria", "Poca", "2026-11-18")
    lp.due_messages(at("2026-11-23", "07:10"), CFG, woke("2026-11-23"), silent=False)
    it = lp.load()["items"][iid]
    assert it["status"] == "closed" and lp.followups_due() == [iid]
    lp.followup_done(iid)
    assert lp.followups_due() == []


def test_undo_e_record(data, monkeypatch):
    iid = active(data, monkeypatch)
    m = lp.due_messages(at("2026-11-16", "07:10"), CFG, woke("2026-11-16"), silent=False)[0]
    lp.undo(m)
    assert lp.due_messages(at("2026-11-16", "07:11"), CFG, woke("2026-11-16"), silent=False)
    lp.record(iid, "aria", "poca", "2026-11-16")
    assert log(data, "2026-11-16")["symptoms"]["meteorismo"]["livello"] == "poca"
    with pytest.raises(lp.PlanError):
        lp.record(iid, "boh", "x", "2026-11-16")
    assert lp.ask_now("2026-11-16")["text"].count("Le feci") == 1
    assert any("manca forma" in x for x in lp.summary("2026-11-16"))


def test_bot_tocco_modifica_il_messaggio(data, fake_call, monkeypatch):
    import telegram_bot as tb
    active(data, monkeypatch)
    m = lp.due_messages(at("2026-11-16", "07:10"), CFG, woke("2026-11-16"), silent=False)[0]
    bot = tb.Bot("123:T", call=fake_call, session_active=lambda: True)
    data_cb = m["markup"]["inline_keyboard"][0][1]["callback_data"]
    out = bot.process_update({"callback_query": {"id": "q1", "data": data_cb,
                                                 "message": {"message_id": 9, "chat": {"id": 42}}}}, {42})
    assert out == "registro-next"
    edits = [p for meth, p in fake_call.calls if meth == "editMessageText"]
    assert edits and "Galleggiavano" in edits[0]["text"] and edits[0]["message_id"] == 9
    assert log(data, "2026-11-16")["symptoms"]["feci"]["tipo"] == "3-4 formate"


def test_bot_tick_manda_dopo_il_mattino(data, fake_call, monkeypatch):
    import push_gate
    import telegram_bot as tb
    active(data, monkeypatch)
    monkeypatch.setattr(push_gate, "load_state", lambda: {"wake_sent": "2026-11-16",
                                                          "wake": {"2026-11-16": "06:50"}})
    bot = tb.Bot("123:T", call=fake_call, session_active=lambda: True)
    assert bot.log_tick(at("2026-11-16", "07:10")) == ["domanda"]
    assert bot.log_tick(at("2026-11-16", "07:11")) == []
    sent = [p for meth, p in fake_call.calls if meth == "sendMessage"]
    assert len(sent) == 1 and sent[0]["reply_markup"]


def test_watcher_segnala_il_followup(data, monkeypatch):
    import service_watch as sw
    iid = active(data, monkeypatch)
    lp.record(iid, "aria", "Poca", "2026-11-18")
    lp._update(lambda st: lp.close_expired(st, "2026-11-23"))
    cues = {}
    got = sw.scheduled_cues(at("2026-11-23", "15:00"), cues, plugins=set())
    assert f"FOLLOWUP {iid}" in got
    assert f"FOLLOWUP {iid}" not in sw.scheduled_cues(at("2026-11-23", "15:02"), cues, plugins=set())


def test_diario_illeggibile_non_si_riscrive(data, monkeypatch):
    active(data, monkeypatch)
    m = lp.due_messages(at("2026-11-16", "07:10"), CFG, woke("2026-11-16"), silent=False)[0]
    p = data / "data" / "logs" / "2026-11-16.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"notes": "giornata intera", "movement": {"x": 1},}')
    r = press(m, "5 morbide")
    assert r["action"] == "stale" and "diario" in r["toast"]
    assert p.read_text() == '{"notes": "giornata intera", "movement": {"x": 1},}'
    p.write_text('{"notes": "giornata intera"}')
    assert press(m, "5 morbide")["action"] == "next"          # il token non era consumato
    assert log(data, "2026-11-16")["notes"].startswith("giornata intera\n[diario")


def test_doppio_tocco_non_toglie_i_bottoni(data, fake_call, monkeypatch):
    import telegram_bot as tb
    active(data, monkeypatch)
    m = lp.due_messages(at("2026-11-16", "07:10"), CFG, woke("2026-11-16"), silent=False)[0]
    bot = tb.Bot("123:T", call=fake_call, session_active=lambda: True)
    cq = {"id": "q1", "data": m["markup"]["inline_keyboard"][0][0]["callback_data"],
          "message": {"message_id": 9, "chat": {"id": 42}}}
    assert bot.process_update({"callback_query": cq}, {42}) == "registro-next"
    assert bot.process_update({"callback_query": {**cq, "id": "q2"}}, {42}) == "registro-stale"
    edits = [meth for meth, _ in fake_call.calls if meth.startswith("edit")]
    assert edits == ["editMessageText"]


def test_target_riservati_e_sovrapposti():
    for t in ("notes.feci", "morning.x", "date.x", "feci"):
        with pytest.raises(lp.PlanError):
            lp.validate({**GUT, "fields": [{"key": "x", "ask": "?", "target": t, "options": ["a"]}]})
    with pytest.raises(lp.PlanError):
        lp.validate({**GUT, "fields": [{"key": "x", "ask": "?", "target": "bowel.a", "options": ["a"]},
                                       {"key": "y", "ask": "?", "target": "bowel.a.b", "options": ["a"]}]})
    with pytest.raises(lp.PlanError):
        lp.validate({**GUT, "start": "20261116"})
    with pytest.raises(lp.PlanError):
        lp.validate({**GUT, "title": "x" * 81})
    with pytest.raises(lp.PlanError):
        lp.validate({**GUT, "followup": {"action": "boh", "question": "?"}})


def test_log_su_richiesta_non_brucia_la_sera(data, monkeypatch):
    active(data, monkeypatch)
    lp.add({**GUT, "title": "Frutta secca", "when": "evening",
            "fields": [{"key": "fs", "ask": "Frutta secca oggi?", "target": "food.frutta_secca", "options": ["Sì", "No"]}]},
           proposed=False, today="2026-11-16")
    m = lp.ask_now("2026-11-16", lp.ask_scope(at("2026-11-16", "08:00")))
    assert "Le feci" in m["text"]
    for lab in ("3-4 formate", "Galleggiano"):
        m = press(m, lab)
    r = press(m, "Poca")
    assert r["action"] == "done"                                      # la sera non entra al mattino
    assert all(not it.get("asked") for it in lp.load()["items"].values())
    out = lp.due_messages(at("2026-11-16", "22:05"), CFG, {"evening_sent": "2026-11-16", "wake_sent": "2026-11-16"},
                          silent=False)
    assert len(out) == 1 and "Frutta secca oggi" in out[0]["text"]


def test_continuo_senza_risposta_va_in_pausa(data, monkeypatch):
    iid = active(data, monkeypatch)
    kinds = []
    for d in ("2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21"):
        kinds.append([m.get("kind") for m in lp.due_messages(at(d, "07:10"), CFG, woke(d), silent=False)])
    assert kinds[3] == ["continue"] and kinds[4] == [] and kinds[5] == []
    assert lp.load()["items"][iid]["status"] == "paused"


def test_tocco_non_sovrascrive_e_proposta_stantia(data, monkeypatch):
    iid = active(data, monkeypatch)
    m = lp.due_messages(at("2026-11-16", "07:10"), CFG, woke("2026-11-16"), silent=False)[0]
    lp.record(iid, "forma", "morbide con muco, scritto da lui", "2026-11-16")
    r = press(m, "1-2 dure")
    assert r["toast"] == "Già registrato"
    assert log(data, "2026-11-16")["symptoms"]["feci"]["tipo"] == "morbide con muco, scritto da lui"
    p = lp.add({**GUT, "title": "Altro"})
    pm = lp.due_messages(at("2026-11-16", "22:05"), CFG, {"evening_sent": "2026-11-16", "wake_sent": "2026-11-16"},
                         silent=False)
    pm = [x for x in pm if x.get("kind") == "propose"][0]
    lp.set_status(p, "active", today="2026-11-16")
    lp.set_status(p, "closed", today="2026-11-16")
    assert press(pm, "Sì")["action"] == "stale" and lp.load()["items"][p]["status"] == "closed"
    with pytest.raises(lp.PlanError):
        lp.add(GUT)                                                    # già attiva: niente doppioni


def test_followup_solo_a_scadenza_e_due_volte(data, monkeypatch):
    import service_watch as sw
    iid = active(data, monkeypatch)
    lp.record(iid, "aria", "Poca", "2026-11-17")
    lp.set_status(iid, "closed", today="2026-11-18")
    assert lp.followups_due() == []                                    # chiusa a mano: niente consiglio
    lp.set_status(iid, "active", today="2026-11-20")                   # ripresa: la fine si sposta
    assert lp.load()["items"][iid]["end"] == "2026-11-24"
    lp._update(lambda st: lp.close_expired(st, "2026-11-25"))
    assert lp.followups_due() == [iid]
    got = [sw.scheduled_cues(at(d, "15:00"), {}, plugins=set()) for d in ("2026-11-25", "2026-11-26", "2026-11-27")]
    assert [f"FOLLOWUP {iid}" in g for g in got] == [True, True, False]


def test_riconciliazione_e_nessuna_scrittura_a_vuoto(data, monkeypatch):
    iid = active(data, monkeypatch)
    lp.record(iid, "aria", "Poca", "2026-11-16")
    p = data / "data" / "logs" / "2026-11-16.json"
    p.write_text(json.dumps({"notes": "riscritto dalla sessione"}))   # la risposta sparisce dal diario
    lp.due_messages(at("2026-11-16", "07:10"), CFG, woke("2026-11-16"), silent=False)
    assert log(data, "2026-11-16")["symptoms"]["meteorismo"]["livello"] == "Poca"
    mt = lp.path().stat().st_mtime_ns
    lp.due_messages(at("2026-11-16", "07:12"), CFG, woke("2026-11-16"), silent=False)
    assert lp.path().stat().st_mtime_ns == mt


def test_undo_toglie_il_token(data, monkeypatch):
    active(data, monkeypatch)
    m = lp.due_messages(at("2026-11-16", "07:10"), CFG, woke("2026-11-16"), silent=False)[0]
    lp.undo(m)
    assert m["tok"] not in lp.load()["asks"]


def test_icone_sui_bottoni_testo_pulito_nel_diario(data, monkeypatch):
    item = {**GUT, "fields": [
        {"key": "forma", "ask": "Le feci?", "target": "bowel.bristol",
         "options": [["🪨 1-2 dure", "🍌 3-4 formate"], ["🚫 Non sono andato"]]},
        {"key": "aspetto", "ask": "Galleggiano?", "target": "bowel.aspetto", "options": ["🛟 Sì", "No"],
         "skip_when": {"forma": ["Non sono andato"]}}]}
    active(data, monkeypatch, item)
    m = lp.due_messages(at("2026-11-16", "07:10"), CFG, woke("2026-11-16"), silent=False)[0]
    assert "🍌 3-4 formate" in labels(m)
    r = press(m, "🚫 Non sono andato")
    assert r["action"] == "done" and r["toast"] == "✓ 🚫 Non sono andato"      # skip_when senza icona vale
    assert log(data, "2026-11-16")["bowel"]["bristol"] == "Non sono andato"
    with pytest.raises(lp.PlanError):
        lp.validate({**GUT, "fields": [{"key": "x", "ask": "?", "target": "a.b", "options": ["🍌 Sì", "Sì"]}]})


def test_clean_toglie_solo_i_pittogrammi():
    for raw, want in [("🍌 3-4 formate", "3-4 formate"), ("<5", "<5"), ("> 5 min", "> 5 min"), ("-1", "-1"),
                      ("+1", "+1"), (".5 L", ".5 L"), ("1️⃣ uno", "uno"), ("😐", "😐"),
                      ("🛟🧲 Tutte e due", "Tutte e due"), ("❤️\u200d🔥 Bene", "Bene"), ("«poco»", "«poco»")]:
        assert lp.clean(raw) == want, raw
    lp.validate({**GUT, "fields": [{"key": "x", "ask": "?", "target": "a.b", "options": ["< 30′", "> 30′"]}]})


def test_badge_registra_conta_le_domande_di_adesso(data, monkeypatch):
    import journal
    active(data, monkeypatch, {**GUT, "title": "Sonno che manca", "when": "evening",
                               "fields": [{"key": "fs", "ask": "?", "target": "food.x", "options": ["Sì", "No"]}]})
    assert journal.text("2026-11-16", now=at("2026-11-16", "10:00"))[1]["missing"] == 0     # sera: non ancora
    assert journal.text("2026-11-16", now=at("2026-11-16", "19:00"))[1]["missing"] == 1
    lp.record("sonno-che-manca", "fs", "🙂 Sì", "2026-11-16")
    assert log(data, "2026-11-16")["food"]["x"] == "Sì"                                    # record pulisce l'icona
    assert journal.text("2026-11-16", now=at("2026-11-16", "19:00"))[1] == {"own": True, "missing": 0}
