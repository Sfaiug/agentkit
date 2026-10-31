"""The writer reviews its own work only while no other marked reviewer has room.

A run launched while every other reviewer was spent starts with its writer as its reviewer.
Before each review -- a round's, or a landing fix's re-review on a resume after a passed
review -- the writer gives way to a marked reviewer that is not the writer and has room now,
on a fresh session.  With none, the writer reviews, as at launch.  A reviewer that is not the
writer is never swapped, even for one ranked higher that regained room.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, with harnesses from
fakeadapter.py whose meters the test sets, on the bare origin of gitrig.py and the GitHub of
fakegh.py.  A shortage ends as a meter does: its window resets.
"""

import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home, _strays
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# ak asks the public boards and fetches the checkout it runs from: a test reaches neither.
OFFLINE = {"https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
           "GIT_ALLOW_PROTOCOL": "file"}
WEEK, HOURS = 604800, 18000
# long enough for a launch to pick while the shortage lasts
SHORTAGE = 30


def meter(used, resets_at, window=WEEK):
    return {"name": "weekly" if window == WEEK else "5h", "used": used,
            "resets_at": int(resets_at), "window_secs": window}


def staged(case, models, reviewers, meters, files=None, **turns):
    """A Home where opus alone builds and `reviewers` review, each harness's meters as given."""
    case.home = home = Home()
    case.addClassCleanup(home.close)
    home.env.update(OFFLINE)
    case.rig = Rig(home, "widgets", **({"files": files} if files else {}))
    akconfig.write(home, models, workers=["opus"], reviewers=reviewers)
    case.fakes = fakeadapter.install(home, **turns)
    for harness, readings in meters.items():
        case.fakes[harness].answer("usage", json.dumps({"meters": readings, "error": None}))
    return home


def until(moment):
    """A turn's `sh` that returns once the shortage is over."""
    return f"until [ $(date +%s) -gt {int(moment)} ]; do sleep 0.2; done"


def until_true(test, bound=120):
    deadline = time.monotonic() + bound
    while not test():
        assert time.monotonic() < deadline, "never came"
        time.sleep(0.1)


def running(home, command):
    """Whether one of the Home's processes runs `command`, as a check runs: `bash -c`."""
    for pid in _strays(home.path):
        try:
            if command.encode() in Path(f"/proc/{pid}/cmdline").read_bytes():
                return True
        except OSError:      # ended meanwhile
            pass
    return False


def record(run_dir):
    try:
        return json.loads((run_dir / "run.json").read_text())
    except (OSError, ValueError):
        return {}


def roles(fake):
    return [run["role"] for run in fake.runs()]


def launched(done):
    """The pair the run picked at launch, as its log names it."""
    line = next(line for line in done.out.splitlines() if " executor=" in line)
    return tuple(word.split("=")[1] for word in line.split()
                 if word.startswith(("executor=", "reviewer=")))


