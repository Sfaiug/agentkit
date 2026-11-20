"""A new install starts at the version that passed: README.md's install line leaves ~/agentkit
on main, clean, at the commit origin's `live` names, and runs install.sh there once.

Only a host that may push moves `live`, after the turns that tested it were paid; a clone left
at main's newest commit would start on code that passed nowhere yet.  On main, clean, the
checkout is one ak moves on like any install behind main (`update.left_as_is`).  Offline: a
temporary HOME's git rewrites the line's GitHub URL to a throwaway origin whose `live` is one
commit behind its main.
"""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]

# The fake install.sh records the commit it ran at outside the checkout, so recording changes
# nothing there, and appends, so a second run shows.
INSTALL = '#!/bin/sh\ngit -C "$(dirname "$0")" rev-parse HEAD >>"$HOME/ran"\n'


def install_line():
    """The command in README.md's first code block that names install.sh."""
    blocks = re.findall(r"^```[^\n]*\n(.*?)^```", (REPO / "README.md").read_text(), re.M | re.S)
    return next(block for block in blocks if "install.sh" in block).strip()


class ANewInstallStartsAtWhatPassed(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-new-install-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home, self.origin = Path(tmp.name) / "home", Path(tmp.name) / "origin"
        self.home.mkdir()
        # Only this HOME's git config counts: none of the caller's, nor a hook's GIT_DIR.
        self.env = {**{k: v for k, v in os.environ.items()
                       if not k.startswith("GIT_") and k != "XDG_CONFIG_HOME"},
                    "HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1"}
        self.line = install_line()
        url = re.search(r"https://github\.com/\S+", self.line).group()
        for key, value in (("user.name", "acme"), ("user.email", "acme@localhost"),
                           (f"url.{self.origin}.insteadOf", url)):
            self.git(self.home, "config", "--global", key, value)
        self.origin.mkdir()
        self.git(self.origin, "init", "-q", "-b", "main")
        (self.origin / "install.sh").write_text(INSTALL)
        (self.origin / "install.sh").chmod(0o755)
        self.git(self.origin, "add", "install.sh")
        self.git(self.origin, "commit", "-q", "-m", "acme passed")
        self.git(self.origin, "branch", "live")
        self.git(self.origin, "commit", "-q", "--allow-empty", "-m", "acme untested")

    def git(self, where, *args):
        return subprocess.run(["git", "-C", str(where), *args], check=True, env=self.env,
                              capture_output=True, text=True).stdout.strip()

    def test_the_install_line_runs_install_sh_once_at_live_on_main(self):
        line = subprocess.run(["sh", "-c", self.line], cwd=self.home, env=self.env,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(line.returncode, 0, line.stderr)
        live, checkout = self.git(self.origin, "rev-parse", "live"), self.home / "agentkit"
        self.assertEqual((self.home / "ran").read_text().split(), [live])
        self.assertEqual(self.git(checkout, "symbolic-ref", "--short", "HEAD"), "main")
        self.assertEqual(self.git(checkout, "rev-parse", "HEAD"), live)
        self.assertEqual(self.git(checkout, "status", "--porcelain", "--untracked-files=all"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
