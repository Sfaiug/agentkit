"""A run whose provider window runs out mid-run waits `exhausted`, and the tick resumes it.

A spent usage window is no failure of the work: the run stops where it was, `exhausted`, with
its checkout and round, and it still reads `working`, since ak moves it on without the owner.
Each tick checks it against the usage it has read: once the window it ran dry on has refilled,
the tick resumes it on the same checkout and round with the same executor, saying `resumed
<id>: <provider> window refilled`; once another marked worker has room instead, it hands the
run to that one; while none has, it leaves the run waiting.  A run that a later merged run of
the same task replaced is settled, marked `replaced`, and never resumed.  Without this every
quota hit is a dead run the owner relaunches by hand.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, with harnesses from fakeadapter.py whose
meters the test sets, on the bare origin of gitrig.py and the GitHub of fakegh.py.
"""

from datetime import datetime, timezone
import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# The tick asks the public boards and fetches the checkout it runs from: a test reaches neither.
OFFLINE = {"https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
           "GIT_ALLOW_PROTOCOL": "file"}
WEEK = 604800
SPENT = "You have hit your usage limit."
WAITING = ("exhausted", "queued", "running")
TITLES = ("Add retry file", "Add notes file")


def record(run_dir):
    try:
        return json.loads((run_dir / "run.json").read_text())
    except (OSError, ValueError):
        return {}


def wait_for(test, what, bound=120):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}")
        time.sleep(0.1)


def staged(case, workers, **turns):
    """A Home where opus (anthropic) and astra (openai) each have most of a week left, and
    `workers` are the models marked to build."""
    case.home = home = Home()
    case.addClassCleanup(home.close)
    home.env.update(OFFLINE)
    case.rig = Rig(home, "widgets")
    akconfig.write(home, ["opus", "astra"], workers=workers)
    case.fakes = fakeadapter.install(home, **turns)
    week = {"name": "weekly", "used": 10, "resets_at": int(time.time()) + 86400,
            "window_secs": WEEK}
    for fake in case.fakes.values():
        fake.answer("usage", json.dumps({"meters": [week], "error": None}))
    return home


def tick(home):
    done = home.ak("watch")
    assert done.code == 0, done.out + done.err
    return done.out


def row(home, title, *only):
    """The row of `ak run status` that shows the run of that title."""
    out = home.ak("run", "status", *only).out
    rows = [line for line in out.splitlines() if title in line]
    assert len(rows) == 1, out
    return rows[0]


def workspaces(fake, role="executor"):
    return [run["argv"][2] for run in fake.runs() if run["role"] == role]


class WindowRefills(unittest.TestCase):
    """opus alone builds; its turn is refused with a moment to try again at."""

    @classmethod
    def setUpClass(cls):
        # The moment comes from the harness's own words and ak reads it against the real
        # clock, so the test waits it out: just long enough for the run to have reached it.
        cls.back = time.time() + 10
        at = datetime.fromtimestamp(cls.back, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        refused = {"final": f"{SPENT} Try again at {at}.", "exit": 1}
        home = staged(cls, ["opus"], claude=[refused, "work"], codex="pass")
        cls.ran = home.ak("run", str(taskfile.write(home, cls.rig.path)), "--no-merge")
        cls.run_dir = taskfile.only_run(home)
        cls.dry = record(cls.run_dir)
        cls.row = row(home, cls.dry["title"])
        wait_for(lambda: time.time() > cls.back + 1, "reached the moment named", bound=60)
        cls.out = tick(home)
        wait_for(lambda: record(cls.run_dir).get("state") not in WAITING, "ended the resumed run")
        cls.state = record(cls.run_dir)

    def test_a_spent_window_mid_run_leaves_it_exhausted_not_failed(self):
        self.assertEqual(self.ran.code, 1, self.ran.out + self.ran.err)
        self.assertEqual(self.dry["state"], "exhausted")
        self.assertEqual(self.dry["executor"], "opus")
        self.assertTrue(Path(self.dry["worktree"]).is_dir())

    def test_it_reads_working_while_it_waits(self):
        self.assertIn("● working", self.row)

    def test_once_the_window_refills_the_tick_resumes_it(self):
        self.assertIn(f"resumed {self.run_dir.name}: anthropic window refilled",
                      self.out.splitlines())
        self.assertEqual(self.state["state"], "pass")

    def test_it_goes_on_in_the_same_checkout_and_round_with_the_same_executor(self):
        self.assertEqual(self.state["worktree"], self.dry["worktree"])
        self.assertEqual([each["round"] for each in self.state["round_summaries"]], [1])
        self.assertEqual(self.state["executor"], "opus")
        self.assertNotIn("executor_history", self.state)
        self.assertEqual(workspaces(self.fakes["claude"]), [self.dry["worktree"]] * 2)


class AnotherWorker(unittest.TestCase):
    """Two runs with opus alone marked to build, both refused; then the owner marks astra
    too, and a later run of the second's task merges."""

    @classmethod
    def setUpClass(cls):
        home = staged(cls, ["opus"], claude="dead", codex="work")
        cls.ran = [home.ak("run", str(taskfile.write(home, cls.rig.path, title)), "--no-merge")
                   for title in TITLES]
        cls.handed, cls.replaced = sorted(taskfile.runs(home),
                                          key=lambda run: record(run)["started_at"])
        cls.idle = tick(home)
        cls.before = [record(run) for run in (cls.handed, cls.replaced)]
        cls.rows = [row(home, title) for title in TITLES]
        akconfig.write(home, ["opus", "astra"])
        GitHub(home).grant(cls.rig.slug, "WRITE")
        cls.later = home.ak("run", str(taskfile.write(home, cls.rig.path, TITLES[1])),
                            timeout=300)
        cls.out = tick(home)
        wait_for(lambda: record(cls.handed).get("state") not in WAITING, "ended the handover")
        cls.after = [record(run) for run in (cls.handed, cls.replaced)]
        cls.settled = row(home, TITLES[1], cls.replaced.name)

    def test_while_no_marked_worker_has_room_the_tick_leaves_them_waiting(self):
        self.assertEqual([done.code for done in self.ran], [1, 1], self.ran)
        self.assertEqual([state["state"] for state in self.before], ["exhausted"] * 2)
        self.assertNotIn("resumed", self.idle)
        for line in self.rows:
            self.assertIn("● working", line)

    def test_once_another_worker_has_room_the_tick_hands_the_run_to_it(self):
        self.assertIn(f"resumed {self.handed.name}: openai window refilled",
                      self.out.splitlines())
        handed = self.after[0]
        self.assertEqual((handed["state"], handed["executor"]), ("pass", "astra"))
        self.assertEqual([(each["from"], each["to"], each["reason"])
                          for each in handed["executor_history"]], [("opus", "astra", "dry")])
        self.assertEqual(handed["worktree"], self.before[0]["worktree"])
        self.assertIn(handed["worktree"], workspaces(self.fakes["codex"]))

    def test_a_run_a_later_merged_run_replaced_is_settled_and_never_resumed(self):
        self.assertEqual(self.later.code, 0, self.later.out + self.later.err)
        replaced = self.after[1]
        self.assertTrue(replaced["replaced"])
        self.assertEqual(replaced["state"], "exhausted")
        self.assertNotIn(f"resumed {self.replaced.name}", self.out)
        self.assertNotIn(replaced["worktree"], workspaces(self.fakes["codex"]))
        self.assertIn("✓ done", self.settled)


if __name__ == "__main__":
    unittest.main()
