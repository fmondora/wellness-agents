"""Alzata: mai prima della fine del sonno. Bagno, cuscino e dormiveglia non sono alzate."""
import random
from datetime import datetime
from zoneinfo import ZoneInfo

import channel_config as cc
import wake_detect as wd

TZ = ZoneInfo("Europe/Rome")
CFG = cc.DEFAULTS["wake"]


def hm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def m_(s):
    return int(s[:2]) * 60 + int(s[3:])


def night(events=None, wake=None, wake_steps=None, until="08:00", sleep_hr=50.0, awake_hr=68.0):
    """Minuti 00:00→until. events: [(HH:MM, [passi...], hr)] risvegli; wake: alzata vera."""
    hr = {m: sleep_hr + (m % 3) * 0.5 for m in range(0, m_(until))}
    st = {}
    for start, steps, h in events or []:
        s0 = m_(start)
        for i, n in enumerate(steps):
            st[s0 + i] = n
        for i in range(len(steps) + 3):
            hr[s0 + i] = h
    if wake:
        w0 = m_(wake)
        pattern = wake_steps or {0: 30, 1: 28, 3: 7, 4: 12, 10: 13, 11: 8, 12: 24}
        for k, n in pattern.items():
            st[w0 + k] = n
        for m in range(w0, m_(until)):
            hr[m] = awake_hr
    return {"hr": {hm(k): v for k, v in hr.items() if k < m_(until)},
            "steps": {hm(k): v for k, v in st.items() if k < m_(until)}}


def at(hhmm):
    return datetime(2026, 11, 7, int(hhmm[:2]), int(hhmm[3:]), tzinfo=TZ)


# il mattino reale tipico: due piccoli movimenti all'alba, poi l'alzata alle 06:51
REAL = [("04:58", [10], 58), ("05:02", [11], 58), ("05:11", [8], 57)]


def test_alzata_rilevata_dopo_la_conferma():
    mins = night(REAL, wake="06:51", until="07:15")
    w = wd.detect_wake(mins, None, at("07:15"), CFG)
    assert w["at"] == "06:51" and w["source"] == "minuto"


def test_finche_la_conferma_non_e_coperta_niente():
    mins = night(REAL, wake="06:51", until="07:05")
    assert wd.detect_wake(mins, None, at("07:05"), CFG) is None


def test_bagno_e_meditazione_sul_cuscino_non_sono_alzate():
    events = [("05:20", [20, 20, 15], 72)]            # bagno dopo il pavimento
    mins = night(events, until="06:30")
    mins["hr"].update({hm(m): 56.0 for m in range(m_("05:26"), m_("06:05"))})   # cuscino: fermo, FC piatta
    assert wd.detect_wake(mins, None, at("06:30"), CFG) is None


def test_giro_in_cucina_e_ritorno_a_letto_non_e_alzata():
    mins = night([("05:20", [40, 30, 20, 25, 10], 75)], until="06:30")
    assert wd.detect_wake(mins, None, at("06:30"), CFG) is None


def test_mai_prima_del_pavimento():
    mins = night(wake="04:10", until="05:30", wake_steps={k: 20 for k in range(20)})
    w = wd.detect_wake(mins, None, at("05:30"), CFG)
    assert w is None or m_(w["at"]) >= m_(CFG["earliest"])


def test_con_la_sessione_del_wearable_mai_prima_della_fine():
    mins = night([("06:20", [25, 25, 25], 70)], wake="06:51", until="07:10")
    sess = {"start": "22:49", "end": "06:45", "minutes_asleep": 400}
    w = wd.detect_wake(mins, sess, at("07:10"), CFG)
    assert w["at"] == "06:51" and w["source"] == "sessione+minuto"


def test_sessione_che_finisce_nel_futuro_e_ignorata():
    mins = night(REAL, wake="06:51", until="07:15")
    sess = {"start": "22:49", "end": "07:40", "minutes_asleep": 400}
    w = wd.detect_wake(mins, sess, at("07:15"), CFG)
    assert w["source"] == "minuto"       # ricade sulla regola stretta


def test_orologio_tolto_niente_dati_niente_alzata():
    assert wd.detect_wake({"hr": {}, "steps": {}}, None, at("08:00"), CFG) is None
    assert wd.detect_wake(None, None, at("08:00"), CFG) is None


def test_dorme_ancora():
    mins = night(until="09:30")
    assert wd.still_asleep(mins, at("09:30"), CFG)
    assert not wd.still_asleep(night(until="09:00"), at("09:30"), CFG)       # dati vecchi: non si sa
    assert not wd.still_asleep(night(wake="09:10", until="09:30"), at("09:30"), CFG)


def test_proprieta_mai_prima_della_fine_del_sonno():
    """200 notti casuali con risvegli notturni: l'alzata, se c'è, è ≥ alla vera."""
    rnd = random.Random(7)
    for _ in range(200):
        wake = m_("05:00") + rnd.randrange(0, 150)
        events = []
        for _k in range(rnd.randrange(0, 4)):
            t = rnd.randrange(m_("01:00"), wake - 15)
            n = rnd.randrange(1, 5)
            events.append((hm(t), [rnd.randrange(5, 15) for _ in range(n)], rnd.randrange(60, 85)))
        until = wake + 40
        mins = night(events, wake=hm(wake), until=hm(until),
                     wake_steps={k: rnd.randrange(8, 40) for k in range(0, 30, rnd.choice([1, 2]))})
        for now_m in range(m_("05:00"), until + 1, 7):
            cut = {"hr": {k: v for k, v in mins["hr"].items() if m_(k) <= now_m},
                   "steps": {k: v for k, v in mins["steps"].items() if m_(k) <= now_m}}
            w = wd.detect_wake(cut, None, at(hm(now_m)), CFG)
            if w:
                assert m_(w["at"]) >= wake, (events, hm(wake), w)
                break
