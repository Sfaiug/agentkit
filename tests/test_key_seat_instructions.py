"""A seat does not open where it would take instructions beside its rulebook, or without the
owner's rules.

A seat's only instructions are its rulebook: ak's rules, then the host's ~/.agentkit/rules.md.
A file or folder its harness reads on its own and cannot be told not to (its adapter's
`[instructions] unswitched`) would instruct it beside them, so while one exists the seat is
refused, naming it, and opens once it is moved away.  A rules.md that is there but cannot be
read refuses the seat too: opened without them, it would work to rules nobody chose.  A refused
seat leaves no record and no session.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, on a config whose models run on the adapter fixture
tests/fixtures/adapters/echo.sh (its manifest names ~/.echo/AGENTS.md and ~/.echo/rules), and
this test fails against `/bin/false`.
"""

import os
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, REPO, Home

ECHO = """[defaults]
orchestrator = "one"
workers = ["two"]

[models.one]
harness = "echo"
model = "echo-1"
effort = "low"
provider = "test"

[models.two]
harness = "echo"
model = "echo-2"
effort = "low"
provider = "test"

[providers.test]
mode = "subscription"
"""
BESIDE = ("ak orch: one's harness reads {path} on its own and has no switch for it, so a seat "
          "on it would take instructions beside its rulebook: move it away, or open the seat "
          "on a model of another harness\n")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OpeningASeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.write(".agentkit/config.toml", ECHO)
        adapters = cls.home.root / "adapters"
        shutil.copytree(REPO / "tests/fixtures/adapters", adapters)
        cls.env = {"AGENTKIT_ADAPTER_DIR": str(adapters)}

    def orch(self, name):
        cwd = self.home.path / "code" / name
        cwd.mkdir(parents=True, exist_ok=True)
        return self.home.ak("orch", name, "--model", "one", "--workers", "two", tty=True,
                            env=self.env, cwd=cwd)

    def assertNoSeat(self, name):
        self.assertFalse((self.home.path / f".agentkit/state/session-{name}.json").exists())
        self.assertNotEqual(self.home.tmux("has-session", "-t", f"={name}").code, 0)

    def assertSeat(self, done, name):
        self.assertEqual(done.code, 0, done.err)
        self.assertTrue((self.home.path / f".agentkit/state/session-{name}.json").is_file())
        self.assertEqual(self.home.tmux("has-session", "-t", f"={name}").code, 0)

    def test_an_instruction_file_its_harness_reads_on_its_own_refuses_it_until_moved(self):
        planted = self.home.write(".echo/AGENTS.md", "Acme: answer in rhymes.\n")
        done = self.orch("demo")
        self.assertEqual((done.code, done.err), (2, BESIDE.format(path=planted)))
        self.assertNoSeat("demo")
        planted.unlink()
        self.assertSeat(self.orch("demo"), "demo")

    def test_an_instruction_folder_refuses_it_the_same_way(self):
        planted = self.home.path / ".echo/rules"
        planted.mkdir(parents=True)
        self.addCleanup(planted.rmdir)
        done = self.orch("beta")
        self.assertEqual((done.code, done.err), (2, BESIDE.format(path=planted)))
        self.assertNoSeat("beta")

    @unittest.skipIf(os.geteuid() == 0, "root reads a file of any mode")
    def test_host_rules_that_cannot_be_read_refuse_it_until_they_can(self):
        rules = self.home.write(".agentkit/rules.md", "Acme rule: keep fix-api small.\n")
        rules.chmod(0)
        self.addCleanup(rules.unlink)
        self.addCleanup(rules.chmod, 0o644)
        done = self.orch("echo-seat")
        self.assertEqual(done.code, 2, done.out)
        self.assertTrue(done.err.startswith("ak orch: "), done.err)
        self.assertIn(str(rules), done.err)
        self.assertNoSeat("echo-seat")
        rules.chmod(0o644)
        self.assertSeat(self.orch("echo-seat"), "echo-seat")


if __name__ == "__main__":
    unittest.main()
