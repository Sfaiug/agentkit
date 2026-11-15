"""A client's move of ak whose program does not start is put back by the move itself.

A client, a home whose `state/server` names its server, runs no tick and no cron line, so no
keeper puts its moves back.  After an install.sh that passes, its `ak update` runs the bin/ak it
put live with `--help` and then `--dry-run`, the client's start up to the ssh it would run, and
where either exits non-zero ~/agentkit goes back to the commit it left, that commit's install.sh
runs, `ak update` exits non-zero with a last line naming both commits and the command, and no
later update moves to the commit put back.  A program that starts goes live, nothing of the
version it replaced kept; a home tries neither command.  Black-box, the Home built as
tests/test_key_ticks_that_stop_after_a_move_put_it_back.py builds it: the commit moved to has a
bin/ak exiting 1 for one flag and running the program for every other verb, and an install.sh
adding `moved` to HOME/installed, the one before `installed`.  `ak update` is the program's own,
as tests/test_key_update_install_retry.py runs it, since the copy at ~/agentkit holds no
tests/live.sh to gate a harness upgrade with, and the one harness configured is one no host has.
The whole file runs in one box, as that key's does (`rerun_boxed`): a /tmp, network and process
table of its own.
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home, rerun_boxed
from fixtures.akinstall import Install

# the commit moved to's bin/ak: `{flag}` exits 1, every other verb is the program's
FAILS = '#!/bin/sh\n[ "$1" != {flag} ] || exit 1\nexec "$(dirname "$0")/program" "$@"\n'
INSTALL = '#!/bin/sh\n[ "$1" != --prepare ] || exit 0\necho moved >>"$HOME/installed"\n'
UNINSTALLED = """[update]
version = ["acme-harness", "--version"]
upgrade = ["acme-harness", "upgrade"]
"""
KEPT = ".agentkit/tmp/keep/ak"     # where a home keeps the version a move replaced


class AClientMoveThatCannotStartIsPutBack(unittest.TestCase):
    def update(self, flag=None, client=True):
        """`ak update` on a Home, a client of `acme-server` with `client`, whose origin is one
        commit ahead, its bin/ak exiting 1 for `flag`: what it did, the commit before and the
        one moved to."""
        self.home = home = self.enterContext(Home())
        adapters = home.root / "adapters"
        adapters.mkdir()
        (adapters / "acme.toml").write_text(UNINSTALLED)
        home.env["AGENTKIT_ADAPTER_DIR"] = str(adapters)
        akconfig.write(home, {"beta": "acme"})
        if client:
            home.write(".agentkit/state/server", "acme-server\n")
        self.install = install = Install(home)
        before, ak = install.head(), install.seed / "bin" / "ak"
        if flag:
            ak.rename(ak.with_name("program"))
            ak.write_text(FAILS.format(flag=flag))
            ak.chmod(0o755)
        (install.seed / "install.sh").write_text(INSTALL)
        after = install.advance()
        return home.ak("update", timeout=300), before, after

    def seen(self):
        """What a person sees of the move: the commit live and the installs."""
        return self.install.head(), self.install.installed.read_text().splitlines()

    def assert_put_back(self, flag):
        done, before, after = self.update(flag)
        self.assertNotEqual(done.code, 0, done.out + done.err)
        last = done.out.splitlines()[-1]
        for named in (before[:7], after[:7], flag):
            self.assertIn(named, last)
        self.assertEqual(self.seen(), (before, ["moved", "installed"]))
        self.home.ak("update", timeout=300)
        self.assertEqual(self.seen(), (before, ["moved", "installed"]))

    def test_a_dry_run_that_fails_is_put_back(self):
        self.assert_put_back("--dry-run")

    def test_a_help_that_fails_is_put_back(self):
        self.assert_put_back("--help")

    def test_a_program_that_starts_goes_live(self):
        done, before, after = self.update()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.seen(), (after, ["moved"]))
        self.assertFalse(os.path.lexists(self.home.path / KEPT))

    def test_a_home_tries_neither(self):
        done, before, after = self.update("--dry-run", client=False)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.seen(), (after, ["moved"]))


if __name__ == "__main__":
    rerun_boxed()
    unittest.main()
