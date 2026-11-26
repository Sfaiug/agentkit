"""A run that took no review is not landed as looks alone.

A target that declares `health:` and `deployed:` and has a time record of its suite lets a change
of looks alone land on its quick checks
(tests/test_key_a_change_of_looks_alone_lands_on_its_quick_checks.py) only when a reviewer gave
its PASS.  A run whose recorded review says `no_review` -- because its change touched only paths
the target marks `ak-checks-only`, or because review is off -- ran none of the tests a reviewer's
PASS runs, so it waits on a busy host and lands through the whole suite, its merge carrying no
`Looks-Alone-Tree` trailer (`Suite-Passed-Tree: <tree>`).  A verdict of looks alone an older lander
saved for such a run never lands it: its resume, or a retry of its failed delivery, runs the
installed ak, never the older one the run is pinned to, and rejoins the line with no verdict.  The
same change on a target without the mark, reviewed, lands as looks alone with no whole run and
`Looks-Alone-Tree: <tree>`.

Black-box, on the fixtures of tests/test_key_a_change_of_looks_alone_lands_on_its_quick_checks.py:
the program `AK_BIN` names, through tests/fixtures/akline.py, fakeadapter.py and fakegh.py's
GitHub, with injected host readings (AK_HOST_READINGS).
"""

import fcntl
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.fakegh import GitHub
import test_key_a_change_of_looks_alone_lands_on_its_quick_checks as quick


class ARunWithoutReviewIsNotLandedAsLooksAlone(unittest.TestCase):
    line, join, land, checked = (vars(quick.AChangeOfLooksAloneLandsOnItsQuickChecks)[name]
                                 for name in ("line", "join", "land", "checked"))

    def task(self, line, settings=None):
        """The restyle's task, its run worked and reviewed by scripted harnesses."""
        home = line.home
        GitHub(home).grant(line.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"],
                       settings=settings)
        self.fakes = fakeadapter.install(home, claude={**fakeadapter.WORK, "write": quick.STYLE,
                                                       "commit": "restyle"}, codex="pass")
        return str(taskfile.write(home, line.rig.path, "Restyle the site",
                                  done_when=("test -f site.css",)))

    def deliver(self, line, readings, *, settings=None):
        home = line.home
        home.env["AK_HOST_READINGS"] = json.dumps(readings)
        done = home.ak("run", self.task(line, settings), timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run_dir, = (path for path in taskfile.runs(home) if path.name.endswith("-restyle-the-site"))
        self.assertTrue(quick.record(run_dir).get("merged"), quick.record(run_dir))
        tree = line.rig.origin("rev-parse", "main^{tree}")
        return (self.fakes["codex"].n, tree,
                line.rig.origin("log", "-1", "--format=%B", "main").rstrip())

    def settled(self, run_dir, done, gone=()):
        """The run's record once `done` holds of what it waits on and no process of its own is
        left, while none of `gone` is there."""
        deadline = time.monotonic() + 300
        while not (done((state := quick.record(run_dir)).get("waiting_on") or {})
                   and not state.get("pid")):
            self.assertFalse([path for path in gone if path.exists()], state)
            self.assertLess(time.monotonic(), deadline, state)
            time.sleep(0.2)
        return state

    def test_marked_stylesheets_land_through_the_whole_suite(self):
        line = self.line(**{".gitattributes": "*.css ak-checks-only\n"})
        reviews, tree, message = self.deliver(line, quick.IDLE)
        self.assertEqual(reviews, 0)
        self.assertEqual(line.whole(), 1, line.runs())
        self.assertTrue(message.endswith(f"\n\nSuite-Passed-Tree: {tree}"), message)
        self.assertNotIn("Looks-Alone-Tree", message)

    def test_review_off_stylesheet_lands_through_the_whole_suite(self):
        line = self.line()
        reviews, tree, message = self.deliver(line, quick.IDLE, settings={"review_rounds": 0})
        self.assertEqual(reviews, 0)
        self.assertEqual(line.whole(), 1, line.runs())
        self.assertTrue(message.endswith(f"\n\nSuite-Passed-Tree: {tree}"), message)
        self.assertNotIn("Looks-Alone-Tree", message)

    def test_an_unreviewed_stylesheet_waits_on_a_busy_host_while_a_reviewed_one_lands(self):
        line = self.line()
        self.join(line, quick.STYLE)
        state = quick.record(line.members[0])
        state["review"]["no_review"] = True
        (line.members[0] / "run.json").write_text(json.dumps(state))
        self.join(line, quick.STYLE)
        self.land(line, quick.BUSY)
        self.assertEqual(self.checked(line), (0, [False, True]), line.runs())

    def test_an_older_landers_verdict_of_looks_alone_is_delivered_by_the_installed_ak(self):
        # a resume, and a retry of a delivery that failed, of a run pinned to the older ak
        for command, ended in (("resume", {}), ("merge", {"state": "pass", "merge_failed": True})):
            with self.subTest(command):
                self.rejoins_under_the_installed_ak(command, ended)

    def rejoins_under_the_installed_ak(self, command, ended):
        line = self.line()
        done = line.home.ak("run", "--bg", self.task(line, {"review_rounds": 0}))
        self.assertEqual(done.code, 0, done.out + done.err)
        run_dir, = taskfile.runs(line.home)
        # on the busy host the line holds its suite, and the run parks with no verdict
        state = self.settled(run_dir, lambda wait: "line" in wait)
        self.assertTrue(state["review"].get("no_review"), state)
        older = line.home.root / "older-ak"
        (older / "bin").mkdir(parents=True)
        (older / "bin" / "ak").write_text(
            "import pathlib\npathlib.Path(__file__).with_name('ran').touch()\n")
        turn = run_dir.parent / state["waiting_on"]["line"]
        with turn.with_suffix(".lander.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)    # no lander pass reads the line meanwhile
            # the verdict an older lander gave such a run, under the ak it ran then
            state["waiting_on"].update(land=state["review"]["tree_sha"], looks=True, after={})
            state.update(ak_checkout=str(older), **ended)
            (run_dir / "run.json").write_text(json.dumps(state))
            # it follows the run, which waits on the lander: the Home ends it
            line.home.spawn("run", command, run_dir.name,
                            env={"AK_HOST_READINGS": json.dumps(quick.IDLE)})
            wait = self.settled(run_dir, lambda wait: "land" not in wait,
                                gone=[older / "bin" / "ran"]).get("waiting_on")
        self.assertEqual(wait, {key: state["waiting_on"][key] for key in ("line", "joined")})

    def test_without_the_mark_a_reviewed_stylesheet_lands_as_looks_alone(self):
        line = self.line()
        reviews, tree, message = self.deliver(line, quick.BUSY)
        self.assertEqual(reviews, 1)
        self.assertEqual(line.whole(), 0, line.runs())
        self.assertTrue(message.endswith(f"\n\nLooks-Alone-Tree: {tree}"), message)


if __name__ == "__main__":
    unittest.main()
