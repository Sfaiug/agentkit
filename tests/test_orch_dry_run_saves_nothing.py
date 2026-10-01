"""`ak orch NAME --dry-run` for a new seat leaves nothing behind.

A dry run only looks: no session record and no rulebook stay for a seat it never opened, so
the next real `ak orch NAME` creates that seat instead of resuming a record nobody launched.

Offline: a temporary HOME, a tmux that holds no session, and fake adapters that write the
rulebook through the real tools/rulebook.py the way every adapter's `interactive` does.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, terminal, usage

FAKE_ADAPTER = f"""#!/bin/sh
[ "$1" = interactive ] || exit 2
rb=$(python3 "{REPO}/tools/rulebook.py" "$AGENTKIT_SESSION") || exit 2
echo "fake-tui --rules $rb"
"""


class DryRun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-dry-run-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        (bin_dir / "tmux").write_text("#!/bin/sh\nexit 1\n")    # no server: no session at all
        for harness in (path.stem for path in (REPO / "adapters").glob("*.toml")):
            (bin_dir / f"{harness}.sh").write_text(FAKE_ADAPTER)
        for path in bin_dir.iterdir():
            path.chmod(0o755)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "NO_COLOR": "1", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "PATH": f"{bin_dir}:{os.environ['PATH']}", config.ADAPTER_DIR_ENV: str(bin_dir)}))
        os.environ.pop(config.SESSION_ENV, None)
        # where rulebook.py, a process of its own, finds them under this HOME
        home = root / ".agentkit"
        stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            stack.enter_context(patch.object(config, name, home / name.lower()))
        stack.enter_context(patch.object(config, "CODE", root / "code"))
        config.ensure_dirs()
        stack.enter_context(patch.object(usage, "collect", return_value={}))
        stack.enter_context(patch.object(terminal.Keyboard, "take", return_value=False))
        stack.enter_context(patch.object(terminal, "readline", return_value=""))
        self.launch = stack.enter_context(patch.object(orch, "launch"))
        self.resume = stack.enter_context(patch.object(orch, "resume", return_value=0))
        stack.enter_context(patch.object(orch, "attach", return_value=0))
        stack.enter_context(patch.object(orch, "maintenance"))

    def dry_run(self, argv, name):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.main([*argv, "--dry-run"]), 0)
        rulebook = config.rulebook_path(name)
        self.assertIn(f"--rules {rulebook}", out.getvalue())    # the adapter did write one
        self.assertFalse(config.session_path(name).exists())
        self.assertNotIn(name, orch.records())
        self.assertFalse(rulebook.exists())
        self.launch.assert_not_called()

    def test_a_dry_run_of_a_new_seat_saves_nothing_and_the_real_one_creates_it(self):
        self.dry_run(["acme-fix"], "acme-fix")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(orch.main(["acme-fix"]), 0)
        self.resume.assert_not_called()
        self.launch.assert_called_once()
        self.assertIn("acme-fix", orch.records())

    def test_an_unnamed_dry_run_saves_nothing(self):
        self.dry_run([], "new")


if __name__ == "__main__":
    unittest.main(verbosity=2)
