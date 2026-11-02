"""What ak tells a seat of `rounds`, `review_lines` and `seat_lines` is what this host set.

The rulebook a seat opens on and `ak run --help` say the numbers in force, whole sentences reading
right at any of them; with no setting they say ak's defaults, and a `$` the owner wrote in
`rules.md` stays as written.  A config.toml ak cannot use stops a command, never its help.
Black-box: the program `AK_BIN` names, judged by the file it writes for a seat and what it prints.
This test fails against `/bin/false`.
"""

import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, REPO, Home

ECHO = {"one": {"harness": "echo", "model": "echo-1", "provider": "test"},
        "two": {"harness": "echo", "model": "echo-2", "provider": "test"}}
OWN = "Acme's own rule: a seat costs $5, and $rounds, $Rounds and $s mean nothing here.\n"
DEFAULTS = ("at most 300 added lines with its tests", "Under 50 added lines you build",
            "ak refuses your own PR from 50 lines", "Three review rounds per change is the budget",
            "ak refuses a fourth.")


def said(home, *args):
    """What `ak` printed for `args`, having exited 0."""
    done = home.ak(*args)
    assert done.code == 0, done.err
    return done.out


class Help(unittest.TestCase):
    def helps(self, **settings):
        with Home() as home:
            akconfig.write(home, ECHO, settings=settings)
            return said(home, "run", "--help"), said(home, "run", "resume", "--help")

    def test_says_the_rounds_in_force(self):
        for rounds, plural in ((4, "4 rounds"), (1, "1 round")):
            with self.subTest(rounds=rounds):
                run, resume = self.helps(rounds=rounds)
                self.assertIn(f"at most {rounds} (default: task rounds or {rounds}).", run)
                self.assertIn(f"a task over {plural} is refused", run)
                self.assertIn(f"raises the round limit, at most {rounds}.", resume)
                self.assertIn(f"--rounds {rounds} --bg", resume)

    def test_says_ak_s_default_with_no_setting(self):
        run, resume = self.helps()
        self.assertIn("at most 3 (default: task rounds or 3).", run)
        self.assertIn("a task over 3 rounds is refused", run)
        self.assertIn("raises the round limit, at most 3.", resume)

    def test_prints_on_a_config_ak_cannot_use(self):
        with Home() as home:
            home.write(".agentkit/config.toml", "rounds = 0\n")
            self.assertIn("at most 3 (default", said(home, "run", "--help"))
            self.assertNotEqual(home.ak("run", "task.md").code, 0)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Rulebook(unittest.TestCase):
    def book(self, **settings):
        """The rulebook a seat opened on this host is handed."""
        with Home() as home:
            adapters = home.root / "adapters"
            shutil.copytree(REPO / "tests/fixtures/adapters", adapters)
            akconfig.write(home, ECHO, settings=settings)
            home.write(".agentkit/rules.md", OWN)
            cwd = home.path / "code" / "acme"
            cwd.mkdir(parents=True)
            done = home.ak("orch", "acme", "--model", "one", "--workers", "two", tty=True,
                           cwd=cwd, env={"AGENTKIT_ADAPTER_DIR": str(adapters)})
            self.assertEqual(done.code, 0, done.err)
            return (home.path / ".agentkit/state/rulebook-acme.md").read_text()

    def test_says_the_numbers_in_force(self):
        book = self.book(review_lines=150, rounds=4, seat_lines=20)
        for words in ("at most 150 added lines with its tests", "Under 20 added lines you build",
                      "ak refuses your own PR from 20 lines",
                      "Four review rounds per change is the budget", "ak refuses a fifth."):
            self.assertIn(words, book)
        for words in DEFAULTS:
            self.assertNotIn(words, book)

    def test_reads_right_at_either_end_of_the_budget(self):
        one, many = self.book(rounds=1), self.book(rounds=7)
        self.assertIn("One review round per change is the budget", one)
        self.assertIn("ak refuses a second.", one)
        self.assertIn("7 review rounds per change is the budget", many)
        self.assertIn("ak refuses round 8.", many)

    def test_says_ak_s_defaults_with_no_setting_and_the_owner_s_dollars_as_written(self):
        book = self.book()
        for words in DEFAULTS:
            self.assertIn(words, book)
        self.assertEqual(book.count("$"), OWN.count("$"))
        self.assertTrue(book.endswith(OWN))


if __name__ == "__main__":
    unittest.main()
