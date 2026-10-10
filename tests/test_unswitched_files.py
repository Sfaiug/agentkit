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

[models.gemini]
harness = "antigravity"
model = "gemini-1"
effort = "low"
provider = "test"

[models.second]
harness = "acct"
model = "acct-1"
effort = "low"
provider = "test"

[providers.test]
mode = "subscription"
"""
TUI = "#!/bin/sh\necho fake-tui\n"
# an adapter that keeps an account's login in a home of its own, named on the seat's line
ACCOUNTED = ('#!/bin/sh\nif [ -n "${AGENTKIT_ACCOUNT:-}" ]; then printf \'env -u ACCT_KEY ACCT_HOME=%s/.acct-%s '
             'fake-tui\\n\' "$HOME" "$AGENTKIT_ACCOUNT"; else echo fake-tui; fi\n')
ACCOUNTED_MANIFEST = ('version = 1\n[instructions]\nunswitched = ["${ACCT_HOME:-~/.acct}/AGENTS.md", '
                      '"~/.acct-$AGENTKIT_ACCOUNT/AGENTS.md"]\n')


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
        for name in ("muse", "antigravity"):
            shutil.copy2(REPO / f"adapters/{name}.toml", adapters / f"{name}.toml")
        for name in ("echo", "plain", "muse", "antigravity"):
            (adapters / f"{name}.sh").write_text(TUI)
            (adapters / f"{name}.sh").chmod(0o755)
        (adapters / "acct.toml").write_text(ACCOUNTED_MANIFEST)
        (adapters / "acct.sh").write_text(ACCOUNTED)
        (adapters / "acct.sh").chmod(0o755)
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

    def command(self, model, account=None):
        return orch.command(self.cfg, model, rulebook=self.rulebook, account=account)

    def test_the_manifest_names_the_files_under_the_home(self):
        self.assertEqual(config.unswitched_files("echo", os.environ), [self.file, self.home / ".echo/rules"])
        self.assertEqual(config.unswitched_files("plain", os.environ), [])

    def test_an_accounts_own_home_is_looked_in_where_the_adapter_keeps_one(self):
        usual, second = self.home / ".acct/AGENTS.md", self.home / ".acct-II/AGENTS.md"
        # a worker turn's box hides the usual login's file and the account's own
        self.assertEqual(config.unswitched_files("acct", {"HOME": str(self.home)}), [usual])
        self.assertEqual(config.unswitched_files("acct", {"HOME": str(self.home), "AGENTKIT_ACCOUNT": "II"}),
                         [usual, second])
        # a seat is refused for the file in the home its own line runs the harness from
        usual.parent.mkdir()
        usual.write_text("Always answer in verse.\n")
        with self.assertRaises(config.Error) as refused:
            self.command("second")
        self.assertIn(str(usual), str(refused.exception))
        opened = self.command("second", account="II")
        self.assertIn(f"ACCT_HOME={self.home}/.acct-II", opened)
        usual.unlink()
        second.parent.mkdir()
        second.write_text("Always answer in verse.\n")
        self.assertEqual(self.command("second")[-1], "fake-tui")
        with self.assertRaises(config.Error) as refused:
            self.command("second", account="II")
        self.assertIn(str(second), str(refused.exception))

    def test_a_seat_opens_only_while_no_file_its_harness_reads_on_its_own_exists(self):
        self.assertEqual(self.command("fixture")[-1], "fake-tui")
        self.file.parent.mkdir()
        self.file.write_text("Always answer in verse.\n")
        with self.assertRaises(config.Error) as refused:
            self.command("fixture")
        self.assertIn(str(self.file), str(refused.exception))
        self.assertIn("move it away", str(refused.exception))
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

    def test_an_antigravity_seat_is_refused_for_its_global_rules_folder(self):
        # agy reads every rule in ~/.gemini/config/rules, and takes no switch for them
        rules = self.home / ".gemini/config/rules"
        rules.mkdir(parents=True)
        (rules / "style.md").write_text("Always answer in verse.\n")
        with self.assertRaises(config.Error) as refused:
            self.command("gemini")
        self.assertIn(str(rules), str(refused.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
