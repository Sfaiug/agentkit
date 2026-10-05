"""A hard exit during a probe cannot move the resumed run off its branch."""

from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, worker
from agentkit import record


@contextmanager
def sandbox(root):
    with ExitStack() as stack:
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, key, root / key.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        stack.enter_context(patch.object(worker, "kill_marked"))
        config.ensure_dirs()
        yield


def make_loop(root):
    directory = root / "run"
    lp = run.Loop(config.load(), directory, record.read_state(directory), {}, lambda _: None,
                  root / "acme", "# Fix empty input", ["PYTHONPATH=. python3 tests/check.py"],
                  "context", [])
    lp.artifacts.add("local-note")  # Existing gate output must survive without being committed.
    lp.rnd = 1
    return lp


def crash(root, probe, phase):
    with sandbox(root):
        real_git, real_out = run.git, run.git_out

        def git(repo, *args, **kwargs):
            if args[:3] == ("checkout", "--quiet", "--detach") and phase == "before":
                os._exit(73)
            if args == ("checkout", "--quiet", "ak/fix-api") and phase == "restore":
                os._exit(73)
            return real_git(repo, *args, **kwargs)

        def git_out(repo, *args, **kwargs):
            if args[:3] == ("checkout", "--quiet", "--detach") and phase == "before":
                os._exit(73)
            return real_out(repo, *args, **kwargs)

        def die(*_args, **_kwargs):
            wt = root / "acme"
            (wt / "tests/check.py").write_text("from broken import first\nassert first([]) is None\n")
            (wt / "keep.txt").write_text("probe edit\n")
            run.git(wt, "add", "tests/check.py", "keep.txt")
            (wt / "branch-only.txt").write_text("probe collision\n")
            (wt / "probe-output").write_text("probe output\n")
            os._exit(73)  # No finally runs, as after SIGKILL or a reboot.

        with patch.object(run, "git", side_effect=git), \
                patch.object(run, "git_out", side_effect=git_out), \
                patch.object(worker, "limited", side_effect=die):
            lp = make_loop(root)
            if phase != "restore":
                if probe == "target":
                    run.target_fails(lp, "main", "$ false\n[exit 1]\n")
                else:
                    run.regression_fails_before(lp)


class ProbeResume(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-probe-resume-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(sandbox(self.root))
        self.wt = self.root / "acme"
        self.wt.mkdir()
        run.git(self.wt, "init", "-qb", "main")
        run.git(self.wt, "config", "user.name", "Fixture")
        run.git(self.wt, "config", "user.email", "fixture@example.invalid")
        (self.wt / "tests").mkdir()
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0]\n")
        (self.wt / "tests/check.py").write_text("assert True\n")
        (self.wt / "keep.txt").write_text("keep\n")
        self.commit("Existing defect")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        run.git(self.wt, "checkout", "-qb", "ak/fix-api")
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        (self.wt / "tests/check.py").write_text("from broken import first\nassert first([]) is None\n")
        (self.wt / "branch-only.txt").write_text("branch\n")
        self.commit("Handle empty input")
        self.head = run.git(self.wt, "rev-parse", "HEAD")
        (self.wt / "local-note").write_text("pre-existing untracked file\n")
        self.directory = self.root / "run"
        (self.directory / "round-1").mkdir(parents=True)
        (self.directory / run.REGRESSION.parent).mkdir()
        (self.directory / run.REGRESSION).write_text("PYTHONPATH=. python3 tests/check.py\n")
        record.save_state(self.directory, {
            "run_id": "probe-test", "title": "fix api", "state": "running", "step": "done-when", "base": "main",
            "base_sha": self.base, "branch": "ak/fix-api", "rounds": 3,
            "review": {"verdict": "PASS", "done_when": True, "head_sha": self.head},
            "executor": "opus", "reviewer": "astra", "round_summaries": []})

    def commit(self, message):
        run.git(self.wt, "add", ".")
        run.git(self.wt, "commit", "-qm", message)

    def kill_probe(self, probe, phase="probe"):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--crash",
                                 str(self.root), probe, phase], cwd=REPO,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 73, result.stdout + result.stderr)

    def assert_restored(self):
        self.assertEqual(run.git(self.wt, "rev-parse", "HEAD"), self.head)
        self.assertEqual(run.git(self.wt, "symbolic-ref", "--short", "HEAD"), "ak/fix-api")
        self.assertEqual(run.git(self.wt, "diff", "HEAD"), "")
        self.assertEqual(run.git(self.wt, "ls-files", "--others", "--exclude-standard"), "local-note")
        self.assertEqual((self.wt / "branch-only.txt").read_text(), "branch\n")
        self.assertEqual((self.wt / "keep.txt").read_text(), "keep\n")
        self.assertEqual((self.wt / "local-note").read_text(), "pre-existing untracked file\n")
        self.assertNotIn("probe_checkout", record.read_state(self.directory))

    def resume_verification(self):
        lp = make_loop(self.root)
        ok, output = run.verify_work(lp)
        self.assertTrue(ok, output)
        self.assertEqual(lp.validation["head_sha"], self.head, "probe edits were committed")
        self.assert_restored()

    def test_dead_target_probe_resumes_verification_on_the_branch(self):
        self.kill_probe("target")
        self.assertEqual(run.git(self.wt, "rev-parse", "HEAD"), self.base)
        self.resume_verification()

    def test_dead_regression_probe_resumes_verification_on_the_branch(self):
        self.kill_probe("regression")
        self.assertEqual(run.git(self.wt, "rev-parse", "HEAD"), self.base)
        self.assertFalse(record.read_state(self.directory).get("regression_checked"))
        self.resume_verification()

    def test_checkout_is_recorded_before_detaching(self):
        self.kill_probe("regression", "before")
        self.assertIn("probe_checkout", record.read_state(self.directory))
        make_loop(self.root)
        self.assert_restored()

    def test_recovery_survives_a_second_hard_exit(self):
        self.kill_probe("target")
        self.kill_probe("target", "restore")
        self.assertIn("probe_checkout", record.read_state(self.directory))
        self.resume_verification()

    def test_failed_recovery_keeps_the_record_and_refuses_to_continue(self):
        real_git = run.git
        for failed in ("checkout", "clean"):
            with self.subTest(failed=failed):
                self.kill_probe("target")

                def refuse(repo, *args, **kwargs):
                    if args[:1] == (failed,):
                        if failed == "clean":
                            # One removable collision and one path Git could not remove.
                            real_git(repo, "clean", "--quiet", "-fd", "--", "branch-only.txt")
                        return ""
                    return real_git(repo, *args, **kwargs)

                with patch.object(run, "git", side_effect=refuse):
                    with self.assertRaises(config.Error):
                        make_loop(self.root)
                self.assertIn("probe_checkout", record.read_state(self.directory))
                self.resume_verification()

    def test_finished_probes_remove_the_recovery_record(self):
        lp = make_loop(self.root)
        with patch.object(run, "start_followups", return_value=None):
            self.assertTrue(run.target_fails(lp, "main", "$ false\n[exit 1]\n"))
        self.assert_restored()
        self.assertEqual(run.regression_fails_before(lp), "")
        self.assert_restored()


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--crash":
        crash(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
    else:
        unittest.main(verbosity=2)
