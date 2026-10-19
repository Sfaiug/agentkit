"""Failed Grok billing asks keep the last reading; offline with the shared fake curl."""

import json
import shutil
import unittest

import test_grokbuild as grok
from agentkit import usage


class BillingFailure(grok.GrokSandbox):
    FAILED = (("000", "", 0), ("429", "", 0), ("503", "", 0),
              ("200", '{"config":', 18), ("200", '{"config":', 0),
              ("200", "", 0), ("200", "null", 0),
              ("200", '{"config":{"creditUsagePercent":42}}', 0))

    def setUp(self):
        super().setUp()
        self.fake = self.home / "fake"
        self.fake.mkdir()
        for name, script in (("curl", grok.UsageVerb.FAKE_CURL),
                             ("grok", grok.UsageVerb.FAKE_GROK)):
            (self.bin / name).write_text(script)
            (self.bin / name).chmod(0o755)
        shutil.copy(grok.FIX / "grok-auth-valid.json", self.grok_home / "auth.json")

    def test_failed_asks_keep_the_cached_meter(self):
        shutil.copy(grok.FIX / "grok-settings-none.json",
                    self.grok_home / "settings_cache.json")
        cached = {"provider": "xai", "meters": [
            {"name": "weekly", "used": 42, "resets_at": 1999999999,
             "window_secs": 604800}], "fetched_at": 1000, "error": None}
        for code, body, exit_code in self.FAILED:
            with self.subTest(code=code, body=body, exit_code=exit_code):
                grok.UsageVerb.answer(self, code, body, exit_code=exit_code)
                proc = self.adapter("usage")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                fresh = json.loads(proc.stdout)
                error = ("unknown: no billing reading from "
                         f"cli-chat-proxy.grok.com/v1/billing (HTTP {code})")
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
        for code, body, exit_code in self.FAILED:
            with self.subTest(code=code, body=body, exit_code=exit_code):
                grok.UsageVerb.answer(self, code, body, exit_code=exit_code)
                proc = self.adapter("usage")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout),
                                 {"provider": "xai", "meters": meters, "error": None})

    def test_meterless_billing_json_answers_none_regardless_of_curl_exit(self):
        shutil.copy(grok.FIX / "grok-settings-none.json",
                    self.grok_home / "settings_cache.json")
        body = (grok.FIX / "grok-billing-nometer.json").read_text()
        for exit_code in (0, 18):
            with self.subTest(exit_code=exit_code):
                grok.UsageVerb.answer(self, 200, body, exit_code=exit_code)
                proc = self.adapter("usage")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                fresh = json.loads(proc.stdout)
                self.assertEqual((fresh["provider"], fresh["meters"], fresh["error"]),
                                 ("xai", [], None))
                self.assertIn("no meter", fresh["none"])

    def test_curl_fail_still_renews_a_refused_key_and_reads_its_meters(self):
        (self.home / ".curlrc").write_text("fail\n")
        (self.fake / "renewed").write_text(json.dumps(grok.UsageVerb.RENEWED))
        renewed = "fixture.renewed.not.a.token"
        body = (grok.FIX / "grok-billing-credits.json").read_text()
        grok.UsageVerb.answer(self, 200, body, key=renewed)
        for code in (401, 403):
            with self.subTest(code=code):
                shutil.copy(grok.FIX / "grok-auth-valid.json", self.grok_home / "auth.json")
                for name in ("asked", "grok-asked"):
                    (self.fake / name).unlink(missing_ok=True)
                grok.UsageVerb.answer(self, code, '{"error":"expired"}')
                proc = self.adapter("usage")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                fresh = json.loads(proc.stdout)
                self.assertIsNone(fresh["error"])
                self.assertNotIn("none", fresh)
                self.assertEqual([(m["name"], m["used"]) for m in fresh["meters"]],
                                 [("weekly", 37), ("build", 52)])
                self.assertEqual((self.fake / "asked").read_text().splitlines(),
                                 ["fixture.not.a.token", renewed])
                self.assertEqual((self.fake / "grok-asked").read_text().splitlines(),
                                 ["models"])


if __name__ == "__main__":
    unittest.main()
