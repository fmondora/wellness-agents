"""Il rito, lato canale: soglia, bottone, ritorno (tempi del motore), diario, comandi."""
import copy
import json
from datetime import datetime
from pathlib import Path

import pytest

import channel_config as cc
import rito_player as rp
import telegram_bot as tb
import telegram_queue as tq
from test_mcp_server import call, payload, run

HERE = Path(__file__).resolve().parent
FX = json.loads((HERE / "fixtures" / "rito-log.json").read_text(encoding="utf-8"))
DEMO = json.loads((HERE.parents[2] / "maestro-sauna" / "apps" / "rito" / "fixtures" / "demo.rito.json")
                  .read_text(encoding="utf-8"))
RULES = {"heat_round_max_min": 15, "heat_total_max_min": 25, "rounds_max": 2, "temp_max_c": 70,
         "cold": {"allowed": True, "max_min": 5, "optional": True}}


def rito(day, **over):
    r = copy.deepcopy(DEMO)
    r.update(date=day, demo=False, **over)
    return r


def write_rito(data, day, **over):
    d = data / "data" / "sauna" / "riti"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{day}.rito.json"
    f.write_text(json.dumps(rito(day, **over)))
    return f


def rules(data, r=RULES):
    d = data / "data" / "sauna"
    d.mkdir(parents=True, exist_ok=True)
    (d / "rules.json").write_text(json.dumps(r))


def moments(s):
    return [(m["id"], m["actual_s"], m["ended"]) for m in s["moments"]]


def test_il_ritorno_ha_gli_stessi_numeri_del_motore():
    want = FX["summary"]
    for key in ("log", "cut", "no_summary"):          # intero, tagliato a 520 byte, senza riassunto (rigiocato)
        s = rp.decode_web_app_data(FX[key])
        got = moments(s)
        exp = [(m["id"], m["actual_s"], m["ended"]) for m in want["moments"]]
        if key == "no_summary":                         # rigiocato da eventi al secondo: un secondo di tolleranza
            assert all(a[0] == b[0] and a[2] == b[2] and abs(a[1] - b[1]) <= 1 for a, b in zip(got, exp)), got
            continue
        assert got == exp, key
        assert (s["rounds"], s["heat_s"], s["cold_s"], s["air_s"], s["rest_s"]) == \
            (want["rounds"], want["heat_s"], want["cold_s"], want["air_s"], want["rest_s"])
        assert s["status"] == "end" and not s["approx"]
    s = rp.decode_web_app_data(FX["log"])
    assert s["answers"]["corpo"] == "🌊 Sciolto" and "secondo calore" in s["note"]
    assert s["started_at"].startswith("2026-11-19T18:00:00") and not s["demo"]
    assert rp.decode_web_app_data(FX["cut"])["truncated_events"] > 0
    cut_old = json.loads(FX["cut"])
    del cut_old["A"]
    assert rp.decode_web_app_data(json.dumps(cut_old))["approx"] is True     # tagliato e senza riassunto: lo dice
    assert rp.is_rito_data(FX["log"]) and not rp.is_rito_data('{"v":1,"B":[]}') and not rp.is_rito_data("x")
    assert not rp.is_rito_data("[" * 3000)
    for bad in ('{"v":1,"k":"rito","t0":1,"M":[],"E":[]}', '{"v":1,"k":"rito","t0":"x","M":[["a","rest"]],"E":[[0,0,-1]]}',
                '[1]', '{"v":2,"k":"rito"}'):
        with pytest.raises(Exception):
            rp.decode_web_app_data(bad)


