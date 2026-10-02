"""A seat whose run waits on the owner reads `needs you`, never `working`.

Three runs nothing moves on its own: a merge wait whose day of tick admission ran out, a
run left parked and undecided after the seat said it was done, and a `stalled` one, which
only `ak run resume` moves.  Each one's seat names the run and asks him.  Offline: run and
session records in a throwaway HOME, a fake tmux, and `watch.session_state` deciding.
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
from agentkit import config, notify, orch, run, watch
from agentkit import record

NOW = 1_800_000_000
DAY = 86400
WAIT = "origin/main is red; retried after the next merge to origin/main"


class SeatNeedsYouForParkedRuns(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {"HOME": str(root), "NO_COLOR": "1"}))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, root / name.lower()))
        self.cfg = config.load()
        config.ensure_dirs()
        self.seat = {"name": "acme", "attached": False, "exited": False}
        config.save_session(self.cfg, "acme", "fable", ["opus"], {"cwd": str(root)})
        stack.enter_context(patch.object(orch, "listing", return_value=[self.seat]))
        stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))

    def receipt(self, name, **extra):
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        record.save_state(directory, {"run_id": name, "title": f"Task {name}",
                                   "launched_session": "acme", "started_at": NOW - 2 * DAY,
                                   **extra})
        return directory

    def decide(self):
        return watch.session_state("acme", NOW, session=self.seat, cfg=self.cfg, live={},
                                   harness="claude", auth_out={}, gh_out={}, token_out={},
                                   previous={})

    def test_a_merge_wait_past_its_admission_needs_you_and_names_the_run(self):
        wait = dict(state="waiting", verdict="PASS", error=WAIT, merge_note=WAIT,
                    waiting_on={"ref": "origin/main"}, finished_at=NOW - 3600)
        self.receipt("fix-api", **wait)
        self.assertEqual(self.decide()["word"], "working")    # the tick's, for a day
        late = self.receipt("fix-api", **{**wait, "finished_at": NOW - DAY - 60})
        for notice in (False, True):    # with or without a done of the seat's own
            if notice:
                notify.record("acme", "done", "Shipped it", time=NOW - 60)
            with self.subTest(done=notice):
                found = self.decide()
                self.assertEqual(found["word"], "needs you")
                self.assertEqual(found["reason"], f"run fix-api waits to merge: {WAIT}")
        # ... unless he already has it: an acknowledged wait is his decision made
        record.save_state(late, {**record.read_state(late), "recovery_acknowledged_at": NOW - 30})
        self.assertEqual(self.decide()["word"], "done")

    def test_a_done_seat_with_an_undecided_run_needs_you(self):
        self.receipt("fix-api", state="interrupted", recovery_pending=True,
                     interrupted_at=NOW - 3600, handed_back=NOW - 3500,
                     interruption_reason="the loop died mid-review")
        notify.record("acme", "done", "Shipped it", time=NOW - 60)
        found = self.decide()
        self.assertEqual(found["word"], "needs you")
        self.assertEqual(found["reason"], "run fix-api parked: the loop died mid-review")

    def test_a_stalled_run_needs_you_and_says_how_to_resume_it(self):
        # a long id and a long step: the recorded error is cut short, the command never is
        name = "20261001-0100-fix-api-a-long-integration-command-in-the"
        stalled = self.receipt(name, state="running", finished_at=None)
        run.park_stalled(stalled, record.read_state(stalled), {"step": "done-when " + "x" * 240})
        found = self.decide()
        self.assertEqual(found["word"], "needs you")
        self.assertEqual(found["reason"], f"run {name} stalled: resume it with `ak run resume {name}`")
        # what `going` means to the tick and every other caller is unchanged
        self.assertTrue(run.going(record.read_state(stalled), now=NOW))


if __name__ == "__main__":
    unittest.main()
