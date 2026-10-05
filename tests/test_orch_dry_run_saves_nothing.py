"""`ak orch NAME --dry-run` leaves nothing behind, and without a terminal no seat opens.

A dry run only looks: no session record and no rulebook stay for a seat it never opened, so
the next real `ak orch NAME` creates that seat instead of resuming a record nobody launched;
and no rulebook a seat was opened with, nor what an adapter makes beside one, is changed, nor
the last notification a seat of that name sent, which only a start clears.

A real `ak orch NAME` for a seat that does not exist opens it only where a person types: an
agent has no terminal, so its guessed `ak orch help` gets the commands, not a new seat.

Offline: a temporary HOME, a tmux that holds no session, and fake adapters that write the
rulebook through the real tools/rulebook.py the way every adapter's `interactive` does.
"""

from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import os
from pathlib import Path
import subprocess
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
RESUME = orch.resume


class DryRun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-dry-run-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        bin_dir = self.bin = root / "bin"
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
        self.typed = stack.enter_context(patch.object(orch, "typed_here", return_value=True))

    def dry_run(self, argv, name):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.main([*argv, "--dry-run"]), 0)
        rulebook = config.rulebook_path(name)
        self.assertIn(f"/{rulebook.name}\n", out.getvalue())    # the adapter did write one
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

    def test_without_a_terminal_a_new_seat_is_refused_and_a_dry_run_still_looks(self):
        self.typed.return_value = False
        for argv in (["help"], [], ["acme-fix", "--model", "fable"]):
            with self.subTest(argv=argv), redirect_stdout(io.StringIO()) as out:
                with self.assertRaisesRegex(config.Error, r"opens only from a terminal[^\n]*\nusage: ak orch"):
                    orch.main(argv)
                self.assertEqual(out.getvalue(), "")
        self.launch.assert_not_called()
        self.assertEqual(orch.records(), {})
        self.dry_run(["acme-fix"], "acme-fix")

    def test_an_unnamed_dry_run_saves_nothing(self):
        self.dry_run([], "new")

    def state(self):
        return {str(path.relative_to(config.STATE)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in config.STATE.rglob("*") if path.is_file()}

    def test_a_dry_run_of_a_seat_tmux_lost_leaves_its_rulebook_as_it_was(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(orch.main(["acme-fix"]), 0)
        config.rulebook_path("acme-fix").write_text("the rules acme-fix was opened with\n")
        before = self.state()
        with patch.object(orch, "resume", RESUME), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.main(["acme-fix", "--dry-run"]), 0)
        self.assertIn("/rulebook-acme-fix.md\n", out.getvalue())
        self.assertEqual(self.state(), before)
        self.launch.assert_called_once()

    def test_a_dry_run_on_antigravity_leaves_no_agent_file(self):
        # the real adapter, which writes the agent.md every Antigravity seat is launched with
        (self.bin / "antigravity.sh").write_text(
            f'#!/bin/sh\nexec bash "{REPO}/adapters/antigravity.sh" "$@"\n')
        before = self.state()
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.main(["acme-fix", "--model", "gemini", "--dry-run"]), 0)
        self.assertIn("--agent agentkit", out.getvalue())
        self.assertEqual(self.state(), before)

    def test_a_dry_run_keeps_the_last_notification(self):
        notice = config.notify_path("acme-fix")
        notice.write_text('{"kind": "question", "summary": "merge acme?"}\n')
        self.dry_run(["acme-fix"], "acme-fix")
        self.assertEqual(notice.read_text(), '{"kind": "question", "summary": "merge acme?"}\n')

    def test_a_named_seat_opened_in_a_project_launches_with_its_rules(self):
        def git(cwd, *args):
            subprocess.run(["git", "-C", str(cwd), "-c", "user.name=Acme", "-c",
                            "user.email=acme@example.com", *args], check=True, capture_output=True)

        upstream, checkout = config.CODE / "acme-origin", config.CODE / "acme"
        git(config.CODE.parent, "init", "-q", "-b", "main", str(upstream))
        (upstream / "AGENTS.md").write_text("# Acme\n\nAcme release policy.\n")
        git(upstream, "add", "AGENTS.md")
        git(upstream, "commit", "-qm", "rules")
        git(config.CODE.parent, "clone", "-q", str(upstream), str(checkout))
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(checkout)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(orch.main(["acme-fix"]), 0)
        self.assertEqual(orch.records()["acme-fix"]["repo"], str(checkout))
        self.assertIn("Acme release policy.", config.rulebook_path("acme-fix").read_text())
        # a new seat by that name whose launch fails leaves the record it had as it was
        before = config.session_path("acme-fix").read_bytes()
        with patch.object(orch, "fresh_command", side_effect=config.Error("no harness")), \
                redirect_stdout(io.StringIO()), self.assertRaisesRegex(config.Error, "no harness"):
            orch.main(["acme-fix", "--model", "gemini"])
        self.assertEqual(config.session_path("acme-fix").read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
