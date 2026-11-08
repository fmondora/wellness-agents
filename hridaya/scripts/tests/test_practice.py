"""Bottoni «Inizia»/«Fine» sotto una pratica: stato, bot, evento practice_done, invii."""
import json
from datetime import datetime, timedelta, timezone

import practice as pr
import telegram_bot as tb
import telegram_queue as tq
from test_bot import make
from test_mcp_server import call, payload, run


def cq(data, uid="t1", mid=77):
    return {"callback_query": {"id": uid, "data": data, "from": {"username": "fra"},
                               "message": {"message_id": mid, "chat": {"id": 42}, "text": "meditazione"}}}


def test_inizia_poi_fine(data):
    pid, mk = pr.create("Il buio che guarda")
    assert mk["inline_keyboard"][0][0]["callback_data"] == f"pr:{pid}:start"
    t0 = datetime(2026, 11, 8, 17, 30, tzinfo=timezone.utc)
    assert pr.tap(f"pr:{pid}:end", "a", t0)["toast"] == "Prima tocca «Inizia»"
    r = pr.tap(f"pr:{pid}:start", "b", t0)
    assert r["action"] == "started" and r["markup"]["inline_keyboard"][0][0]["text"] == "⏹ Fine"
    assert pr.tap(f"pr:{pid}:start", "b", t0)["action"] == "noop"            # tocco ripetuto (update riletto)
    r = pr.tap(f"pr:{pid}:end", "c", t0 + timedelta(minutes=31))
    assert r["action"] == "ended" and r["markup"]["inline_keyboard"][0][0]["text"] == "✓ 18:30–19:01 · 31′"
    text, ev = pr.event(r["practice"])
    assert ev == {"id": pid, "title": "Il buio che guarda", "kind": "meditation", "date": "2026-11-08",
                  "start": "18:30", "end": "19:01", "minutes": 31}
    assert "meditation_detect.py 18:30 19:01 --date 2026-11-08" in text
    assert pr.tap(f"pr:{pid}:end", "d")["toast"] == "Già registrata"


def test_inizio_troppo_vecchio_si_rifa(data):
    pid, _ = pr.create("x")
    t0 = datetime(2026, 11, 8, 8, 0, tzinfo=timezone.utc)
    pr.tap(f"pr:{pid}:start", "a", t0)
    r = pr.tap(f"pr:{pid}:end", "b", t0 + timedelta(hours=5))
    assert r["action"] == "stale" and "Inizia" in r["markup"]["inline_keyboard"][0][0]["text"]


def test_il_bot_registra_e_avvisa_la_sessione(data, fake_call):
    pid, _ = pr.create("Il buio che guarda")
    b = make(fake_call, active=True)
    assert b.process_update(cq(f"pr:{pid}:start", "a"), {42}) == "pratica-started"
    assert b.process_update(cq(f"pr:{pid}:end", "b"), {42}) == "pratica-ended"
    assert not [r for r in tq.list_pending() if r.get("event") == "practice_done"]      # non subito
    assert b.practice_tick() == []
    later = datetime.now(timezone.utc) + timedelta(minutes=31)
    assert b.practice_tick(later) == [pid] and b.practice_tick(later) == []
    ev = [r for r in tq.list_pending() if r.get("event") == "practice_done"]
    assert len(ev) == 1 and ev[0]["data"]["id"] == pid
    edits = [p for m, p in fake_call.calls if m == "editMessageReplyMarkup"]
    assert edits[-1]["reply_markup"]["inline_keyboard"][0][0]["text"].startswith("✓ ")
    assert b.process_update(cq(f"pr:{pid}:end", "c"), {42}) == "pratica-stale"
    assert len([r for r in tq.list_pending() if r.get("event") == "practice_done"]) == 1
    assert b.process_update(cq(f"pr:{pid}:start", "x"), {99}) == "ignorato"


def test_messaggio_con_pratica(data, tmp_path):
    mid = tq.enqueue(42, "una pratica per adesso?")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_reply", {"id": mid, "text": "Siediti…", "practice": "Hamsa"}),
                     call(2, "telegram_send", {"text": "x", "practice": "y", "buttons": {"options": ["a", "b"]}})], log)
    assert payload(out[0])["status"] == "sent"
    sent = [json.loads(x) for x in log.read_text().splitlines()]
    kb = sent[0]["params"]["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["text"] == "▶️ Inizia" and kb[0][0]["callback_data"].startswith("pr:")
    assert out[1]["result"]["isError"]
