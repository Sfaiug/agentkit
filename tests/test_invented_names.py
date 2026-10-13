"""agentkit is public: its tests, docs and texts use invented names (`acme`, `fix-api`), never
this host's.

Read from the host the suite runs on, so the check holds wherever ak runs: the user's name
and home directory name (`pwd`), and the names of the checkouts under that home's `code` (hidden
directories aside), five characters or longer -- `agentkit` aside, the name these files give
this project whatever its checkout is called.  A name that is also a path in the repository,
which prose names for its own sake, is looked for as `code/<name>`.  Each is matched whole and
literally, case aside, in tests/, docs/, README.md, AGENTS.md, ARCHITECTURE.md and
orchestrator.md, this file too.  Offline: `git grep` over the tracked files of this checkout.
"""

import os
from pathlib import Path
import pwd
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[1]
PUBLIC = ("tests", "docs", "README.md", "AGENTS.md", "ARCHITECTURE.md", "orchestrator.md")


def host_names():
    """The names this host gives away, longest first."""
    me = pwd.getpwuid(os.getuid())
    home = Path(me.pw_dir)
    names = {me.pw_name, home.name}
    code = home / "code"
    if code.is_dir():
        names.update(child.name for child in code.iterdir()
                     if child.is_dir() and not child.name.startswith("."))
    return sorted((f"code/{name}" if (REPO / name).exists() else name
                   for name in names if len(name) >= 5 and name != "agentkit"),
                  key=len, reverse=True)


def mentions(name):
    """Each `path:line: text` naming `name` whole, case aside, in the public files."""
    proc = subprocess.run(["git", "-C", str(REPO), "grep", "-n", "-I", "-F", "-i", "-w",
                           "--no-color", "-e", name, "--", *PUBLIC], capture_output=True, text=True)
    if proc.returncode not in (0, 1):
        raise AssertionError(f"git grep failed: {proc.stderr}")
    return proc.stdout.splitlines()


class InventedNames(unittest.TestCase):
    def test_no_public_file_names_this_hosts_user_home_or_checkouts(self):
        found = {name: mentions(name) for name in host_names()}
        found = {name: lines for name, lines in found.items() if lines}
        self.assertEqual(found, {}, "a real name in a public file; use an invented one:\n"
                         + "\n".join(f"  {line}" for lines in found.values() for line in lines))


if __name__ == "__main__":
    unittest.main(verbosity=2)