def test_seduta_salvata_una_volta_e_detta_in_prosa(data):
    s = rp.decode_web_app_data(FX["log"])
    f1 = rp.store_session(s, data)
    f2 = rp.store_session(rp.decode_web_app_data(FX["log"]), data)          # reinvio dello stesso rito
    assert f1 == f2 and f1.name == "2026-11-19.session.json"
    poor = rp.decode_web_app_data(FX["cut"])                                # stesso t0, meno eventi: non copre
    rp.store_session(poor, data)
    assert len(json.loads(f1.read_text())["events"]) == len(s["events"])
    assert len(list((data / "data" / "sauna" / "sessions").iterdir())) == 1
    text = rp.reply_text(s)
    assert "due passaggi nel calore, 20 minuti in tutto" in text and "riposo 28 minuti" in text and "acqua" not in text
    assert rp.diary_entry(s) == {"done": True, "rounds": 2, "heat_min": 20, "cold_min": 0.0, "rest_min": 28,
                                 "started_at": "18:00", "ended_at": "18:59", "status": "end", "source": "rito"}
    assert rp._min(150) == "3 minuti" and rp._min(30) == "un minuto" and rp._min(20) == "meno di un minuto"   # come la pagina


def test_diario_unito_e_nel_giorno_del_rito(data):
    logs = data / "data" / "logs"
    logs.mkdir(parents=True)
    (logs / "2026-11-19.json").write_text(json.dumps(
        {"notes": "giornata", "movement": {"walk": "40'", "sauna": {"planned": True, "note": "10-15', prima delle 20", "done": None}}}))
    s = rp.decode_web_app_data(FX["log"])
    p = rp.write_diary(s, data)
    assert p.name == "2026-11-19.json"                                      # il giorno del rito, non oggi
    log = json.loads(p.read_text())
    sa = log["movement"]["sauna"]
    assert sa["planned"] is True and sa["note"].startswith("10-15") and sa["done"] is True and sa["rounds"] == 2
    assert log["movement"]["walk"] == "40'" and log["notes"] == "giornata"
    stopped = json.loads(FX["log"])
    stopped.update(E=[[0, 0, -1], [0, 1, 0], [30, 8, 0]], A=[[30, "stop"]] + [[-1, "never"]] * 8, st="stop")
    rp.write_diary(rp.decode_web_app_data(json.dumps(stopped)), data)       # un rito fermato alla soglia non copre quello fatto
    assert json.loads(p.read_text())["movement"]["sauna"]["rounds"] == 2
    (logs / "2026-11-19.json").write_text(json.dumps({"movement": "camminata", "x": 1}))
    rp.write_diary(s, data)
    assert json.loads(p.read_text())["movement"] == {"text": "camminata", "sauna": {**rp.diary_entry(s)}}
    (logs / "2026-11-19.json").write_text("{rotto")
    assert rp.write_diary(s, data) is None and p.read_text() == "{rotto"    # illeggibile: non si riscrive


def test_il_bot_salva_il_rito_scrive_il_diario_e_avvisa_la_sessione(data, fake_call):
    bot = tb.Bot("123:T", call=fake_call, session_active=lambda: True)
    upd = {"message": {"chat": {"id": 42}, "web_app_data": {"data": FX["log"]}}}
    assert bot.process_update(upd, {42}) == "seduta"
    assert (data / "data" / "sauna" / "sessions" / "2026-11-19.session.json").exists()
    sent = [p for m, p in fake_call.calls if m == "sendMessage"][-1]
    assert "Rito registrato" in sent["text"] and sent["reply_markup"] == {"remove_keyboard": True}
    ev = [r for r in tq.list_pending() if r.get("event") == "rito_session"]
    assert len(ev) == 1 and ev[0]["data"]["file"] == "data/sauna/sessions/2026-11-19.session.json"
    log = json.loads((data / "data" / "logs" / "2026-11-19.json").read_text())
    assert log["movement"]["sauna"]["rounds"] == 2 and log["movement"]["sauna"]["done"] is True
    bot.process_update(upd, {42})                                           # reinvio: un solo evento
    assert len([r for r in tq.list_pending() if r.get("event") == "rito_session"]) == 1
    demo = json.loads(FX["log"])
    demo.update(demo=1, t0=demo["t0"] + 5000)
    bot.process_update({"message": {"chat": {"id": 42}, "web_app_data": {"data": json.dumps(demo)}}}, {42})
    assert len([r for r in tq.list_pending() if r.get("event") == "rito_session"]) == 1      # la prova non avvisa
    assert "prova a secco" in fake_call.texts()[-1]
    for junk in ('{"k":"rito","v":1}', '{"k":"rito","v":1,"t0":1,"M":[["a","rest",0,0,0]],"E":[[0,1,99]]}'):
        bot.process_update({"message": {"chat": {"id": 42}, "web_app_data": {"data": junk}}}, {42})
    raw = [f for f in (data / "data" / "sauna" / "sessions").iterdir() if f.name.endswith(".session-raw.txt")]
    assert len(raw) >= 1 and "illeggibile" in fake_call.texts()[-2] + fake_call.texts()[-1]


