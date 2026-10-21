"""`ak orch NEW --dry-run` shows the seat it would open and opens and saves nothing.

A person checks which models a new seat would take, and the command it would run, before
opening it.  A dry run that left a record behind would make the next `ak orch NEW` resume a seat
nobody opened, and one that started tmux would open it, so a preview writes no seat's files and
starts no server; a model it does not know is refused before anything.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py, on the shipped config and on
one whose only model is the adapter fixture tests/fixtures/adapters/echo.sh, whose TUI is $SHELL.
"""

import shlex
import shutil
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, REPO, Home

ECHO = """[defaults]
orchestrator = "echo"
workers = ["echo"]

[models.echo]
harness = "echo"
model = "echo-1"
effort = "low"
provider = "test"

[providers.test]
mode = "subscription"
"""


def seat_files(home, name):
    """Whatever ak keeps under HOME that names that seat, or is the tmux config it opens seats
    with; a lock is only how ak takes turns."""
    return sorted(str(path.relative_to(home.path)) for path in home.path.rglob("*")
                  if path.is_file() and not path.name.endswith(".lock")
                  and (name in path.name or path.name == "tmux.conf"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OnTheEchoAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.home.write(".agentkit/config.toml", ECHO)
        adapters = cls.home.root / "adapters"
        shutil.copytree(REPO / "tests/fixtures/adapters", adapters)
        cls.env = {"AGENTKIT_ADAPTER_DIR": str(adapters)}
        cls.cwd = cls.home.path / "code"
        cls.cwd.mkdir()

    def orch(self, *args):
        return self.home.ak("orch", "new-seat", "--dry-run", *args, env=self.env, cwd=self.cwd)

    def test_it_prints_the_selection_and_the_command_and_saves_nothing(self):
        done = self.orch("--model", "echo", "--workers", "echo")
        self.assertEqual(done.code, 0, done.err)
        *said, command = done.out.splitlines()
        self.assertEqual(said, ["orch: echo (--model)",
                                f"session new-seat in {self.cwd} (new)",
                                "workers echo"])
        self.assertEqual(shlex.split(command)[-1], "/bin/sh")   # the adapter's TUI command
        self.assertEqual(seat_files(self.home, "new-seat"), [])
        self.assertNotEqual(self.home.tmux("list-sessions").code, 0)   # no server was started

    def test_a_model_the_config_does_not_define_is_refused(self):
        for args in (("--model", "nosuch", "--workers", "echo"),
                     ("--model", "echo", "--workers", "nosuch")):
            with self.subTest(args=args):
                done = self.orch(*args)
                self.assertEqual(done.code, 2, done.out)
                self.assertEqual(done.err, "ak orch: unknown model 'nosuch'; "
                                           "~/.agentkit/config.toml defines: echo\n")
                self.assertEqual(done.out, "")
        self.assertEqual(seat_files(self.home, "new-seat"), [])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class FromATerminal(unittest.TestCase):
    def test_a_person_s_dry_run_starts_and_saves_nothing(self):
        with Home() as home:
            done = home.ak("orch", "acme", "--model", "opus", "--workers", "opus", "--dry-run",
                           tty=True)
            self.assertEqual(done.code, 0, done.err)
            *said, _command = done.out.splitlines()
            self.assertEqual(said, ["orch: opus (--model)", f"session acme in {home.path} (new)",
                                    "workers opus"])
            self.assertEqual(seat_files(home, "acme"), [])
            self.assertNotEqual(home.tmux("list-sessions").code, 0)


if __name__ == "__main__":
    unittest.main()
