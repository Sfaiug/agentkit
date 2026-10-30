"""A turn on a machine leaves the conversation it reported once its results came home, whatever
its exit, else the one it was given: a lost or killed turn's streamed id names a conversation that
is nowhere, and a retry resuming it would resume nothing, for ever.

Offline: a temporary HOME holding the conversation the turn resumes, and stand-ins for the
machine's ssh (`helper`) and the worker's watchdog, which streams an id.
"""

from contextlib import ExitStack
import io
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gitcall, helper, machine_turn

AWAY = SimpleNamespace(alias="acme", key="turn", image="acme", memory_mb=1024, repo="acme",
                       branch="main", default="main")


class ALostMachineKeepsTheConversationItHad(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="lost-machine-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        (self.home / ".acme").mkdir(parents=True)
        (self.home / ".acme/had.jsonl").write_text("had\n")
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "_read_toml",
                                         return_value={"turns_on_machines": True}))
        stack.enter_context(patch.object(config, "manifest", return_value={
            "worker": {"sessions": ["~/.acme/{id}*"]}}))
        stack.enter_context(patch.object(machine_turn, "_program",
                                         return_value=("acme/1.2.3/acme", {})))
        stack.enter_context(patch.object(machine_turn, "_lend", return_value=["login"]))
        stack.enter_context(patch.object(helper, "start", return_value=(AWAY, "")))
        stack.enter_context(patch.object(helper, "finish"))
        stack.enter_context(patch.object(gitcall, "git", return_value="left"))

    def leaves(self, watched, collected=None):
        """(exit, killed, session) of a turn resuming `had`, its ssh ending as `watched`
        (exit, killed), its results the files `collected`, None: the machine does not answer."""
        def remote(_alias, verb, *_args, **_kw):
            if verb != "collect":
                return ["ssh"]
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode="w") as tar:
                for name, content in (collected or {}).items():
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    tar.addfile(info, io.BytesIO(content))
            return SimpleNamespace(returncode=helper.LOST if collected is None else 0,
                                   stdout=data.getvalue())

        def watch(_argv, stdout, **_kw):
            stdout.write(b'{"session_id": "streamed"}\n')
            return watched[0], "", watched[1]

        with patch.object(helper, "_remote", remote):
            return machine_turn.call({"harness": "acme", "provider": "acme"}, ["run"], self.root,
                                     tempfile.mkdtemp(dir=self.root), {"HOME": str(self.home)},
                                     (), "had", watch)

    def test_a_lost_or_killed_turn_leaves_the_one_it_was_given(self):
        self.assertEqual(self.leaves((0, False)), (helper.LOST, False, "had"))
        self.assertEqual(self.leaves((helper.LOST, False), {}), (helper.LOST, False, "had"))
        self.assertEqual(self.leaves((124, True), {}), (124, True, "had"))

    def test_a_turn_whose_results_came_home_leaves_its_own_whatever_its_exit(self):
        self.assertEqual(self.leaves((0, False), {
            "code": b"255", "back.bundle": b"", "out/session_id": b"received",
            "home/.acme/received.jsonl": b"whole\n"}), (255, False, "received"))
        self.assertEqual((self.home / ".acme/received.jsonl").read_text(), "whole\n")


if __name__ == "__main__":
    unittest.main()
