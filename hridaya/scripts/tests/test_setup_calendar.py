"""Bootstrap Telegram (portachiavi, controlli, launchd) e calendario delle review."""
import plistlib
import subprocess
from datetime import datetime

import channel_config as cc
import hridaya_calendar as hc
import telegram_setup as ts
import tg_transport as tt
from conftest import FakeCall


class Keychain:
    def __init__(self, ok=True):
        self.store, self.ok = {}, ok

    def __call__(self, argv, **kw):
        if argv[1] == "add-generic-password" and self.ok:
            self.store[argv[argv.index("-a") + 1]] = argv[argv.index("-w") + 1]
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[1] == "find-generic-password":
            acc = argv[argv.index("-a") + 1]
            if acc in self.store:
                return subprocess.CompletedProcess(argv, 0, self.store[acc] + "\n", "")
        return subprocess.CompletedProcess(argv, 44, "", "not found")


def test_migrazione_token_nel_portachiavi(data):
    kc = Keychain()
    assert ts.store_token("123:T", remove_from_env=True, runner=kc, system="Darwin") == "keychain"
    env = cc.load_env()
    assert "TELEGRAM_BOT_TOKEN" not in env and env["TELEGRAM_TOKEN_SOURCE"] == "keychain"
    assert env["ALLOWED_CHAT_IDS"] == "42"                    # il resto del .env resta
    assert cc.bot_token(env, runner=kc) == "123:T"


def test_portachiavi_che_fallisce_lascia_il_token_nel_env(data):
    assert ts.store_token("999:Z", runner=Keychain(ok=False), system="Darwin") == "env"
    assert cc.load_env()["TELEGRAM_BOT_TOKEN"] == "999:Z"


def test_token_malformato_rifiutato(data):
    import pytest
    with pytest.raises(ValueError):
        ts.store_token("ciao", runner=Keychain(), system="Darwin")


def test_check_vede_il_409_e_il_webhook():
    fc = FakeCall(fail={"getUpdates": tt.TelegramError("getUpdates", 409, "Conflict: terminated by other getUpdates")})
    r = ts.check("T", call=fc)
    assert r["bot"] == "@hridaya_bot (Hridaya)" and r["webhook_ok"] and r["conflict"]
    assert "poll_ok" not in ts.check("T", call=FakeCall(), poll=False)


def test_wait_start_registra_e_conferma(data):
    class Calls(FakeCall):
        def __call__(self, token, method, **p):
            self.calls.append((method, p))
            if method == "getUpdates" and p.get("timeout") == 10:
                return {"ok": True, "result": [{"update_id": 5, "message": {
                    "text": "/start", "chat": {"id": 777, "type": "private", "first_name": "F"}}}]}
            return {"ok": True, "result": {}}
    fc = Calls()
    who = ts.wait_start("T", 5, call=fc, sleep=lambda s: None)
    assert who["id"] == 777
    ts.register_chat(777, "T", call=fc)
    assert cc.load_env()["ALLOWED_CHAT_IDS"] == "777"
    assert "Hṛdaya" in fc.texts()[-1]


def test_plist_del_bot(data):
    pl = plistlib.loads(ts.launchd_plist("com.x.bot", data / "scripts/telegram_bot.py", "/py", data))
    assert pl["KeepAlive"] and pl["EnvironmentVariables"]["WELLNESS_DATA"] == str(data)
    assert pl["ProgramArguments"] == ["/py", str(data / "scripts/telegram_bot.py")]


def test_calendario_review(data):
    sun = datetime(2026, 11, 8, 18, 30)
    ids = {j["id"] for j in hc.due(sun)}
    assert {"coach-longevita:weekly_review", "dream-agent:weekly_review",
            "coach-longevita:monthly_review"} <= ids
    assert hc.due(datetime(2026, 11, 8, 17, 0)) == []
    hc.mark_done("coach-longevita:weekly_review", "2026-11-08")
    hc.mark_done("coach-longevita:monthly_review", "2026-11-08")
    ids = {j["id"] for j in hc.due(datetime(2026, 11, 15, 18, 30), plugins={"coach-longevita"})}
    assert ids == {"coach-longevita:weekly_review"}
    assert {j["id"] for j in hc.due(datetime(2026, 12, 6, 19, 0), plugins={"coach-longevita"})} == \
        {"coach-longevita:weekly_review", "coach-longevita:monthly_review"}


def test_servizio_cue_una_volta_al_giorno(data):
    import service_watch as sw
    import telegram_queue as tq
    tz = cc.tz()
    cues = {}
    got = sw.scheduled_cues(datetime(2026, 11, 8, 22, 1, tzinfo=tz), cues, plugins={"coach-longevita"})
    assert "SERA 2026-11-08" in got and "REVIEW coach-longevita:weekly_review" in got
    assert sw.scheduled_cues(datetime(2026, 11, 8, 22, 3, tzinfo=tz), cues, plugins={"coach-longevita"}) == []
    seen = set()
    mid = tq.enqueue(42, "ciao\ncome va")
    tq.enqueue_system("wake", "alzata 06:51")
    ev = sw.queue_events(seen)
    assert ev[0] == f"MSG {mid} ciao come va" and ev[1].startswith("SYS wake ")
    assert sw.queue_events(seen) == []
