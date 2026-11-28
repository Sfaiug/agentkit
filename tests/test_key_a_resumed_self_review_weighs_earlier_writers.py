"""A resumed saved self-review steps aside beside every model that built before it.

When a handover in a shortage leaves the new builder reviewing its own work and the run is
interrupted and resumed once other labs have usage again:

- before the saved builder has answered, the replacement pair weighs the earlier builder's lab
  too, so an independent reviewer reviews an independent builder rather than a reviewer of the
  earlier builder's lab reviewing the first builder in the draw;
- once the saved builder has answered, the builder stays and the replacement reviewer still
  avoids the earlier builder's lab.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py.
"""

import json
import os
import signal
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig
from test_key_a_replacement_builder_keeps_an_independent_reviewer import FIX
from test_key_a_review_waits_for_another_provider import refused
from test_key_reviewer_other_provider_first import meters
from test_key_writer_reviews_only_without_room import OFFLINE, record, roles

# nova and seat share claude's lab; bolt (codex), reef (muse) and vale (opencode/vale) are each
# another lab with no lineup stored.
MODELS = {
    "nova": {"harness": "claude", "model": "claude-nova-2"},
    "seat": {"harness": "claude", "model": "claude-seat-1"},
    "bolt": {"harness": "codex", "model": "bolt-3"},
    "reef": {"harness": "muse", "model": "reef-1"},
    "vale": {"harness": "opencode", "provider": "vale", "model": "vale-1"},
}
# Executors draw bolt, reef, nova, vale; reviewers draw seat, bolt, vale (`usage.pick_order`).
DRAW = "20261128-1042"


# A commit that leaves retry.txt intact so round 2 ends on the earlier finding cleanly.
WIP = {"write": {"note.txt": "wip\n"}, "commit": "wip",
       "final": "## Summary\nwip", "hand_in": [["done"]]}


def wait_for(marker, proc, home, timeout=120):
    deadline = time.monotonic() + timeout
    while not marker.exists():
        if proc.poll() is not None or time.monotonic() > deadline:
            raise AssertionError("the run never reached its interrupt point: "
                                 + home.log("spawn-1.err").read_text())
        time.sleep(0.1)


def stage(case, *, answered):
    """Run round 1 on nova/vale (FAIL), round 2 handed from nova to vale/vale (FAIL), interrupt
    round 3 before or after vale answers, refill every provider, and resume."""
    home = Home()
    case.addClassCleanup(home.close)
    home.env.update(OFFLINE)
    rig = Rig(home, "widgets")
    akconfig.write(home, MODELS, workers=["bolt", "reef", "vale", "nova"],
                   reviewers=["seat", "bolt", "vale"])
    if answered:
        # `done-when` runs in a box whose /var/tmp is a tmpfs, while the repository's `.git`
        # common dir and worktree are bound: use `.git` for the gate and marker so nothing
        # dirties the worktree.  Ending without `ak hand-in done` writes final.md first, then
        # the loop runs done-when before review_pending is written.
        marker = rig.path / ".git" / "ak-interrupt"
        gate = rig.path / ".git" / "ak-gate"
        gate.touch()
        done_when = (f"test ! -f fixed.txt || test ! -f {gate} || {{ touch {marker}; sleep 60; }}",)
        fix = {**FIX, "write": {"fixed.txt": "1\n"}, "hand_in": ()}
        # r1 review fail -> r2 fix (WIP) -> r2 review fail -> r3 fix answers, then blocks in check
        opencode = ["fail", WIP, "fail", fix, "pass"]
    else:
        marker = home.root / "adapters" / "interrupt"
        done_when = ("true",)
        # r1 review fail -> r2 fix (WIP) -> r2 review fail -> r3 fix interrupted before answering
        opencode = ["fail", WIP, "fail", {"sh": f"touch {marker}; sleep 60"}, "pass"]
    fakes = fakeadapter.install(home, claude=["work", refused(3600)], codex="pass",
                                muse=FIX, opencode=opencode)
    fakes["claude"].answer("usage", json.dumps(meters(10, "weekly")))
    fakes["opencode"].answer("usage", json.dumps(meters(10, "weekly")))
    fakes["codex"].answer("usage", json.dumps(meters(100, "weekly")))
    fakes["muse"].answer("usage", json.dumps(meters(100, "weekly")))
    env = {"AK_PICK_DRAW": DRAW}
    task = taskfile.write(home, rig.path, done_when=done_when)
    proc = home.spawn("run", str(task), "--no-merge", env=env)
    wait_for(marker, proc, home)
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()
    if answered:
        gate.unlink()
        marker.unlink()
    cache = home.path / ".agentkit" / "state" / "usage.json"
    if cache.exists():
        cache.unlink()
    for fake in fakes.values():
        fake.answer("usage", json.dumps(meters(10, "weekly")))
    fakes["claude"].behave("pass")
    fakes["opencode"].behave("pass")
    run_dir = taskfile.only_run(home)
    done = home.ak("run", "resume", run_dir.name, env=env, timeout=300)
    return fakes, done, record(run_dir)


class UnansweredSavedSelfReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fakes, cls.done, cls.state = stage(cls, answered=False)

    def test_hands_to_reef_with_bolt_reviewing(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual([(move["from"], move["to"]) for move in self.state["executor_history"]],
                         [("nova", "vale"), ("vale", "reef")])
        self.assertEqual((self.state["executor"], self.state["review"]["reviewer"]),
                         ("reef", "bolt"))
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "fixer"])
        self.assertEqual(roles(self.fakes["muse"]), ["fixer"])
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"])


class AnsweredSavedSelfReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fakes, cls.done, cls.state = stage(cls, answered=True)

    def test_keeps_vale_and_picks_bolt_to_review(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual([(move["from"], move["to"]) for move in self.state["executor_history"]],
                         [("nova", "vale")])
        self.assertEqual((self.state["executor"], self.state["review"]["reviewer"]),
                         ("vale", "bolt"))
        self.assertEqual((self.state["state"], self.state["verdict"]), ("pass", "PASS"))
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "fixer"])
        self.assertEqual(roles(self.fakes["muse"]), [])
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"])


if __name__ == "__main__":
    unittest.main()
