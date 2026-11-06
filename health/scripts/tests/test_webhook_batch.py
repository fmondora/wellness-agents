"""Ricevitore webhook: Google può mandare una notifica o un lotto (lista).

Prima del 6/11 un lotto faceva crashare l'handler (500): Google ritentava
all'infinito e le notifiche si perdevano. Ora: una riga d'inbox per notifica.
"""
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

import webhook_receiver as wr  # noqa: E402

AUTH = {"Authorization": "Bearer s3cret"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "INBOX", tmp_path / "insights" / "webhook-inbox.jsonl")
    monkeypatch.setattr(wr, "_secret", lambda: "s3cret")
    return TestClient(wr.app)


def _rows():
    if not wr.INBOX.exists():
        return []
    return [json.loads(line) for line in wr.INBOX.read_text().splitlines() if line.strip()]


def test_lotto_una_riga_per_notifica(client):
    batch = [{"dataType": "steps", "n": 1}, {"dataType": "sleep", "n": 2}, {"dataType": "hr", "n": 3}]
    r = client.post("/webhook", content=json.dumps(batch), headers={**AUTH, "google-health-api-signature": "sig"})
    assert r.status_code == 204
    rows = _rows()
    assert [row["payload"] for row in rows] == batch
    assert {row["signature"] for row in rows} == {"sig"}
    assert all(row["processed"] is False for row in rows)
    assert len({row["received_at"] for row in rows}) == 1


def test_notifica_singola_invariata(client):
    r = client.post("/webhook", content=json.dumps({"dataType": "steps"}), headers=AUTH)
    assert r.status_code == 204
    rows = _rows()
    assert len(rows) == 1 and rows[0]["payload"] == {"dataType": "steps"}


def test_lotto_vuoto_204_senza_righe(client):
    r = client.post("/webhook", content="[]", headers=AUTH)
    assert r.status_code == 204
    assert _rows() == []


def test_verification_solo_se_oggetto(client):
    assert client.post("/webhook", content=json.dumps({"type": "verification"}), headers=AUTH).status_code == 200
    assert _rows() == []
    # una lista che contiene un oggetto "verification" non è l'handshake: si accoda
    r = client.post("/webhook", content=json.dumps([{"type": "verification"}]), headers=AUTH)
    assert r.status_code == 204 and len(_rows()) == 1


def test_lotto_senza_bearer_rifiutato(client):
    r = client.post("/webhook", content="[{}]")
    assert r.status_code == 401
    assert _rows() == []
