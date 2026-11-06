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
    daily = data / "data" / "coach-longevita" / "daily"
    daily.mkdir(parents=True)
    (daily / "demo.player.json").write_text((fix / "demo.player.json").read_text())
    (daily / "rotto.player.json").write_text('{"blocks": []}')
    out = run(data, [call(1, "telegram_send_player", {"player_json": "data/coach-longevita/daily/demo.player.json",
                                                      "dry_run": True}),
                     call(2, "telegram_send_player", {"player_json": str(daily / "rotto.player.json")}),
                     call(3, "telegram_send_player", {"player_json": str(fix / "demo.player.json"), "dry_run": True})],
              tmp_path / "log.jsonl")
    assert payload(out[0])["url_length"] > 20
    assert out[1]["result"]["isError"]
    assert out[2]["result"]["isError"] and "fuori" in out[2]["result"]["content"][0]["text"]


def test_file_fuori_dal_repo_dati_mai_spediti(data, tmp_path):
    secret = tmp_path / "fuori" / "id_rsa"
    secret.parent.mkdir()
    secret.write_text("PRIVATA")
    reports = data / "data" / "reports"
    reports.mkdir(parents=True)
    (reports / "link").symlink_to(secret)                    # symlink che esce dal repo dati
    (reports / "ok.pdf").write_text("pdf")
    (data / "data" / "altro.pdf").write_text("pdf")          # nel repo dati ma fuori dall'allowlist
    mid = tq.enqueue(42, "mandami il pdf")
    log = tmp_path / "log.jsonl"
    out = run(data, [
        call(1, "telegram_send_file", {"path": str(secret), "in_reply_to": mid}),
        call(2, "telegram_send_file", {"path": "data/reports/link", "in_reply_to": mid}),
        call(3, "telegram_send_file", {"path": "../fuori/id_rsa", "in_reply_to": mid}),
        call(4, "telegram_send_file", {"path": "data/altro.pdf", "in_reply_to": mid}),
        call(5, "telegram_send_card", {"steps": [{"photos": [str(secret)]}], "in_reply_to": mid}),
        call(6, "telegram_send_card", {"steps": [{"text": "x"}], "base_dir": str(secret.parent), "in_reply_to": mid}),
        call(7, "telegram_send_file", {"path": "data/reports/ok.pdf", "in_reply_to": mid}),
    ], log)
    assert all(r["result"]["isError"] for r in out[:6]), out
    assert payload(out[6])["status"] == "sent"
    sent = log.read_text()
    assert "id_rsa" not in sent and "PRIVATA" not in sent and "ok.pdf" in sent


def test_segreti_rifiutati_anche_via_symlink(data, tmp_path):
    (data / "data" / "fitbit").mkdir(parents=True)
    (data / "data" / "fitbit" / "token.json").write_text('{"access_token": "SEGRETO"}')
    (data / "scripts").mkdir()
    (data / "scripts" / "server.key").write_text("CHIAVE")
    daily = data / "data" / "coach-longevita" / "daily"
    (daily / "img").mkdir(parents=True)
    # file sensibili copiati o linkati dentro le cartelle ammesse: rifiutati per nome
    (daily / "token.json").write_text('{"x": "SEGRETO"}')
    (daily / "server.key").write_text("CHIAVE")
    (daily / "scheda.pdf").symlink_to(data / "scripts" / "server.key")
    (daily / "img" / "foto.png").symlink_to(data / ".env")
    (daily / "notte.log").write_text("log")
    (daily / "img" / "nota.txt").write_text("x")
    mid = tq.enqueue(42, "?")
    log = tmp_path / "log.jsonl"
    reqs = [call(i, "telegram_send_file", {"path": pth, "in_reply_to": mid}) for i, pth in enumerate([
        "data/fitbit/token.json", "scripts/server.key", ".env",
        "data/coach-longevita/daily/token.json", "data/coach-longevita/daily/server.key",
        "data/coach-longevita/daily/scheda.pdf", "data/coach-longevita/daily/notte.log"], 1)]
    reqs += [call(20, "telegram_send_card", {"steps": [{"photos": ["img/foto.png"]}],
                                             "base_dir": "data/coach-longevita/daily", "in_reply_to": mid}),
             call(21, "telegram_send_card", {"steps": [{"photos": ["img/nota.txt"]}],
                                             "base_dir": "data/coach-longevita/daily", "in_reply_to": mid}),
             call(22, "telegram_send_card", {"spec_path": "data/fitbit/token.json", "in_reply_to": mid})]
    out = run(data, reqs, log)
    assert all(r["result"]["isError"] for r in out), [r["id"] for r in out if not r["result"]["isError"]]
    assert not log.exists() or ("SEGRETO" not in log.read_text() and "CHIAVE" not in log.read_text())


