"""With no terminal on stdin, or from a seat, `ak orch` opens no seat: it says how one opens.

Only a person opens a seat (owner rules): an agent's guessed `ak orch help` once opened a real
seat, which sat in the owner's list reading `needs you`.  Agents run ak with no terminal on
stdin, so a name no seat has, or no name at all, is refused, with the two ways a person opens a
seat and the usage; a seat that gives its `ak orch` a terminal is refused all the same.  Nothing
is left behind: no seat record and no tmux session.  Arguments ak cannot read are refused first,
each saying what was wrong.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py; this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

USAGE = ("usage: ak orch [name] [--model NAME] [--workers A,B] [--dry-run] | "
         "ak orch list [--why] | ak orch why NAME | ak orch stop <name> | "
         "ak orch rename [--auto] [OLD] NEW | ak orch project [<seat>] <checkout>")
FROM_A_TERMINAL = ("; a new seat opens only from a terminal (the menu's n, or `ak orch NAME` "
                   "typed there)\n" + USAGE + "\n")


class OpenWithoutTerminal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def refused(self, args, err, **kw):
        done = self.home.ak("orch", *args, timeout=30, **kw)
        self.assertEqual((done.code, done.out, done.err), (2, "", err))
        state = self.home.path / ".agentkit" / "state"
        self.assertEqual([path.name for path in state.iterdir()
                          if path.name.startswith(("session-", "seat-"))], [])
        self.assertEqual(self.home.tmux("list-sessions", "-F", "#{session_name}").out, "")

    def test_a_name_no_seat_has_is_refused_saying_how_a_person_opens_one(self):
        # Naming the model or the workers is how a person asks for a new seat: still a person's.
        for args in (("brand-new",), ("brand-new", "--model", "opus"),
                     ("--workers", "opus", "brand-new")):
            with self.subTest(args=args):
                self.refused(args, "ak orch: no seat named brand-new" + FROM_A_TERMINAL)

    def test_no_name_is_refused_the_same_way(self):
        self.refused((), "ak orch: no seat name given" + FROM_A_TERMINAL)

    def test_a_seat_opens_no_seat_even_from_a_terminal(self):
        # A seat once gave its `ak orch` a terminal through a tmux session of its own.
        self.refused(("brand-new",), "ak orch: no seat named brand-new; a seat opens no seat: "
                     "only the owner does, with the menu's n\n" + USAGE + "\n",
                     tty=True, env={"AGENTKIT_SESSION": "acme"})

    def test_arguments_it_cannot_read_are_refused_saying_what_was_wrong(self):
        cases = {("acme", "beta"): f"ak orch: {USAGE}  (got 'beta')\n",
                 ("--bogus",): f"ak orch: {USAGE}  (got '--bogus')\n",
                 ("--model",): "ak orch: --model needs a model name\n",
                 ("acme", "--workers"):
                     "ak orch: --workers needs a comma-separated list of model names\n"}
        for args, err in cases.items():
            with self.subTest(args=args):
                self.refused(args, err)


if __name__ == "__main__":
    unittest.main()
