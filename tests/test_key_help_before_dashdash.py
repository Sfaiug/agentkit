"""Help comes before everything but `--`: before config is read, and before arguments are checked.

A model reaching for `-h` is usually lost, often in a HOME whose config.toml it or a person just
broke, so help must print there, with flags help cannot judge, and write nothing.  `--` is the
one way to name a file called `--help`, as `ak fetch -h` says.  Black-box: the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py, and this test fails against
`/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

HELPS = (("usage", "--help"), ("doctor", "-h"), ("models", "-h"), ("worker", "-h"),
         ("run", "-h"), ("orch", "-h"), ("hand-in", "-h"))
# Flags help cannot judge: a round count run refuses, a flag nothing knows.
BAD_ARGS = (("run", "--rounds", "0", "--help"), ("run", "--help", "--bogus"))
MENU = ("ak attach: usage: ak [--client] [--overlay] [--dry-run]   "
        "(the menu; `ak attach` is the same)  (got '--')\n")


def tree(root):
    """Every file and directory under `root`, with each file's bytes."""
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in sorted(root.rglob("*"))}


class HelpBeforeTheDoubleDash(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.work = cls.home.path / "code" / "acme"
        cls.home.write("code/acme/--help", "notes\n")
        cls.home.write("code/acme/-h", "notes\n")

    def test_help_before_the_double_dash_is_help_with_nothing_after_it(self):
        done = self.home.ak("run", "--help", "--")
        self.assertEqual((done.code, done.err), (0, ""))
        self.assertEqual(done.out, self.home.ak("run", "-h").out)

    def test_run_refuses_the_double_dash_so_help_after_it_runs_nothing(self):
        for flag in ("--help", "-h"):
            with self.subTest(flag):
                done = self.home.ak("run", "--", flag, cwd=self.work)
                self.assertEqual((done.code, done.out), (2, ""), done.err)
                self.assertTrue(done.err.startswith("ak run: unknown flag '--'"), done.err)

    def test_fetch_takes_a_help_flag_after_the_double_dash_as_a_path(self):
        # A path that is not here would wait on the Mac; a zero wait keeps a wrong build short.
        done = self.home.ak("fetch", "--", "--help", "-h", cwd=self.work,
                            env={"AK_FETCH_TIMEOUT": "0"})
        self.assertEqual((done.code, done.err), (0, ""))
        self.assertEqual(done.out, f"{self.work}/--help\n{self.work}/-h\n")

    def test_the_menu_takes_help_after_the_double_dash_as_a_flag_it_refuses(self):
        done = self.home.ak("--", "--help")
        self.assertEqual((done.code, done.out, done.err), (2, "", MENU))


class HelpBeforeConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.good = {args: cls.home.ak(*args).out for args in HELPS}
        cls.config = cls.home.write(".agentkit/config.toml", "garbage = = =\n")

    def test_help_prints_the_same_with_a_config_that_does_not_load(self):
        for args in HELPS:
            with self.subTest(args=args):
                done = self.home.ak(*args)
                self.assertEqual((done.code, done.err), (0, ""))
                self.assertEqual(done.out, self.good[args])
                self.assertTrue(done.out)

    def test_help_prints_whatever_flags_stand_beside_it(self):
        for args in BAD_ARGS:
            with self.subTest(args=args):
                done = self.home.ak(*args)
                self.assertEqual((done.code, done.err), (0, ""))
                self.assertEqual(done.out, self.good["run", "-h"])

    def test_help_writes_nothing_under_home(self):
        before = tree(self.home.path)
        for args in HELPS + BAD_ARGS:
            with self.subTest(args=args):
                self.assertEqual(self.home.ak(*args).code, 0)
        self.assertEqual(tree(self.home.path), before)

    def test_the_command_itself_refuses_that_config_and_names_it(self):
        done = self.home.ak("usage")
        self.assertEqual(done.code, 2, done.out)
        self.assertTrue(done.err.startswith(f"ak usage: {self.config}:"), done.err)


if __name__ == "__main__":
    unittest.main()
