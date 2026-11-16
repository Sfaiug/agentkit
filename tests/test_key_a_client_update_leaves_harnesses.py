"""`ak update` on a client touches no harness and runs no gate: its seats and runs are its home's,
and the gate needs the home's logins and its shared browser, so there it can only fail, putting
back each harness the client's owner keeps for their own use.  It says in a line that this
machine's harnesses are its owner's own, and moves ak's install as a client's move goes
(tests/test_key_a_client_follows_its_home.py): to its home's commit, though ak's remote is past
it, its install.sh run once, exiting as that move does.  `ak update --dry-run` there says the
same line and plans no harness.  On the same machine as a home, with no `state/server`, `ak
update` runs the upgrade command as before.  Black-box, through tests/fixtures/twohomes.py: the
one harness configured on `acme-vm` is installed there, a fake whose upgrade command adds a line
to HOME/upgrades, and ak's install holds a tests/live.sh, the gate, adding one to HOME/gated.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import boxable
from fixtures.twohomes import Machines

HARNESS = """#!/bin/sh
case $1 in
  --version) echo "acme-harness 1.0.0" ;;
  upgrade) echo upgraded >>"$HOME/upgrades" ;;
esac
"""
ADAPTER = """[update]
version = ["acme-harness", "--version"]
upgrade = ["acme-harness", "upgrade"]
"""
GATE = '#!/bin/sh\necho gated >>"$HOME/gated"\n'
SAYS = "update: harnesses: skipped: this machine is acme-mini's client; they are its owner's own"


@unittest.skipUnless(boxable(), "no bwrap able to build a machine here")
class AClientUpdateLeavesHarnesses(unittest.TestCase):
    def setUp(self):
        """`acme-vm`, a client of `acme-mini` with `acme` installed, at `first`; its home one
        commit past it, at `commit`, and ak's remote one past that."""
        machines = Machines("acme-mini", "acme-vm")
        self.addCleanup(machines.close)
        home, self.here = machines
        self.here.client_of(home)
        gate = home.install.seed / "tests" / "live.sh"
        gate.parent.mkdir()
        gate.write_text(GATE)
        self.first = self.pulled(self.here, home.install.advance())
        self.commit = self.pulled(home, home.install.advance())
        home.install.advance()
        (self.here.root / "adapters").mkdir()
        (self.here.root / "adapters" / "acme.toml").write_text(ADAPTER)
        self.here.env["AGENTKIT_ADAPTER_DIR"] = str(self.here.at / "adapters")
        self.here.fake("acme-harness", HARNESS)
        akconfig.write(self.here, {"beta": "acme"})

    def pulled(self, machine, commit):
        """`machine`'s clone moved with git to `commit` on origin's main; `commit`."""
        machine.install.git("fetch", "-q", "origin")
        machine.install.git("merge", "-q", "--ff-only", commit)
        return commit

    def ran(self, name):
        """How many times the upgrade (`upgrades`) or the gate (`gated`) ran here."""
        path = self.here.path / name
        return len(path.read_text().splitlines()) if path.exists() else 0

    def seen(self):
        return self.here.install.head(), self.here.install.installs()

    def test_ak_update_leaves_the_harness_and_moves_ak_to_its_homes_commit(self):
        done = self.here.ak("update", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn(SAYS, done.out.splitlines())
        self.assertEqual((self.ran("upgrades"), self.ran("gated")), (0, 0))
        self.assertEqual(self.seen(), (self.commit, 1))

    def test_the_dry_run_says_so_and_plans_no_harness(self):
        done = self.here.ak("update", "--dry-run", timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertIn(SAYS, done.out.splitlines())
        # a plan line starts with its harness's name
        self.assertNotIn("acme", [line.split(" ")[0] for line in done.out.splitlines()])
        self.assertEqual((self.ran("upgrades"), self.ran("gated")), (0, 0))
        self.assertEqual(self.seen(), (self.first, 0))

    def test_a_home_runs_the_upgrade_as_before(self):
        (self.here.path / ".agentkit" / "state" / "server").unlink()
        self.here.ak("update", timeout=300)
        self.assertEqual(self.ran("upgrades"), 1)


if __name__ == "__main__":
    unittest.main()
