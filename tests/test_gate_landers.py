"""A run verifying to land takes its repository's next gate turn ahead of round checks.

Offline: a temporary HOME, fake run records and fake repositories; live waiters
are this process's own records. Nothing here signals a real process.
"""

from contextlib import ExitStack
from types import SimpleNamespace
import fcntl
import os
from pathlib import Path
import shlex
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, worker

ACME = "/home/fixture/code/acme"        # a main checkout as the records name it; never opened


class Gate(threading.Thread):
    """One `run_done_when` in a thread of its own, its result or its exception kept."""

    def __init__(self, case, name, repo, cmds, first=False, landing=False, **kw):
        super().__init__(daemon=True)
        self.run_dir = case.record(name, repo, first, landing)
        self.logs, self.result, self.error = [], None, None
        self.args = (cmds, case.root, self.run_dir / "donewhen.log", set())
        self.kw = {"log": self.logs.append, "run_dir": self.run_dir, **kw}

    def run(self):
        try:
            self.result = run.run_done_when(*self.args, **self.kw)
        except BaseException as exc:      # noqa: BLE001 -- the test reads it
            self.error = exc


class GateLanders(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".gate-turns-landers-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        # a worker running this file carries its run's marker, which a killed command below
        # would end, and the suites' AK_MAX_RUNS=0, under which no gate takes a turn
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root),
                                                          "AGENTKIT_RUN": "", "AK_RUN_DEPTH": "0"}))
        os.environ.pop("AK_MAX_RUNS", None)
        self.stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        self.stack.enter_context(patch.object(run, "GATE_POLL", 0.05))
        self.stack.enter_context(patch.object(worker, "ACTIVITY_POLL", 0.05))
        config.RUNS.mkdir(parents=True)
        config.HOME.mkdir()
        (config.HOME / config.CONFIG_NAME).write_text("max_gates = 1\n")
        self.marks = self.root / "marks"
        self.marks.touch()

    def record(self, name, repo, first=False, landing=False):
        """A running run's record, this process its loop, landing when told so."""
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "title": name, "state": "running", "verdict": None,
                 "repo": repo, **run.process_owner(),
                 "started_at": time.time(), "round_summaries": []}
        if first:
            state["first"] = True
        if landing:
            state["landing"] = True
        run.save_state(directory, state)
        return directory

    def waiter(self, name, repo, since, first=False, landing=False, landing_since=None):
        """A record marked waiting for a gate turn of `repo` since `since`.

        A landing waiter ranks by when its first landing wait began, kept in its
        marker beside the record; a round waiter's mark is the old shape, with no
        landing key at all.
        """
        directory = self.record(name, repo, first, landing)
        state = run.read_state(directory)
        mark = {"pid": state["pid"], "of": str(run.main_checkout(repo)), "since": since}
        if landing:
            mark["landing"] = True
            (directory / "landing_since").write_text(
                repr(since if landing_since is None else landing_since))
        state["gate_turn"] = mark
        run.save_state(directory, state)
        return directory

    def turn(self, name):
        return (run.read_state(config.RUNS / name) or {}).get("gate_turn") or {}

    def mark(self, word, seconds=0):
        return f"echo {word} >> {shlex.quote(str(self.marks))}; sleep {seconds}"

    def until(self, check, what, seconds=20):
        deadline = time.monotonic() + seconds
        while not check():
            self.assertLess(time.monotonic(), deadline, f"timed out waiting for {what}")
            time.sleep(0.02)

    def test_landing_waiter_takes_freed_turn_before_longer_round_waiter(self):
        plain = Gate(self, "round-waiter", ACME, [self.mark("round")])
        lander = Gate(self, "landing-waiter", ACME, [self.mark("lander")], landing=True)
        holder = run.gate_lock(ACME, 0).open("a")
        self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)
        plain.start()
        self.until(lambda: self.turn("round-waiter").get("since") is not None,
                   "the round waiter to mark its wait")
        lander.start()
        self.until(lambda: self.turn("landing-waiter").get("since") is not None,
                   "the lander to mark its wait")
        round_since = self.turn("round-waiter")["since"]
        lander_mark = self.turn("landing-waiter")
        self.assertLess(round_since, lander_mark["since"])
        self.assertTrue(lander_mark.get("landing"))
        lander_first = run._first_landing_wait(lander.run_dir)
        self.assertEqual(lander_first, lander_mark["since"])
        repo = run.main_checkout(ACME)
        self.assertTrue(run._gate_waiter_before(repo, "round-waiter", False, round_since))
        self.assertFalse(run._gate_waiter_before(repo, "landing-waiter", False,
                                                 lander_first, True))
        fcntl.flock(holder, fcntl.LOCK_UN)
        plain.join(20)
        lander.join(20)
        self.assertIsNone(plain.error, plain.error)
        self.assertIsNone(lander.error, lander.error)
        self.assertTrue(plain.result[0] and lander.result[0])
        self.assertEqual(self.marks.read_text(), "lander\nround\n")

    def test_earlier_first_landing_wait_wins_between_landers_across_laps(self):
        # the old lander is on its second lap: waiting since 3000, but its first
        # landing wait began at 1000, ahead of the new lander's 2000
        self.waiter("old-lander", ACME, 3000, landing=True, landing_since=1000)
        self.waiter("new-lander", ACME, 2000, landing=True, landing_since=2000)
        repo = run.main_checkout(ACME)
        self.assertTrue(run._gate_waiter_before(repo, "new-lander", False, 2000, True))
        self.assertFalse(run._gate_waiter_before(repo, "old-lander", False, 1000, True))
        # between landers --first still goes before the rest, whatever the waits
        self.waiter("lander-first", ACME, 2500, first=True, landing=True,
                    landing_since=2500)
        self.assertTrue(run._gate_waiter_before(repo, "old-lander", False, 1000, True))
        self.assertFalse(run._gate_waiter_before(repo, "lander-first", True, 2500, True))
        # across laps in a real landing: each lap waits, and a whole-record save of
        # the loop's own state between two waits keeps the landing's start
        run_dir = self.record("lap-run", ACME)
        state = run.read_state(run_dir)
        state["base_sha"] = "base0001"
        run.save_state(run_dir, state)
        lp = SimpleNamespace(state=run.read_state(run_dir), run_dir=run_dir,
                             wt=self.root / "wt", base_sha="base0001",
                             log=lambda msg: None, no_pickup=True)
        firsts = []

        def verify():
            began = run.mark_gate_wait(run_dir, repo)
            firsts.append(began)
            self.assertEqual(run._first_landing_wait(run_dir), began)
            run.mark_gate_wait(run_dir, None)
            run.save_state(run_dir, lp.state)   # an inner save, as final_check does
            return True

        with patch.object(run, "git", return_value="tip9999"), \
                patch.object(run, "git_out", return_value=(0, "")), \
                patch.object(run, "disjoint_move", return_value=False):
            self.assertFalse(run.land(lp, "origin/main", verify, lambda: True,
                                      execv=lambda *a: self.fail("no pickup here")))
        self.assertEqual(len(firsts), 3)
        self.assertEqual(firsts[1], firsts[0])
        self.assertEqual(firsts[2], firsts[0])
        # a landing mark with no recorded start still seeds one rather than failing
        bare = self.record("bare-lander", ACME, landing=True)
        began = run.mark_gate_wait(bare, repo)
        self.assertEqual(run._first_landing_wait(bare), began)

    def test_two_land_driven_landers_compare_by_their_first_waits(self):
        # no hand-built starts: each landing's first real mark seeds its count,
        # and a later lap's wait keeps it
        early = self.record("seed-early", ACME, landing=True)
        late = self.record("seed-late", ACME, landing=True)
        repo = run.main_checkout(ACME)
        with patch.object(run.time, "time", side_effect=[1000.0, 1100.0, 2000.0, 2100.0,
                                                         3000.0, 3100.0]):
            self.assertEqual(run.mark_gate_wait(early, repo), 1000.0)
            run.mark_gate_wait(early, None)
            self.assertEqual(run.mark_gate_wait(late, repo), 2000.0)
            run.mark_gate_wait(late, None)
            # second laps wait now but count from their seeds
            self.assertEqual(run.mark_gate_wait(early, repo), 1000.0)
            self.assertEqual(run.mark_gate_wait(late, repo), 2000.0)
        self.assertTrue(run._gate_waiter_before(repo, "seed-late", False, 2000.0, True))
        self.assertFalse(run._gate_waiter_before(repo, "seed-early", False, 1000.0, True))
        # a lander that never waited counts from now, behind both seeds
        fresh = self.record("seed-fresh", ACME, landing=True)
        self.assertIsNone(run._first_landing_wait(fresh))
        self.assertTrue(run._gate_waiter_before(repo, "seed-fresh", False, 4000.0, True))

    def test_round_waiters_keep_wait_order_without_landers(self):
        self.waiter("early", ACME, 1000)
        self.waiter("late", ACME, 2000)
        repo = run.main_checkout(ACME)
        self.assertTrue(run._gate_waiter_before(repo, "late", False, 2000))
        self.assertFalse(run._gate_waiter_before(repo, "early", False, 1000))

    def test_land_marks_landing_for_its_gate_waits_and_clears_it(self):
        run_dir = self.record("landing-run", ACME)
        state = run.read_state(run_dir)
        state["base_sha"] = "base0001"
        run.save_state(run_dir, state)
        logs = []
        lp = SimpleNamespace(state=run.read_state(run_dir), run_dir=run_dir,
                             wt=self.root / "wt", base_sha="base0001",
                             log=logs.append, no_pickup=True)
        repo = run.main_checkout(ACME)

        def verify():
            on_disk = run.read_state(run_dir)
            self.assertTrue(on_disk.get("landing"))
            # the landing starts unwaited: the first wait seeds the count
            self.assertIsNone(run._first_landing_wait(run_dir))
            began = run.mark_gate_wait(run_dir, repo)
            mark = self.turn("landing-run")
            self.assertTrue(mark.get("landing"))
            self.assertEqual(run._first_landing_wait(run_dir), began)
            run.mark_gate_wait(run_dir, None)
            return True

        def deliver():
            self.assertTrue(run.read_state(run_dir).get("landing"))
            return True

        with patch.object(run, "git", return_value="base0001"), \
                patch.object(run, "git_out", return_value=(0, "")):
            self.assertTrue(run.land(lp, "origin/main", verify, deliver,
                                     execv=lambda *a: self.fail("no pickup here")))
        self.assertNotIn("landing", lp.state)
        self.assertNotIn("landing", run.read_state(run_dir))
        self.assertFalse((run_dir / "landing_since").exists())
        # a pickup resume keeps its marker with its lap count
        rerun = self.record("landing-resumed", ACME)
        state = run.read_state(rerun)
        state.update(base_sha="base0001", land_lap=2)
        run.save_state(rerun, state)
        (rerun / "landing_since").write_text("1000.0")
        kept = SimpleNamespace(state=run.read_state(rerun), run_dir=rerun,
                               wt=self.root / "wt", base_sha="base0001",
                               log=lambda msg: None, no_pickup=True)

        def again():
            self.assertEqual(run.mark_gate_wait(rerun, repo), 1000.0)
            run.mark_gate_wait(rerun, None)
            return True

        with patch.object(run, "git", return_value="base0001"), \
                patch.object(run, "git_out", return_value=(0, "")):
            self.assertTrue(run.land(kept, "origin/main", again, lambda: True,
                                     execv=lambda *a: self.fail("no pickup here")))
        self.assertFalse((rerun / "landing_since").exists())


if __name__ == "__main__":
    unittest.main()
