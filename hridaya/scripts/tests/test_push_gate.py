"""Cancello: silenzio dall'ora di letto all'alzata, fusione, red flag subito, sera e mattino una volta."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import channel_config as cc
import push_gate as pg
import telegram_queue as tq
from test_wake_detect import REAL, night

TZ = ZoneInfo("Europe/Rome")
D, D1 = "2026-11-06", "2026-11-07"
TEXTS = (lambda d: f"MATTINO {d}", lambda d: f"SERA {d}")


class Sender:
    def __init__(self):
        self.sent = []

    def text(self, text, parse_mode=None):
        self.sent.append(text)

    def card(self, steps, base):
        self.sent.append(("card", len(steps)))


def t(day, hhmm):
    y, mo, d = map(int, day.split("-"))
    return datetime(y, mo, d, int(hhmm[:2]), int(hhmm[3:]), tzinfo=TZ)


def tick(now, sender, active=False, mins=None, session=None, notes=None):
    return pg.tick(now, sender, active, cfg=cc.rhythm(),
                   minutes_loader=lambda d, f: mins, session_loader=lambda d: session,
                   notify=(lambda *a, **k: notes.append(a)) if notes is not None else (lambda *a, **k: None),
                   texts=TEXTS)


def test_ora_di_letto_dalla_config(data):
    assert cc.rhythm()["bedtime"] == "22:15"


def test_notte_trattenuta_e_fusa_nel_mattino(data):
    s = Sender()
    pg.submit("🚶 Com'era la camminata?", source="insights", created_at=t(D, "23:00"))
    tick(t(D, "23:05"), s)
    assert s.sent == []
    # bagno alle 03:10 e pavimento: niente
    tick(t(D1, "03:15"), s, mins=night([("03:10", [15, 15, 10], 70)], until="03:15"))
    tick(t(D1, "05:30"), s, mins=night(REAL, until="05:30"))
    assert s.sent == []
    # alzata vera, sessione spenta → fallback del mattino con dentro il push della notte
    acts = tick(t(D1, "07:12"), s, mins=night(REAL, wake="06:51", until="07:12"))
    assert any("alzata 06:51" in a for a in acts)
    assert len(s.sent) == 1 and "MATTINO" in s.sent[0] and "camminata" in s.sent[0]
    tick(t(D1, "07:20"), s, mins=night(REAL, wake="06:51", until="07:20"))
    assert len(s.sent) == 1
    assert pg.load_state()["wake_sent"] == D1


def test_sessione_accesa_scrive_lei_il_mattino(data):
    s, notes = Sender(), []
    pg.submit("push della notte", source="x", created_at=t(D, "23:30"))
    mins = night(REAL, wake="06:51", until="07:12")
    tick(t(D1, "07:12"), s, active=True, mins=mins, notes=notes)
    assert s.sent == [] and notes and notes[0][0] == "wake"
    r = pg.deliver("🫀 Buongiorno, la notte…", "wake", s, now=t(D1, "07:15"), cfg=cc.rhythm())
    assert r["status"] == "sent" and r["merged"] == 1
    assert "push della notte" in s.sent[0]
    tick(t(D1, "07:40"), s, active=True, mins=mins)
    assert len(s.sent) == 1
    assert pg.deliver("di nuovo", "wake", s, now=t(D1, "08:00"))["status"] == "duplicate"


def test_sessione_accesa_ma_muta_dopo_la_grazia_parte_il_fallback(data):
    s = Sender()
    mins = night(REAL, wake="06:51", until="07:30")
    tick(t(D1, "07:12"), s, active=True, mins=mins)
    tick(t(D1, "07:20"), s, active=True, mins=mins)
    assert s.sent == []
    tick(t(D1, "07:28"), s, active=True, mins=mins)
    assert s.sent == [f"MATTINO {D1}"]


def test_red_flag_subito_anche_di_notte(data):
    s = Sender()
    pg.submit("🚨 red flag", source="x", priority="red_flag", created_at=t(D1, "02:00"))
    tick(t(D1, "02:00"), s)
    assert s.sent == ["🚨 red flag"]


def test_iniziativa_di_notte_trattenuta(data):
    s = Sender()
    r = pg.deliver("review", "review", s, now=t(D1, "02:00"))
    assert r["status"] == "held" and s.sent == []
    assert pg.deliver("buongiorno", "wake", s, now=t(D1, "04:00"))["status"] == "silent"


def test_sera_fallback_una_volta_e_mai_dopo_l_ora_di_letto(data):
    s = Sender()
    pg.save_state({"wake": {D: {"at": "06:30", "source": "minuto", "recorded_at": t(D, "06:50").isoformat()}},
                   "wake_sent": D})
    tick(t(D, "22:05"), s)
    assert s.sent == []
    tick(t(D, "22:10"), s)
    assert s.sent == [f"SERA {D}"]
    tick(t(D, "22:11"), s)
    assert len(s.sent) == 1


def test_sera_della_sessione_dopo_l_ora_di_letto_non_parte(data):
    s = Sender()
    pg.save_state({"wake": {D: {"at": "06:30", "source": "minuto", "recorded_at": t(D, "06:50").isoformat()}}})
    assert pg.deliver("meditazione", "evening", s, now=t(D, "22:20"))["status"] == "too_late"
    assert s.sent == []


def test_fusione_dopo_la_finestra(data):
    s = Sender()
    pg.save_state({"wake": {D: {"at": "06:30", "source": "minuto", "recorded_at": t(D, "06:50").isoformat()}},
                   "wake_sent": D, "evening_sent": D})
    pg.submit("uno", source="a", created_at=t(D, "15:00"))
    pg.submit("due", source="b", created_at=t(D, "15:00"))
    tick(t(D, "15:00") + timedelta(seconds=20), s)
    assert s.sent == []
    tick(t(D, "15:01") + timedelta(seconds=5), s)
    assert s.sent == ["uno\n\ndue"]


def test_fallback_rinviato_se_dorme_ancora(data):
    s = Sender()
    sleeping = night(until="09:31")
    acts = tick(t(D1, "09:31"), s, mins=sleeping)
    assert "fallback rinviato: dorme ancora" in acts and s.sent == []
    assert pg.is_silent(t(D1, "09:40"), cc.rhythm(), pg.load_state())
    tick(t(D1, "11:31"), s, mins=night(until="11:31"))
    assert s.sent == [f"MATTINO {D1}"]


def test_fallback_senza_dati_all_ora_configurata(data):
    s = Sender()
    tick(t(D1, "09:29"), s, mins=None)
    assert s.sent == []
    tick(t(D1, "09:30"), s, mins=None)
    assert s.sent == [f"MATTINO {D1}"]


def test_mai_un_invio_prima_della_fine_del_sonno(data):
    """Giro completo minuto per minuto: il primo invio arriva dopo l'alzata vera."""
    s = Sender()
    pg.submit("notte", source="x", created_at=t(D, "23:30"))
    wake = "06:51"
    for minute in range(0, 8 * 60, 3):
        now = t(D1, f"{minute // 60:02d}:{minute % 60:02d}")
        mins = night([("03:10", [15, 15, 10], 70)] + REAL, wake=wake, until=now.strftime("%H:%M"))
        tick(now, s, mins=mins)
        if s.sent:
            assert now.strftime("%H:%M") >= wake
            break
    assert s.sent, "dopo l'alzata il mattino deve partire"


def test_cli_submit_scrive_lo_schema(data):
    pg.submit("ciao", source="cli", kind="review", card={"steps": [{"text": "x"}], "base": "/tmp"})
    row = tq.read_jsonl(pg.push_path())[0]
    assert row["status"] == "pending" and row["kind"] == "review" and row["card"]["steps"]
    json.dumps(row)
