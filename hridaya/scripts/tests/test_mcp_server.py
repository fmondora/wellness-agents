"""Server MCP: handshake stdio JSON-RPC e tool con trasporto finto (nessuna rete)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import telegram_queue as tq

SERVER = Path(__file__).resolve().parent.parent / "mcp_server.py"


def run(data, msgs, log):
    env = {**os.environ, "WELLNESS_DATA": str(data), "HRIDAYA_TRANSPORT_LOG": str(log)}
    env.pop("TELEGRAM_BOT_TOKEN", None)
    p = subprocess.run([sys.executable, str(SERVER)], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                       capture_output=True, text=True, env=env, cwd=str(data), timeout=30)
    assert p.returncode == 0, p.stderr
    return [json.loads(x) for x in p.stdout.splitlines()]


def call(i, name, args=None):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}


def payload(resp):
    return json.loads(resp["result"]["content"][0]["text"])


def test_handshake_e_lista_tool(data, tmp_path):
    out = run(data, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
        {"jsonrpc": "2.0", "id": 4, "method": "boh"},
    ], tmp_path / "log.jsonl")
    assert [r["id"] for r in out] == [1, 2, 3, 4]          # la notifica non ha risposta
    assert out[0]["result"]["protocolVersion"] == "2025-06-18"
    assert out[0]["result"]["capabilities"]["tools"] is not None
    names = {t["name"] for t in out[1]["result"]["tools"]}
    assert {"telegram_send", "telegram_send_card", "telegram_send_file", "telegram_send_player",
            "telegram_inbox", "telegram_reply"} <= names
    assert out[3]["error"]["code"] == -32601


def test_inbox_e_reply_col_trasporto_finto(data, tmp_path):
    mid = tq.enqueue(42, "come ho dormito?")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_inbox"), call(2, "telegram_reply", {"id": mid, "text": "Bene, 7h."})], log)
    assert payload(out[0])["count"] == 1
    assert payload(out[1])["status"] == "sent"
    sent = [json.loads(x) for x in log.read_text().splitlines()]
    assert sent[0]["method"] == "sendMessage" and sent[0]["params"]["text"] == "Bene, 7h."
    assert sent[0]["params"]["chat_id"] == 42
    assert tq.list_pending() == []
    assert tq.read_jsonl(tq.outbox_path())[-1]["sent"] is True    # storico, il bot non lo rispedisce


def test_send_passa_dal_cancello(data, tmp_path):
    out = run(data, [call(1, "telegram_send", {"text": "review della settimana", "kind": "review"})],
              tmp_path / "log.jsonl")
    assert payload(out[0])["status"] in ("sent", "held")


def test_player_dry_run_e_validazione(data, tmp_path):
    fix = Path(__file__).resolve().parent / "fixtures"
    out = run(data, [call(1, "telegram_send_player", {"player_json": str(fix / "demo.player.json"), "dry_run": True}),
                     call(2, "telegram_send_player", {"player_json": str(fix / "2026-11-06.webappdata.txt")})],
              tmp_path / "log.jsonl")
    assert payload(out[0])["url_length"] > 20
    assert out[1]["result"]["isError"]


def test_servizio_acceso_poi_spento_alla_chiusura(data, tmp_path):
    out = run(data, [call(1, "hridaya_service", {"action": "on"})], tmp_path / "log.jsonl")
    r = payload(out[0])
    assert r["on"] and r["active_for_bot"] and any("coda" in x for x in r["listening"])
    st = json.loads((data / "data" / "telegram" / "session.json").read_text())
    assert st["on"] is False                         # stdin chiuso = sessione finita


def test_fuori_dal_repo_dati_errore_chiaro(tmp_path):
    out = run(tmp_path, [call(1, "telegram_inbox")], tmp_path / "log.jsonl")
    assert out[0]["result"]["isError"] and "repo dati" in out[0]["result"]["content"][0]["text"]
