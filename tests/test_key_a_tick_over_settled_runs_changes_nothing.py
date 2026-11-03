"""A tick over a home whose runs are all settled leaves every run, seat and checkout as it was.

A live Claude seat at its prompt, its plan with nothing open, has a checkout of a repository its
GitHub account owns, with no pull request open, and five runs it launched with `ak run`, each
ended and handed back: one passed and merged, one failed with its rounds spent, one the owner
stopped, one ended not needed and one passed with `--no-merge`.  Over three ticks every tick
exits 0, every run's record and result.md stay byte for byte, nothing is typed into the seat, no
run, review or seat starts, GitHub is changed in nothing, and the checkout keeps its branches
and work tree.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, each tick in the box `home.tick()` builds, on a project from gitrig.py
with the GitHub of fakegh.py, the seat of akseat.py and harnesses of fakeadapter.py.
"""

import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig

SEAT = {"AGENTKIT_SESSION": "acme"}
# The words a fix run's task carries (a failed night's, a follow-up's): only such a run ends
# `not needed`, where its first turn finds the command passing already.
FIX = ("Your checkout starts on the target branch's tip, fetched when this run started: run "
       "the command below there first. If it passes there now, run `ak hand-in not-needed "
       '"<why>"`, with no edits or PR. Otherwise fix the root cause so it passes, and show it '
       "failing before the fix and passing afterwards in your summary. If only the owner can "
       'decide, run `ak hand-in blocked "<question>"`.')


def work(name):
    """An executor's or fixer's turn that commits `name`."""
    return {**fakeadapter.WORK, "write": {name: f"{name}\n"}, "commit": f"add {name}"}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class SettledRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(home, claude="work", codex="pass")
        cls.gh = GitHub(home)
        cls.rig = Rig(home, "app")
        cls.seat = Seat(home, "acme", cwd=cls.rig.path, record={"workers": ["opus", "astra"]})
        cls.seat_says("orch", "project", str(cls.rig.path))
        cls.seat_says("plan", "add", "the api file is in", "--check", "test -f api.txt")
        cls.launch("Add retry file", ["work"], ["fail"])
        cls.launch("Fix the docs", [{"final": "Not needed.",
                                     "hand_in": [["not-needed", "it passes already"]]}], ["pass"],
                   body=FIX + "\n")
        cls.launch("Add web file", [work("web.txt")], ["pass"], "--no-merge")
        cls.stopped()
        cls.launch("Add api file", [work("api.txt")], ["pass"])
        # the seat's plan, read, ticks its one line: the merge proved it
        cls.seat_says("plan")
        # the tick after a merge keeps its commit on the run's record, once: the home has had it
        cls.ticks = [home.tick()]
        cls.before = cls.world()
        cls.ticks += [home.tick() for _ in range(3)]
        cls.after = cls.world()

    @classmethod
    def seat_says(cls, *args):
        done = cls.home.ak(*args, env=SEAT, cwd=cls.rig.path)
        assert done.code == 0, done.out + done.err

    @classmethod
    def launch(cls, title, claude, codex, *args, body=""):
        """The seat runs a task in the foreground, its harnesses doing as scripted."""
        cls.fakes["claude"].behave(*claude)
        cls.fakes["codex"].behave(*codex)
        task = taskfile.write(cls.home, cls.rig.path, title, done_when=("true",), body=body)
        done = cls.home.ak("run", str(task), *args, env=SEAT, timeout=600)
        assert done.code in (0, 1), done.out + done.err

    @classmethod
    def stopped(cls):
        """A run the seat launched, which the owner stops while its first turn waits."""
        go = cls.home.root / "go"
        cls.fakes["claude"].behave({"sh": f"until [ -f {go} ]; do sleep 0.1; done",
                                    **work("held.txt")})
        before = cls.fakes["claude"].n
        task = taskfile.write(cls.home, cls.rig.path, "Hold it", done_when=("true",))
        running = cls.home.spawn("run", str(task), env=SEAT)
        deadline = time.monotonic() + 300
        while cls.fakes["claude"].n == before:
            assert time.monotonic() < deadline and running.poll() is None, "the turn never began"
            time.sleep(0.1)
        run = next(run for run in taskfile.runs(cls.home) if run.name.endswith("-hold-it"))
        done = cls.home.ak("run", "stop", run.name)
        assert done.code == 0, done.out + done.err
        go.touch()
        running.wait(timeout=300)

    @classmethod
    def world(cls):
        home, rig = cls.home, cls.rig
        return {
            "runs": {run.name: {name: (run / name).read_bytes()
                                for name in ("run.json", "result.md")}
                     for run in taskfile.runs(home)},
            "typed": cls.seat.typed(),
            "turns": {harness: fake.n for harness, fake in cls.fakes.items()},
            "seats": home.tmux("list-sessions", "-F", "#{session_name}").out.split(),
            "github": json.loads(cls.gh.file.read_text()),
            "branches": (rig.git("for-each-ref", "--format=%(refname) %(objectname)"),
                         rig.origin("for-each-ref", "--format=%(refname) %(objectname)")),
            "tree": (rig.git("rev-parse", "HEAD"), rig.git("status", "--porcelain", "-uall"),
                     rig.git("worktree", "list", "--porcelain")),
        }

    def test_every_tick_exits_0(self):
        for done in self.ticks:
            self.assertEqual(done.code, 0, done.out + done.err)

    def test_the_runs_are_the_five_endings(self):
        states = sorted((json.loads(files["run.json"])["state"], name.split("-", 2)[2])
                        for name, files in self.before["runs"].items())
        self.assertEqual(states, [("fail", "add-retry-file"), ("not_needed", "fix-the-docs"),
                                  ("pass", "add-api-file"), ("pass", "add-web-file"),
                                  ("stopped", "hold-it")])
        self.assertEqual(("api.txt" in self.rig.files(), "web.txt" in self.rig.files()),
                         (True, False))

    def test_every_run_s_record_and_result_stay_byte_for_byte(self):
        self.assertEqual(self.after["runs"], self.before["runs"])

    def test_nothing_is_typed_and_no_run_review_or_seat_starts(self):
        for part in ("typed", "turns", "seats"):
            self.assertEqual(self.after[part], self.before[part], part)

    def test_github_is_changed_in_nothing(self):
        self.assertEqual(self.after["github"], self.before["github"])

    def test_the_checkout_keeps_its_branches_and_work_tree(self):
        self.assertEqual(self.after["branches"], self.before["branches"])
        self.assertEqual(self.after["tree"], self.before["tree"])


if __name__ == "__main__":
    unittest.main()
