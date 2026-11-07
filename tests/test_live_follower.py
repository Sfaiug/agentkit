"""A project's one live follower follows each run on a thread and a clock of its own.  Offline: a
Sandbox HOME, fake probes and seat, and one clock all the follower's threads read and sleep on."""

import os
import threading
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, orch, record, watch

T0, SEAT, WINDOW = 2000000, "fix-api", watch.AFTER_MERGE_WINDOW
TAKES = {("slow", "health"): 30, ("live", "deployed"): 5}     # what a run's probe takes
UP = {("live", "health"): T0 + 40, ("live", "deployed"): T0}  # and when it passes from


class Clock:
    """Stands still while any thread runs, and moves to the earliest wake once all sleep: what a
    thread reads of it is what its own sleeps and probes spent, however the host runs them."""

    def __init__(self):
        self.now, self.wakes, self.moved = T0, {}, threading.Condition()

    def __getattr__(self, name):
        return getattr(time, name)

    def time(self):
        return self.now

    def sleep(self, seconds):
        me, stuck = threading.get_ident(), time.monotonic() + 60
        with self.moved:
            self.wakes[me] = self.now + seconds
            while self.now < self.wakes[me]:
                if len(self.wakes) == threading.active_count() and min(self.wakes.values()) > self.now:
                    self.now = min(self.wakes.values())
                    self.moved.notify_all()
                else:   # a thread that ends instead of sleeping wakes no one
                    assert time.monotonic() < stuck, "a thread neither sleeps nor ends"
                    self.moved.wait(0.01)
            del self.wakes[me]


class LiveFollower(Sandbox):
    def setUp(self):
        super().setUp()
        self.clock, self.began = Clock(), {}
        for module, name, fake in (
                # the follower started is this process, with the lock it is handed on its stdin
                (orch, "start_in_slice", lambda *_a, stdin, **_kw: os.dup2(stdin, 0)),
                (orch, "find", lambda _name: {"name": SEAT, "created": 100, "exited": False}),
                (watch, "type_at_prompt", lambda *_a, **_kw: False),        # never at its prompt
                (watch, "health_command", self.probe),
                (watch, "time", self.clock)):
            self.stack.enter_context(patch.object(module, name, fake))

    def probe(self, _repo, _sha, _command, checked, **_kw):
        """A run's `health:` or `deployed:` probe, taking `TAKES` and passing from `UP`."""
        name, kind = checked[0].name, checked[2]
        self.began.setdefault(name, []).append((kind, self.clock.now))
        self.clock.sleep(TAKES.get((name, kind), 0))
        return self.clock.now >= UP.get((name, kind), float("inf")), "deploying"

    def test_a_slow_probe_moves_no_other_runs_times(self):
        """`live` and `red` keep the times each has followed alone: probed 15 s after its own
        last probe ends, `live` up at T0 + 40 and `red` until its window ends."""
        for name, fields in (("slow", {"finished_at": T0 - WINDOW + 100}),
                             ("live", {"deployed": "probe"}),
                             ("red", {"finished_at": T0 - WINDOW + 50})):
            (config.RUNS / name).mkdir()
            record.save_state(config.RUNS / name, {
                "run_id": name, "state": "pass", "merged": True, "merge_sha": "a" * 40,
                "pr": "https://github.com/acme/widget/pull/7", "launched_session": SEAT,
                "repo": str(self.root), "finished_at": T0, "handed_back": T0, "reported": True,
                "health": {"command": "probe"}, "deployed": None, **fields})
            watch.start_live_probe(config.RUNS / name)     # handed to its project's follower,
        self.assertEqual(watch.live_follower("slow"), 0)    # which this process is, until it ends
        self.assertEqual(threading.active_count(), 1)
        self.assertEqual(self.began["slow"], [("health", T0 + at) for at in (0, 45, 90)])
        self.assertEqual(self.began["live"], [(kind, T0 + at) for at in (0, 20, 40)
                                              for kind in ("health", "deployed")])
        self.assertEqual(self.began["red"], [("health", T0 + at) for at in (0, 15, 30, 45)])
        live = record.read_state(config.RUNS / "live")
        self.assertEqual((live["live_at"], live["deployed_at"]), (T0 + 40, T0 + 5))

    def test_one_read_of_the_records_serves_every_run_an_interval(self):
        """Three runs live and owed their line by a seat owing work, their windows ending 15 s
        apart: whichever asks first in an interval reads every run's record, the rest take it,
        up to the last look that finds the last window past."""
        reads, every = [], record.runs
        self.stack.enter_context(patch.object(
            record, "runs", lambda: reads.append(self.clock.now) or every()))
        config.plan_path(SEAT).write_text("- [ ] the parser parses\n")
        for at, name in enumerate(("one", "two", "three"), 1):
            (config.RUNS / name).mkdir()
            record.save_state(config.RUNS / name, {
                "run_id": name, "state": "pass", "merged": True, "merge_sha": "a" * 40,
                "pr": "https://github.com/acme/widget/pull/7", "launched_session": SEAT,
                "repo": str(self.root), "finished_at": T0 - WINDOW + 15 * at, "live_at": T0,
                "handed_back": T0, "reported": True, "health": {}, "deployed": None})
            watch.start_live_probe(config.RUNS / name)
        self.assertEqual(watch.live_follower("one"), 0)
        self.assertEqual(reads, [T0 + at for at in (0, 15, 30, 45, 60)])
        self.assertFalse(any(record.read_state(config.RUNS / name).get("live_notified")
                             for name in ("one", "two", "three")))


if __name__ == "__main__":
    unittest.main()
