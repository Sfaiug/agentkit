"""`ak update` owes ~/agentkit's install.sh until it passes, and moves ~/agentkit only to a
commit whose tests/live.sh check passed.

The fast-forward moves HEAD before install.sh runs, so once install.sh fails origin's main is no
longer ahead and only a mark under state says the install is owed: without it, live code would
run on a half-installed host until the next merge.  A commit with a live check reaches the host
only once that check passed, and then exactly that commit, however far main has gone on.  A
failure is said once per origin commit, so a host that keeps failing does not fill its log.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, with
~/agentkit a clone of a gitrig.py origin.  The configured harness is one no host has, so `ak
update` upgrades nothing and goes straight to ~/agentkit, which it does from any build; the
tick's own retry acts only on the checkout ak runs from, so it is not judged here.
"""

import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home
from fixtures.gitrig import Rig

# Each run leaves a line, and it passes only once the test has put install-ok in HOME.
INSTALL = """#!/bin/sh
echo ran >>"$HOME/install-runs"
[ -e "$HOME/install-ok" ] || { echo "install: not yet"; exit 3; }
touch "$HOME/installed"
"""
UNINSTALLED = """[update]
version = ["acme-harness", "--version"]
upgrade = ["acme-harness", "upgrade"]
"""
LIVE = "#!/bin/sh\nexit 0\n"
PENDING = ".agentkit/state/agentkit-install-pending"


def live_install(home):
    """~/agentkit as a host holds it, a clone of the origin; merges land through the rig's
    own clone.  The rig."""
    adapters = home.root / "adapters"
    adapters.mkdir()
    (adapters / "acme.toml").write_text(UNINSTALLED)
    home.env["AGENTKIT_ADAPTER_DIR"] = str(adapters)
    akconfig.write(home, {"beta": "acme"})
    rig = Rig(home, "agentkit")
    script = rig.path / "install.sh"
    script.write_text(INSTALL)
    script.chmod(0o755)
    rig.commit({"install.sh": INSTALL}, "add install.sh")
    done = home.run("git", "clone", "-q", str(rig.bare), str(home.path / "agentkit"))
    assert done.code == 0, done.err
    return rig


def head(home):
    return home.run("git", "-C", str(home.path / "agentkit"), "rev-parse", "HEAD").out.strip()


def install_runs(home):
    try:
        return len((home.path / "install-runs").read_text().splitlines())
    except FileNotFoundError:
        return 0


class InstallOwed(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = live_install(self.home)
        self.new = self.rig.commit({"notes.md": "second\n"}, "second")
        self.pending = self.home.path / PENDING

    def update(self, code):
        done = self.home.ak("update")
        self.assertEqual(done.code, code, done.out + done.err)
        return done.out

    def test_a_failed_install_is_owed_until_an_update_runs_it_to_a_pass(self):
        self.assertRegex(self.update(3), r"update: .*install\.sh exited 3")
        # the pull went through, so origin's main is no longer ahead: only the mark is left
        self.assertEqual(head(self.home), self.new)
        self.assertTrue(self.pending.is_file())
        self.home.write("install-ok", "")
        self.update(0)
        self.assertEqual(install_runs(self.home), 2)
        self.assertTrue((self.home.path / "installed").is_file())
        self.assertFalse(self.pending.exists())
        self.assertEqual(head(self.home), self.new)

    def test_the_same_failure_is_said_once_per_origin_commit(self):
        self.assertRegex(self.update(3), r"install\.sh exited 3")
        # run again and failing again, with the same code, but nothing more to say
        self.assertNotRegex(self.update(3), r"install\.sh exited")
        self.assertEqual(install_runs(self.home), 2)
        self.assertTrue(self.pending.is_file())
        newer = self.rig.commit({"notes.md": "third\n"}, "third")
        self.assertRegex(self.update(3), r"install\.sh exited 3")
        self.assertEqual(head(self.home), newer)


class LiveCheckGate(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.rig = live_install(self.home)
        self.home.write("install-ok", "")      # an install, were one run, would pass
        self.before = head(self.home)

    def checked(self, commit, code):
        """A check of `commit` that ran to its end with `code`, as ak records one."""
        started = int(time.time()) - 900
        self.home.write(f".agentkit/state/live-checks/{commit}-{started}/exit", f"{code}\n",
                        ago=600)

    def test_main_with_a_live_check_waits_while_no_check_of_it_passed(self):
        tip = self.rig.commit({"tests/live.sh": LIVE}, "add a live check")
        for verdict in (None, 1):
            with self.subTest(check=verdict):
                if verdict is not None:
                    self.checked(tip, verdict)
                done = self.home.ak("update")
                # waiting for the check is no failure of the update
                self.assertEqual(done.code, 0, done.out + done.err)
                self.assertEqual(head(self.home), self.before)
                self.assertEqual(install_runs(self.home), 0)
                self.assertFalse((self.home.path / PENDING).exists())

    def test_it_moves_to_exactly_the_commit_whose_check_passed(self):
        passed = self.rig.commit({"tests/live.sh": LIVE}, "add a live check")
        self.checked(passed, 0)
        tip = self.rig.commit({"notes.md": "unchecked\n"}, "newer, not checked yet")
        self.assertEqual(self.rig.head(), tip)
        done = self.home.ak("update")
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(head(self.home), passed)
        self.assertTrue((self.home.path / "installed").is_file())
        self.assertFalse((self.home.path / PENDING).exists())


if __name__ == "__main__":
    unittest.main()
