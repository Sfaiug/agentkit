"""A run verifying to land takes the next heavy turn ahead of round checks.

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
from fixtures.sandbox import account_home
from agentkit import gate, config, run, worker
from agentkit import record as run_record

ACME = "/home/fixture/code/acme"        # a main checkout as the records name it; never opened


class Gate(threading.Thread):
    """One `run_done_when` in a thread of its own, its result or its exception kept."""

    def __init__(self, case, name, repo, cmds, first=False, landing=False, heavy=True, **kw):
        super().__init__(daemon=True)
        self.run_dir = case.record(name, repo, first, landing)
        self.logs, self.result, self.error = [], None, None
        self.args = (cmds, case.root, self.run_dir / "donewhen.log", set())
        self.kw = {"log": self.logs.append, "run_dir": self.run_dir,
                   "heavy": heavy, **kw}

    def run(self):
        try:
            self.result = gate.run_done_when(*self.args, **self.kw)
        except BaseException as exc:      # noqa: BLE001 -- the test reads it
            self.error = exc


class GateLanders(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-gate-turns-landers-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(account_home(self.root))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        # a worker running this file carries its run's marker, which a killed command below
        # would end, and the suites' AK_MAX_RUNS=0, under which no gate takes a turn
        self.stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root),
                                                          "AGENTKIT_RUN": "", "AK_RUN_DEPTH": "0"}))
        os.environ.pop("AK_MAX_RUNS", None)
        self.stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        self.stack.enter_context(patch.object(gate, "GATE_POLL", 0.05))
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
                 "repo": repo, **run_record.process_owner(),
                 "started_at": time.time(), "round_summaries": []}
        if first:
            state["first"] = True
        if landing:
            state["landing"] = True
        run_record.save_state(directory, state)
        return directory

    def waiter(self, name, repo, since, first=False, landing=False, landing_since=None,
               own_file=True):
        """A record marked waiting for a gate turn of `repo` since `since`.

        A landing waiter ranks by when its first landing wait began, kept in its
        marker beside the record and published in its wait's file, as a lap of
        `gate_turn` publishes it -- unless it is on code from before those files; a
        round waiter's mark is the old shape, with no landing key at all.
        """
        directory = self.record(name, repo, first, landing)
        state = run_record.read_state(directory)
        mark = {"pid": state["pid"], "of": str(run.main_checkout(repo)), "since": since}
        if landing:
            mark["landing"] = True
            (directory / "landing_since").write_text(
                repr(since if landing_since is None else landing_since))
            if own_file:
                self.stack.enter_context(gate.landing_wait(
                    True, gate._first_landing_wait(directory), name))
        state["gate_turn"] = mark
        run_record.save_state(directory, state)
        return directory

    def turn(self, name):
        return (run_record.read_state(config.RUNS / name) or {}).get("gate_turn") or {}

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
        holder = gate.gate_lock(ACME, 0).open("a")
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
        lander_first = gate._first_landing_wait(lander.run_dir)
        # its first landing wait starts at its first look at the turns, as its file says
        self.assertLessEqual(lander_first, lander_mark["since"])
        # and its record says the start its file says: a waiter on older code reads the record
        self.assertIn((lander_first, "landing-waiter"), gate._landing_waiters())
        repo = run.main_checkout(ACME)
        self.assertTrue(gate._gate_waiter_before(repo, "round-waiter", round_since))
        self.assertFalse(gate._gate_waiter_before(repo, "landing-waiter", lander_first, True))
        fcntl.flock(holder, fcntl.LOCK_UN)
        plain.join(20)
        lander.join(20)
        self.assertIsNone(plain.error, plain.error)
        self.assertIsNone(lander.error, lander.error)
        self.assertTrue(plain.result[0] and lander.result[0])
        self.assertEqual(self.marks.read_text(), "lander\nround\n")

    def test_the_line_checkers_wait_holds_round_checks_and_new_runs(self):
        # The line's checker marks no member's record; its wait still goes first.
        plain = Gate(self, "round-waiter", ACME, [self.mark("round")])
        holder = gate.gate_lock(ACME, 0).open("a")
        self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)
        plain.start()
        self.until(lambda: self.turn("round-waiter").get("since") is not None,
                   "the round waiter to mark its wait")
        context = {"repo": ACME, "run_id": "member", "landing": True, "since": time.time()}
        def check():
            with gate.gate_turn(None, self.root / "line.log", None, None, self.root,
                                context=context):
                with self.marks.open("a") as marks:
                    marks.write("lander\n")
        checker = threading.Thread(target=check, daemon=True)
        checker.start()
        self.until(gate.landing_waits, "the checker to wait for a turn")
        repo = run.main_checkout(ACME)
        self.assertTrue(gate._gate_waiter_before(repo, "round-waiter",
                                                 self.turn("round-waiter")["since"]))
        readings = {"free_mb": 8000, "mem_total_mb": 16000, "slice_cpu_pressure": 0}
        new = {"run_id": "new-run", "run_depth": 0}
        self.assertFalse(gate.claim_slot(new, 0, readings))
        self.assertEqual(new["slot_wait_kind"], "landing")
        repair = {"run_id": "repair", "run_depth": 0, "first": True}
        self.assertFalse(gate.claim_slot(repair, 0, readings))   # its first steady poll
        self.assertTrue(gate.claim_slot(repair, 0, readings))
        fcntl.flock(holder, fcntl.LOCK_UN)
        checker.join(20)
        plain.join(20)
        self.assertIsNone(plain.error, plain.error)
        self.assertEqual(self.marks.read_text(), "lander\nround\n")
        self.assertFalse(gate.landing_waits())
        self.assertFalse(gate.claim_slot(new, 0, readings))   # its first steady poll
        self.assertTrue(gate.claim_slot(new, 0, readings))

    def test_a_landing_check_is_seen_from_its_first_look_at_the_turns(self):
        # No new run or round check slips in while the checker reads headroom for its pieces.
        seen, real = [], gate._heavy_max_existing
        def look():
            seen.append(gate.landing_waits())
            return real()
        context = {"repo": ACME, "run_id": "member", "landing": True, "since": time.time()}
        with patch.object(gate, "_heavy_max_existing", side_effect=look):
            with gate.gate_turn(None, self.root / "line.log", None, None, self.root,
                                context=context):
                self.assertFalse(gate.landing_waits())    # it holds its turn: no wait left
        self.assertEqual(seen[:1], [True])

    def test_an_older_line_check_takes_the_turn_before_a_younger_one(self):
        # The line's checkers mark no record; their waits still rank by when they joined.
        holder = gate.gate_lock(ACME, 0).open("a")
        self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)
        polled = {"older": threading.Semaphore(0), "younger": threading.Semaphore(0)}
        go = {"older": threading.Semaphore(0), "younger": threading.Semaphore(0)}
        order, real, scripted = [], time.sleep, threading.Event()
        scripted.set()
        def poll(seconds):
            name = threading.current_thread().name
            if name not in polled or not scripted.is_set():
                return real(seconds)
            polled[name].release()
            go[name].acquire(timeout=20)
        def check(name, joined):
            context = {"repo": ACME, "run_id": name, "landing": True, "since": joined}
            with gate.gate_turn(None, self.root / f"{name}.log", None, None, self.root,
                                context=context):
                order.append(name)
        threads = [threading.Thread(target=check, args=(name, joined), name=name, daemon=True)
                   for name, joined in (("older", 1000), ("younger", 2000))]
        with patch.object(gate.time, "sleep", side_effect=poll):
            for thread in threads:
                thread.start()
                self.assertTrue(polled[thread.name].acquire(timeout=20), thread.name)
            fcntl.flock(holder, fcntl.LOCK_UN)
            go["younger"].release()        # the younger polls first and finds the turn free
            self.until(lambda: order or polled["younger"].acquire(blocking=False),
                       "the younger check to poll")
            scripted.clear()               # from here on both poll freely
            go["older"].release()
            go["younger"].release()
            for thread in threads:
                thread.join(20)
        self.assertEqual(order, ["older", "younger"])
        self.assertFalse(gate.landing_waits())

    def test_a_landing_wait_ranks_by_its_file_alone(self):
        # Its record's marker may say otherwise -- a clock set back between the two reads --
        # and two waiters that each ranked the other first would both give a free turn away.
        repo = run.main_checkout(ACME)
        lander = self.record("record-lander", ACME, landing=True)
        state = run_record.read_state(lander)
        state["gate_turn"] = {"pid": state["pid"], "of": str(repo), "since": 1000,
                              "landing": True}
        run_record.save_state(lander, state)
        (lander / "landing_since").write_text("1000")
        self.stack.enter_context(gate.landing_wait(True, 3000, "record-lander"))
        self.stack.enter_context(gate.landing_wait(True, 2000, "line"))
        self.assertTrue(gate._gate_waiter_before(repo, "record-lander", 3000, True))
        self.assertFalse(gate._gate_waiter_before(repo, "line", 2000, True))

    def test_a_lander_waiting_on_older_code_still_ranks_and_holds_back(self):
        # A run keeps the code it loaded while it waits: one from before the files shows its
        # wait only on its record and by holding the shared file.
        self.waiter("older-code", ACME, 1000, landing=True, own_file=False)
        shared = (config.RUNS / ".heavy-landing.wait").open("a")
        self.addCleanup(shared.close)
        fcntl.flock(shared, fcntl.LOCK_SH)
        repo = run.main_checkout(ACME)
        self.assertTrue(gate.landing_waits())
        self.assertTrue(gate._gate_waiter_before(repo, "round", time.time()))
        self.assertTrue(gate._gate_waiter_before(repo, "younger", 2000, True))
        self.assertFalse(gate._gate_waiter_before(repo, "older-code", 1000, True))
        readings = {"free_mb": 8000, "mem_total_mb": 16000, "slice_cpu_pressure": 0}
        new = {"run_id": "new-run", "run_depth": 0}
        self.assertFalse(gate.claim_slot(new, 0, readings))
        self.assertEqual(new["slot_wait_kind"], "landing")

    def test_a_dead_line_checks_wait_holds_nobody_back(self):
        # Its holder is gone, so nothing holds its file: no round check or new run waits on it.
        dead = config.RUNS / ".landing-wait-gone"
        dead.write_text('{"since": 1, "run_id": "gone"}')
        repo = run.main_checkout(ACME)
        self.assertFalse(gate._gate_waiter_before(repo, "round", time.time()))
        self.assertFalse(gate.landing_waits())
        self.assertFalse(dead.exists())

    def test_a_check_whose_member_left_the_line_holds_nobody_back(self):
        turn = config.RUNS / ".merge-acme.lock"
        member = self.record("member", ACME)
        state = run_record.read_state(member)
        run_record.save_state(member, {**state, "state": "waiting", "pid": None,
                                       "waiting_on": {"line": turn.name, "joined": 1}})
        holder = gate.gate_lock(ACME, 0).open("a")
        self.addCleanup(holder.close)
        fcntl.flock(holder, fcntl.LOCK_EX)
        context = {"repo": ACME, "run_id": "member", "landing": True, "since": 1,
                   "line": turn.name}
        done = []
        def check():
            with gate.gate_turn(None, self.root / "line.log", None, None, self.root,
                                context=context):
                done.append(True)
        checker = threading.Thread(target=check, daemon=True)
        checker.start()
        self.until(gate.landing_waits, "the checker to wait for a turn")
        with run_record.record(member) as current:
            current["state"] = "stopped"
        self.until(lambda: not gate.landing_waits(), "the checker to stop holding others back")
        readings = {"free_mb": 8000, "mem_total_mb": 16000, "slice_cpu_pressure": 0}
        new = {"run_id": "new-run", "run_depth": 0}
        self.assertFalse(gate.claim_slot(new, 0, readings))   # its first steady poll
        self.assertTrue(gate.claim_slot(new, 0, readings))
        repo = run.main_checkout(ACME)
        self.assertFalse(gate._gate_waiter_before(repo, "round", time.time() - 60))
        fcntl.flock(holder, fcntl.LOCK_UN)
        checker.join(20)
        self.assertEqual(done, [True])

    def test_earlier_first_landing_wait_wins_between_landers_across_retries(self):
        # the old lander is on its second wait: waiting since 3000, but its first
        # landing wait began at 1000, ahead of the new lander's 2000
        self.waiter("old-lander", ACME, 3000, landing=True, landing_since=1000)
        self.waiter("new-lander", ACME, 2000, landing=True, landing_since=2000)
        repo = run.main_checkout(ACME)
        self.assertTrue(gate._gate_waiter_before(repo, "new-lander", 2000, True))
        self.assertFalse(gate._gate_waiter_before(repo, "old-lander", 1000, True))
        # between landers a later --first waits its turn like the rest
        self.waiter("lander-first", ACME, 2500, first=True, landing=True,
                    landing_since=2500)
        self.assertFalse(gate._gate_waiter_before(repo, "old-lander", 1000, True))
        self.assertTrue(gate._gate_waiter_before(repo, "lander-first", 2500, True))
        # a landing mark with no recorded start still seeds one rather than failing
        bare = self.record("bare-lander", ACME, landing=True)
        began = gate.mark_gate_wait(bare, repo)
        self.assertEqual(gate._first_landing_wait(bare), began)

    def test_two_land_driven_landers_compare_by_their_first_waits(self):
        # no hand-built starts: each landing's first real mark seeds its count,
        # and a later retry's wait keeps it
        early = self.record("seed-early", ACME, landing=True)
        late = self.record("seed-late", ACME, landing=True)
        repo = run.main_checkout(ACME)
        clock = [1000.0]
        with patch.object(gate.time, "time", side_effect=lambda: clock[0]):
            self.assertEqual(gate.mark_gate_wait(early, repo), 1000.0)
            clock[0] = 1100.0
            gate.mark_gate_wait(early, None)
            clock[0] = 2000.0
            self.assertEqual(gate.mark_gate_wait(late, repo), 2000.0)
            clock[0] = 2100.0
            gate.mark_gate_wait(late, None)
            # second waits wait now but count from their seeds
            clock[0] = 3000.0
            self.assertEqual(gate.mark_gate_wait(early, repo), 1000.0)
            clock[0] = 3100.0
            self.assertEqual(gate.mark_gate_wait(late, repo), 2000.0)
        # each lap's wait publishes the seed in its file, as `gate_turn` does
        for directory in (early, late):
            self.stack.enter_context(gate.landing_wait(True, gate._first_landing_wait(directory),
                                                       directory.name))
        self.assertTrue(gate._gate_waiter_before(repo, "seed-late", 2000.0, True))
        self.assertFalse(gate._gate_waiter_before(repo, "seed-early", 1000.0, True))
        # a lander that never waited counts from now, behind both seeds
        fresh = self.record("seed-fresh", ACME, landing=True)
        self.assertIsNone(gate._first_landing_wait(fresh))
        self.assertTrue(gate._gate_waiter_before(repo, "seed-fresh", 4000.0, True))

    def test_round_waiters_keep_wait_order_without_landers(self):
        self.waiter("early", ACME, 1000)
        self.waiter("late", ACME, 2000)
        repo = run.main_checkout(ACME)
        self.assertTrue(gate._gate_waiter_before(repo, "late", 2000))
        self.assertFalse(gate._gate_waiter_before(repo, "early", 1000))

    def test_land_marks_landing_for_its_gate_waits_and_clears_it(self):
        run_dir = self.record("landing-run", ACME)
        state = run_record.read_state(run_dir)
        state["base_sha"] = "base0001"
        run_record.save_state(run_dir, state)
        logs = []
        lp = SimpleNamespace(state=run_record.read_state(run_dir), run_dir=run_dir,
                             wt=self.root / "wt", base_sha="base0001", once=[],
                             log=logs.append, no_pickup=True,
                             write=lambda: run_record.save_state(run_dir, lp.state))
        repo = run.main_checkout(ACME)

        def verify():
            on_disk = run_record.read_state(run_dir)
            self.assertTrue(on_disk.get("landing"))
            # the landing starts unwaited: the first wait seeds the count
            self.assertIsNone(gate._first_landing_wait(run_dir))
            began = gate.mark_gate_wait(run_dir, repo)
            mark = self.turn("landing-run")
            self.assertTrue(mark.get("landing"))
            self.assertEqual(gate._first_landing_wait(run_dir), began)
            gate.mark_gate_wait(run_dir, None)
            return True

        def deliver():
            self.assertTrue(run_record.read_state(run_dir).get("landing"))
            return True

        with patch.object(run, "git", return_value="base0001"), \
                patch.object(run, "git_out", return_value=(0, "")):
            self.assertTrue(run.land(lp, "origin/main", verify, deliver,
                                     execv=lambda *a: self.fail("no pickup here")))
        self.assertNotIn("landing", lp.state)
        self.assertNotIn("landing", run_record.read_state(run_dir))
        self.assertFalse((run_dir / "landing_since").exists())


if __name__ == "__main__":
    unittest.main()
