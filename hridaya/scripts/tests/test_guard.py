"""Un solo ascoltatore: la sessione dedicata ha la precedenza, quelle di lavoro cedono."""
import os
import subprocess
import sys
from pathlib import Path

import session_state as ss

WATCH = Path(__file__).resolve().parent.parent / "service_watch.py"


def test_lavoro_cede_alla_dedicata(data, monkeypatch):
    monkeypatch.delenv("HRIDAYA_SERVICE", raising=False)
    assert ss.guard() is None                       # nessuno batte
    ss.beat(["lavoro"])
    assert ss.guard() is None                       # batte una sessione di lavoro: non blocco
    monkeypatch.setenv("HRIDAYA_SERVICE", "1")
    assert ss.guard() is None                       # la dedicata subentra sempre
    ss.beat(["dedicata"])
    assert ss.read()["dedicated"] is True
    monkeypatch.delenv("HRIDAYA_SERVICE")
    assert "sessione dedicata" in ss.guard()        # ora il lavoro non ascolta
    assert ss.dedicated_elsewhere()


def test_watcher_rifiuta_con_la_dedicata_attiva(data, monkeypatch):
    monkeypatch.setenv("HRIDAYA_SERVICE", "1")
    ss.beat(["dedicata"])
    env = {**os.environ, "WELLNESS_DATA": str(data)}
    env.pop("HRIDAYA_SERVICE", None)
    p = subprocess.run([sys.executable, str(WATCH), "--max-minutes", "0.01"], capture_output=True, text=True,
                       env=env, cwd=str(data), timeout=30)
    assert p.returncode == 3 and "sessione dedicata" in p.stdout
    p = subprocess.run([sys.executable, str(WATCH), "--max-minutes", "0.01"], capture_output=True, text=True,
                       env={**env, "HRIDAYA_SERVICE": "1"}, cwd=str(data), timeout=30)
    assert p.returncode == 0


def test_viva_ma_non_ascolta(data, monkeypatch):
    """Il server MCP batte, il Monitor è scaduto: la sessione è viva ma non è lei che risponde."""
    from datetime import datetime, timedelta, timezone
    monkeypatch.setenv("HRIDAYA_SERVICE", "1")
    t0 = datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc)
    ss.beat(["mcp"], now=t0)
    assert ss.is_active(t0) and ss.read().get("listen_at") is None          # appena accesa: tolleranza
    ss.beat(["coda"], now=t0 + timedelta(seconds=30), listener=True)
    assert ss.read()["pid"] and ss.read()["listen_pid"] and ss.read()["started_at"] == t0.isoformat()
    t1 = t0 + timedelta(minutes=45)
    ss.beat(["mcp"], now=t1)                                                 # batte solo il server MCP
    assert ss.is_alive(t1) and not ss.is_active(t1)
    assert int(ss.listen_age_s(t1)) == 45 * 60 - 30
    ss.beat(["coda"], now=t1, listener=True)                                 # Monitor riarmato
    assert ss.is_active(t1)
    ss.off()
    ss.beat(["mcp"], now=t1 + timedelta(minutes=1))                          # sessione nuova: riparte la tolleranza
    assert ss.read().get("listen_at") is None and ss.is_active(t1 + timedelta(minutes=2))


def test_un_solo_ascoltatore(data, monkeypatch):
    monkeypatch.setenv("HRIDAYA_SERVICE", "1")
    ss.beat(["coda"], listener=True)
    assert ss.other_listener() is None                                       # sono io
    st = ss.read()
    st["listen_pid"] = os.getppid()                                          # un altro processo vivo
    ss._write(st)
    assert ss.other_listener() == os.getppid()
    p = subprocess.run([sys.executable, str(WATCH), "--max-minutes", "0.01"], capture_output=True, text=True,
                       env={**os.environ, "WELLNESS_DATA": str(data)}, cwd=str(data), timeout=30)
    assert p.returncode == 3 and "altro ascoltatore" in p.stdout
    st["listen_pid"] = 2 ** 22 + 12345                                       # pid morto: si riarma
    ss._write(st)
    assert ss.other_listener() is None