def test_risposta_che_fallisce_non_perde_diario_ed_evento(data):
    class Down:
        def __call__(self, token, method, **params):
            raise OSError("rete giù")
    bot = tb.Bot("123:T", call=Down(), session_active=lambda: True)
    bot.process_update({"message": {"chat": {"id": 42}, "web_app_data": {"data": FX["log"]}}}, {42})
    assert [r for r in tq.list_pending() if r.get("event") == "rito_session"]
    assert json.loads((data / "data" / "logs" / "2026-11-19.json").read_text())["movement"]["sauna"]["done"] is True


def test_sauna_riapre_il_rito_di_oggi_e_la_soglia_vale_ancora(data, fake_call, monkeypatch):
    (data / ".env").write_text((data / ".env").read_text() + "RITO_PLAYER_URL=https://rito.pages.dev/\n")
    bot = tb.Bot("123:T", call=fake_call, session_active=lambda: True)
    assert bot.handle_message(42, "/sauna", "f") == "sauna"
    assert "non ha scritto un rito" in fake_call.texts()[-1]
    day = tb.today_str()
    write_rito(data, day, threshold=[{"id": "x", "ok": True, "note": "nota privata della soglia"}])
    seen = []
    monkeypatch.setattr(rp, "guard", lambda r, root=None, reopen=False: seen.append(reopen) or [])
    bot.handle_message(42, "/sauna", "f")
    sent = [p for m, p in fake_call.calls if m == "sendMessage"][-1]
    kb = sent["reply_markup"]["keyboard"]
    url = kb[0][0]["web_app"]["url"]
    assert kb[0][0]["text"] == rp.BUTTON_TEXT and url.startswith("https://rito.pages.dev/#")
    assert kb[1][0]["text"] == rp.CLOSE_TEXT == tb.RITO_CLOSE_TEXT
    assert "threshold" not in json.dumps(rito(day)) or "bm90YSBwcml2YXRh" not in url          # la nota della soglia non viaggia
    bot.handle_message(42, "/sauna", "f")
    assert seen == [False, True]                                             # la seconda è una riapertura
    monkeypatch.setattr(rp, "guard", lambda r, root=None, reopen=False: ["potrebbe finire alle 20:40, oltre le 20:00"])
    bot.handle_message(42, "/sauna", "f")
    assert "soglia resta chiusa" in fake_call.texts()[-1] and "20:40" in fake_call.texts()[-1]
    assert bot.handle_message(42, rp.CLOSE_TEXT, "f") == "chiudi"
    assert "/sauna" in fake_call.texts()[-1] and not tq.list_pending()
    s = rp.decode_web_app_data(FX["log"])
    s["started_at"] = day + s["started_at"][10:]
    rp.store_session(s, data)                                                # il rito di oggi è già chiuso
    bot.handle_message(42, "/sauna", "f")
    assert "già compiuto" in fake_call.texts()[-1]
    monkeypatch.setattr(rp, "installed", lambda: False)
    bot.handle_message(42, "/sauna", "f")
    assert "non è installato" in fake_call.texts()[-1]


