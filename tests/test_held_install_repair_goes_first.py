"""The seat told of a red that holds the install gets one first place for its next agentkit review.

Offline: a temporary HOME; Git, the receiving seat, the slot claim, the lander and the seat's bar are fakes.
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
from fixtures.sandbox import account_home
from agentkit import config, deliver, gate, land, run, update, watch  # noqa: E402
from agentkit import record as run_record

HELD = "abcdef0123456789" * 2 + "abcdef01"
AGENTKIT_PR = "https://github.com/acme/agentkit/pull/7"


class HeldInstallRepairGoesFirst(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-held-first-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(account_home(self.root))
        for name in ("HOME", "RUNS", "STATE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root), "AGENTKIT_RUN": "",
                                                     "AK_PARENT_RUN": "", "AK_RUN_DEPTH": "0",
                                                     "AGENTKIT_SESSION": ""}))
        config.RUNS.mkdir(parents=True)
        self.moved = False
        stack.enter_context(patch.object(update, "_git", side_effect=self.git))
        stack.enter_context(patch.object(watch, "after_merge_deliver", return_value="fix-api"))
        for name in ("redress_seat", "history_start"):
            stack.enter_context(patch.object(run, name))
        stack.enter_context(patch.object(gate, "claim_slot"))
        stack.enter_context(patch.object(land, "start_line"))     # no lander for a parked fake
        self.check = config.STATE / update.LIVE / f"{HELD}-1000"
        self.check.mkdir(parents=True)
        (self.check / "output").write_text("FAIL  4 acme meter: missing reading\n[exit 1]\n")
        self.logs = []

    def git(self, *args, **_kw):
        if args[:2] == ("remote", "get-url"):
            return 0, "git@github.com:acme/agentkit.git"
        if args[:2] == ("merge-base", "--is-ancestor"):
            return (0 if self.moved else 1), ""
        return 0, ""

    def hand_back(self):
        update.live_hand_back(HELD, self.check, 1, self.logs.append)
        return watch.after_merge_deliver.call_args.args[3]

    def review(self, name, seat="fix-api", url=AGENTKIT_PR):
        directory = config.RUNS / name
        directory.mkdir()
        with patch.dict(os.environ, {"AGENTKIT_SESSION": seat}):
            run.capture_launch(directory, {"--review-pr": url})
        return directory, run_record.read_state(directory)

    def test_the_told_seats_next_agentkit_review_is_admitted_and_lands_first(self):
        earlier, _ = self.review("20261022-1200-earlier", seat="other")
        line = self.hand_back()
        self.assertTrue(line.endswith("Fix main: your next agentkit PR review goes first in line, "
                                      "so make it the fix."))
        fix, state = self.review("20261022-1300-fix")
        self.assertTrue(state["first"])
        self.assertLess(gate.slot_order(state),
                        gate.slot_order(run_record.read_state(earlier)))

        delivery, _ = self.review("20261022-1400-delivery", seat="other")
        lock = deliver.merge_lock_path("https://github.com/acme/agentkit.git", "origin/main")
        for directory, wait in ((earlier, {"joined": 10}), (fix, {"joined": 20}),
                                (delivery, {"joined": 30, "land": "tree"})):
            state = run_record.read_state(directory)
            state.update(state="waiting", waiting_on={"line": lock.name, **wait})
            run_record.save_state(directory, state)
        self.assertEqual([directory for directory, _ in land.line(lock)], [delivery, fix, earlier])

    def test_only_that_seats_one_agentkit_review_before_the_install_moves_is_first(self):
        self.hand_back()
        for name, seat, url in (("other-seat", "other", AGENTKIT_PR),
                                ("other-repo", "fix-api", "https://github.com/acme/widget/pull/3")):
            self.assertNotIn("first", self.review(name, seat, url)[1])
        self.assertTrue(self.review("fix")[1]["first"])
        self.assertNotIn("first", self.review("second")[1])

        self.check = config.STATE / update.LIVE / f"{'0' * 40}-2000"
        self.check.mkdir()
        (self.check / "output").write_text("[exit 1]\n")
        self.hand_back()
        self.moved = True
        self.assertNotIn("first", self.review("after-the-move")[1])


if __name__ == "__main__":
    unittest.main()
