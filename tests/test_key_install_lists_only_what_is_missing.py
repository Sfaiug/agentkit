"""A server install's closing list names a model program only where none is installed.

install.sh asks which model program to install, and one is enough.  So its closing list ("what
this run could not do") names no program the machine does not have, unless it has none at all:
then one line says so and that a terminal run of ./install.sh asks which to install.  A file of
a program's name that cannot be run is no program.  Each program installed and not logged in
keeps its one login line, as before, and the `summary:` line counts the lines listed.
Black-box: install.sh of the checkout `AK_BIN` names runs from outside in a Home made the
account's own by tests/fixtures/installer.py, first with its fake of every program and no login,
then with none on its PATH, the host's taken off too, but a `codex` file it cannot run, then
with only a fake codex and its login on disk.  The claude worker token is on disk, so the only
lines naming a program are the ones under test.
"""

from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import Home

# each program, its adapter and how its login line says the login goes
PROGRAMS = {"claude": ("claude", "(device code)"), "codex": ("codex", "(device code)"),
            "muse": ("muse", "(device code)"), "grok": ("grokbuild", "(device code)"),
            "opencode": ("opencode", "paste the provider key"),
            "agy": ("antigravity", "(open the URL, paste the code)")}
NONE = ("  no model program is installed -- re-run ./install.sh in a terminal; "
        "it asks which to install")


def listed(done):
    """The `summary:` line's count and the lines it lists, each with its two-space indent."""
    lines = done.out[done.out.index("summary: "):].splitlines()
    count = re.fullmatch(r"summary: server; (\d+) thing\(s\) this install could not do:",
                         lines[0])
    items = []
    for line in lines[1:]:
        if not line.startswith("  "):
            break
        items.append(line)
    return int(count[1]) if count else 0, items


def naming_a_program(items):
    return [item for item in items if item.split()[0] in PROGRAMS]


@unittest.skipUnless(sys.platform.startswith("linux"), "a Linux host's install")
class ListsOnlyWhatIsMissing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        installer.prepare(home)
        installer.own_home(home)
        home.write(".agentkit/secrets/claude_oauth_token", "acme-token\n")
        cls.logged_out = installer.run(home, "--server")
        installer.without(home, *PROGRAMS)
        (home.bin / "codex").touch(mode=0o644)
        cls.none = installer.run(home, "--server")
        home.fake("codex", "#!/bin/sh\nexit 0\n")
        home.write(".codex/auth.json", "{}\n")
        cls.chosen = installer.run(home, "--server")

    def items(self, done):
        self.assertEqual(done.code, 0, done.out + done.err)
        count, items = listed(done)
        self.assertEqual(count, len(items), done.out)
        return items

    def test_with_none_installed_one_line_says_so(self):
        items = self.items(self.none)
        self.assertEqual(naming_a_program(items), [])
        self.assertEqual(items.count(NONE), 1, items)
        self.assertEqual([item for item in items if item != NONE], self.items(self.chosen))

    def test_with_one_installed_and_logged_in_no_program_is_named(self):
        items = self.items(self.chosen)
        self.assertEqual(naming_a_program(items), [])
        self.assertNotIn(NONE, items)

    def test_each_installed_and_not_logged_in_keeps_its_login_line(self):
        items = self.items(self.logged_out)
        logins = naming_a_program(items)
        for name, (adapter, how) in PROGRAMS.items():
            self.assertEqual(len([item for item in logins
                                  if item.startswith(f"  {name} login -- run `") and
                                  item.endswith(f"/adapters/{adapter}.sh login` in a terminal "
                                                f"{how}")]), 1, logins)
        self.assertEqual(len(logins), len(PROGRAMS), logins)
        self.assertEqual([item for item in items if item not in logins], self.items(self.chosen))


if __name__ == "__main__":
    unittest.main()
