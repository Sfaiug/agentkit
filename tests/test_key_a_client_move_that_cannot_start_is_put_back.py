"""A client's move of ak whose program does not start is put back by the move itself.

A client, a home whose `state/server` names its server, runs no tick and no cron line, so no
keeper puts its moves back.  Its move goes to the commit ak is at on its server
(tests/test_key_a_client_follows_its_home.py).  After an install.sh that passes, its `ak update`
runs the bin/ak it put live with `--help` and then `--dry-run`, the client's start up to the ssh
it would run, and where either exits non-zero ~/agentkit goes back to the commit it left, that
commit's install.sh runs, `ak update` exits non-zero with a last line naming both commits and the
command, and no later update moves to the commit put back, as where that install.sh failed once
and the next `ak update` ran it again, that move's keep link gone as a client's move before clients
kept one left none, its home moved on meanwhile, which goes back to the commit before both, or where
it was a home its install.sh made a client, as a Mac becomes its Linux machine's.  A program that starts goes live, nothing of the version it replaced kept; a home tries
neither command.  Black-box, through
tests/fixtures/twohomes.py: `acme-vm`'s install is the one moved, to the commit `acme-mini`'s is
at, which has a bin/ak exiting 1 for one flag and running the program for every other verb, and an
install.sh adding `moved` to HOME/installed, the one before `installed`.  `ak update` is the
program's own, as tests/test_key_update_install_retry.py runs it, since the copy at ~/agentkit
holds no tests/live.sh to gate a harness upgrade with, and the one harness configured is one no
host has.
"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import AK, boxable
from fixtures.twohomes import Machines

# the commit moved to's bin/ak: `{flag}` exits 1, every other verb is the program's
FAILS = '#!/bin/sh\n[ "$1" != {flag} ] || exit 1\nexec "$(dirname "$0")/program" "$@"\n'
INSTALL = '#!/bin/sh\n[ "$1" != --prepare ] || exit 0\necho moved >>"$HOME/installed"\n'
ONCE = ('#!/bin/sh\n[ "$1" != --prepare ] || exit 0\n'    # INSTALL, its first run failing
        '[ -e "$HOME/tried" ] || { touch "$HOME/tried"; exit 3; }\n'
        'echo moved >>"$HOME/installed"\n')
UNINSTALLED = """[update]
version = ["acme-harness", "--version"]
upgrade = ["acme-harness", "upgrade"]
"""
KEPT = ".agentkit/tmp/keep/ak"     # where a move keeps the version it replaced till final


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AClientMoveThatCannotStartIsPutBack(unittest.TestCase):
    def update(self, flag=None, client=True, script=INSTALL):
        """`ak update` on `acme-vm`, with `client` a client of `acme-mini`, whose install is at
        origin's main one commit ahead, its bin/ak exiting 1 for `flag` and its install.sh
        `script`: what it did, the commit before and the one moved to."""
        server, home = self.enterContext(Machines("acme-mini", "acme-vm"))
        self.server, self.home = server, home
        home.program = AK     # the program's own `ak update`, as above
        (home.root / "adapters").mkdir()
        (home.root / "adapters" / "acme.toml").write_text(UNINSTALLED)
        home.env["AGENTKIT_ADAPTER_DIR"] = str(home.at / "adapters")
        akconfig.write(home, {"beta": "acme"})
        if client:
            home.client_of(server)
        self.install = install = home.install
        before, ak = install.head(), install.seed / "bin" / "ak"
        if flag:
            ak.rename(ak.with_name("program"))
            ak.write_text(FAILS.format(flag=flag))
            ak.chmod(0o755)
        (install.seed / "install.sh").write_text(script)
        after = install.advance()
        server.install.git("fetch", "-q", "origin")
        server.install.git("merge", "-q", "--ff-only", after)
        return home.ak("update", timeout=300), before, after

    def seen(self):
        """What a person sees of the move: the commit live and the installs."""
        return self.install.head(), self.install.installed.read_text().splitlines()

    def assert_put_back(self, done, before, after, flag):
        self.assertNotEqual(done.code, 0, done.out + done.err)
        last = done.out.splitlines()[-1]
        for named in (before[:7], after[:7], flag):
            self.assertIn(named, last)
        self.assertEqual(self.seen(), (before, ["moved", "installed"]))
        self.home.ak("update", timeout=300)
        self.assertEqual(self.seen(), (before, ["moved", "installed"]))

    def test_a_dry_run_that_fails_is_put_back(self):
        self.assert_put_back(*self.update("--dry-run"), "--dry-run")

    def test_a_help_that_fails_is_put_back(self):
        self.assert_put_back(*self.update("--help"), "--help")

    def test_a_retried_install_still_puts_back_a_program_that_cannot_start(self):
        done, before, after = self.update("--help", script=ONCE)
        self.assertNotEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.install.head(), after)    # live, its install.sh owed
        self.assert_put_back(self.home.ak("update", timeout=300), before, after, "--help")

    def test_a_retry_of_a_move_that_kept_no_link_still_puts_it_back(self):
        done, before, after = self.update("--help", script=ONCE)
        self.assertNotEqual(done.code, 0, done.out + done.err)
        (self.home.path / KEPT).unlink()
        self.assert_put_back(self.home.ak("update", timeout=300), before, after, "--help")

    def test_a_move_on_from_one_that_kept_no_link_puts_back_the_one_before(self):
        done, before, after = self.update("--help", script=ONCE)
        self.assertNotEqual(done.code, 0, done.out + done.err)
        (self.home.path / KEPT).unlink()
        onward = self.install.advance()
        self.server.install.git("fetch", "-q", "origin")
        self.server.install.git("merge", "-q", "--ff-only", onward)
        self.assert_put_back(self.home.ak("update", timeout=300), before, onward, "--help")

    def test_a_home_its_install_makes_a_client_tries_both(self):
        script = INSTALL + 'echo acme-mini >"$HOME/.agentkit/state/server"\n'
        self.assert_put_back(*self.update("--dry-run", client=False, script=script), "--dry-run")

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
    unittest.main()
