"""Bottoni di risposta: creazione, tocco singolo e multiplo, coda, cancello, tool MCP."""
import json

import pytest

import choices
import push_gate as pg
import telegram_bot as tb
import telegram_queue as tq
from test_mcp_server import _night, call, payload, run


_TAPS = iter(range(10**6))


def cq(data, chat=42, mid=7, cid=None):
    return {"update_id": 9, "callback_query": {
        "id": cid or f"t{next(_TAPS)}", "data": data, "from": {"username": "fra"},
        "message": {"message_id": mid, "chat": {"id": chat}, "text": "Quante ore ti servono?"}}}


def bot(fake_call, active=True):
    return tb.Bot("123:T", call=fake_call, session_active=lambda: active)


def test_opzioni_validate(data):
    assert choices.normalize(["a", "b", "c", "d", "e"]) == [["a", "b", "c", "d"], ["e"]]
    assert choices.normalize([["a"], ["b", "c"]]) == [["a"], ["b", "c"]]
    for bad in ([], ["a", "a"], ["x" * 41], [str(i) for i in range(13)], ["a", ["b"]], "ab",
                [[str(i) for i in range(9)]]):
        with pytest.raises(choices.ChoiceError):
            choices.normalize(bad)


def test_scelta_singola_va_in_coda_come_suo_messaggio(data, fake_call):
    cid, mk = choices.create(["7h", "7½h", "8h"], "Quante ore ti servono?")
    assert [b["callback_data"] for b in mk["inline_keyboard"][0]] == [f"ch:{cid}:0", f"ch:{cid}:1", f"ch:{cid}:2"]
    b = bot(fake_call)
    assert b.process_update(cq(f"ch:{cid}:1"), {42}) == "bottone"
    row = tq.list_pending(include_system=False)[0]
    assert row["text"] == "7½h" and row["choice"]["selected"] == ["7½h"]
    assert row["reply_to_text"] == "Quante ore ti servono?"
    methods = [m for m, _ in fake_call.calls]
    assert "answerCallbackQuery" in methods and "editMessageReplyMarkup" in methods
    edit = next(p for m, p in fake_call.calls if m == "editMessageReplyMarkup")
    assert edit["reply_markup"]["inline_keyboard"][0][0]["text"] == "✓ 7½h"
    # secondo tocco: già risposto, niente doppione in coda
    assert b.process_update(cq(f"ch:{cid}:2"), {42}) == "bottone-stale"
    assert len(tq.list_pending(include_system=False)) == 1


def test_scelta_multipla_accende_spegne_e_conferma(data, fake_call):
    cid, mk = choices.create(["Deadlift", "Pull-up", "HSW"], "Quali goal tieni?", multi=True)
    assert mk["inline_keyboard"][-1][0]["callback_data"] == f"ch:{cid}:ok"
    b = bot(fake_call)
    assert b.process_update(cq(f"ch:{cid}:0"), {42}) == "bottone-toggle"
    assert b.process_update(cq(f"ch:{cid}:2"), {42}) == "bottone-toggle"
    assert b.process_update(cq(f"ch:{cid}:2"), {42}) == "bottone-toggle"   # spento di nuovo
    assert b.process_update(cq(f"ch:{cid}:1"), {42}) == "bottone-toggle"
    last = [p for m, p in fake_call.calls if m == "editMessageReplyMarkup"][-1]
    assert [x["text"] for x in last["reply_markup"]["inline_keyboard"][0]] == ["✓ Deadlift", "✓ Pull-up", "HSW"]
    assert tq.list_pending(include_system=False) == []        # niente finché non conferma
    assert b.process_update(cq(f"ch:{cid}:ok"), {42}) == "bottone"
    row = tq.list_pending(include_system=False)[0]
    assert row["choice"]["selected"] == ["Deadlift", "Pull-up"] and row["text"] == "Deadlift, Pull-up"


def test_bottoni_estranei_scaduti_o_da_altre_chat(data, fake_call):
    b = bot(fake_call)
    assert b.process_update(cq("ch:noop"), {42}) == "bottone-noop"
    assert b.process_update(cq("ch:boh:0"), {42}) == "bottone-stale"
    cid, _ = choices.create(["a", "b"], "?")
    assert b.process_update(cq(f"ch:{cid}:9"), {42}) == "bottone-stale"
    assert b.process_update(cq(f"ch:{cid}:ok"), {42}) == "bottone-stale"   # conferma su una singola
    assert b.process_update(cq(f"ch:{cid}:0", chat=99), {42}) == "ignorato"
    assert tq.list_pending() == []


def test_sessione_spenta_la_scelta_resta_in_coda(data, fake_call):
    cid, _ = choices.create(["sì", "no"], "Va bene domani?")
    assert bot(fake_call, active=False).process_update(cq(f"ch:{cid}:0"), {42}) == "bottone-inattivo"
    assert tb.INACTIVE_REPLY in fake_call.texts()
    assert tq.list_pending(include_system=False)[0]["text"] == "sì"


class Sender:
    def __init__(self):
        self.sent = []

    def text(self, text, parse_mode=None, reply_markup=None):
        self.sent.append((text, reply_markup))

    def card(self, steps, base):
        self.sent.append(("card", None))


