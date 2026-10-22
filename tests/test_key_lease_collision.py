"""Two live runs of one repository that change the same lines: the younger waits on the older.

A run's claim is its own diff, uncommitted edits included, and nobody declares one.  When a
tick finds two live runs to land whose changes cannot merge, the younger, still before its
review, is stopped there with its branch and checkout kept, waiting on the older: `ak run
status` names the wait, and the seat still reads `working`.  Once the older has landed or is
over, the tick starts the younger's task again as a new run of the same seat, on the newest
base; a stop of the waiting run calls that off.  A younger run already past its review is only
written down, for the lander to order.  Without this two seats build conflicting work and one
fails at landing.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, on the bare origin of gitrig.py and the GitHub of fakegh.py, beside a
seat of akseat.py; each executor is a fakeadapter.py turn that edits line 5 of api.py and holds
there until the test lets it go.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

# The tick asks the public boards and fetches the checkout it runs from: a test reaches neither.
OFFLINE = {"https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
           "GIT_ALLOW_PROTOCOL": "file"}
API = "".join(f"line {n}\n" for n in range(1, 31))
TITLES = ("Change line five", "Reword line five", "Shorten line five")
GOING = ("queued", "running")


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


class Stage:
    """A Home whose widgets has a 30-line api.py, opus building and astra reviewing, a seat
    `acme` there unless `seat` is false, and the runs the test launched, oldest first."""

    @classmethod
    def stage(cls, claude, codex="pass", seat=True):
        """`claude` and `codex` script each harness's turns from the folder they mark in."""
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        home.env.update(OFFLINE)
        # a collection on record from just now: a due one would sweep the host's /tmp
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        cls.rig = Rig(home, "widgets", files={"api.py": API})
        GitHub(home).grant(cls.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        cls.marks = marks = home.root / "adapters"      # where fakeadapter.py keeps its files
        cls.fakes = fakeadapter.install(home, claude=claude(marks),
                                        codex=codex(marks) if callable(codex) else codex)
        if seat:
            Seat(home, "acme", cwd=cls.rig.path, record={"workers": ["opus", "astra"]})
        cls.env = {"AGENTKIT_SESSION": "acme"} if seat else {}
        cls.runs, cls.loops = [], {}

    @classmethod
    def launch(cls, title, mark):
        """Start a run of that task and wait for its turn to reach `mark`."""
        task = taskfile.write(cls.home, cls.rig.path, title, done_when=("true",))
        loop = cls.home.spawn("run", str(task), env=cls.env)
        wait_for(lambda: (cls.marks / mark).exists() or loop.poll() is not None, f"{mark}")
        assert loop.poll() is None, f"{title} ended before {mark}"
        cls.runs.append(next(run for run in taskfile.runs(cls.home) if run not in cls.runs))
        cls.loops[cls.runs[-1]] = loop
        return cls.runs[-1]

    @classmethod
    def tick(cls):
        done = cls.home.ak("watch")
        assert done.code == 0, done.out + done.err
        return done.out

    @classmethod
    def waits(cls):
        """The collisions ak has written down for the repository."""
        found = list((cls.home.path / ".agentkit/state/leases").glob("*.json"))
        assert len(found) == 1, found
        return json.loads(found[0].read_text())

    @classmethod
    def again(cls):
        """The one run started since the runs this test launched, once it has ended."""
        new = [run for run in taskfile.runs(cls.home) if run not in cls.runs]
        assert len(new) == 1, [run.name for run in new]
        wait_for(lambda: record(new[0]).get("state") not in (None, *GOING), "ended")
        return new[0]


def held(marks, name, text):
    """An executor turn that writes `text` on line 5, uncommitted, and holds until let go."""
    return {"sh": f"sed -i '5s/.*/{text}/' api.py; touch '{marks}/{name}.held'; "
                  f"while [ -d '{marks}' ] && [ ! -e '{marks}/{name}.go' ]; do sleep 0.1; done",
            "commit": f"{text} line 5", "final": "Done.", "hand_in": [["done"]]}


def seen(marks, name):
    """An executor turn that keeps line 5 as it finds it, then hands in blocked."""
    return {"sh": f"sed -n 5p api.py >'{marks}/{name}.seen'", "final": "Blocked.",
            "hand_in": [["blocked", "the fixture stops here"]]}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OlderLands(Stage, unittest.TestCase):
    """Two runs of the seat change line 5; once the younger waits, the older is let go."""

    @classmethod
    def setUpClass(cls):
        cls.stage(lambda marks: [held(marks, "older", "older"),
                                 held(marks, "younger", "younger"), seen(marks, "again")])
        cls.older = cls.launch(TITLES[0], "older.held")
        cls.younger = cls.launch(TITLES[1], "younger.held")
        cls.tick()
        cls.parked, cls.holding, cls.written = (record(cls.younger), record(cls.older),
                                                cls.waits())
        cls.left = (Path(cls.parked["worktree"]) / "api.py").read_text().splitlines()[4]
        cls.status = cls.home.ak("run", "status").out
        cls.why = cls.home.ak("orch", "why", "acme").out
        (cls.marks / "older.go").touch()
        wait_for(lambda: cls.loops[cls.older].poll() is not None, "landed the older")
        cls.main = cls.rig.head()
        cls.second = cls.tick()
        cls.restarted = cls.again()
        cls.cleared = cls.waits()

    def test_the_younger_run_is_stopped_before_its_review_with_its_branch_and_checkout_kept(self):
        self.assertEqual(self.parked["state"], "stopped")
        self.assertEqual(self.parked["lease_wait"]["on"], self.older.name)
        self.assertEqual(self.parked["lease_wait"]["files"], ["api.py"])
        self.assertEqual([run["role"] for run in self.fakes["codex"].runs()], ["reviewer"],
                         "only the older was reviewed")
        self.assertEqual(self.left, "younger")
        self.assertTrue(self.rig.git("rev-parse", "--verify", self.parked["branch"]))

    def test_the_older_run_goes_on_and_lands(self):
        self.assertEqual(self.holding["state"], "running")
        self.assertTrue(record(self.older)["merged"])
        self.assertEqual(self.rig.origin("show", "main:api.py").splitlines()[4], "older")

    def test_ak_run_status_names_the_wait_and_the_seat_still_reads_working(self):
        lines = self.status.splitlines()
        at = next(n for n, line in enumerate(lines) if TITLES[1] in line)
        self.assertIn("● working", lines[at])
        self.assertEqual(lines[at + 1].strip(),
                         f"stopped · waits on {self.older.name}: both change api.py")
        self.assertEqual(self.why.splitlines()[0], "acme  working")

    def test_the_collision_is_written_down_until_the_older_has_landed(self):
        self.assertEqual(set(self.written), {self.younger.name})
        wait = self.written[self.younger.name]
        self.assertEqual((wait["waits_on"], wait["files"]), (self.older.name, ["api.py"]))
        self.assertIsInstance(wait["since"], (int, float))
        self.assertEqual(self.cleared, {})

    def test_then_its_task_starts_again_as_a_new_run_of_the_seat_on_the_newest_base(self):
        again = record(self.restarted)
        self.assertEqual(again["restarted"], {"run": self.younger.name,
                                              "why": f"{self.older.name} has landed"})
        self.assertEqual(record(self.younger)["lease_restarted"], self.restarted.name)
        self.assertEqual((again["title"], again["launched_session"]), (TITLES[1], "acme"))
        self.assertEqual(again["base_sha"], self.main)
        self.assertEqual((self.marks / "again.seen").read_text(), "older\n")
        self.assertIn(f"{self.younger.name} started again as {self.restarted.name}: "
                      f"{self.older.name} has landed", self.second)
        self.assertTrue(self.rig.git("rev-parse", "--verify", self.parked["branch"]))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class WaitingRunStopped(Stage, unittest.TestCase):
    """Two younger runs wait on one older; the owner stops one of them, then the older."""

    @classmethod
    def setUpClass(cls):
        cls.stage(lambda marks: [*(held(marks, name, name) for name in ("one", "two", "three")),
                                 seen(marks, "again")])
        cls.older, cls.stopped, cls.waiting = (cls.launch(title, f"{name}.held") for title, name
                                               in zip(TITLES, ("one", "two", "three")))
        cls.tick()
        cls.stops = [cls.home.ak("run", "stop", run.name) for run in (cls.stopped, cls.older)]
        cls.out = cls.tick()
        cls.restarted = cls.again()

    def test_a_stop_of_a_waiting_run_calls_its_restart_off(self):
        self.assertEqual([done.code for done in self.stops], [0, 0], self.stops)
        state = record(self.stopped)
        self.assertEqual(state["state"], "stopped")
        self.assertNotIn("lease_wait", state)
        self.assertNotIn("lease_restarted", state)
        self.assertNotIn(f"{self.stopped.name} started again", self.out)

    def test_the_other_waiting_run_starts_again_once_the_older_is_over(self):
        self.assertEqual(record(self.restarted)["restarted"],
                         {"run": self.waiting.name, "why": f"{self.older.name} is over"})
        self.assertEqual(record(self.restarted)["title"], TITLES[2])


class PastItsReview(Stage, unittest.TestCase):
    """The younger has built and is under review when the older first writes the same line."""

    @classmethod
    def setUpClass(cls):
        def late(marks):
            turn = held(marks, "older", "older")
            turn["sh"] = (f"touch '{marks}/older.started'; while [ -d '{marks}' ] && "
                          f"[ ! -e '{marks}/older.write' ]; do sleep 0.1; done; " + turn["sh"])
            return [turn, {"sh": "sed -i '5s/.*/younger/' api.py", "commit": "younger line 5",
                           "final": "Done.", "hand_in": [["done"]]}]
        cls.stage(late, lambda marks: {
            "sh": f"touch '{marks}/review.held'; while [ -d '{marks}' ]; do sleep 0.1; done",
            "final": "Handed in.", "hand_in": [["done"]]}, seat=False)
        marks = cls.marks
        cls.older = cls.launch(TITLES[0], "older.started")
        cls.younger = cls.launch(TITLES[1], "review.held")
        (marks / "older.write").touch()
        wait_for(lambda: (marks / "older.held").exists(), "the older's edit")
        cls.out = cls.tick()
        cls.state, cls.written = record(cls.younger), cls.waits()
        for run in (cls.younger, cls.older):
            cls.addClassCleanup(cls.home.ak, "run", "stop", run.name)

    def test_a_younger_run_past_its_review_is_only_written_down(self):
        self.assertEqual(self.state["state"], "running")
        self.assertNotIn("lease_wait", self.state)
        wait = self.written[self.younger.name]
        self.assertEqual((wait["waits_on"], wait["files"]), (self.older.name, ["api.py"]))


if __name__ == "__main__":
    unittest.main()
