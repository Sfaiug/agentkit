"""A file a harness reads on its own and cannot be told not to (`[instructions] unswitched` in
its manifest) is refused, not read: a seat on that harness opens only while none of them exists,
since nothing but its rulebook may instruct it.  Offline: a temporary HOME, a fake adapter whose
manifest names one such file, and a second harness naming none.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch

CONFIG = """[tiers]
A = ["fixture", "bare"]
B = ["fixture", "bare"]

[models.fixture]
harness = "echo"
model = "echo-1"
effort = "low"
provider = "test"

[models.bare]
harness = "plain"
model = "plain-1"
effort = "low"
provider = "test"

[models.spark]
harness = "muse"
model = "muse-1"
effort = "low"
provider = "test"

[providers.test]
mode = "subscription"
"""
TUI = "#!/bin/sh\necho fake-tui\n"


class UnswitchedFiles(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-unswitched-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / ".agentkit/state").mkdir(parents=True)
        (self.home / ".agentkit/config.toml").write_text(CONFIG)
        adapters = self.home / "adapters"
        adapters.mkdir()
        shutil.copy2(REPO / "tests/fixtures/adapters/echo.toml", adapters / "echo.toml")
        (adapters / "plain.toml").write_text("version = 1\n")
        shutil.copy2(REPO / "adapters/muse.toml", adapters / "muse.toml")
        for name in ("echo", "plain", "muse"):
            (adapters / f"{name}.sh").write_text(TUI)
            (adapters / f"{name}.sh").chmod(0o755)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.home), config.ADAPTER_DIR_ENV: str(adapters), config.ACCOUNT_ENV: ""}))
        os.environ.pop(config.SESSION_ENV, None)
        self.stack.enter_context(patch.object(config, "HOME", self.home / ".agentkit"))
        self.stack.enter_context(patch.object(config, "STATE", self.home / ".agentkit/state"))
        self.cfg = config.load()
        self.rulebook = self.home / "rulebook.md"
        self.rulebook.write_text("# rules\n")
        self.file = self.home / ".echo/AGENTS.md"

    def command(self, model):
        return orch.command(self.cfg, model, rulebook=self.rulebook)

    def test_the_manifest_names_the_files_under_the_home(self):
        self.assertEqual(config.unswitched_files("echo"), [self.file])
        self.assertEqual(config.unswitched_files("plain"), [])

    def test_a_seat_opens_only_while_no_file_its_harness_reads_on_its_own_exists(self):
        self.assertEqual(self.command("fixture")[-1], "fake-tui")
        self.file.parent.mkdir()
        self.file.write_text("Always answer in verse.\n")
        with self.assertRaises(config.Error) as refused:
            self.command("fixture")
        self.assertIn(str(self.file), str(refused.exception))
        self.assertIn("move that file away", str(refused.exception))
        # a harness that names no such file is not refused for another's
        self.assertEqual(self.command("bare")[-1], "fake-tui")
        self.file.unlink()
        self.assertEqual(self.command("fixture")[-1], "fake-tui")

    def test_a_muse_seat_is_refused_for_codexs_own_file_too(self):
        # Muse's TUI reads Claude's and Codex's personal rules, and takes no switch for them
        codex = self.home / ".codex/AGENTS.md"
        codex.parent.mkdir()
        codex.write_text("Always answer in verse.\n")
        with self.assertRaises(config.Error) as refused:
            self.command("spark")
        self.assertIn(str(codex), str(refused.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