def test_bot_sveglia_la_sessione_che_non_ascolta(data, fake_call, monkeypatch):
    import subprocess as sp
    from datetime import datetime, timedelta, timezone
    import telegram_bot as tb
    monkeypatch.setenv("HRIDAYA_SERVICE", "1")
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    ss.beat(["coda"], now=old, listener=True)
    ss.beat(["mcp"])                                                          # viva adesso, ascolto di 5' fa
    bot = tb.Bot("123:T", call=fake_call)
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return sp.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(tb, "NUDGE_ENTER_DELAY_S", 0)
    screen = {"text": "❯ \n  ⏵⏵ auto mode on"}

    def run(cmd, **kw):
        calls.append(cmd)
        out = screen["text"] if "capture-pane" in cmd else ""
        return sp.CompletedProcess(cmd, 0, out, "")
    assert "riarmarlo" in bot.listener_tick(run)
    sent = [c for c in calls if "send-keys" in c]
    assert sent[0][-1] == tb.NUDGE_TEXT and not any(ch.isdigit() for ch in tb.NUDGE_TEXT)
    assert sent[1][-1] == "Enter" and len(sent) == 2                          # testo, poi invio a parte
    assert bot.listener_tick(run) is None and len(calls) == 3                 # non a ogni giro
    for blocked in ("Do you want to proceed?\n❯ 1. Yes\n  2. Yes, and don't ask again", "✻ Pondering… (12s · ↓ 2k)"):
        screen["text"], bot._nudged_at = blocked, 0
        n = len(calls)
        assert "non digito" in bot.listener_tick(run)                         # dialog o turno in corso: niente tasti
        assert not any("send-keys" in c for c in calls[n:])
    screen["text"] = "❯ "
    assert bot.session_active()                                               # 5': ancora dentro la tolleranza
    ss.beat(["coda"], now=datetime.now(timezone.utc) - timedelta(minutes=20), listener=True)
    ss.beat(["mcp"])
    assert bot.session_active()                                               # 20': un turno lungo, ancora lei
    ss.beat(["coda"], now=datetime.now(timezone.utc) - timedelta(minutes=30), listener=True)
    ss.beat(["mcp"])
    assert not bot.session_active()                                           # 30': non risponde lei
    ss.beat(["coda"], listener=True)
    bot._nudged_at = 0
    assert bot.listener_tick(run) is None                                     # ascolta: niente da fare
    monkeypatch.delenv("HRIDAYA_SERVICE")
    ss.off(); ss.beat(["lavoro"], now=old); ss.beat(["lavoro"])               # sessione di lavoro: non si tocca
    assert bot.listener_tick(run) is None


def test_versione_dalla_cache_vera(tmp_path):
    import json as _j
    import plugin_version as pv
    for v in ("0.12.1", "0.13.0", "0.9.3"):
        d = tmp_path / "hridaya" / v / ".claude-plugin"
        d.mkdir(parents=True)
        (d / "plugin.json").write_text(_j.dumps({"version": v}))
    old = tmp_path / "hridaya" / "0.12.1"
    assert pv.running(old) == "0.12.1" and pv.latest(old) == "0.13.0"       # 0.13 > 0.9: ordine numerico
    co = tmp_path / "checkout"
    (co / ".claude-plugin").mkdir(parents=True)
    (co / ".claude-plugin" / "plugin.json").write_text(_j.dumps({"version": "1.0.0"}))
    assert pv.latest(co) == "1.0.0"                                           # checkout: il manifest sul posto


def test_server_vecchio_lo_dice(data, monkeypatch):
    import mcp_server as m
    assert m.outdated() is None
    monkeypatch.setattr(m, "STARTED_VERSION", "0.0.1")
    assert "0.0.1" in m.outdated()
    out = m.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "gate_status", "arguments": {}}})
    assert "server_outdated" in out["result"]["content"][0]["text"]


def test_dedicata_sorda_resta_dedicata(data, monkeypatch):
    """Viva ma senza ascolto: la sessione di lavoro non subentra (la sveglia il bot, la riavvia il custode)."""
    from datetime import datetime, timedelta, timezone
    monkeypatch.setenv("HRIDAYA_SERVICE", "1")
    ss.beat(["coda"], now=datetime.now(timezone.utc) - timedelta(hours=1), listener=True)
    ss.beat(["mcp"])
    monkeypatch.delenv("HRIDAYA_SERVICE")
    assert not ss.is_active() and ss.dedicated_elsewhere() and "dedicata" in ss.guard()


def test_battiti_concorrenti_non_si_perdono(data):
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    ps = [ctx.Process(target=_beater, args=(str(data), i % 2 == 0)) for i in range(4)]
    for p in ps:
        p.start()
    for p in ps:
        p.join(60)
    assert all(p.exitcode == 0 for p in ps)
    st = ss.read()
    assert st["on"] and st.get("listen_at") and st.get("pid")


def _beater(root, listener):
    os.environ["WELLNESS_DATA"] = root
    import session_state as s
    for _ in range(300):
        s.beat(["x"], listener=listener)
        assert isinstance(s.read(), dict)
