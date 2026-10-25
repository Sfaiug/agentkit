"""`ak update --dry-run` says what an update would do to each harness and gate, and does none of it.

A person asks for the dry run before trusting an update with every harness on the host, so it
must say, in the words of each adapter's `[update]` table, which harness it would move with
what command, which one it could not put back and why, which is missing here, which gates would
run, and what it would do to the agentkit checkout -- and then move nothing: no upgrade command
runs, the checkout stays on its commit and no file under HOME changes outside ak's own state.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, with
the harnesses' manifests in an adapter directory of the test's own.
"""

import re
import shlex
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import LOG, REPO, Home
from fixtures.gitrig import Rig

FIXTURE = REPO / "tests" / "fixtures" / "adapters"
ECHO = ("echo 1.0.0 (cannot be reverted: it is a fixture and has no installer at all): "
        "echo already-current")
MANIFESTS = {
    # one with a versioned reinstall, so the plan can say it would put it back
    "gamma": '[update]\nversion = ["gamma-cli", "--version"]\n'
             'upgrade = ["gamma-cli", "upgrade", "--yes"]\n'
             'revert = ["gamma-cli", "install", "{version}"]\n',
    # one whose command this host does not have
    "delta": '[update]\nversion = ["delta-cli", "--version"]\nupgrade = ["delta-cli", "upgrade"]\n',
    # one that says nothing of how it is upgraded
    "omega": "",
}


class DryRun(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.adapters = self.home.root / "adapters"
        self.adapters.mkdir()
        shutil.copy(FIXTURE / "echo.toml", self.adapters)
        for name, update in {"echo": None, **MANIFESTS}.items():
            shutil.copy(FIXTURE / "echo.sh", self.adapters / f"{name}.sh")
            if update is not None:
                (self.adapters / f"{name}.toml").write_text(f"version = 1\n{update}")
        self.home.fake("gamma-cli", LOG.format(python=shlex.quote(sys.executable),
                                               log=shlex.quote(str(self.home.log("gamma-cli"))))
                       + "echo 2.1.0\n")

    def dry_run(self, adapters=None):
        """The dry run's output, once it has exited 0 leaving every file under HOME as it was,
        ak's own state aside."""
        before = self.files()
        done = self.home.ak("update", "--dry-run",
                            env={"AGENTKIT_ADAPTER_DIR": str(adapters or self.adapters)})
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.files(), before)
        return done.out.splitlines()

    def files(self):
        state = self.home.path / ".agentkit" / "state"
        return {path: path.read_bytes() for path in self.home.path.rglob("*")
                if path.is_file() and state not in path.parents}

    def test_the_fixture_harness_is_planned_with_the_reason_it_cannot_be_put_back(self):
        akconfig.write(self.home, {"echo": {"harness": "echo", "model": "echo-1"}})
        lines = self.dry_run(FIXTURE)
        self.assertIn(ECHO, lines)
        self.assertTrue([line for line in lines
                         if line.startswith("update: dry run, nothing changed")], lines)
        self.assertIn(f"update: agentkit: skipped: no checkout at {self.home.path / 'agentkit'}",
                      lines)

    def test_each_gate_says_whether_it_would_run(self):
        akconfig.write(self.home, {"echo": {"harness": "echo", "model": "echo-1"}})
        lines = self.dry_run()
        for gate in ("live", "fresh"):
            with self.subTest(gate):
                said = [line for line in lines if line.startswith(f"update: gate {gate}: ")]
                self.assertEqual(len(said), 1, lines)
                self.assertRegex(said[0],
                                 rf"^update: gate {gate}: (run \(`bash .+`\)|skipped: .+)$")

    def test_each_manifest_says_how_its_harness_would_move_and_none_is_moved(self):
        akconfig.write(self.home, {name: name for name in ("echo", "gamma", "delta", "omega")})
        lines = self.dry_run()
        self.assertIn(ECHO, lines)
        self.assertIn("gamma 2.1.0 (versioned reinstall available): gamma-cli upgrade --yes",
                      lines)
        self.assertIn("update: delta: skipped: not installed here", lines)
        self.assertIn("delta not installed (cannot be reverted: it offers no versioned "
                      "reinstall): delta-cli upgrade", lines)
        self.assertFalse([line for line in lines if re.match(r"(update: )?omega\b", line)], lines)
        # The installed release is read; neither the upgrade nor the reinstall is run.
        self.assertTrue(self.home.calls("gamma-cli"))
        self.assertEqual([call for call in self.home.calls("gamma-cli") if call != ["--version"]],
                         [])

    def test_a_checkout_behind_its_origin_would_move_forward_and_stays_on_its_commit(self):
        akconfig.write(self.home, {"echo": "echo"})
        rig = Rig(self.home, "agentkit")
        checkout = self.home.path / "agentkit"
        self.home.run("git", "clone", "-q", str(rig.bare), str(checkout))
        rig.commit({"newer.txt": "on origin only\n"}, "newer")

        def git(*args):
            return self.home.run("git", "-C", str(checkout), *args).out.strip()
        head, short = git("rev-parse", "HEAD"), git("rev-parse", "--short", "HEAD")
        lines = self.dry_run()
        said = [line for line in lines if line.startswith("update: agentkit")]
        self.assertEqual(len(said), 1, lines)
        self.assertTrue(said[0].startswith(f"update: agentkit {short}"), said)
        self.assertIn("would move forward", said[0])
        self.assertEqual(git("rev-parse", "HEAD"), head)
        self.assertNotEqual(rig.head(), head)
        self.assertEqual(git("status", "--porcelain"), "")

    def test_with_no_harness_that_says_how_it_is_upgraded_it_refuses(self):
        akconfig.write(self.home, {"omega": "omega"})
        done = self.home.ak("update", "--dry-run",
                            env={"AGENTKIT_ADAPTER_DIR": str(self.adapters)})
        self.assertEqual(done.code, 2, done.out + done.err)
        self.assertEqual(done.out, "")
        self.assertIn("[update]", done.err)


if __name__ == "__main__":
    unittest.main()
