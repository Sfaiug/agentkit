"""`ak orch rename` refuses a name it cannot give, and then moves nothing.

A name is spoken for while a seat has it, while a rename still leads from it to another seat
(that seat's orchestrator still answers to it) and while tmux holds a session by it; a seat given
one of those would take another's calls, or tmux would refuse it.  Each refusal exits 2, says
why in the words below and leaves every seat, record, tmux session and pane as it was.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py on seats
from tests/fixtures/akseat.py, and this test fails against `/bin/false`.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat

INSIDE = {"AGENTKIT_SESSION": "parser-fix"}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class RenameRefusals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.seats = [Seat(cls.home, "parser-fix"), Seat(cls.home, "busy")]
        cls.home.write(".agentkit/state/session-gone.json", {"renamed": "busy"})
        # a session on ak's server that runs no agent: no seat, yet tmux holds its name
        done = cls.home.tmux("new-session", "-d", "-s", "loop", "sleep 600")
        assert done.code == 0, done.err

    def standing(self):
        """Every record and pointer, by name, every session tmux holds and what each seat was
        typed."""
        state = self.home.path / ".agentkit" / "state"
        records = {path.name: json.loads(path.read_text()).get("renamed")
                   for path in state.glob("session-*.json")}
        held = self.home.tmux("list-sessions", "-F", "#{session_name}").out.split()
        return records, sorted(held), [seat.typed() for seat in self.seats]

    def refused(self, args, env, error):
        before = self.standing()
        done = self.home.ak("orch", "rename", *args, env=env)
        self.assertEqual(done.code, 2, done)
        self.assertEqual(done.out, "")
        if error is not None:
            self.assertEqual(done.err.strip(), f"ak orch: {error}")
        self.assertEqual(self.standing(), before)

    def test_auto_leaves_a_seat_that_has_a_name_alone(self):
        for args, env in ((("--auto", "other-name"), INSIDE),
                          (("--auto", "parser-fix", "other-name"), None)):
            with self.subTest(args=args):
                before = self.standing()
                done = self.home.ak("orch", "rename", *args, env=env)
                self.assertEqual((done.code, done.out),
                                 (0, "seat is already named parser-fix\n"), done.err)
                self.assertEqual(self.standing(), before)

    def test_a_name_a_seat_a_pointer_or_tmux_holds_is_spoken_for(self):
        for name in ("busy", "gone", "loop"):
            for args, env in (((name,), INSIDE), (("parser-fix", name), None)):
                with self.subTest(args=args):
                    self.refused(args, env, f"the name {name!r} is already spoken for")

    def test_a_name_that_is_a_flag_or_nothing_is_no_name(self):
        self.refused(("--", "-x"), INSIDE, "not a session name: '-x'")
        # Its wording names the environment variable, not the name given: only the refusal is
        # the key here.
        self.refused(("parser-fix", "!!!"), None, None)

    def test_more_or_fewer_names_than_old_and_new_are_shown_the_usage(self):
        for args in (("a", "b", "c"), ()):
            with self.subTest(args=args):
                self.refused(args, INSIDE, "usage: ak orch rename [--auto] [OLD] NEW")

    def test_an_unknown_seat_is_refused_naming_the_seats_there_are(self):
        self.refused(("nosuch", "newname"), INSIDE,
                     "no orchestrator session 'nosuch' (running: busy, parser-fix)")

    def test_one_name_outside_a_seat_says_which_seat_to_name(self):
        self.refused(("newname",), None,
                     "ak orch rename <new> renames the session it runs in, and this is not one; "
                     "use ak orch rename <old> <new>")


if __name__ == "__main__":
    unittest.main()
