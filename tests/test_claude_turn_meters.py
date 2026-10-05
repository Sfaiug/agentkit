"""A Claude worker turn's own stream becomes its account's reading, with no request.

Every `claude -p` turn prints its account's limits as `rate_limit_event`s. The
last one is the reading of the account the turn ran on: `five_hour` is the
session meter and `seven_day` the weekly_all one. The menu, `ak usage` and the
next pick see it at once. Temporary HOME, a fake worker `events.jsonl`, and two
invented accounts (`default`, `acme-second`); no real login or endpoint.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, usage  # noqa: E402
from agentkit.harness import claude as claude_hook  # noqa: E402
from agentkit.harness import load as harness_plugin  # noqa: E402

CONFIG = """[defaults]
orchestrator = "opus"
workers = ["opus"]

[models.opus]
harness = "claude"
model = "claude-opus-5-5"
effort = "high"
provider = "anthropic"

[providers.anthropic]
accounts = ["default", "acme-second"]
"""

WEEK = 604800
SESSION = 18000


class TurnMeters(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-claude-turn-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        home = self.root / ".agentkit"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, key, home / key.lower()))
        self.stack.enter_context(patch.object(config, "HOME", home))
        self.stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        env = {k: v for k, v in os.environ.items()
               if k not in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "AGENTKIT_JOB_DIR",
                            "AGENTKIT_RUN_DIR", "AGENTKIT_SESSION", "AGENTKIT_ACCOUNT",
                            "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR")}
        env.update(HOME=str(self.root), AK_RUN_DEPTH="0", AK_MAX_RUNS="0",
                   AGENTKIT_DISCORD_WEBHOOK="off")
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        config.ensure_dirs()
        (config.HOME / "config.toml").write_text(CONFIG)
        self.cfg = config.load()
        self.now = time.time()
        # A turn reading makes no request: any adapter call is a failure.
        self.stack.enter_context(patch.object(
            usage, "_probe", side_effect=AssertionError("turn reading must not probe")))
        self.work = self.root / "work"
        self.work.mkdir()

    # --- the fixture ------------------------------------------------------

    def meter(self, name, used, offset, window, at=None):
        return usage._normalized({"name": name, "used": used,
                                  "resets_at": self.now + offset,
                                  "window_secs": window}, self.now if at is None else at)

    def cache(self, default_weekly=50, second_weekly=55):
        """Endpoint readings for both accounts, fresh enough that `collect` asks nothing."""
        accounts = {
            "default": {"provider": "anthropic", "harness": "claude", "via": "opus",
                        "meters": [self.meter("session", 10, 3600, SESSION),
                                   self.meter("weekly_all", default_weekly, 3 * 86400, WEEK),
                                   self.meter("weekly_scoped", 40, 3 * 86400, WEEK)],
                        "error": None, "pace": None, "resets": 0.0,
                        "exhausted": False, "probed_at": self.now},
            "acme-second": {"provider": "anthropic", "harness": "claude", "via": "opus",
                            "meters": [self.meter("session", 15, 3600, SESSION),
                                       self.meter("weekly_all", second_weekly, 3 * 86400, WEEK),
                                       self.meter("weekly_scoped", 30, 3 * 86400, WEEK)],
                            "error": None, "pace": None, "resets": 0.0,
                            "exhausted": False, "probed_at": self.now},
        }
        (config.STATE / "usage.json").write_text(json.dumps(
            {"fetched_at": self.now, "reset_checked_at": self.now,
             "providers": {"anthropic": {"provider": "anthropic", "accounts": accounts}}}))

    def event(self, five, seven, five_reset=None, seven_reset=None):
        return {"type": "rate_limit_event",
                "rate_limit_info": {"status": "allowed", "unifiedWindows": {
                    "five_hour": {"utilization": five,
                                  "resetsAt": self.now + 3600 if five_reset is None
                                              else five_reset},
                    "seven_day": {"utilization": seven,
                                  "resetsAt": self.now + 3 * 86400 if seven_reset is None
                                              else seven_reset}}}}

    def out(self, *lines):
        """A fake worker out dir whose `events.jsonl` holds those JSON lines."""
        target = self.root / "out"
        if target.exists():
            target = self.root / f"out-{len(list(self.root.glob('out*')))}"
        target.mkdir(parents=True)
        (target / "events.jsonl").write_text(
            "".join(json.dumps(line) + "\n" for line in lines))
        return target

    def used(self, account, name="weekly_all"):
        prov = usage.collect(self.cfg)["anthropic"]["accounts"][account]
        return next(m for m in prov["meters"] if m["name"] == name)

    # --- the reading ------------------------------------------------------

    def test_the_last_event_becomes_only_that_accounts_reading(self):
        self.cache()
        first, last = self.event(0.5, 0.6), self.event(0.02, 0.13)
        target = self.out({"type": "result", "result": "ok"},
                          first, {"type": "assistant", "text": "working"}, last)
        meters = harness_plugin("claude").turn_meters(target)
        self.assertEqual({m["name"]: m["used"] for m in meters},
                         {"session": 2.0, "weekly_all": 13.0})
        self.assertEqual(meters[0]["resets_at"], last["rate_limit_info"]["unifiedWindows"]
                         ["five_hour"]["resetsAt"])
        self.assertEqual(meters[1]["resets_at"], last["rate_limit_info"]["unifiedWindows"]
                         ["seven_day"]["resetsAt"])
        self.assertTrue(usage.record_turn_meters(self.cfg, "anthropic", meters,
                                                 "acme-second", now=self.now + 10))
        # `collect` -- the menu, `ak usage`, the next pick -- sees it at once.
        second = self.used("acme-second")
        self.assertEqual(second["used"], 13.0)
        self.assertEqual(self.used("acme-second", "session")["used"], 2.0)
        # A meter the event does not carry keeps the endpoint's last reading.
        self.assertEqual(self.used("acme-second", "weekly_scoped")["used"], 30)
        # A turn on one account never changes the other account's reading.
        self.assertEqual(self.used("default")["used"], 50)
        self.assertEqual(self.used("default", "session")["used"], 10)
        self.assertEqual(self.used("default", "weekly_scoped")["used"], 40)

    def test_a_turn_without_the_event_changes_nothing(self):
        self.cache()
        before = (config.STATE / "usage.json").read_text()
        target = self.out({"type": "assistant", "text": "working"},
                          {"type": "result", "result": "## Summary\nDone."})
        self.assertEqual(claude_hook.turn_meters(target), [])
        self.assertEqual(harness_plugin("other").turn_meters(target), [])
        self.assertFalse(usage.record_turn_meters(self.cfg, "anthropic", [], "acme-second"))
        run.note_turn_meters(self.cfg, "opus", target, "acme-second")
        self.assertEqual((config.STATE / "usage.json").read_text(), before)

    def test_an_older_reading_never_replaces_a_newer_one(self):
        self.cache()
        newer = claude_hook.turn_meters(self.out(self.event(0.02, 0.2)))
        older = claude_hook.turn_meters(self.out(self.event(0.8, 0.8)))
        self.assertTrue(usage.record_turn_meters(self.cfg, "anthropic", newer,
                                                 "acme-second", now=self.now + 100))
        self.assertEqual(self.used("acme-second")["used"], 20.0)
        self.assertFalse(usage.record_turn_meters(self.cfg, "anthropic", older,
                                                  "acme-second", now=self.now + 50))
        self.assertEqual(self.used("acme-second")["used"], 20.0)
        self.assertFalse(usage.record_turn_meters(self.cfg, "anthropic", older,
                                                  "acme-second", now=self.now - 10))
        self.assertEqual(self.used("acme-second")["used"], 20.0)

    def test_a_turn_clears_only_its_accounts_rate_limit(self):
        self.cache()
        blob = json.loads((config.STATE / "usage.json").read_text())
        for name in ("default", "acme-second"):
            acc = blob["providers"]["anthropic"]["accounts"][name]
            acc.update({"probe_error": "unknown: HTTP 429 from api.anthropic.com",
                        "probe_failed_at": self.now + 5, "stale_since": self.now + 5,
                        "fetched_at": self.now})
        (config.STATE / "usage.json").write_text(json.dumps(blob))
        meters = claude_hook.turn_meters(self.out(self.event(0.02, 0.13)))
        self.assertTrue(usage.record_turn_meters(self.cfg, "anthropic", meters,
                                                 "acme-second", now=self.now + 10))
        accounts = usage.collect(self.cfg)["anthropic"]["accounts"]
        self.assertNotIn("probe_error", accounts["acme-second"])
        self.assertEqual(next(m["used"] for m in accounts["acme-second"]["meters"]
                               if m["name"] == "weekly_all"), 13.0)
        self.assertIn("probe_error", accounts["default"])

    def test_a_turn_leaves_the_endpoints_cadence_alone(self):
        self.cache()
        meters = claude_hook.turn_meters(self.out(self.event(0.02, 0.13)))
        # Real time, as a turn records it: a fake future stamp would read as no
        # ask at all, however the cadence file was written.
        self.assertTrue(usage.record_turn_meters(self.cfg, "anthropic", meters,
                                                 "acme-second"))
        # No ask went out, so none is written down: the account is not cooling.
        self.assertFalse(usage._cooling("anthropic", "acme-second", 900))
        # A stale snapshot still asks the endpoint, and the meter the turn does
        # not carry takes the endpoint's answer.
        blob = json.loads((config.STATE / "usage.json").read_text())
        blob["fetched_at"] = self.now - 600
        blob["reset_checked_at"] = self.now - 600
        (config.STATE / "usage.json").write_text(json.dumps(blob))
        asked = []

        def endpoint(cfg, provider, now, account=None):
            asked.append(account)
            scoped = 100 if account == "acme-second" else 40
            week = 60 if account == "acme-second" else 50
            return {"provider": provider, "harness": "claude", "via": "opus",
                    "meters": [self.meter("session", 20, 3600, SESSION, at=now),
                               self.meter("weekly_all", week, 3 * 86400, WEEK, at=now),
                               self.meter("weekly_scoped", scoped, 3 * 86400, WEEK,
                                          at=now)],
                    "error": None, "pace": None, "resets": 0.0,
                    "exhausted": False, "probed_at": now}

        with patch.object(usage, "_probe", side_effect=endpoint):
            providers = usage.collect(self.cfg)
        self.assertEqual(sorted(asked), ["acme-second", "default"])
        second = providers["anthropic"]["accounts"]["acme-second"]
        self.assertEqual(next(m["used"] for m in second["meters"]
                               if m["name"] == "weekly_scoped"), 100)
        # The probe moved the cadence, as a real ask does.
        self.assertTrue(usage._cooling("anthropic", "acme-second", 900))

    def test_a_refused_probe_in_flight_keeps_the_turns_newer_reading(self):
        self.cache(second_weekly=90)
        blob = json.loads((config.STATE / "usage.json").read_text())
        blob["providers"]["anthropic"]["accounts"]["acme-second"]["probed_at"] = (
            self.now - 3600)
        (config.STATE / "usage.json").write_text(json.dumps(blob))
        entered, release, errors = (threading.Event(), threading.Event(), [])

        def slow(cfg, provider, now, account=None):
            entered.set()
            if not release.wait(30):
                raise AssertionError("probe was never released")
            return {"provider": provider, "meters": [],
                    "error": "unknown: HTTP 429 from api.anthropic.com",
                    "probed_at": now}

        def probe():
            try:
                with patch.object(usage, "_probe", side_effect=slow):
                    usage._probe_gently(self.cfg, "anthropic", "acme-second")
            except Exception as exc:  # a thread cannot fail the test; its error does
                errors.append(exc)

        worker = threading.Thread(target=probe, daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(30), "probe never started")
            # The probe holds the account's lock from here to its write; the
            # turn waits on it, then records over the refusal it wrote back.
            timer = threading.Timer(1.0, release.set)
            timer.start()
            try:
                meters = claude_hook.turn_meters(self.out(self.event(0.02, 0.13)))
                self.assertTrue(usage.record_turn_meters(
                    self.cfg, "anthropic", meters, "acme-second", now=self.now + 10))
            finally:
                timer.join(30)
        finally:
            worker.join(60)
        self.assertFalse(worker.is_alive(), "probe thread never finished")
        self.assertEqual(errors, [])
        kept = usage._cached_provider("anthropic", "acme-second")
        self.assertEqual(next(m["used"] for m in kept["meters"]
                               if m["name"] == "weekly_all"), 13.0)
        self.assertNotIn("probe_error", kept)

    def test_a_finished_turn_records_through_the_loop(self):
        self.cache(default_weekly=10, second_weekly=30)
        self.assertEqual(usage.account(self.cfg, "anthropic")[0], "acme-second")
        lines = []

        def turn(cfg, model, body, workspace, out_dir, role, session, env=None, limit=None, **_kw):
            Path(out_dir).mkdir(parents=True, exist_ok=True)
            (Path(out_dir) / "events.jsonl").write_text(
                json.dumps(self.event(0.04, 0.13)) + "\n"
                + json.dumps({"type": "result", "result": "## Summary\nDone.",
                              "session_id": "s1"}) + "\n")
            (Path(out_dir) / "stderr.log").write_text("")
            return 0, "## Summary\nDone.", "s1", False

        out = self.root / "run" / "round-1" / "executor"
        out.parent.mkdir(parents=True, exist_ok=True)
        with patch.object(run.worker, "call", side_effect=turn):
            code, _, session, _ = run.call_retrying(
                self.cfg, "opus", "Do the task.", self.work, out, "executor", None,
                lines.append, limit=120)
        self.assertEqual((code, session), (0, "s1"))
        self.assertEqual(self.used("acme-second")["used"], 13.0)
        self.assertEqual(self.used("acme-second", "session")["used"], 4.0)
        self.assertEqual(self.used("default")["used"], 10)


if __name__ == "__main__":
    unittest.main()