def test_scheda_con_foto_nel_repo_dati(data, tmp_path):
    img = data / "data" / "coach-longevita" / "daily" / "img"
    img.mkdir(parents=True)
    (img / "a.png").write_bytes(b"x")
    mid = tq.enqueue(42, "scheda?")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_send_card", {"steps": [{"text": "<b>Scheda</b>"},
                                                              {"photos": ["img/a.png"], "caption": "Plank"}],
                                                    "base_dir": "data/coach-longevita/daily",
                                                    "in_reply_to": mid})], log)
    assert payload(out[0])["steps"] == 2
    assert "sendPhoto" in log.read_text()


def test_servizio_acceso_poi_spento_alla_chiusura(data, tmp_path):
    out = run(data, [call(1, "hridaya_service", {"action": "on"})], tmp_path / "log.jsonl")
    r = payload(out[0])
    assert r["on"] and r["active_for_bot"] and any("coda" in x for x in r["listening"])
    st = json.loads((data / "data" / "telegram" / "session.json").read_text())
    assert st["on"] is False                         # stdin chiuso = sessione finita


def test_fuori_dal_repo_dati_errore_chiaro(tmp_path):
    out = run(tmp_path, [call(1, "telegram_inbox")], tmp_path / "log.jsonl")
    assert out[0]["result"]["isError"] and "repo dati" in out[0]["result"]["content"][0]["text"]


# --- regressioni della revisione finale ----------------------------------------------

def _night(data):
    """Ritmo che rende «notte» qualunque ora del test (silenzio fino alle 23:59)."""
    (data / "config" / "hridaya.json").write_text(json.dumps(
        {"bedtime": "00:01", "wake": {"fallback": "23:59", "fallback_max": "23:59", "late_cutoff": "23:59"}}))


def test_agli_eventi_di_sistema_non_si_risponde(data, tmp_path):
    sid = tq.enqueue_system("red_flag", "Red flag da Telegram: …")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_reply", {"id": sid, "text": "ok"}),
                     call(2, "telegram_send", {"text": "ok", "in_reply_to": sid})], log)
    assert all(r["result"]["isError"] for r in out)
    assert "evento di sistema" in out[0]["result"]["content"][0]["text"]
    assert not log.exists()


def test_di_notte_la_risposta_passa_dal_cancello_e_segna_fatto(data, tmp_path):
    _night(data)
    mid = tq.enqueue(42, "ci sei?")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_reply", {"id": mid, "text": "Domattina ne parliamo."})], log)
    r = payload(out[0])
    assert r["status"] == "held" and r["done"]
    assert not log.exists()                                  # nessun invio di notte
    assert tq.list_pending() == []
    held = tq.read_jsonl(data / "data" / "telegram" / "push.jsonl")
    assert held[0]["text"] == "Domattina ne parliamo." and held[0]["kind"] == "reply"


def test_di_notte_urgent_solo_con_red_flag(data, tmp_path):
    _night(data)
    rf = tq.enqueue(42, "ho un dolore toracico")
    plain = tq.enqueue(42, "non dormo")
    log = tmp_path / "log.jsonl"
    out = run(data, [call(1, "telegram_reply", {"id": plain, "text": "x", "urgent": True}),
                     call(2, "telegram_reply", {"id": rf, "text": "Chiama il 112.", "urgent": True})], log)
    assert out[0]["result"]["isError"]
    assert payload(out[1])["status"] == "sent" and "Chiama il 112." in log.read_text()


def test_scheda_in_risposta_segna_fatto(data, tmp_path):
    img = data / "data" / "coach-longevita" / "daily" / "img"
    img.mkdir(parents=True)
    (img / "a.png").write_bytes(b"x")
    pg_state = data / "data" / "telegram"
    pg_state.mkdir(parents=True, exist_ok=True)
    mid = tq.enqueue(42, "mandami la scheda")
    out = run(data, [call(1, "telegram_send_card", {"steps": [{"photos": ["img/a.png"]}],
                                                    "base_dir": "data/coach-longevita/daily",
                                                    "in_reply_to": mid})], tmp_path / "log.jsonl")
    r = payload(out[0])
    assert r["done"] and tq.list_pending() == []


def test_json_non_oggetto_e_batch_non_uccidono_il_server(data, tmp_path):
    out = run(data, [[], 3, "x", [{"jsonrpc": "2.0", "id": 7, "method": "ping"},
                                  {"jsonrpc": "2.0", "method": "notifications/initialized"}],
                     {"jsonrpc": "2.0", "id": 8, "method": "ping"}], tmp_path / "log.jsonl")
    assert [o["error"]["code"] for o in out[:3]] == [-32600, -32600, -32600]
    assert out[3] == [{"jsonrpc": "2.0", "id": 7, "result": {}}]
    assert out[4]["id"] == 8                                  # il server è ancora vivo
