"""Credits left count as usage left; offline, with invented readings and a fake endpoint.

An adapter's `usage` may carry `"credits": <number left>`: Codex's from chatgpt.com's
`credits.balance` while `has_credits` and no `overage_limit_reached`.  A provider or account
whose windows are spent but which holds credits is not spent: workers, reviewers and seats
are still picked on it, after every one with a window left.  With none, or 0, a spent
window stays spent.  Its usage row and `ak usage` say how many are left.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, terminal, usage  # noqa: E402
import test_usual_account_first as seats  # noqa: E402

WEEK = 604800

# /usage as chatgpt.com answers it, the credits object from $CREDITS; the token stays unread.
FAKE_CURL = r'''#!/usr/bin/env python3
import json, os, sys
body = {"rate_limit": {"allowed": False, "limit_reached": True,
                       "primary_window": {"used_percent": 100, "reset_at": 4102444800,
                                          "limit_window_seconds": 604800}},
        "credits": json.loads(os.environ["CREDITS"])}
sys.stdout.write(json.dumps(body) + "\n200")
'''


class Adapter(unittest.TestCase):
    def usage(self, credits):
        with tempfile.TemporaryDirectory(prefix="ak-test-credits-") as tmp:
            root = Path(tmp)
            (root / ".codex").mkdir()
            (root / ".codex/auth.json").write_text(json.dumps(
                {"tokens": {"access_token": "tok", "account_id": "acct"}}))
            (root / "bin").mkdir()
            (root / "bin/curl").write_text(FAKE_CURL)
            (root / "bin/curl").chmod(0o755)
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("AK_", "AGENTKIT_")) and k != "CODEX_HOME"}
            env.update(HOME=tmp, PATH=f"{root / 'bin'}:{os.environ['PATH']}",
                       CREDITS=json.dumps(credits))
            proc = subprocess.run(["bash", str(REPO / "adapters/codex.sh"), "usage"], env=env,
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_codex_usage_carries_the_balance_while_credits_answer(self):
        said = self.usage({"has_credits": True, "unlimited": False,
                           "overage_limit_reached": False, "balance": "62469.6695175000"})
        self.assertEqual(said["meters"][0]["used"], 100)
        self.assertAlmostEqual(said["credits"], 62469.6695175)

    def test_codex_usage_leaves_credits_out_otherwise(self):
        for credits in ({"has_credits": False, "overage_limit_reached": False, "balance": "0"},
                        {"has_credits": True, "overage_limit_reached": True, "balance": "12"},
                        # no balance to read leaves the credits out, never the meters
                        {"has_credits": True, "unlimited": True, "overage_limit_reached": False,
                         "balance": None},
                        None):
            with self.subTest(credits=credits):
                said = self.usage(credits)
                self.assertNotIn("credits", said)
                self.assertIsNone(said["error"])
                self.assertEqual(len(said["meters"]), 1)


class Picks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-credits-")
        self.addCleanup(tmp.cleanup)
        self.state = patch.object(config, "STATE", Path(tmp.name))
        self.state.start()
        self.addCleanup(self.state.stop)
        config.STATE.mkdir(exist_ok=True)
        self.cfg = tomllib.loads((REPO / "config.default.toml").read_text())
        for model in ("grok", "gemini", "mimo"):
            self.cfg["providers"].pop(self.cfg["models"].pop(model)["provider"])
        self.cfg["defaults"] = {"orchestrator": "astra", "workers": ["opus", "astra", "spark"]}
        self.now = time.time()

    def meter(self, used, name="weekly"):
        return {"name": name, "used": used, "window_secs": WEEK,
                "resets_at": self.now + WEEK / 2, "elapsed": 50.0, "pace": used - 50.0}

    def read(self, openai, anthropic=40, meta=97):
        def provider(name, used, **extra):
            # `weekly_all` is the week every Claude model runs inside, Fable's own cap aside
            meter = self.meter(used, "weekly_all" if name == "anthropic" else "weekly")
            return {"provider": name, "meters": [meter], "resets": 0, "error": None, **extra}
        return usage._gate_flags({"anthropic": provider("anthropic", anthropic),
                                  "openai": openai if isinstance(openai, dict)
                                  else provider("openai", 100, credits=openai),
                                  "meta": provider("meta", meta)}, self.now, self.cfg)

    def order(self, providers, role="executor"):
        with patch.object(config, "active_session", return_value=None):
            return usage.pick_order(self.cfg, providers, ["opus", "astra", "spark"], role=role,
                                    quiet=True)

    def test_a_spent_week_with_credits_is_picked_after_every_window_left(self):
        providers = self.read(62469.67)
        self.assertFalse(providers["openai"]["exhausted"])
        self.assertTrue(providers["openai"]["on_credits"])
        self.assertEqual(usage.model_exhausted(self.cfg, "astra", providers), (False, None))
        # meta has 3% of its week left, and still goes first: the subscription is paid for
        for role in ("executor", "reviewer"):
            self.assertEqual(self.order(providers, role), ["opus", "spark", "astra"])
        # ... and once every window is spent, the credits are what is left
        providers = self.read(62469.67, anthropic=100, meta=100)
        self.assertEqual(self.order(providers), ["astra"])

    def test_no_credits_or_none_left_keeps_a_spent_week_spent(self):
        for credits in (None, 0, 0.0):
            with self.subTest(credits=credits):
                providers = self.read(credits)
                self.assertTrue(providers["openai"]["exhausted"])
                self.assertFalse(providers["openai"]["on_credits"])
                self.assertTrue(usage.model_exhausted(self.cfg, "astra", providers)[0])
                self.assertEqual(self.order(providers), ["opus", "spark"])
                self.assertIsNotNone(usage.spent_meter(self.cfg, "astra", providers))

    def test_an_account_on_credits_goes_after_every_account_with_a_window(self):
        self.cfg["providers"]["openai"]["accounts"] = ["default", "second"]

        def account(used, credits=None):
            return {"provider": "openai", "meters": [self.meter(used)], "resets": 0,
                    "error": None, **({"credits": credits} if credits else {})}
        # the usual login with room before another on credits, though it ranks after a spare
        prov = {"provider": "openai", "accounts": {"default": account(60),
                                                   "second": account(100, 500)}}
        flagged = self.read(prov)["openai"]
        self.assertEqual(flagged["account"], "default")
        self.assertFalse(flagged["exhausted"])
        # ... and with both weeks spent, the one with credits, and nothing is spent
        prov = {"provider": "openai", "accounts": {"default": account(100),
                                                   "second": account(100, 500)}}
        flagged = self.read(prov)["openai"]
        self.assertEqual(flagged["account"], "second")
        self.assertFalse(flagged["exhausted"])
        self.assertEqual(usage.credits_left(flagged), 500)
        # a seat's accounts are ranked the same way, its home on credits going after one with room
        readings = flagged["accounts"]
        readings["default"] = usage._gate_flags({"openai": account(30)}, self.now,
                                                self.cfg)["openai"]
        self.assertEqual(orch.account_order(self.cfg, "astra", readings, first="second"),
                         ["default", "second"])

    def test_a_seat_takes_a_model_on_credits_only_after_every_window(self):
        providers = self.read(62469.67)
        model, why = orch.choose(self.cfg, providers)
        self.assertNotEqual(model, "astra")
        # the default passed over says why, as a spent one does
        self.assertIn("skipped astra: weekly 100% used, 62,469 credits left", why)
        self.assertEqual(orch.spent_note(self.cfg, "astra", providers), "")
        providers = self.read(62469.67, anthropic=100, meta=100)
        model, why = orch.choose(self.cfg, providers)
        self.assertEqual(model, "astra")
        self.assertNotIn("WARN", why)
        self.assertIn("62,469 credits left", why)

    def test_a_refused_probe_keeps_the_credits_beside_the_meters_it_keeps(self):
        cached = {"meters": [self.meter(100)], "credits": 62469.67, "probed_at": self.now}
        kept = usage._kept(cached, {"meters": [], "error": "unknown: HTTP 429"}, self.now)
        self.assertEqual(kept["credits"], 62469.67)

    def test_the_probe_reads_credits_off_the_adapter(self):
        said = {"meters": [{"name": "weekly", "used": 100, "resets_at": self.now + 3600,
                            "window_secs": WEEK}], "credits": 62469.67, "error": None}
        answer = subprocess.CompletedProcess([], 0, stdout=json.dumps(said), stderr="")
        with patch.object(usage.subprocess, "run", return_value=answer), \
                patch.object(usage, "_resets", return_value=0.0):
            self.assertEqual(usage._probe(self.cfg, "openai", self.now)["credits"], 62469.67)

    def test_the_row_and_ak_usage_say_how_many_are_left(self):
        providers = self.read(62469.67)
        (config.STATE / "usage.json").write_text(json.dumps(
            {"fetched_at": self.now, "providers": providers}))
        rows = [terminal.plain(line) for line in menu.usage_lines(self.cfg, 100)]
        chat = next(row for row in rows if row.lstrip().startswith("ChatGPT"))
        self.assertIn("0% left · 62,469 credits left", chat)
        self.assertFalse(any("credits" in row for row in rows if row is not chat), rows)
        with patch.object(usage, "review_pair", return_value=None):
            shown = terminal.plain(usage.render(self.cfg, providers, self.order(providers)))
        self.assertIn("openai: 62,469 credits left", shown)
        self.assertNotIn("exhausted", shown)


class Seat(unittest.TestCase):
    """A live seat, on `seats`' fake tmux and meters: only the credits are this file's."""

    def setUp(self):
        self.seat = seats.UsualAccountFirst()
        self.addCleanup(self.seat.doCleanups)
        self.seat.setUp()

    def account_after_tick(self, first, second, credited, login=lambda *_a, **_k: (True, "")):
        self.seat.meters(first, second)
        path = config.STATE / "usage.json"
        cached = json.loads(path.read_text())
        claude = cached["providers"]["anthropic"]
        for account in credited:
            claude["accounts"][account]["credits"] = 500
        claude["credits"] = claude["accounts"]["default"].get("credits")
        path.write_text(json.dumps(cached))
        with patch.object(seats.watch.worker, "auth_ok", side_effect=login):
            self.seat.tick()
        return config.session_records()[seats.NAME]["account"]

    def test_a_seat_on_credits_moves_to_an_account_with_a_window_left(self):
        self.assertEqual(self.account_after_tick(100, 20, ["default"]), "second")
        # ... and does not come home onto credits while its account has a window
        self.assertEqual(self.account_after_tick(100, 20, ["default"]), "second")

    def test_a_seat_stays_on_credits_when_no_account_has_a_window(self):
        self.assertEqual(self.account_after_tick(100, 100, ["default"]), "default")
        self.assertEqual(self.seat.commands, [])

    def test_a_seat_stays_on_credits_when_the_window_cannot_take_it(self):
        def worker_only(*_a, account=None, **_k):
            return account != "second", "no seat login"
        self.assertEqual(self.account_after_tick(100, 20, ["default"], worker_only), "default")
        with patch.object(orch, "resumable", return_value=False):
            self.assertEqual(self.account_after_tick(100, 20, ["default"]), "default")
        self.assertEqual(self.seat.commands, [])
        self.assertIsNone(seats.watch.seat_read(seats.NAME).get("usage_wait"))

    def test_a_seat_waiting_for_usage_continues_on_credits(self):
        seats.watch.seat_write(seats.NAME, usage_wait={"reason": "anthropic out of usage",
                                                       "until": self.seat.now + 3600,
                                                       "since": self.seat.now})
        with patch.object(orch, "resumable", return_value=False):
            self.assertEqual(self.account_after_tick(100, 20, ["default"]), "default")
        self.assertIsNone(seats.watch.seat_read(seats.NAME).get("usage_wait"))


if __name__ == "__main__":
    unittest.main()
