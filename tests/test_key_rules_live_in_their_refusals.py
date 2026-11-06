"""A rule ak refuses a seat for breaking, naming the fix, lives in that refusal, not the rulebook.

The rulebook a seat is handed says nothing of the most checks a task has, of naming a model, of
the round budget, of retired front matter or of how the plan works: a seat's launch that breaks
one is refused, with what to do instead, before any harness takes a turn.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, with a seat of
tests/fixtures/akseat.py whose hooks fire as Claude fires them (tests/fixtures/hookdrive.py), on
a project from gitrig.py with scripted harnesses from fakeadapter.py.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.akseat import Seat
from fixtures.gitrig import Rig
from fixtures.hookdrive import Hooks

# Words of the rulebook lines each refusal below made redundant.
GONE = ("three at most", "naming no model", "done_when_minutes",
        "is the budget, counted across runs", "Your plan is `ak plan`")


class RulesLiveInTheirRefusals(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, ["opus", "astra"])
        self.fakes = fakeadapter.install(self.home, claude="work", codex="pass")
        self.rig = Rig(self.home, "widgets")

    def refused(self, *flags, planned=True, **task):
        """What a seat's launch of a task into the project said, refused before any turn."""
        Seat(self.home, "acme", alive=False, planned=planned)
        path = taskfile.write(self.home, self.rig.path, "Fix api", **task)
        done = self.home.ak("run", str(path), *flags, "--no-merge", timeout=300,
                            env={"AGENTKIT_SESSION": "acme"})
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertEqual([fake.n for fake in self.fakes.values()], [0, 0])
        return done.err

    def test_the_rulebook_a_seat_is_handed_holds_none_of_their_lines(self):
        Seat(self.home, "acme", alive=False)
        fired = Hooks(self.home).fire("UserPromptSubmit",
                                      {"prompt": "go", "session_id": "conv-acme"})
        self.assertEqual(fired.code, 0, fired.err)
        book = (self.home.path / ".agentkit/state/change-acme.md").read_text()
        self.assertIn("# You are the orchestrator", book)
        for words in GONE:
            with self.subTest(words=words):
                self.assertNotIn(words, book)

    def test_four_checks_are_refused_to_be_split(self):
        self.assertIn("split it", self.refused(done_when=("test -f a", "test -f b",
                                                          "test -f c", "test -f d")))

    def test_a_named_model_is_refused_since_ak_picks(self):
        self.assertIn("ak picks the models", self.refused("--exec", "opus"))

    def test_a_seat_with_no_open_plan_line_is_told_to_add_one(self):
        self.assertIn("ak plan add", self.refused(planned=False))

    def test_rounds_past_the_budget_are_refused_to_split_or_re_scope(self):
        self.assertIn("split or re-scope", self.refused(front={"rounds": 4}))


if __name__ == "__main__":
    unittest.main()
