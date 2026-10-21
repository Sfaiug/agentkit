"""`ak --help` and `ak -h` print one listing, the one the owner approved: the menu and each verb
a seat uses, a row each with its purpose, then the verbs ak runs for itself on one `internal:`
line, and how to learn more.

A model or a person finds a verb here before anything else, so its words, its order and its
closing lines are pinned exactly, piped output carries no colour whatever the terminal type, and
printing it reads no config, runs nothing and writes nothing.  `help` is not a verb.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and
this test fails against `/bin/false`.
"""

import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REFUSED, Home

LISTING = """\
usage: ak [command]

  ak       the menu
  run      execute a task file to a merged PR
  plan     show or write this session's checked plan
  notify   record a needs-you question
  wait     end this turn waiting on a pull request or run
  usage    show provider usage and worker pick order
  models   score every model and effort per role from the public boards, recommend one per role
  browser  inspect the shared browser, sign in, register MCP tools, or install the stack
  fetch    copy requested Mac files to this host

internal:  orch  worker  hand-in  watch  update  macbridge  attach  doctor

Use -h or --help after any command.
Example: ak run task.md --bg
"""
VERBS = ("run", "plan", "notify", "wait", "usage", "models", "browser", "fetch",
         "orch", "worker", "hand-in", "watch", "update", "macbridge", "attach", "doctor")


def tree(root):
    """Every path under `root` with what each file holds."""
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in sorted(root.rglob("*"))}


class Listing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def test_both_flags_print_the_approved_listing_and_nothing_else(self):
        for flag in ("--help", "-h"):
            with self.subTest(flag):
                done = self.home.ak(flag)
                self.assertEqual((done.code, done.err), (0, ""))
                self.assertEqual(done.out, LISTING)

    def test_the_rows_and_the_internal_line_name_every_verb_once(self):
        lines = self.home.ak("--help").out.splitlines()
        rows = [line.split(None, 1) for line in lines if line.startswith("  ")]
        self.assertTrue(all(len(row) == 2 for row in rows), rows)
        internal = next(line for line in lines if line.startswith("internal:")).split()[1:]
        named = [name for name, _purpose in rows[1:]] + internal
        self.assertEqual(rows[0][0], "ak")
        self.assertEqual(sorted(named), sorted(VERBS))

    def test_a_pipe_gets_no_colour_even_from_a_colour_terminal_type(self):
        done = self.home.ak("--help", env={"NO_COLOR": None, "TERM": "xterm-256color",
                                           "COLORTERM": "truecolor"})
        self.assertEqual(done.code, 0, done.err)
        self.assertNotIn("\x1b", done.out)
        self.assertEqual(done.out, LISTING)

    def test_help_is_not_a_verb_and_the_refusal_names_the_verbs(self):
        done = self.home.ak("help")
        self.assertEqual(done.code, 2, done.out)
        self.assertEqual(done.out, "")
        self.assertIn("'help'", done.err)
        for verb in VERBS:
            self.assertRegex(done.err, rf"(?<![\w-]){verb}(?![\w-])")


class NothingWritten(unittest.TestCase):
    def test_an_empty_home_prints_the_listing_and_stays_empty(self):
        with Home() as home:
            shutil.rmtree(home.path / ".agentkit")
            before = tree(home.path)
            for flag in ("--help", "-h"):
                with self.subTest(flag):
                    done = home.ak(flag)
                    self.assertEqual((done.code, done.out), (0, LISTING), done.err)
            self.assertEqual(home.ak("help").code, 2)
            self.assertEqual(tree(home.path), before)
            self.assertFalse((home.path / ".agentkit").exists())
            self.assertEqual({name: home.calls(name) for name in REFUSED if home.calls(name)},
                             {})
            # no tmux server of ak's was started to print it
            self.assertNotEqual(home.tmux("list-sessions").code, 0)


if __name__ == "__main__":
    unittest.main()
