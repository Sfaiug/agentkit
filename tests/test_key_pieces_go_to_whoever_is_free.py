"""A suite's pieces go to whichever place frees first: this host's one turn or the suite helper's
one VM. Offline: test_suite_helper's fake `ssh` is the Mac, gone while $FAKE/gone exists, on
battery while $FAKE/battery does, until the first piece starts. Pieces run at their place's pace
on a clock that moves only while every place runs one: an idle place stops it (`idle`).
"""

from collections import Counter
import io
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_suite_helper as fixture
from test_suite_on_both import Turn
from agentkit import gate, helper, worker

SSH = fixture.FAKE_SSH.replace("probe)", 'probe) [ -e "$here/gone" ] && exit 255\n'
                               '  [ -e "$here/battery" ] && exit 251\n'
                               "  printf 'cpus 2\\nload 0\\nroom_mb 65536\\n' ;;\nnever)")
PACE = {"helper": 1, "here": 3}    # the helper is three times faster


class Clock:
    def __init__(self, places, total):
        self.now, self.places, self.ends, self.idle, self.left = 0, places, [], 0, total
        self.cond = threading.Condition()

    def run(self, place):
        with self.cond:
            self.ends.append(end := self.now + PACE[place])
            while self.now < end:
                due = min(self.ends) > self.now    # none due waits to leave
                if due and len(self.ends) >= min(self.places(), self.left):
                    self.now = min(self.ends)
                    self.cond.notify_all()
                elif not self.cond.wait(30) and due:
                    self.idle += 1    # a place stayed idle while a piece waited
                    self.now = min(self.ends)
            self.ends.remove(end)
            self.left -= 1
            self.cond.notify_all()


class PiecesGoToWhoeverIsFree(unittest.TestCase):
    def turn(self, *_args, **_kw):
        return Turn(1)

    def setUp(self):
        fixture.SuiteHelper.setUp(self)
        (self.fake / "ssh").write_text(SSH)
        self.stack.enter_context(patch.object(gate, "GATE_POLL", 0.05))

    def suite(self, total, drop=False):
        """Where each piece ran, once each, and the log; `drop`: the helper goes in its second."""
        ran, logs, gone, battery = [], [], self.fake / "gone", self.fake / "battery"
        clock = self.clock = Clock(lambda: 1 + (not gone.exists() and not battery.exists()), total)

        def piece(place, _argv, _limit, *, env, **_kw):
            battery.unlink(missing_ok=True)
            if place == "helper" and (gone.exists() or drop and len(ran) == 1):
                gone.touch()
                with clock.cond:
                    clock.cond.notify_all()
                return helper.LOST, "", False
            clock.run(place)
            ran.append((place, env["AK_SHARD"]))
            return 0, "", False

        with patch.object(worker, "limited", side_effect=lambda *a, **kw: piece("helper", *a, **kw)), \
                patch.object(worker, "boxed", side_effect=lambda *a, **kw: piece("here", *a, **kw)):
            code, text, killed = gate.run_suite(fixture.SUITE, 30, cwd=self.repo,
                                                activity=self.root / "live.log",
                                                output=io.BytesIO(), log=logs.append)
        self.assertEqual((code, killed, clock.idle), (0, False, 0), text)
        self.assertEqual(sorted(shard for _, shard in ran),
                         [f"{k}/{total}" for k in range(1, total + 1)])
        return Counter(place for place, _ in ran), logs

    def test_a_helper_three_times_faster_takes_three_times_the_pieces_and_none_idles(self):
        self.assertEqual(self.suite(4)[0], {"helper": 3, "here": 1})
        self.assertEqual(self.clock.now, 3)    # each place ran to the end with no piece waiting

    def test_what_a_helper_that_drops_left_runs_here(self):
        places, logs = self.suite(4, drop=True)
        self.assertEqual(places, {"helper": 1, "here": 3})
        self.assertIn("the suite helper lost AK_SHARD=3/4; it runs here", logs)

    def test_an_absent_helper_leaves_the_whole_suite_here(self):
        (self.fake / "gone").touch()
        self.assertEqual(self.suite(2)[0], {"here": 2})

    def test_a_helper_on_battery_at_the_start_takes_what_waits_once_on_power(self):
        (self.fake / "battery").touch()
        places, logs = self.suite(2)
        self.assertEqual(places, {"helper": 1, "here": 1})
        self.assertIn("suite on acme-mac: 1 pieces, 2 CPUs and 820 MiB each", logs)


if __name__ == "__main__":
    unittest.main()