def test_cancello_non_fonde_i_bottoni(data):
    s = Sender()
    pg.submit("push della notte", source="t")
    mk = {"inline_keyboard": [[{"text": "a", "callback_data": "ch:x:0"}]]}
    r = pg.deliver("Scegli:", "review", s, reply_markup=mk)
    assert r["status"] == "sent"
    assert s.sent == [("push della notte", None), ("Scegli:", mk)]   # fusi prima, bottoni a sé sotto


def test_tool_reply_con_bottoni(data, tmp_path):
    mid = tq.enqueue(42, "quante ore?")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_reply", {"id": mid, "text": "Scegli:",
                                                "buttons": {"options": ["7h", "8h"]}}),
                     call(2, "telegram_send", {"text": "Goal?", "kind": "review",
                                               "buttons": {"options": ["A", "B"], "multi": True}}),
                     call(3, "telegram_reply", {"id": mid, "text": "x", "buttons": {"options": []}})], log)
    r1, r2 = payload(out[0]), payload(out[1])
    assert r1["status"] == "sent" and r1["choice_id"] and r2["choice_id"]
    assert out[2]["result"]["isError"]
    sent = [json.loads(x) for x in log.read_text().splitlines()]
    kb = [x["params"]["reply_markup"] for x in sent if x["params"].get("reply_markup")]
    assert kb[0]["inline_keyboard"][0][0]["callback_data"] == f"ch:{r1['choice_id']}:0"
    assert kb[1]["inline_keyboard"][-1][0]["callback_data"] == f"ch:{r2['choice_id']}:ok"
    st = json.loads((data / "data" / "telegram" / "choices.json").read_text())
    assert set(st) == {r1["choice_id"], r2["choice_id"]}               # la terza non è stata registrata


def test_di_notte_la_risposta_con_bottoni_aspetta_col_suo_markup(data, tmp_path):
    _night(data)
    mid = tq.enqueue(42, "domani?")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_reply", {"id": mid, "text": "Domattina:",
                                                "buttons": {"options": ["sì", "no"]}})], log)
    r = payload(out[0])
    assert r["status"] == "held" and r["choice_id"]
    held = tq.read_jsonl(data / "data" / "telegram" / "push.jsonl")
    assert held[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"ch:{r['choice_id']}:0"
    assert not log.exists()


def test_rete_giu_dopo_il_tocco_la_scelta_resta_in_coda(data):
    class Down:
        def __init__(self):
            self.calls = []

        def __call__(self, token, method, **params):
            self.calls.append(method)
            if method in ("answerCallbackQuery", "editMessageReplyMarkup"):
                raise OSError("rete giù")
            return {"ok": True, "result": {}}
    cid, _ = choices.create(["7h", "8h"], "Quante ore?")
    assert tb.Bot("123:T", call=Down(), session_active=lambda: True).process_update(
        cq(f"ch:{cid}:1"), {42}) == "bottone"
    assert tq.list_pending(include_system=False)[0]["text"] == "8h"


def test_conferma_vuota_e_tocco_ripetuto(data, fake_call):
    cid, _ = choices.create(["A", "B"], "Quali?", multi=True)
    b = bot(fake_call)
    assert b.process_update(cq(f"ch:{cid}:ok"), {42}) == "bottone-stale"      # niente acceso: resta aperta
    assert b.process_update(cq(f"ch:{cid}:0", cid="x1"), {42}) == "bottone-toggle"
    assert b.process_update(cq(f"ch:{cid}:0", cid="x1"), {42}) == "bottone-noop"   # update riletto
    assert b.process_update(cq(f"ch:{cid}:ok"), {42}) == "bottone"
    assert tq.list_pending(include_system=False)[0]["choice"]["selected"] == ["A"]


def test_scelta_sconosciuta_toglie_la_tastiera(data, fake_call):
    bot(fake_call).process_update(cq("ch:deadbeef00:0"), {42})
    edit = next(p for m, p in fake_call.calls if m == "editMessageReplyMarkup")
    assert edit["reply_markup"] == {"inline_keyboard": []}


def test_toast_entro_i_200(data):
    cid, _ = choices.create([f"{i:02d}" + "x" * 38 for i in range(12)], "?", multi=True)
    for i in range(12):
        choices.tap(f"ch:{cid}:{i}")
    assert len(choices.tap(f"ch:{cid}:ok")["toast"]) <= 200


def test_tool_rifiuta_bottoni_malformati_o_testo_lungo(data, tmp_path):
    mid = tq.enqueue(42, "?")
    out = run(data, [call(1, "telegram_reply", {"id": mid, "text": "x", "buttons": ["Sì", "No"]}),
                     call(2, "telegram_reply", {"id": mid, "text": "x", "buttons": {"options": ["a"], "multi": "no"}}),
                     call(3, "telegram_reply", {"id": mid, "text": "x", "buttons": {}}),
                     call(4, "telegram_reply", {"id": mid, "text": "x" * 4097, "buttons": {"options": ["a"]}})],
              tmp_path / "log.jsonl")
    assert all(r["result"]["isError"] for r in out)
    assert not (tmp_path / "log.jsonl").exists()
