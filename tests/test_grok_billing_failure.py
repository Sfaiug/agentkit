"""Failed Grok billing asks keep the last reading; offline with the shared fake curl."""

import json
import shutil
import unittest

import test_grokbuild as grok
from agentkit import usage


class BillingFailure(grok.GrokSandbox):
    def setUp(self):
        super().setUp()
        self.fake_grok()
        self.fake = self.home / "fake"
        self.fake.mkdir()
        (self.bin / "curl").write_text(grok.UsageVerb.FAKE_CURL)
        (self.bin / "curl").chmod(0o755)
        shutil.copy(grok.FIX / "grok-auth-valid.json", self.grok_home / "auth.json")

    def test_failed_asks_keep_the_cached_meter(self):
        shutil.copy(grok.FIX / "grok-settings-none.json",
                    self.grok_home / "settings_cache.json")
        cached = {"provider": "xai", "meters": [
            {"name": "weekly", "used": 42, "resets_at": 1999999999,
             "window_secs": 604800}], "fetched_at": 1000, "error": None}
        for code in ("000", "429", "503"):
            with self.subTest(code=code):
                grok.UsageVerb.answer(self, code)
                proc = self.adapter("usage")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                fresh = json.loads(proc.stdout)
                error = f"unknown: HTTP {code} from cli-chat-proxy.grok.com/v1/billing"
                self.assertEqual(fresh, {"provider": "xai", "meters": [], "error": error})
                self.assertNotIn("none", fresh)
                kept = usage._kept(cached, fresh, 1060)
                self.assertEqual(kept["meters"], cached["meters"])
                self.assertEqual(kept["fetched_at"], cached["fetched_at"])
                self.assertEqual(kept["probe_error"], error)

    def test_settings_meters_answer_before_the_billing_error(self):
        cache = grok.FIX / "grok-settings-meters.json"
        shutil.copy(cache, self.grok_home / "settings_cache.json")
        meters = json.loads(json.loads(cache.read_text())["payload"])["settings"]["subscription_usage"]
        for code in ("000", "429", "503"):
            with self.subTest(code=code):
                grok.UsageVerb.answer(self, code)
                proc = self.adapter("usage")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout),
                                 {"provider": "xai", "meters": meters, "error": None})


if __name__ == "__main__":
    unittest.main()
