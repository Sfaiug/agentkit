"""A word ak does not know, or a flag its menu does not know, exits 2 and says what it takes.

A model guesses verbs: `ak help`, `ak preview`, `ak trial` (there is no in-house model test).
The refusal must name the verbs there are, so the next guess is right, and must start nothing:
no run, no tmux server, no call to GitHub, no file.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

VERBS = ("usage, models, worker, run, notify, wait, orch, attach, update, watch, browser, fetch, "
         "macbridge, doctor, hand-in, plan")
GUESSES = ("bogus", "frobnicate", "help", "preview", "trial")
MENU = ("ak attach: usage: ak [--client] [--overlay] [--dry-run]   "
        "(the menu; `ak attach` is the same)  (got '{}')\n")


class UnknownVerb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def test_an_unknown_first_word_is_refused_with_the_list_of_verbs(self):
        for word in GUESSES:
            with self.subTest(word):
                done = self.home.ak(word)
                self.assertEqual((done.code, done.out), (2, ""))
                self.assertEqual(done.err, f"ak: unknown subcommand '{word}'; "
                                           f"expected one of {VERBS}\n")

    def test_what_follows_an_unknown_word_changes_nothing_not_even_help(self):
        for args in (("trial", "opus"), ("help", "run"), ("preview", "--help")):
            with self.subTest(args=args):
                done = self.home.ak(*args)
                self.assertEqual((done.code, done.out), (2, ""))
                self.assertEqual(done.err, f"ak: unknown subcommand '{args[0]}'; "
                                           f"expected one of {VERBS}\n")

    def test_a_refused_word_starts_nothing_and_writes_nothing(self):
        before = self.home.tree()
        for word in GUESSES:
            with self.subTest(word):
                self.assertEqual(self.home.ak(word).code, 2)
        self.assertEqual(self.home.tree(), before)
        self.assertFalse((self.home.path / ".agentkit/runs").exists())
        self.assertNotEqual(self.home.tmux("list-sessions").code, 0, "ak's tmux server started")
        self.assertEqual(self.home.calls("gh"), [])

    def test_a_flag_the_menu_does_not_know_exits_2_with_the_menus_usage(self):
        for args in (("attach", "--bogus"), ("--bogus",), ("--dry-run", "--bogus-menu-flag")):
            with self.subTest(args=args):
                done = self.home.ak(*args)
                self.assertEqual((done.code, done.out), (2, ""))
                self.assertEqual(done.err, MENU.format(args[-1]))


if __name__ == "__main__":
    unittest.main()
