"""A turn on a machine whose results did not come home leaves the run on the conversation it had:
the id it streamed names one that is nowhere, and a retry would resume nothing, for ever.

Offline: a temporary HOME, a fake harness `acme`, and a stand-in for the machine that streams an id
and returns as `agentkit/machine_turn.py` does.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, machine_turn, worker

CONFIG = """[defaults]
orchestrator = "acme"
workers = ["acme"]

[models.acme]
harness = "acme"
model = "acme-1"
effort = "low"
provider = "acme"

[providers.acme]
mode = "subscription"
"""


class ALostMachineKeepsTheConversationItHad(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="lost-machine-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "acme.sh").touch(0o755)
        (adapters / "acme.toml").write_text("version = 1\n")
        home = self.root / "home"
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(home), config.ADAPTER_DIR_ENV: str(adapters), "AGENTKIT_RUN": ""}))
        stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, home / name.lower()))
        stack.enter_context(patch.dict(config._MANIFESTS))
        stack.enter_context(patch.object(worker, "auth_ok", return_value=(True, "")))
        config.ensure_dirs()
        (home / "config.toml").write_text(CONFIG)
        self.cfg = config.load()

    def session_after(self, result, session):
        """The conversation `worker.call` says a machine's turn leaves, ended as `result`."""
        def away(_harness, _cmd, _cwd, out_dir, *_args):
            Path(out_dir, "events.jsonl").write_text('{"session_id": "streamed"}\n')
            return result

        with patch.object(machine_turn, "call", away):
            return worker.call(self.cfg, "acme", "do it", self.root,
                               tempfile.mkdtemp(dir=self.root), session=session)[2]

    def test_a_lost_or_killed_turn_goes_on_from_the_one_it_was_given(self):
        for result in ((machine_turn.LOST, False), (124, True)):
            with self.subTest(result=result):
                self.assertIsNone(self.session_after(result, None))
                self.assertEqual(self.session_after(result, "had"), "had")

    def test_a_turn_that_came_home_reports_its_own(self):
        for code in (0, 1):
            with self.subTest(code=code):
                self.assertEqual(self.session_after((code, False), "had"), "streamed")


if __name__ == "__main__":
    unittest.main()
