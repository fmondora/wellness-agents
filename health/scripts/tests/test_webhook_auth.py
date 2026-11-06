"""Ricevitore webhook: il Bearer si confronta a tempo costante."""
import pytest

pytest.importorskip("fastapi")
import webhook_receiver as wr  # noqa: E402


def test_bearer_giusto():
    assert wr.auth_ok("Bearer s3cret", "s3cret")


@pytest.mark.parametrize("auth", [None, "", "Bearer", "Bearer s3cre", "bearer s3cret", "Bearer s3cret "])
def test_bearer_sbagliato_o_assente(auth):
    assert not wr.auth_ok(auth, "s3cret")


def test_senza_secret_non_entra_nessuno():
    assert not wr.auth_ok("Bearer ", "")
    assert not wr.auth_ok(None, "")


def test_usa_compare_digest(monkeypatch):
    calls = []
    real = wr.hmac.compare_digest
    monkeypatch.setattr(wr.hmac, "compare_digest", lambda a, b: calls.append((a, b)) or real(a, b))
    wr.auth_ok("Bearer x", "x")
    assert calls == [(b"Bearer x", b"Bearer x")]