class ShortageEndsBeforeReview(unittest.TestCase):
    """astra is spent at launch, so opus is to review its own work; astra's window resets
    while opus builds."""

    @classmethod
    def setUpClass(cls):
        over = time.time() + SHORTAGE
        home = staged(cls, ["opus", "astra"], ["opus", "astra"],
                      {"codex": [meter(100, over, HOURS), meter(10, time.time() + 86400)]},
                      claude={**fakeadapter.WORK, "sh": until(over)}, codex="pass")
        cls.done = home.ak("run", str(taskfile.write(home, cls.rig.path)), "--no-merge",
                           timeout=300)
        cls.run_dir = taskfile.only_run(home)
        cls.state = record(cls.run_dir)

    def test_it_launched_self_reviewed(self):
        self.assertEqual(launched(self.done), ("opus", "opus"))

    def test_the_reviewer_with_room_reviews_it(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(roles(self.fakes["claude"]), ["executor"])
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"])
        self.assertEqual((self.state["reviewer"], self.state["review"]["reviewer"]),
                         ("astra", "astra"))
        self.assertEqual(self.state["verdict"], "PASS")


class ResumeAfterPassedReview(unittest.TestCase):
    """opus reviews its own work while astra is spent, and it passes; the run is cut off in
    its landing suite.  Resumed once astra's window reset, the suite is red, and the fix's
    re-review is astra's."""

    @classmethod
    def setUpClass(cls):
        over = time.time() + SHORTAGE
        # the landing suite holds the work until the run is cut off, then judges it: a check
        # reads HOME as it was when its box was built
        suite = ("if [ -f $HOME/cut ]; then test ! -f bad.txt; "
                 "else until [ -f $HOME/cut ]; do sleep 0.1; done; false; fi")
        work = {**fakeadapter.WORK, "write": {"retry.txt": "hello\n", "bad.txt": "stale\n"}}
        fix = {"sh": "git rm -q bad.txt", "commit": "remove bad.txt",
               "final": "## Summary\nremoved bad.txt", "hand_in": [["done"]]}
        home = staged(cls, ["opus", "astra"], ["opus", "astra"],
                      {"codex": [meter(100, over, HOURS), meter(10, time.time() + 86400)]},
                      files={"AGENTS.md": f"---\ntests: {suite}\n---\n# widgets\n"},
                      claude=[work, "pass", fix], codex="pass")
        GitHub(home).grant(cls.rig.slug, "WRITE")
        first = threading.Thread(target=home.ak, args=(
            "run", str(taskfile.write(home, cls.rig.path))), kwargs={"timeout": 300})
        first.start()
        until_true(lambda: running(home, suite))
        cls.run_dir = taskfile.only_run(home)
        cls.landing = record(cls.run_dir)
        # cut off as a restart cuts a run off: every process the Home runs ends at once, one
        # that ended since the scan found it and one started before its parent was killed too
        while strays := _strays(home.path):
            for pid in strays:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        first.join()
        home.write("cut", "")
        until_true(lambda: time.time() > over + 1)
        cls.resumed = home.ak("run", "resume", cls.run_dir.name, timeout=300)
        cls.state = record(cls.run_dir)

    def test_the_writer_reviewed_it_and_it_passed_before_the_cut(self):
        self.assertEqual(self.landing["round_summaries"][-1]["verdict"], "PASS")
        self.assertEqual(self.landing["review"]["reviewer"], "opus")

    def test_the_landing_fix_is_re_reviewed_by_the_reviewer_with_room(self):
        self.assertEqual(self.resumed.code, 0, self.resumed.out + self.resumed.err)
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer", "fixer"])
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"])
        self.assertEqual((self.state["reviewer"], self.state["review"]["reviewer"]),
                         ("astra", "astra"))
        self.assertEqual((self.state["state"], self.state.get("merged")), ("pass", True))


class NoOtherReviewerHasRoom(unittest.TestCase):
    """astra stays spent: opus reviews its own work."""

    @classmethod
    def setUpClass(cls):
        home = staged(cls, ["opus", "astra"], ["opus", "astra"],
                      {"codex": [meter(100, time.time() + 86400)]}, claude="work", codex="pass")
        cls.done = home.ak("run", str(taskfile.write(home, cls.rig.path)), "--no-merge",
                           timeout=300)
        cls.state = record(taskfile.only_run(home))

    def test_the_writer_reviews(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(roles(self.fakes["claude"]), ["executor", "reviewer"])
        self.assertEqual(self.fakes["codex"].runs(), [])
        self.assertEqual(self.state["review"]["reviewer"], "opus")


class CrossPairIsKept(unittest.TestCase):
    """opus builds and astra reviews, picked while mimo was spent; mimo's window resets, with
    its whole week left, while opus builds."""

    @classmethod
    def setUpClass(cls):
        over = time.time() + SHORTAGE
        week = time.time() + 86400
        home = staged(cls, ["opus", "astra", "mimo"], ["astra", "mimo"],
                      {"codex": [meter(60, week)],
                       "opencode": [meter(100, over, HOURS), meter(0, week)]},
                      claude={**fakeadapter.WORK, "sh": until(over)}, codex="pass",
                      opencode="pass")
        cls.done = home.ak("run", str(taskfile.write(home, cls.rig.path)), "--no-merge",
                           timeout=300)
        cls.run_dir = taskfile.only_run(home)
        cls.state = record(cls.run_dir)

    def test_the_reviewer_picked_at_launch_reviews(self):
        self.assertEqual(self.done.code, 0, self.done.out + self.done.err)
        self.assertEqual(launched(self.done), ("opus", "astra"))
        self.assertEqual(roles(self.fakes["codex"]), ["reviewer"])
        self.assertEqual(self.fakes["opencode"].runs(), [])
        self.assertEqual(self.state["review"]["reviewer"], "astra")


if __name__ == "__main__":
    unittest.main()
