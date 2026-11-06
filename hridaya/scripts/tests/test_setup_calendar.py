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
        self.store, self.ok, self.argvs = {}, ok, []

    def __call__(self, argv, **kw):
        if argv[1] == "add-generic-password" and self.ok:
            assert argv[-1] == "-w"                       # il token non passa mai in argv
            pw, again = kw["input"].splitlines()
            assert pw == again
            self.store[argv[argv.index("-a") + 1]] = pw
            self.argvs.append(argv)
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
    assert all("123:T" not in a for argv in kc.argvs for a in argv)


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


class Updates(FakeCall):
    """getUpdates finto: backlog (offset=-1) e poi i messaggi della finestra."""

    def __init__(self, backlog, window):
        super().__init__()
        self.backlog, self.window = backlog, window

    def __call__(self, token, method, **p):
        self.calls.append((method, p))
        if method == "getUpdates" and p.get("offset") == -1:
            return {"ok": True, "result": self.backlog[-1:]}
        if method == "getUpdates" and p.get("timeout") == 10:
            got, self.window = self.window, []
            return {"ok": True, "result": [u for u in got if u["update_id"] >= p["offset"]]}
        return {"ok": True, "result": {}}


def _u(uid, text, chat=777, date=2000, kind="private"):
    return {"update_id": uid, "message": {"text": text, "date": date,
                                          "chat": {"id": chat, "type": kind, "first_name": "F"}}}


def test_wait_start_vuole_il_codice_e_ignora_il_backlog(data):
    backlog = [_u(1, "/start AB12CD", chat=666, date=500)]           # arrivato prima del setup
    window = [_u(2, "/start", chat=555), _u(3, "/start ZZZZZZ", chat=444),
              _u(4, "/start ab12cd", chat=333, kind="group"), _u(5, "/start AB12CD", chat=777)]
    fc = Updates(backlog, window)
    who = ts.wait_start("T", "AB12CD", 5, call=fc, sleep=lambda s: None, clock=lambda: 1990)
    assert who["id"] == 777
    assert ("getUpdates", {"offset": 2, "timeout": 0}) in fc.calls      # backlog confermato e scartato
    ts.register_chat(777, "T", call=fc)
    assert cc.load_env()["ALLOWED_CHAT_IDS"] == "777"
    assert "Hṛdaya" in fc.texts()[-1]


def test_wait_start_messaggio_vecchio_col_codice_non_vale(data):
    fc = Updates([], [_u(9, "/start AB12CD", date=100)])
    assert ts.wait_start("T", "AB12CD", 1, call=fc, sleep=lambda s: None, clock=lambda: 2000) is None


def test_codice_monouso():
    a, b = ts.new_code(), ts.new_code()
    assert len(a) == 6 and a != b


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



def test_setup_riusa_il_job_del_bot_esistente(tmp_path):
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    (agents / "com.francesco.lucia.telegram.plist").write_bytes(plistlib.dumps(
        {"Label": "com.francesco.lucia.telegram", "ProgramArguments": ["/py", "/x/scripts/telegram_bot.py"]}))
    (agents / "altro.plist").write_bytes(plistlib.dumps({"Label": "altro", "ProgramArguments": ["/bin/true"]}))
    jobs = ts.existing_bot_jobs(agents)
    assert [j["label"] for j in jobs] == ["com.francesco.lucia.telegram"]
    assert ts.choose_label(None, jobs) == "com.francesco.lucia.telegram"
    assert ts.choose_label("com.francesco.lucia.telegram", jobs) == "com.francesco.lucia.telegram"
    import pytest
    with pytest.raises(SystemExit):
        ts.choose_label("com.wellness.hridaya.telegram", jobs)
    assert ts.choose_label(None, []) == "com.wellness.hridaya.telegram"


def test_servizio_non_riemette_dopo_il_riarmo(data):
    import service_watch as sw
    import telegram_queue as tq
    mid = tq.enqueue(42, "ciao")
    seen = set(sw.load_cues().get("seen") or [])
    assert sw.queue_events(seen) == [f"MSG {mid} ciao"]
    cues = sw.load_cues()
    cues["seen"] = sorted(seen)
    sw.save_cues(cues)
    seen2 = set(sw.load_cues().get("seen") or [])           # nuovo processo dopo il riarmo
    assert sw.queue_events(seen2) == []


def test_servizio_non_invita_al_mattino_chiuso(data):
    import push_gate as pg
    import service_watch as sw
    import telegram_queue as tq
    pg.save_state({"wake": {"2026-11-07": {"at": "14:30", "source": "fallback"}}, "wake_skipped": "2026-11-07"})
    tq.enqueue_system("wake", "alzata", {"date": "2026-11-07"})
    assert sw.queue_events(set()) == []
    tz = cc.tz()
    assert not any(c.startswith("MATTINO") for c in
                   sw.scheduled_cues(datetime(2026, 11, 7, 17, 16, tzinfo=tz), {}, plugins=set()))
