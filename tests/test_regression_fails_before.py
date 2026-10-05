"""A fix's real regression passes on HEAD, fails on base, and leaves HEAD clean."""

from contextlib import ExitStack
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from agentkit import config, run, worker
from agentkit import record


class RegressionFailsBefore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-regression-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.stack.enter_context(patch.object(worker, "kill_marked"))
        config.ensure_dirs()
        self.cfg = config.load()
        self.wt = self.root / "acme"
        self.wt.mkdir()
        run.git(self.wt, "init", "-qb", "main")
        run.git(self.wt, "config", "user.name", "Fixture")
        run.git(self.wt, "config", "user.email", "fixture@example.invalid")
        (self.wt / "tests").mkdir()
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0]\n")
        (self.wt / "keep.txt").write_text("base\n")
        (self.wt / "tests/check.py").write_text("assert True\n")
        (self.wt / "tests/removed.py").write_text("assert True\n")
        self.commit("Existing defect")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        run.git(self.wt, "checkout", "-qb", "ak/fix-api")
        self.directory = self.root / "run files"
        (self.directory / "round-1").mkdir(parents=True)
        self.script = self.directory / run.REGRESSION
        self.script.parent.mkdir()
        self.logs = []

    def commit(self, message):
        run.git(self.wt, "add", ".")
        run.git(self.wt, "commit", "-qm", message)

    def loop(self, cmds=None, state=None):
        if state is None:
            workers = self.cfg["defaults"]["workers"]
            executor = workers[0]
            reviewer = next(n for n in workers if config.model(self.cfg, n)["provider"] !=
                            config.model(self.cfg, executor)["provider"])
            state = {"run_id": "regression-test", "state": "running", "base": "main",
                     "base_sha": self.base, "branch": "ak/fix-api", "rounds": 3,
                     "executor": executor, "reviewer": reviewer, "round_summaries": []}
            record.save_state(self.directory, state)
        cmds = cmds if cmds is not None else [f"bash {shlex.quote(str(self.script))}"]
        lp = run.Loop(self.cfg, self.directory, state, {}, self.logs.append, self.wt,
                      "# Fix empty input", cmds, "context", [])
        lp.rnd = 1
        return lp

    def assert_restored(self, head):
        self.assertEqual(run.git(self.wt, "rev-parse", "HEAD"), head)
        self.assertEqual(run.git(self.wt, "symbolic-ref", "--short", "HEAD"), "ak/fix-api")
        self.assertEqual(run.git(self.wt, "status", "--porcelain"), "")

    def test_passing_everywhere_fails_the_gate_even_when_the_reviewer_passes(self):
        self.script.write_text("exit 0\n")
        lp = self.loop()
        head = run.git(self.wt, "rev-parse", "HEAD")
        ok, text = run.verify_work(lp)
        self.assertFalse(ok, "exit 0 passed the regression gate")
        self.assertIn(f"regression.sh passes on base {self.base}: it does not show the defect", text)
        self.assert_restored(head)
        lp.state["step"] = "reviewer"
        self.assertIsNone(run.settled_gate(lp))
        with patch.object(run, "call_retrying", side_effect=submitting((0, "VERDICT: PASS", None, False))):
            self.assertEqual(run.review(lp, "Fixture summary", ok, text), "FAIL")

    def test_a_run_started_before_the_check_had_its_folder_keeps_its_gate(self):
        legacy = self.directory / "regression.sh"
        legacy.write_text("exit 0\n")
        lp = self.loop([f"bash {shlex.quote(str(legacy))}"])
        ok, text = run.verify_work(lp)
        self.assertFalse(ok, "exit 0 passed the regression gate")
        self.assertIn(f"regression.sh passes on base {self.base}: it does not show the defect", text)
        lp.state["step"] = "reviewer"
        self.assertIsNone(run.settled_gate(lp))

    def test_real_regression_is_red_then_green_and_probed_once_across_resume(self):
        (self.wt / "tests/check.py").write_text("from broken import first\nassert first([]) is None\n")
        (self.wt / "tests/check [1].py").write_text("from broken import first\nassert first([]) is None\n")
        (self.wt / "tests/removed.py").unlink()
        self.script.write_text(
            "set -e\nexport PYTHONPATH=.\n"
            "test ! -e tests/removed.py || exit 0\n"
            "if ! git symbolic-ref -q HEAD >/dev/null; then\n"
            "  echo probe > probe-output\n  echo probe > keep.txt\nfi\n"
            "python3 tests/check.py\npython3 'tests/check [1].py'\necho 'empty input passed'\n")
        before = subprocess.run(["bash", str(self.script)], cwd=self.wt, capture_output=True, text=True)
        self.assertNotEqual(before.returncode, 0)
        self.assertIn("IndexError", before.stderr)
        (self.wt / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        self.commit("Handle empty input")
        head = run.git(self.wt, "rev-parse", "HEAD")
        lp = self.loop()
        ok, text = run.verify_work(lp)
        self.assertTrue(ok, text)
        base_output = (self.directory / "regression-base.log").read_text()
        self.assertIn(self.base, base_output)
        self.assertIn("[exit 1]", base_output)
        self.assertIn("IndexError", base_output)
        self.assertIn("[exit 0]", text)
        self.assertIn("empty input passed", text)
        self.assert_restored(head)
        lp.state["step"] = "reviewer"
        self.assertEqual(run.settled_gate(lp), (True, text))
        resumed = self.loop(state=record.read_state(self.directory))
        with patch.object(worker, "limited", wraps=worker.limited) as limited:
            self.assertTrue(run.verify_work(resumed)[0])
        self.assertEqual(len(limited.call_args_list), 1, "base was probed again after resume")
        self.assertEqual((self.directory / "regression-base.log").read_text(), base_output)
        self.assert_restored(head)

    def test_base_bytecode_does_not_leak_into_done_when_on_head(self):
        module = self.wt / "same.py"
        module.write_text('value = "base"\n')
        (self.wt / ".gitignore").write_text("__pycache__/\n")
        self.commit("Add same-size fixture")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        size = module.stat().st_size
        module.write_text('value = "head"\n')
        self.assertEqual(module.stat().st_size, size)
        # Equal whole-second mtimes make the base's bytecode look valid on HEAD.
        (self.wt / "tests/check.py").write_text(
            'import os\nos.utime("same.py", (1700000000, 1700000000))\n'
            'import same\nprint("saw", same.value)\nassert same.value == "head", same.value\n')
        self.script.write_text("PYTHONPATH=. python3 tests/check.py\n")
        self.commit("Change the fixture without changing its size")
        head = run.git(self.wt, "rev-parse", "HEAD")
        lp = self.loop()
        with patch.dict(os.environ, {"PYTHONDONTWRITEBYTECODE": "", "PYTHONPYCACHEPREFIX": ""}):
            self.assertEqual(run.regression_fails_before(lp), "")
            self.assertTrue(record.read_state(self.directory)["regression_checked"])
            base_output = (self.directory / "regression-base.log").read_text()
            self.assertIn("saw base", base_output)
            self.assertIn("[exit 1]", base_output)
            self.assert_restored(head)
            ok, text = run.verify_work(lp)
            self.assertTrue(ok, text)
            self.assertIn("saw head", text)
        self.assertTrue(list((self.wt / "__pycache__").glob("same.*.pyc")))
        self.assert_restored(head)

    def test_a_branch_changing_only_tests_is_proven_on_base_as_it_is(self):
        (self.wt / "tests/check.py").write_text("assert False, 'flaky'\n")
        self.commit("Flaky check")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        (self.wt / "tests/check.py").write_text("assert True\n")
        self.commit("Fix the flaky check")
        head = run.git(self.wt, "rev-parse", "HEAD")
        self.script.write_text("python3 tests/check.py\n")
        lp = self.loop()
        self.assertEqual(run.regression_fails_before(lp), "")
        self.assertIn("flaky", (self.directory / "regression-base.log").read_text())
        self.assert_restored(head)

    def test_other_runs_and_failing_done_when_do_not_probe(self):
        lp = self.loop(["true"])
        self.assertTrue(run.verify_work(lp)[0])
        self.assertFalse((self.directory / "regression-base.log").exists())
        self.script.write_text("exit 0\n")
        lp = self.loop(["false"])
        self.assertFalse(run.verify_work(lp)[0])
        self.assertFalse((self.directory / "regression-base.log").exists())
        self.assert_restored(self.base)

    def test_interrupted_probe_restores_the_branch_without_recording_success(self):
        self.script.write_text("exit 0\n")
        lp = self.loop(["true"])
        limited = worker.limited

        def interrupt(cmd, *args, **kwargs):
            if cmd == ["bash", "-c", f"bash {shlex.quote(str(self.script))}"]:
                (self.wt / "broken.py").write_text("probe\n")
                (self.wt / "probe-output").write_text("probe\n")
                raise run.Stopped("fixture stop")
            return limited(cmd, *args, **kwargs)

        with patch.object(worker, "limited", side_effect=interrupt):
            with self.assertRaises(run.Stopped):
                run.verify_work(lp)
        self.assert_restored(self.base)
        self.assertFalse(record.read_state(self.directory).get("regression_checked"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
