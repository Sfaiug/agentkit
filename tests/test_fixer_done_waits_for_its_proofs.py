"""A fixer hears a failing earlier proof before it can close its turn."""

import json
import os
from pathlib import Path
import py_compile
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import hand_in, record, worker


class FixerDoneWaitsForItsProofs(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-fixer-proofs-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.workspace = self.root / "acme"
        self.workspace.mkdir()
        (self.workspace / "api.py").write_text("answer = 0\n")
        self.command = "python3 -c " + shlex.quote(
            "import api; assert api.answer == 1, 'answer is still wrong'")
        self.findings = [self.finding(self.command)]
        self.env = {**os.environ, "HOME": str(self.root), "AGENTKIT_RUN": "",
                    "AGENTKIT_RUN_DIR": "", "AGENTKIT_SESSION": "", "AK_PARENT_RUN": "",
                    "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
                    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": ""}
        self.start()

    def finding(self, command, line=1):
        return {"kind": "finding", "path": "api.py", "line": line, "what": "wrong answer",
                "why": "breaks callers", "evidence": {"run": command, "returncode": 1,
                                                        "output": "earlier failure"}}

    def start(self, role="fixer", previous=None):
        findings = self.root / "findings.json"
        findings.write_text(json.dumps(self.findings))
        self.file = Path(hand_in.start(self.root, self.workspace, previous=previous,
                                      role=role, findings=findings))
        self.env[hand_in.ENV] = str(self.file)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(REPO / "bin/ak"), "hand-in", *args],
                              cwd=self.workspace, env=self.env, capture_output=True,
                              text=True, timeout=30)

    def test_done_refuses_a_failing_proof_then_accepts_the_uncommitted_fix(self):
        before = self.file.read_bytes()
        result = self.cli("done")
        self.assertEqual(result.returncode, 2, result.stderr)
        for message in ("api.py:1", "wrong answer", "exit 1", "answer is still wrong",
                        "Fix the code", "ak hand-in dispute", "--run", "exits 0"):
            self.assertIn(message, result.stderr)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertFalse(hand_in.read(self.file).done)
        (self.workspace / "api.py").write_text("answer = 1\n")
        result = self.cli("done")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(hand_in.read(self.file).done)
        self.assertEqual((self.workspace / "api.py").read_text(), "answer = 1\n")

    def test_a_dispute_must_pass_and_then_skips_every_proof_at_its_site(self):
        self.findings.append(self.finding("touch replayed; exit 1"))
        self.start()
        result = self.cli("dispute", "api.py:1", "The proof uses an obsolete API.", "--run", "false")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.cli("done").returncode, 2)
        (self.workspace / "replayed").unlink()
        result = self.cli("dispute", "api.py:1", "The proof uses an obsolete API.", "--run", "true")
        self.assertEqual(result.returncode, 0, result.stderr)
        # A resumed fixer keeps the dispute that its previous turn handed in.
        self.start(previous=self.file)
        result = self.cli("done")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.workspace / "replayed").exists())
        self.assertEqual(len(hand_in.read(self.file).disputes), 1)

    def test_every_undisputed_proof_runs_and_reports_its_last_lines(self):
        self.findings = [self.finding("printf 'start\\n'; seq 1 30; exit 1"),
                         self.finding("touch second-proof; echo last failure; exit 7", line=2)]
        self.start()
        result = self.cli("done")
        self.assertEqual(result.returncode, 2, result.stderr)
        for message in ("api.py:1", "api.py:2", "exit 1", "exit 7", "29\n30", "last failure"):
            self.assertIn(message, result.stderr)
        self.assertNotIn("\nstart\n", result.stderr)
        self.assertTrue((self.workspace / "second-proof").exists())

    def test_a_proof_reads_the_working_file_even_with_stale_bytecode(self):
        path = self.workspace / "api.py"
        cache = self.workspace / "__pycache__" / f"api.{sys.implementation.cache_tag}.pyc"
        py_compile.compile(str(path), cfile=str(cache), doraise=True)
        stamp = path.stat().st_mtime_ns
        path.write_text("answer = 1\n")
        os.utime(path, ns=(stamp, stamp))
        result = self.cli("done")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_replaying_a_proof_adds_nothing_to_the_working_files(self):
        self.findings = [self.finding("python3 -c " + shlex.quote(
            "from pathlib import Path; assert {p.name for p in Path('.').iterdir()} == {'api.py'}"))]
        self.start()
        result = self.cli("done")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_quotes_and_other_roles_do_not_replay_proofs(self):
        for role in ("executor", "executor-scratch", "reviewer", "reviewer-pr", "reviewer-scratch"):
            with self.subTest(role=role):
                self.findings = [self.finding("touch wrong-role; exit 1")]
                self.start(role)
                self.assertEqual(self.cli("done").returncode, 0)
                self.assertFalse((self.workspace / "wrong-role").exists())
        self.findings[0]["evidence"] = {"quote": "answer = 0"}
        self.start()
        self.assertEqual(self.cli("done").returncode, 0)

    def test_unrunnable_or_signalled_proofs_allow_done_but_plain_exit_124_does_not(self):
        for command in ("exit 126", "exit 127", "kill -TERM $$", "exit 124"):
            with self.subTest(command=command):
                self.findings = [self.finding(command)]
                self.start("fixer-scratch")
                result = self.cli("done")
                self.assertEqual(result.returncode, 2 if command == "exit 124" else 0, result.stderr)

    def test_a_timed_out_proof_allows_done(self):
        self.findings = [self.finding("exec sleep 30")]
        self.start()
        with patch.dict(os.environ, self.env), patch.object(record, "CEILING_HOURS", 0), \
                patch.object(worker, "kill_marked"):
            self.assertEqual(hand_in.main(["done"]), 0)
        self.assertTrue(hand_in.read(self.file).done)

    def test_a_shell_that_cannot_start_allows_done(self):
        bindir = self.root / "proof-bin"
        bindir.mkdir()
        self.env["PATH"] = str(bindir)
        for missing in (True, False):
            with self.subTest(missing=missing):
                if not missing:
                    (bindir / "bash").write_text("unexecutable shell\n")
                self.start()
                result = self.cli("done")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_proof_cannot_close_the_fixer_turn(self):
        self.findings = [self.finding(
            f"{shlex.quote(sys.executable)} {shlex.quote(str(REPO / 'bin/ak'))} hand-in done")]
        self.start()
        result = self.cli("done")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("needs an active worker turn", result.stderr)
        self.assertFalse(hand_in.read(self.file).done)


if __name__ == "__main__":
    unittest.main()
