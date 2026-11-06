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
TEXTS = (lambda d, **k: f"MATTINO {d}", lambda d, **k: f"SERA {d}")


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


def test_scheda_in_coda_con_foto_fuori_viene_scartata(data, tmp_path):
    s = Sender()
    pg.save_state({"wake": {D: {"at": "06:30", "source": "minuto", "recorded_at": t(D, "06:50").isoformat()}},
                   "wake_sent": D, "evening_sent": D})
    out = tmp_path / "fuori.png"
    out.write_bytes(b"x")
    pg.submit("", source="x", card={"steps": [{"photos": [str(out)]}], "base": str(tmp_path)},
              created_at=t(D, "15:00"))
    tick(t(D, "15:05"), s)
    assert s.sent == []


def test_bot_acceso_nel_pomeriggio_mattino_saltato_per_sempre(data):
    """Regressione 6/11: bot (ri)avviato dopo il late_cutoff. Il primo giro segna il
    mattino saltato; i giri dopo NON devono mandare il fallback del mattino."""
    s = Sender()
    for hhmm in ("17:15", "17:16", "17:30", "18:00"):
        tick(t(D1, hhmm), s)
    assert s.sent == []
    st = pg.load_state()
    assert st["wake_skipped"] == D1 and st.get("wake_sent") != D1


# --- regressioni della revisione finale ----------------------------------------------

import tg_transport as tt  # noqa: E402


class Flaky(Sender):
    """Rifiuta (400) i testi con BAD e le schede; 500 se transient=True."""

    def __init__(self, transient=False, partial=False):
        super().__init__()
        self.transient, self.partial = transient, partial

    def text(self, text, parse_mode=None):
        if self.partial:
            self.sent.append(text)
            raise tt.PartialSendError(1, tt.TelegramError("sendMessage", 400, "boh"))
        if "BAD" in text:
            raise tt.TelegramError("sendMessage", 500 if self.transient else 400, "can't parse entities")
        self.sent.append(text)

    def card(self, steps, base):
        raise tt.TelegramError("sendPhoto", 400, "PHOTO_INVALID_DIMENSIONS")


def _day_state():
    pg.save_state({"wake": {D: {"at": "06:30", "source": "minuto", "recorded_at": t(D, "06:50").isoformat()}},
                   "wake_sent": D, "evening_sent": D})


def _rows():
    return {r["id"]: r for r in tq.read_jsonl(pg.push_path())}


def test_scheda_rifiutata_non_fa_ripetere_il_testo(data):
    _day_state()
    img = data / "data" / "coach-longevita" / "daily" / "img"
    img.mkdir(parents=True)
    (img / "a.png").write_bytes(b"x")
    pg.submit("domanda del detector", source="x", push_id="q", created_at=t(D, "15:00"))
    pg.submit("", source="coach", push_id="c", created_at=t(D, "15:00"),
              card={"steps": [{"photos": ["img/a.png"]}], "base": str(img.parent)})
    s = Flaky()
    for k in range(4):
        tick(t(D, f"15:0{2 + k}"), s)
    assert sum("domanda del detector" in x for x in s.sent) == 1
    rows = _rows()
    assert rows["q"]["status"] == "sent" and rows["c"]["status"] == "failed"
    alerts = [r for r in rows.values() if r.get("kind") == "alert"]
    assert len(alerts) == 1 and "non è partito" in alerts[0]["text"]   # un solo avviso, dal cancello


def test_html_rotto_isolato_il_resto_parte_una_volta(data):
    _day_state()
    pg.submit("buono", source="a", push_id="ok", created_at=t(D, "15:00"))
    pg.submit("BAD <b", source="b", push_id="ko", parse_mode="HTML", created_at=t(D, "15:00"))
    s = Flaky()
    tick(t(D, "15:02"), s)
    tick(t(D, "15:03"), s)
    assert s.sent.count("buono") == 1
    assert _rows()["ko"]["status"] == "failed"


def test_errore_transitorio_backoff_poi_scarto(data):
    _day_state()
    pg.submit("BAD rete", source="a", push_id="r", created_at=t(D, "15:00"))
    s = Flaky(transient=True)
    tick(t(D, "15:02"), s)
    row = _rows()["r"]
    assert row["status"] == "pending" and row["attempts"] == 1 and row["next_try_at"]
    tick(t(D, "15:03"), s)                                           # in backoff: nessun nuovo tentativo
    assert _rows()["r"]["attempts"] == 1
    for _ in range(pg.MAX_ATTEMPTS):                                 # scaduto il backoff ogni volta
        rows = tq.read_jsonl(pg.push_path())
        for r in rows:
            r.pop("next_try_at", None)
        tq.write_jsonl(pg.push_path(), rows)
        tick(t(D, "15:10"), s)
    assert _rows()["r"]["status"] == "failed"


