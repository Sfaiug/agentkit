"""A merge to a project's AGENTS.md reaches each seat filed under it through the tick's fetch.

A seat's rulebook carries its project's AGENTS.md as on the default branch last fetched, and
its harness reads the rulebook only when it opens, so a seat left open across a merge made
anywhere would keep working to the old rules.  The tick fetches every project a seat is filed
under, and the next prompt of each such seat carries what changed in its rulebook;
before a tick has fetched, a prompt says nothing, since it never waits on the network.  A seat
filed under no project is told nothing, and the owner's checkout keeps its branch and files:
only what it knows of origin moves.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, beside seats of tests/fixtures/akseat.py whose Claude hooks
fire as tests/fixtures/hookdrive.py fires them; the merge is pushed to the bare origin from
another clone, and the tick runs in a network of its own with nothing but loopback.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.gitrig import Rig
from fixtures.hookdrive import Hooks

RULES = "# widgets\n\nKeep the API stable.\n"
ADDED = "Never break the CLI."
CONVERSATIONS = {"acme": "7d3c1e2a-5b4f-4a6e-8c9d-0e1f2a3b4c5d",
                 "beta": "2b8e4f6a-1c3d-4e5f-9a7b-6c5d4e3f2a1b"}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ProjectRulesFetched(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus"])
        cls.rig = Rig(home, "widgets", files={"AGENTS.md": RULES})
        # what a clone of a repository with commits knows of its default branch: the rig's
        # origin was empty when it was cloned
        cls.rig.git("remote", "set-head", "origin", "--auto")
        cls.checkout = cls.rig.git("rev-parse", "HEAD")
        cls.hooks = Hooks(home)
        Seat(home, "acme", cwd=cls.rig.path, record={
            "conversation": CONVERSATIONS["acme"], "repo": str(cls.rig.path)})
        Seat(home, "beta", record={"conversation": CONVERSATIONS["beta"]})
        for seat in CONVERSATIONS:
            assert cls.prompt(seat), f"{seat} is handed its rulebook"
            assert cls.prompt(seat) == "", f"{seat} is told the rules it was handed"
        # the merge, made in another clone: the owner's knows nothing of it until a fetch
        elsewhere = home.root / "elsewhere"
        cls.git("clone", "-q", str(cls.rig.bare), str(elsewhere))
        (elsewhere / "AGENTS.md").write_text(f"{RULES}{ADDED}\n")
        cls.git("-C", str(elsewhere), "commit", "-qam", "Add a rule")
        cls.git("-C", str(elsewhere), "push", "-q", "origin", "main")
        cls.unfetched = cls.prompt("acme")
        cls.tick = home.tick()
        cls.told = {seat: cls.prompt(seat) for seat in CONVERSATIONS}

    @classmethod
    def git(cls, *args):
        done = cls.home.run("git", *args)
        assert done.code == 0, done.err

    @classmethod
    def prompt(cls, seat):
        """What the seat's next prompt is told, as Claude reads it: '' for nothing."""
        fired = cls.hooks.fire("UserPromptSubmit", {
            "prompt": "go on", "session_id": CONVERSATIONS[seat]}, seat=seat)
        assert fired.code == 0, fired.err
        return "".join(said["hookSpecificOutput"]["additionalContext"] for said in fired.said
                       if "hookSpecificOutput" in said)

    def test_before_a_tick_has_fetched_the_merge_a_prompt_says_nothing(self):
        self.assertEqual(self.unfetched, "")

    def test_after_the_tick_the_seat_is_told_what_changed(self):
        self.assertEqual(self.tick.code, 0, self.tick.out + self.tick.err)
        news = self.told["acme"]
        self.assertIn(f"\n+{ADDED}\n", news)
        self.assertNotIn("\n+Keep the API stable.\n", news)

    def test_a_seat_filed_under_no_project_is_told_nothing(self):
        self.assertEqual(self.told["beta"], "")

    def test_the_owner_s_checkout_keeps_its_branch_and_files(self):
        self.assertEqual(self.rig.git("rev-parse", "HEAD"), self.checkout)
        self.assertEqual((self.rig.path / "AGENTS.md").read_text(), RULES)
        self.assertEqual(self.rig.git("status", "--porcelain"), "")
        self.assertEqual(self.rig.git("rev-parse", "origin/main"), self.rig.head())


if __name__ == "__main__":
    unittest.main()
