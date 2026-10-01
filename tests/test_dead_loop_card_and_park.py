"""A dead loop is carded only when nothing will resume it, and parked at its third death.

Whoever notices a death first -- the menu, `ak run status`, a job waiter, all of them a
`reap` -- records it, and any number of reaps before the tick's resume stay quiet. The
third death within an hour parks the run with one card, whoever recorded it.

Offline: fake run directories, a fake process table a resume adopts the record into, an
injected tree stop, and the card channel replaced. No process, unit, tmux or webhook is
touched.
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
from agentkit import config, notify, orch, run, watch


class DeadLoopCardAndPark(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".dead-loop-card-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_DISCORD_WEBHOOK": "off", "AK_RUN_ROLE": "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for key in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(key, None)
        # the process table is this set, and ending a tree signals nothing
        self.alive = set()
        self.stack.enter_context(patch.object(
            run, "process_active", lambda state: state.get("pid") in self.alive))
        self.stack.enter_context(patch.object(run, "stop_run_tree", lambda *_a, **_kw: None))
        self.stack.enter_context(patch.object(run, "memory_cap_reason", lambda *_a, **_kw: None))
        self.resumed = []
        self.stack.enter_context(patch.object(watch, "launch_resume", self.adopt))
        self.cards = []
        self.stack.enter_context(patch.object(
            notify, "shaped", lambda *a, **kw: self.cards.append((a, kw)) or 0))
        self.stack.enter_context(patch.object(orch, "watching", return_value=False))
        self.stack.enter_context(patch.object(watch, "orphan_fresh", return_value=False))
        self.stack.enter_context(patch.object(watch, "seat_closed", return_value=False))
        self.stack.enter_context(patch.object(watch, "seat_closed_by_owner", return_value=False))
        self.stack.enter_context(patch.object(run, "record_result", lambda *_a, **_kw: None))
        config.ensure_dirs()
        self.now = time.time()  # reap reads the host clock, so the pass measures the same
        self.dir = config.RUNS / "20261001-0300-acme-fix-api"
        self.dir.mkdir()
        (self.dir / "log.txt").touch()
        work = config.WORK / "fix-api"
        work.mkdir()
        run.save_state(self.dir, {
            "run_id": self.dir.name, "title": "fix-api", "state": "running", "pid": 1000,
            "started_at": self.now - 100, "launched_session": "seat", "executor": "opus",
            "reviewer": "astra", "rounds": 3, "round_summaries": [], "step": "executor",
            "worktree": str(work), "scratch": True, "base": None})

    def adopt(self, run_id, *_a, **_kw):
        """The resumed loop starts and adopts the record, as a real resume does."""
        self.resumed.append(run_id)
        state = run.read_state(self.dir)
        state.pop("stall_resume_at", None)
        state["pid"] = 1000 + len(self.resumed)
        self.alive.add(state["pid"])
        run.save_state(self.dir, state)
        return True

    def look(self):
        """A menu redraw, `ak run status` or a job waiter: a reap and nothing else."""
        run.reap(self.dir, run.read_state(self.dir))

    def tick(self, now):
        watch.resume_dead_loops(dry_run=False, log=lambda _line: None, now=now)
        self.look()

    def dies(self):
        self.alive.discard(run.read_state(self.dir)["pid"])

    def test_reaps_before_the_resume_never_card_a_death_the_tick_resumes(self):
        self.look()
        self.look()
        self.assertEqual(self.cards, [], "a second look before the resume is still nobody's news")
        self.tick(self.now)
        self.assertEqual(self.resumed, [self.dir.name])
        # the next death falls inside the backoff: the tick holds off and its own reap,
        # like any look, leaves the record waiting without a card
        self.dies()
        self.look()
        self.tick(self.now + 60)
        self.look()
        self.assertEqual(self.resumed, [self.dir.name])
        self.assertEqual(run.read_state(self.dir)["state"], "interrupted")
        self.assertEqual(self.cards, [], "a death the tick resumes after its backoff is nobody's news")
        self.tick(self.now + 700)
        self.assertEqual(len(self.resumed), 2)
        self.assertEqual(self.cards, [])

    def test_a_third_death_a_look_noticed_first_parks_with_one_card(self):
        self.look()
        self.tick(self.now)
        self.dies()
        self.look()
        self.tick(self.now + 700)
        self.assertEqual(len(self.resumed), 2)
        self.dies()
        self.look()
        self.tick(self.now + 760)
        self.tick(self.now + 1400)
        state = run.read_state(self.dir)
        self.assertEqual(len(self.resumed), 2, "a third death within the hour is not resumed")
        self.assertEqual(state["state"], "interrupted")
        self.assertEqual(len(state["deaths"]), 3)
        self.assertTrue(state["deaths"][-1]["parked"])
        self.assertEqual(len(self.cards), 1, "the park is told once")


if __name__ == "__main__":
    unittest.main()
