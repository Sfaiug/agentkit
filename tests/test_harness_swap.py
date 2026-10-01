"""A worker turn that fails while its harness is being swapped starts again after the swap.

`update.swapping` records an install or revert of a harness; `call_retrying` waits out one that
overlapped a failed turn and starts the turn again on its session, instead of reading the
missing command as a harness that cannot run.  A launch naming a model is not refused for a
harness asked mid-swap either: `refuse_unready` waits the swap out and asks again.  Offline:
the worker is a fake, the swap is the record alone, and every wait is patched to return at once.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, update, usage  # noqa: E402

MISSING = "adapters/claude.sh: line 70: claude: command not found\n"


class HarnessSwap(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-harness-swap-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, key, self.root / key.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AGENTKIT_TMUX_SOCKET": "harness-swap-test", "TMUX_TMPDIR": str(self.root)}))
        config.ensure_dirs()
        self.cfg = config.load()
        self.calls, self.logs, self.sleeps = [], [], []

    def call(self, answers, session=None):
        """call_retrying for opus, whose worker plays `answers` back: (code, text, stderr).

        A turn that exits 127 never ran, so it names no session.
        """
        def fake(*args, **_kw):
            code, text, stderr = answers[min(len(self.calls), len(answers) - 1)]
            self.calls.append(args)
            out = Path(args[4])
            out.mkdir(parents=True, exist_ok=True)
            (out / "final.md").write_text(text)
            (out / "stderr.log").write_text(stderr)
            (out / "events.jsonl").write_text("")
            return code, text, None if code == 127 else "sess-1", False

        with patch.object(run.worker, "call", side_effect=fake):
            return run.call_retrying(self.cfg, "opus", "body", self.root,
                                     self.root / "run" / "round-1" / "executor", "executor",
                                     session, self.logs.append)

    def test_a_turn_failing_during_a_swap_waits_for_its_end_then_passes(self):
        swap = update.swapping("claude")
        swap.__enter__()

        def sleep(delay):
            # the upgrade's install step returns while the loop waits
            self.sleeps.append(delay)
            if len(self.sleeps) == 2:
                swap.__exit__(None, None, None)

        # a resume the missing command failed is not a session that cannot be opened
        with patch.object(run.time, "sleep", side_effect=sleep):
            code, text, session, _ = self.call([(127, "", MISSING),
                                                (0, "## Summary\nDone.\n", "")], "sess-1")
        self.assertEqual((code, session), (0, "sess-1"))
        self.assertIn("Done.", text)
        self.assertEqual(len(self.sleeps), 2)
        self.assertTrue(all(0 < delay <= run.SWAP_POLL for delay in self.sleeps), self.sleeps)
        # the second start resumed the same session, after the swap ended
        self.assertEqual([args[6] for args in self.calls], ["sess-1", "sess-1"])
        self.assertTrue(any("being swapped" in line for line in self.logs), self.logs)

    def test_a_fresh_turn_failing_during_a_swap_waits_before_finishing_in_the_foreground(self):
        swap = update.swapping("claude")
        self.addCleanup(swap.__exit__, None, None, None)
        begun = []

        def begin(*_a):
            # the resume failed with no swap, and the install starts under the fresh turn
            if not begun:
                begun.append(swap.__enter__())

        def sleep(delay):
            self.sleeps.append(delay)
            swap.__exit__(None, None, None)

        with patch.object(run, "note_turn_meters", side_effect=begin), \
                patch.object(run.time, "sleep", side_effect=sleep):
            code, _, _, _ = self.call([(1, "", ""),
                                       (127, "", MISSING + "Background tasks still running\n"),
                                       (0, "## Summary\nDone.\n", "")], "sess-0")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.sleeps), 1)
        # no call to finish in the foreground went out while the swap ran
        self.assertEqual([Path(args[4]).name for args in self.calls],
                         ["executor", "executor-retry1", "executor-retry2"])

    def test_a_turn_failing_again_after_the_swap_cannot_run(self):
        swap = update.swapping("claude")
        swap.__enter__()
        ended = lambda _delay: swap.__exit__(None, None, None)
        with patch.object(run.time, "sleep", side_effect=ended), \
                self.assertRaises(run.CannotRun):
            self.call([(127, "", MISSING)])
        # one start again per swap: the second failure began after the swap had ended
        self.assertEqual(len(self.calls), 2)

    def test_a_turn_failing_with_no_swap_cannot_run(self):
        with patch.object(run.time, "sleep", side_effect=AssertionError("waited")), \
                self.assertRaises(run.CannotRun) as broken:
            self.call([(127, "", MISSING)])
        self.assertEqual(len(self.calls), 1)
        self.assertIn("command not found", str(broken.exception))

    def test_a_swap_begun_after_the_turn_ended_holds_nothing(self):
        swap = update.swapping("claude")
        self.addCleanup(swap.__exit__, None, None, None)

        def begin(*_a):
            # the turn has returned, and the upgrade starts its install a moment later
            with patch.object(update.time, "time", return_value=time.time() + 1):
                swap.__enter__()

        with patch.object(run, "note_turn_meters", side_effect=begin), \
                patch.object(run.time, "sleep", side_effect=AssertionError("waited")), \
                self.assertRaises(run.CannotRun):
            self.call([(127, "", MISSING)])
        self.assertEqual(len(self.calls), 1)

    def test_a_swap_left_without_an_end_past_the_cap_holds_nothing(self):
        # the upgrade died mid-install and never wrote the end: its step was killed at the cap
        began = time.time() - update.STEP_CAP - 60
        swap = update.swapping("claude")
        self.addCleanup(swap.__exit__, None, None, None)
        with patch.object(update.time, "time", return_value=began):
            swap.__enter__()
        self.assertEqual(update.swap_end("claude", began, began), began + update.STEP_CAP)
        with patch.object(run.time, "sleep", side_effect=AssertionError("waited")), \
                self.assertRaises(run.CannotRun):
            self.call([(127, "", MISSING)])
        self.assertEqual(len(self.calls), 1)

    def test_a_launch_naming_a_model_asked_mid_swap_waits_for_the_swap_and_asks_again(self):
        swap = update.swapping("claude")
        self.addCleanup(swap.__exit__, None, None, None)
        swap.__enter__()
        # the pick's read asked the harness while its command was moved aside
        read = usage.Readings({})
        read.harnesses, read.asked_at = {"claude": "claude is not installed"}, time.time()

        def sleep(delay):
            self.sleeps.append(delay)
            swap.__exit__(None, None, None)

        with patch.object(run.usage, "harness_unready", return_value=None) as asked, \
                patch.object(run.time, "sleep", side_effect=sleep):
            run.refuse_unready(self.cfg, read, "opus")
        self.assertEqual(len(self.sleeps), 1)
        self.assertTrue(0 < self.sleeps[0] <= run.SWAP_POLL, self.sleeps)
        asked.assert_called_once_with("claude")
        # a swap that ended between the read and the pick is asked about again at once, and
        # one still missing its command after the swap is refused in the harness's own words
        with patch.object(run.usage, "harness_unready", return_value="claude is not installed"), \
                patch.object(run.time, "sleep", side_effect=AssertionError("waited")), \
                self.assertRaisesRegex(config.Error, "^opus cannot run here: claude is not installed$"):
            run.refuse_unready(self.cfg, read, "opus")
        # a read taken after the swap ended is the answer: nothing is waited for or asked again
        read.asked_at = time.time() + 1
        with patch.object(run.usage, "harness_unready", side_effect=AssertionError("asked")), \
                patch.object(run.time, "sleep", side_effect=AssertionError("waited")), \
                self.assertRaisesRegex(config.Error, "^opus cannot run here"):
            run.refuse_unready(self.cfg, read, "opus")


if __name__ == "__main__":
    unittest.main()
