"""`ak worker` refuses a call it cannot run as asked, says why, and never reaches the harness.

One worker turn is spent tokens: a typo in the model, the role, a flag or a path must stop at
exit 2 with the reason, before any adapter verb runs, rather than run the turn some other way
than asked.  The Home's config defines one model on a fourth harness whose adapter logs every
call, so an empty log means no call: a well-formed one does reach it.  Black-box: the program
`AK_BIN` names runs from outside through tests/fixtures/akbin.py.
"""

import shutil
import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REPO, Home

ECHO = REPO / "tests" / "fixtures" / "adapters"
CONFIG = """[defaults]
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
USAGE = ("usage: ak worker MODEL TASK [--workspace DIR] [--out DIR] [--session ID]\n"
         "       [--role executor|reviewer|fixer|reviewer-pr|executor-scratch|"
         "fixer-scratch|reviewer-scratch]")
ROLES = "executor, reviewer, fixer, reviewer-pr, executor-scratch, fixer-scratch, reviewer-scratch"


class Refusals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        # A turn runs boxed with a /tmp of its own, so the adapter it runs lives outside /tmp,
        # and logs into the workspace the box lets it write.
        adapters = Path(tempfile.mkdtemp(prefix=".ak-test-key-worker-", dir=REPO))
        cls.addClassCleanup(shutil.rmtree, adapters, ignore_errors=True)
        shutil.copy(ECHO / "echo.toml", adapters / "echo.toml")
        shutil.copy(ECHO / "echo.sh", adapters / "logged-echo.sh")
        cls.ws = home.path / "ws"
        cls.ws.mkdir()
        cls.log = cls.ws / "adapter.log"
        script = adapters / "echo.sh"
        script.write_text(f'#!/bin/sh\necho "$*" >>"{cls.log}"\n'
                          f'exec "{adapters}/logged-echo.sh" "$@"\n')
        script.chmod(0o755)
        home.write(".agentkit/config.toml", CONFIG)
        cls.task = home.write("task.md", "say hi\n")
        cls.env = {"AGENTKIT_ADAPTER_DIR": str(adapters)}

    def worker(self, *args):
        return self.home.ak("worker", *args, env=self.env)

    def logged(self):
        return self.log.read_text() if self.log.exists() else ""

    def assertRefused(self, args, said):
        before = self.logged()
        done = self.worker(*args)
        self.assertEqual(done.code, 2, done.out)
        self.assertEqual(done.err, f"ak worker: {said}\n")
        self.assertEqual(self.logged(), before, "the adapter was called")

    def test_an_unknown_model_names_the_ones_the_config_defines(self):
        for task in ("task.md", str(self.task)):
            with self.subTest(task=task):
                self.assertRefused(("nosuch", task, "--workspace", str(self.ws)),
                                   "unknown model 'nosuch'; ~/.agentkit/config.toml defines: echo")

    def test_a_role_outside_the_seven_is_refused_with_the_seven(self):
        for role in ("bogus", "boss"):
            with self.subTest(role=role):
                self.assertRefused(("echo", "task.md", "--role", role),
                                   f"--role must be one of {ROLES} (got '{role}')")

    def test_a_missing_task_file_is_named_as_it_was_given(self):
        absent = str(self.home.path / "nothere.md")
        for task in ("missing.md", absent):
            with self.subTest(task=task):
                self.assertRefused(("echo", task, "--workspace", str(self.ws)),
                                   f"no such task file: {task}")

    def test_a_missing_workspace_is_named_by_its_absolute_path(self):
        for given in ("nope", str(self.home.path / "nows")):
            with self.subTest(workspace=given):
                self.assertRefused(("echo", "task.md", "--workspace", given),
                                   f"no such workspace: {self.home.path / Path(given).name}")

    def test_anything_but_a_model_and_a_task_prints_the_usage(self):
        for args in ((), ("echo",), ("echo", "task.md", "beta")):
            with self.subTest(args=args):
                self.assertRefused(args, USAGE)

    def test_an_unknown_flag_is_refused_with_the_usage_wherever_it_stands(self):
        for args in (("echo", "task.md", "--zzz"), ("--zzz",),
                     ("echo", "task.md", "--role", "boss", "--zzz")):
            with self.subTest(args=args):
                self.assertRefused(args, f"unknown flag '--zzz'; {USAGE}")

    def test_a_flag_that_takes_a_value_refuses_to_end_the_line(self):
        for flag in ("--out", "--role", "--session", "--workspace"):
            with self.subTest(flag=flag):
                self.assertRefused(("echo", "task.md", flag), f"{flag} needs a value")

    def test_a_well_formed_call_does_reach_the_adapter(self):
        before = self.logged()
        self.worker("echo", "task.md", "--workspace", str(self.ws),
                    "--out", str(self.home.path / "out"))
        self.assertNotEqual(self.logged(), before)


if __name__ == "__main__":
    unittest.main()
