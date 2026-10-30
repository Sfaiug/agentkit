"""`-h` or `--help` anywhere before `--` prints help and exits 0; after `--` it is an argument.

Models learn a command by adding `-h` wherever they were typing it, among other flags or after a
task file, so help must never run the command instead.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

COMMANDS = ("run", "plan", "notify", "wait", "usage", "models", "browser", "fetch",
            "orch", "worker", "hand-in", "watch", "update", "macbridge", "attach", "doctor",
            "move")
NESTED = ("run status", "orch list", "hand-in done", "notify needs", "browser login")


class HelpAnywhere(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def helped(self, *args):
        done = self.home.ak(*args)
        self.assertEqual(done.code, 0, f"ak {' '.join(args)}: {done.err}")
        return done.out

    def test_ak_alone_lists_every_command(self):
        for flag in ("-h", "--help"):
            with self.subTest(flag):
                out = self.helped(flag)
                for command in COMMANDS:
                    self.assertRegex(out, rf"(?<![\w-]){re.escape(command)}(?![\w-])")

    def test_every_command_prints_its_own_help(self):
        for command in COMMANDS + NESTED:
            for flag in ("-h", "--help"):
                with self.subTest(command=command, flag=flag):
                    self.assertIn(f"ak {command}", self.helped(*command.split(), flag))

    def test_help_after_other_arguments_is_the_same_help(self):
        cases = {("run",): [("run", "task.md", "-h"), ("run", "task.md", "--bg", "--help"),
                            ("run", "--rounds", "2", "-h", "task.md")],
                 ("run", "status"): [("run", "status", "--json", "-h")],
                 ("orch", "list"): [("orch", "list", "--why", "--help")]}
        for alone, placed in cases.items():
            expected = self.helped(*alone, "-h")
            for args in placed:
                with self.subTest(args=args):
                    self.assertEqual(self.helped(*args), expected)

    def test_after_the_double_dash_it_is_an_argument(self):
        for args in (("wait", "--", "-h"), ("orch", "rename", "--", "-h")):
            with self.subTest(args=args):
                done = self.home.ak(*args)
                self.assertNotEqual(done.code, 0, done.out)
                self.assertNotEqual(done.out, self.helped(args[0], "-h"))


if __name__ == "__main__":
    unittest.main()