def test_invio_parziale_conta_come_consegnato(data):
    _day_state()
    pg.submit("lungo", source="a", push_id="p", created_at=t(D, "15:00"))
    s = Flaky(partial=True)
    tick(t(D, "15:02"), s)
    tick(t(D, "15:03"), s)
    assert len(s.sent) == 1 and _rows()["p"]["status"] == "sent"


def test_il_mattino_non_assorbe_righe_gia_fallite(data):
    pg.submit("BAD rete", source="a", push_id="r", created_at=t(D, "23:00"))
    rows = tq.read_jsonl(pg.push_path())
    rows[0]["attempts"] = 1
    tq.write_jsonl(pg.push_path(), rows)
    pg.save_state({"wake": {D1: {"at": "06:51", "source": "minuto", "recorded_at": t(D1, "07:00").isoformat()}}})
    s = Sender()
    assert pg.deliver("buongiorno", "wake", s, now=t(D1, "07:05"))["status"] == "sent"
    assert s.sent == ["buongiorno"] and _rows()["r"]["status"] == "pending"


def test_sera_con_sessione_accesa_aspetta_il_kaula(data):
    _day_state()
    st = pg.load_state()
    st.pop("evening_sent")
    pg.save_state(st)
    s = Sender()
    tick(t(D, "22:10"), s, active=True)
    tick(t(D, "22:12"), s, active=True)
    assert s.sent == []
    r = pg.deliver("🕉️ Kaula: domattina…", "evening", s, now=t(D, "22:12"))
    assert r["status"] == "sent" and s.sent == ["🕉️ Kaula: domattina…"]
    tick(t(D, "22:14"), s, active=True)
    assert len(s.sent) == 1


def test_sera_sessione_accesa_muta_fallback_all_ultimo_minuto_senza_non_attivo(data):
    import morning_message as mm
    _day_state()
    st = pg.load_state()
    st.pop("evening_sent")
    pg.save_state(st)
    s = Sender()
    tick(t(D, "22:13"), s, active=True)
    assert s.sent == []
    tick(t(D, "22:14"), s, active=True)
    assert s.sent == [f"SERA {D}"]
    assert "non è attivo" not in mm.evening_text(D, active=True)
    assert "non è attivo" in mm.evening_text(D, active=False)


def test_mattino_in_partenza_altrove_e_doppione(data):
    pg.save_state({"wake": {D1: {"at": "06:51", "source": "minuto", "recorded_at": t(D1, "07:00").isoformat()}}})
    inner = []

    class Reentrant(Sender):
        def text(self, text, parse_mode=None):     # un secondo bot che prova mentre il primo invia
            inner.append(pg.deliver("doppio", "wake", Sender(), now=t(D1, "07:05")))
            super().text(text, parse_mode)
    s = Reentrant()
    assert pg.deliver("buongiorno", "wake", s, now=t(D1, "07:05"))["status"] == "sent"
    assert inner[0]["status"] == "duplicate" and s.sent == ["buongiorno"]
    assert "wake_sending" not in pg.load_state()


def test_mattino_dopo_la_scadenza_non_parte_da_nessuna_strada(data):
    pg.save_state({"wake": {D1: {"at": "13:50", "source": "fallback", "recorded_at": t(D1, "13:50").isoformat()}}})
    s = Sender()
    assert pg.deliver("buongiorno", "wake", s, now=t(D1, "17:16"))["status"] == "too_late"
    pg.save_state({"wake": {D1: {"at": "06:51", "source": "minuto", "recorded_at": t(D1, "07:00").isoformat()}},
                   "wake_skipped": D1})
    assert pg.deliver("buongiorno", "wake", s, now=t(D1, "09:00"))["status"] == "too_late"
    assert s.sent == []


def test_bot_riavviato_tardi_non_invita_la_sessione(data):
    s, notes = Sender(), []
    tick(t(D1, "17:15"), s, active=True, mins=None, notes=notes)
    assert notes == [] and s.sent == []


def test_testo_della_sessione_rifiutato_non_brucia_il_mattino(data):
    pg.save_state({"wake": {D1: {"at": "06:51", "source": "minuto", "recorded_at": t(D1, "07:00").isoformat()}}})
    pg.submit("push della notte", source="x", push_id="n", created_at=t(D, "23:30"))
    s = Flaky()
    r = pg.deliver("BAD <b>buongiorno", "wake", s, now=t(D1, "07:05"), parse_mode="HTML")
    assert r["status"] == "failed"
    st = pg.load_state()
    assert st.get("wake_sent") != D1 and "wake_sending" not in st       # la sessione può riprovare
    assert _rows()["n"]["status"] in ("sent", "pending")                   # mai perso, mai doppio
    r2 = pg.deliver("buongiorno", "wake", Sender(), now=t(D1, "07:06"))
    assert r2["status"] == "sent"