def test_la_soglia_vera_del_maestro(data):
    """Senza monkeypatch: il canale chiama davvero rito_guard del plugin maestro-sauna."""
    day = datetime.now(cc.tz()).date().isoformat()
    assert "manca data/sauna/rules.json" in rp.guard(rito(day), data)[0]    # senza setup: chiusa
    rules(data)
    r = rito(day)
    for m in r["moments"]:
        if m["type"] == "heat":
            m["max_s"] = 3000
    assert any("tetto" in x for x in rp.guard(r, data))
    assert any("riscrive per oggi" in x for x in rp.guard(rito("2020-01-01"), data))
    assert rp.guard(rito(day), data, reopen=True) == []


def test_tool_send_rito(data, tmp_path):
    day = datetime.now(cc.tz()).date().isoformat()
    rules(data)
    f = write_rito(data, day)
    r = json.loads(f.read_text())
    old = data / "data" / "sauna" / "riti" / "2020-01-01.rito.json"
    old.write_text(json.dumps(r))                                           # il file dice un giorno, la partitura un altro
    log = tmp_path / "log.jsonl"
    nourl = run(data, [call(1, "telegram_send_rito", {"rito_json": str(f), "dry_run": True})], log)
    assert nourl[0]["result"]["isError"] and "RITO_PLAYER_URL" in nourl[0]["result"]["content"][0]["text"]
    (data / ".env").write_text((data / ".env").read_text() + "RITO_PLAYER_URL=https://rito.pages.dev/\n")
    out = run(data, [call(1, "telegram_send_rito", {"rito_json": str(old), "dry_run": True}),
                     call(2, "telegram_send_rito", {"rito_json": "data/profile.json"}),
                     call(3, "telegram_send_rito", {"rito_json": str(f), "dry_run": True, "parse_mode": "HTML"})], log)
    assert out[0]["result"]["isError"] and "vale per il suo giorno" in out[0]["result"]["content"][0]["text"]
    assert out[1]["result"]["isError"]                                      # fuori da data/sauna/riti
    third = out[2]["result"]
    # passa forma e tetti; di sera tardi o di notte può fermarsi solo sulle regole dell'ora (qui non ce ne sono)
    assert not third["isError"], third["content"][0]["text"]
    assert payload(out[2])["status"] == "ok" and payload(out[2])["url_length"] > 500
    s = rp.decode_web_app_data(FX["log"])
    s["started_at"] = day + s["started_at"][10:]
    rp.store_session(s, data)
    again = run(data, [call(1, "telegram_send_rito", {"rito_json": str(f), "dry_run": True})], log)
    assert again[0]["result"]["isError"] and "già stato fatto" in again[0]["result"]["content"][0]["text"]


def test_fragment_compresso_e_bottone_con_un_limite():
    r = rito("2026-11-19", threshold=[{"id": "x", "ok": True, "note": "privata"}])
    assert rp.encode_fragment(r).startswith("z=")                           # la partitura piena supera i 2 KB
    assert rp.encode_fragment(r) == rp.encode_fragment({k: v for k, v in r.items() if k != "threshold"})
    small = {"v": 1, "moments": [{"id": "a", "name": "A", "type": "rest"}]}
    frag = rp.encode_fragment(small)
    assert frag.startswith("r=") and "=" not in frag[2:]
    import os
    huge = rito("2026-11-19")
    for m in huge["moments"]:
        m["cues"] = [{"at_s": k, "text": os.urandom(100).hex()} for k in range(12)]   # testo che non si comprime
    with pytest.raises(ValueError, match="troppo lunga"):
        rp.build_url("https://x/", huge)


def test_menu_senza_sauna_se_il_maestro_non_c_e(monkeypatch):
    import _plugins
    import workout_player as wp
    assert any(c["command"] == "sauna" for c in wp.bot_commands())
    monkeypatch.setattr(_plugins, "plugin_scripts", lambda name: None)
    assert not any(c["command"] == "sauna" for c in wp.bot_commands())
