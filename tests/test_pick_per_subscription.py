"""The pick reads each subscription's own login, room and refusal.

A temporary HOME, a fake adapter whose `auth` answers by AGENTKIT_ACCOUNT, and fake meters:
no real login, provider or usage endpoint is reached.  Provider names are invented.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, usage  # noqa: E402

NOW = 1_800_000_000.0
DAY, WEEK = 86400, 604800

CONFIG = """
[models.one]
harness = "fake"
model = "m-one"
effort = "high"
provider = "acme"

[models.two]
harness = "fake"
model = "m-two"
effort = "high"
provider = "beta"

[providers.acme]
mode = "subscription"
accounts = ["default", "second"]

[providers.beta]
mode = "subscription"
"""

# `auth` says yes for the accounts named in logged-in beside it, `default` being the empty name
ADAPTER = """#!/bin/sh
[ "$1" = auth ] || exit 2
grep -qx "${AGENTKIT_ACCOUNT:-default}" "$(dirname "$0")/logged-in" 2>/dev/null \\
  && { echo "token for ${AGENTKIT_ACCOUNT:-default}"; exit 0; }
echo "no login"; exit 1
"""


class PickPerSubscription(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-pick-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        adapters = self.root / "adapters"
        adapters.mkdir()
        for path in (adapters / "fake.sh", adapters / "fake"):   # the adapter and its program
            path.write_text(ADAPTER)
            path.chmod(0o755)
        env = {k: v for k, v in os.environ.items() if k != config.ACCOUNT_ENV}
        env.update(HOME=str(self.root), PATH=f"{adapters}:{env.get('PATH', '')}",
                   **{config.ADAPTER_DIR_ENV: str(adapters)})
        self.stack.enter_context(patch.dict(os.environ, env, clear=True))
        config.ensure_dirs()
        (config.HOME / config.CONFIG_NAME).write_text(CONFIG)
        self.cfg = config.load()
        self.now = NOW
        self.stack.enter_context(patch.object(usage.time, "time", side_effect=lambda: self.now))
        self.meters = []

    def logged_in(self, *accounts):
        (self.root / "adapters/logged-in").write_text("".join(f"{a}\n" for a in accounts))

    def reading(self, meters, error=None):
        return {"provider": "acme", "harness": "fake", "resets": 0.0, "error": error,
                "meters": [usage._normalized(dict(meter), self.now) for meter in meters]}

    def fake_probe(self, cfg, provider, now, account=None):
        return {**self.reading(self.meters), "provider": provider, "exhausted": False,
                "probed_at": now}

    def test_a_provider_is_not_logged_in_only_when_none_of_its_accounts_is(self):
        # the usual login has expired and `second` still works: its models can run
        self.logged_in("second")
        for listed in ([], ["default"]):
            self.cfg["providers"]["beta"]["accounts"] = listed
            read = usage.readiness(self.cfg, usage.Readings({}))
            self.assertIsNone(usage.unready(self.cfg, "one", read))
            # ... and another provider's on the same harness, which is no login of beta's
            self.assertEqual(usage.unready(self.cfg, "two", read), "fake is not logged in")
        self.logged_in()
        read = usage.readiness(self.cfg, usage.Readings({}))
        self.assertEqual(usage.unready(self.cfg, "one", read), "fake is not logged in")

    def test_an_unknown_reading_never_ranks_ahead_of_the_usual_account_with_room(self):
        def rank(default, second):
            providers = {"acme": {**default, "accounts": {"default": default,
                                                          "second": second}}}
            return usage._gate_flags(providers, self.now, self.cfg)["acme"]["account"]

        def week(used):
            return self.reading([{"name": "weekly", "used": used,
                                  "resets_at": self.now + DAY, "window_secs": WEEK}])
        failed = self.reading([], error="unknown: fake.sh usage exited 1")
        self.assertEqual(rank(week(40), failed), "default")
        # ... and still ahead of a usual account with nothing left
        self.assertEqual(rank(week(100), failed), "second")
        # another account with known room goes first, as before
        self.assertEqual(rank(week(40), week(10)), "second")

    def assert_parked_through_session_rollovers(self, until, week_end, reads):
        """`beta`, refused at NOW until NOW + `until` beside a week ending at NOW + `week_end`,
        still parked at each NOW + `at` of `reads` with a fresh session of `length` (None: of
        no reported length) whose window has room: the week is the one the refusal was in."""
        self.stack.enter_context(patch.object(usage, "_probe", side_effect=self.fake_probe))
        week = {"name": "weekly", "used": 80, "resets_at": NOW + week_end, "window_secs": WEEK}
        self.meters = [{"name": "session", "used": 30, "resets_at": NOW + 3600,
                        "window_secs": usage.SESSION_SECS}, week]
        usage.mark_exhausted(self.cfg, "beta", NOW + until)
        for at, length in reads:
            self.now = NOW + at
            session = {"name": "session", "used": 0, "resets_at": self.now + usage.SESSION_SECS}
            self.meters = [{**session, "window_secs": length} if length else session, week]
            providers = usage.collect(self.cfg)
            self.assertEqual(providers["beta"].get("exhausted_until"), NOW + until, at)
            self.assertNotIn("two", usage.pick_order(self.cfg, providers, ["two"], quiet=True))

    def test_a_fresh_session_window_leaves_a_refusal_dated_later_in_force(self):
        # refused "until Tue", a refusal the weekly meter does not show at 100%: the session
        # rolls over early, and an hour before the deadline with a window running past it
        self.assert_parked_through_session_rollovers(5 * DAY, 6 * DAY, [
            (3700, usage.SESSION_SECS), (5 * DAY - 3600, usage.SESSION_SECS),
            (5 * DAY - 3000, None)])

    def test_a_fresh_session_window_leaves_a_refusal_shorter_than_it_in_force(self):
        # refused for the week's last four hours, the session ending after the first
        self.assert_parked_through_session_rollovers(4 * 3600, 4 * 3600, [
            (3700, usage.SESSION_SECS), (4300, None)])

if __name__ == "__main__":
    unittest.main()
