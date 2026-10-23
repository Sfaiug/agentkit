"""From a seat, `ak run` refuses --exec, --review, --anyway and --first; outside one they stand.

A seat is a model typing in the owner's conversation.  ak picks the models, decides what goes
first and refuses a second run of a change under way, so a seat that named a model, jumped the
queue or forced a rival would undo what ak decides: the launch is refused before any run, turn
or pull request exists, and the refusal says why and what to do.  A seat is a recorded session,
under its name now or the one it had before a rename; a name with no record is nobody's seat,
and there, as with no name at all, the owner's flags stand.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, beside a seat of
tests/fixtures/akseat.py, on a project from gitrig.py with scripted harnesses from
fakeadapter.py.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig

WHY = ("not a seat's; ak picks the models, decides what goes first and refuses a second run of "
       "a change under way, so launch without")


def refusal(*flags):
    return f"ak run: {', '.join(flags)}: {WHY}\n"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class FromASeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="work")
        cls.task = taskfile.write(cls.home, cls.rig.path, "Fix api")
        cls.seat = Seat(cls.home, "acme")
        # what `ak orch rename` leaves under the name the seat was started with
        cls.home.write(".agentkit/state/session-old.json", {"renamed": "acme"})

    def launch(self, seat, *args):
        return self.home.ak("run", *args, env={"AGENTKIT_SESSION": seat})

    def assertNothingStarted(self):
        self.assertEqual(taskfile.runs(self.home), [])
        self.assertEqual([fake.n for fake in self.fakes.values()], [0, 0])
        self.assertEqual(self.home.calls("gh"), [])
        sessions = self.home.tmux("list-sessions", "-F", "#{session_name}").out.split()
        self.assertEqual(sessions, ["acme"])
        self.assertEqual(self.seat.lines(), [])

    def test_each_owner_flag_from_a_seat_is_refused_and_nothing_starts(self):
        for args in (("--exec", "astra"), ("--review", "astra"), ("--anyway",), ("--first",)):
            with self.subTest(args[0]):
                done = self.launch("acme", str(self.task), *args)
                self.assertEqual((done.code, done.out, done.err), (2, "", refusal(args[0])))
        self.assertNothingStarted()

    def test_several_flags_are_refused_together_in_one_order_whatever_order_they_came_in(self):
        done = self.launch("acme", str(self.task), "--exec", "opus", "--anyway")
        self.assertEqual((done.code, done.err), (2, refusal("--exec", "--anyway")))
        done = self.launch("acme", str(self.task), "--first", "--anyway", "--review", "astra",
                           "--exec", "opus")
        self.assertEqual((done.code, done.err),
                         (2, refusal("--exec", "--review", "--anyway", "--first")))
        self.assertNothingStarted()

    def test_a_seat_launching_under_the_name_it_had_before_a_rename_is_still_a_seat(self):
        done = self.launch("old", str(self.task), "--first")
        self.assertEqual((done.code, done.err), (2, refusal("--first")))
        done = self.launch("old", "--review-pr", "https://github.com/acme/api/pull/1",
                           "--review", "astra")
        self.assertEqual((done.code, done.err), (2, refusal("--review")))
        self.assertNothingStarted()

    def test_a_seat_name_that_is_no_file_name_is_refused_whatever_the_flags(self):
        for args in (("--first",), ()):
            with self.subTest(args=args):
                done = self.launch("a/b", str(self.task), *args)
                self.assertEqual((done.code, done.out, done.err),
                                 (2, "", "ak run: invalid AGENTKIT_SESSION name 'a/b'\n"))
        self.assertNothingStarted()


class OutsideASeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets")
        akconfig.write(cls.home, ["opus", "astra"])
        cls.fakes = fakeadapter.install(cls.home, claude="work", codex="work")

    def launch(self, title, *args, env=None):
        """A --no-merge run of a task of its own: the executor its record names, and codex's
        turns in it."""
        task = taskfile.write(self.home, self.rig.path, title)
        before = len(self.fakes["codex"].runs())
        done = self.home.ak("run", str(task), "--no-merge", *args, env=env, timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run = [path for path in taskfile.runs(self.home)
               if path.name.endswith(taskfile.slug(title))]
        self.assertEqual(len(run), 1, taskfile.runs(self.home))
        executor = json.loads((run[0] / "run.json").read_text())["executor"]
        return executor, self.fakes["codex"].runs()[before:]

    def test_the_owner_s_exec_picks_the_executor_and_first_and_anyway_are_taken(self):
        # unnamed, ak picks opus on claude here (test_key_run_nomerge_pass.py): astra is the
        # owner's pick, and its turn is on codex
        executor, turns = self.launch("Fix api", "--exec", "astra", "--first", "--anyway")
        self.assertEqual(executor, "astra")
        self.assertEqual([turn["role"] for turn in turns], ["executor"])
        self.assertEqual(turns[0]["argv"][0], akconfig.SHIPPED["astra"]["model"])

    def test_a_session_name_with_no_record_is_no_seat_and_its_flags_stand(self):
        executor, turns = self.launch("Fix beta", "--exec", "astra",
                                      env={"AGENTKIT_SESSION": "ghost"})
        self.assertEqual(executor, "astra")
        self.assertEqual([turn["role"] for turn in turns], ["executor"])


if __name__ == "__main__":
    unittest.main()
