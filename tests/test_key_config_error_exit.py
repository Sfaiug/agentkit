"""A config.toml ak cannot use stops every command that reads it: exit 2, and one line saying why.

The owner edits ~/.agentkit/config.toml by hand, and a model may too.  A file ak refuses is
named in a single line, `ak <command>: <path>: <reason>`, never a traceback, and the command
does nothing else: the file and the rest of HOME stay as they were, so the person fixes the
file and runs the command again.  The reason is ak's own words for each rule it checks; for a
file that is not TOML at all it is the parser's, which another build words its own way, so
there only the one line naming the file is pinned.  `ak doctor` reports on the host before it
reads the config, so its stdout is left unpinned.  Black-box: the program `AK_BIN` names runs
from outside through tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import os
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

BASE = ('[defaults]\norchestrator = "beta"\nworkers = ["beta"]\n\n'
        '[models.beta]\nharness = "claude"\nmodel = "beta"\neffort = "high"\n'
        'provider = "acme"\n\n[providers.acme]\nmode = "subscription"\n')
MODELS = BASE[BASE.index("[models.beta]"):]
TASK = "# Fix the parser\n\nMake it accept an empty file.\n\n## Done when\n\nIt does.\n"
# Each command that reads the config, given everything else it needs to start working.
COMMANDS = (("usage", "--json"), ("models", "--json"), ("doctor",),
            ("worker", "beta", "task.md"), ("run", "task.md"))


def changed(old, new):
    assert old in BASE, old
    return BASE.replace(old, new)


# Each file ak parses and refuses, and its reason.
REFUSED = {
    "defaults only": ('[defaults]\norchestrator = "beta"\n', "missing [models] table"),
    "no providers": (BASE[:BASE.index("[providers.acme]")], "missing [providers] table"),
    "no model's provider has a table": (
        changed('provider = "acme"', 'provider = "zeta"'),
        "no [models.*] entry names a provider with a [providers.*] table"),
    "defaults is not a table": ("defaults = 3\n\n" + MODELS, "[defaults] must be a table"),
    "within is a word": ('within = "x"\n' + BASE,
                         "within must be a number of points from 0 to 10 (got 'x')"),
    "within is below zero": ("within = -1\n" + BASE,
                             "within must be a number of points from 0 to 10 (got -1)"),
    "orchestrator is a number": (changed('orchestrator = "beta"', "orchestrator = 3"),
                                 "[defaults].orchestrator must be a model name (got 3)"),
    "workers repeat a model": (
        changed('workers = ["beta"]', 'workers = ["beta", "beta"]'),
        "[defaults].workers must list distinct model names (got ['beta', 'beta'])"),
    "workers is not a list": (changed('workers = ["beta"]', 'workers = "beta"'),
                              "[defaults].workers must list distinct model names (got 'beta')"),
    "reviewers is empty": (changed('workers = ["beta"]', 'workers = ["beta"]\nreviewers = []'),
                           "[defaults].reviewers must list distinct model names (got [])"),
    "an account name holds a slash": (
        BASE + 'accounts = ["acme/two"]\n',
        "[providers.acme].accounts must list distinct names of letters, digits, '.', '_' "
        "and '-' (got ['acme/two'])"),
    "an account name repeats": (
        BASE + 'accounts = ["one", "one"]\n',
        "[providers.acme].accounts must list distinct names of letters, digits, '.', '_' "
        "and '-' (got ['one', 'one'])"),
}
NOT_TOML = {
    "an unclosed list": (BASE + "within = [\n").encode(),
    "a key set twice": ("max_runs = 1\nmax_runs = 2\n" + BASE).encode(),
    "bytes that are not UTF-8": BASE.encode() + b'name = "\xff"\n',
}


class ConfigErrorExit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.write("task.md", TASK)
        cls.config = cls.home.path / ".agentkit" / "config.toml"

    def refused(self, data, check):
        """Run each command against a config holding `data`, and `check` its stderr once it has
        exited 2 and left HOME as it was."""
        self.config.write_bytes(data)
        before = self.home.tree()
        for command in COMMANDS:
            with self.subTest(command=" ".join(command)):
                done = self.home.ak(*command)
                self.assertEqual(done.code, 2, done.err)
                self.assertNotIn("Traceback", done.err)
                if command[0] != "doctor":
                    self.assertEqual(done.out, "")
                self.assertEqual(self.home.tree(), before)
                check(f"ak {command[0]}: {self.config}: ", done.err)

    def test_each_rule_broken_is_named_in_one_line_after_the_file(self):
        for case, (text, reason) in REFUSED.items():
            with self.subTest(case):
                self.refused(text.encode(),
                             lambda prefix, err: self.assertEqual(err, f"{prefix}{reason}\n"))

    def test_a_file_that_is_not_toml_is_one_line_after_the_file(self):
        def one_line(prefix, err):
            self.assertTrue(err.startswith(prefix), err)
            self.assertRegex(err[len(prefix):], r"\A[^\n]*\S[^\n]*\n\Z")
        for case, data in NOT_TOML.items():
            with self.subTest(case):
                self.refused(data, one_line)

    @unittest.skipIf(os.geteuid() == 0, "root reads a file whatever its mode")
    def test_a_file_that_cannot_be_read_says_so_in_one_line(self):
        self.config.write_bytes(BASE.encode())
        self.config.chmod(0)
        self.addCleanup(self.config.chmod, 0o644)
        for command in COMMANDS:
            with self.subTest(command=" ".join(command)):
                done = self.home.ak(*command)
                self.assertEqual(done.code, 2, done.err)
                self.assertTrue(done.err.startswith(
                    f"ak {command[0]}: cannot read {self.config}: "), done.err)
                self.assertEqual(done.err.count("\n"), 1, done.err)


if __name__ == "__main__":
    unittest.main()
