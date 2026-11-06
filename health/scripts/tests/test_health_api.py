import unittest
from datetime import datetime, timedelta

from health_api import token_is_expired, SCOPES


class TokenExpiryTest(unittest.TestCase):
    def test_token_fresco_non_scaduto(self):
        token = {"saved_at": datetime.now().isoformat(), "expires_in": 3600}
        self.assertFalse(token_is_expired(token))

    def test_token_vecchio_scaduto(self):
        old = (datetime.now() - timedelta(hours=2)).isoformat()
        token = {"saved_at": old, "expires_in": 3600}
        self.assertTrue(token_is_expired(token))

    def test_token_senza_saved_at_scaduto(self):
        self.assertTrue(token_is_expired({"expires_in": 3600}))

    def test_margine_5_minuti(self):
        # scade tra 4 minuti → considerato scaduto (margine 300s)
        saved = (datetime.now() - timedelta(seconds=3360)).isoformat()
        token = {"saved_at": saved, "expires_in": 3600}
        self.assertTrue(token_is_expired(token))


class ScopesTest(unittest.TestCase):
    def test_scope_richiesti(self):
        base = "https://www.googleapis.com/auth/googlehealth"
        for suffix in (".sleep.readonly",
                       ".health_metrics_and_measurements.readonly",
                       ".activity_and_fitness.readonly"):
            self.assertIn(base + suffix, SCOPES)


if __name__ == "__main__":
    unittest.main()
