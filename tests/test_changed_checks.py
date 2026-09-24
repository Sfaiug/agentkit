"""The reviewer sees changed checks first, with their committed diff stats. Entirely offline."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import run, worker


class ChangedChecks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".changed-checks-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull,
                                     "GIT_CONFIG_NOSYSTEM": "1"})
        env.start()
        self.addCleanup(env.stop)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        run.git(self.repo, "init", "-b", "main")
        run.git(self.repo, "config", "user.name", "fixture")
        run.git(self.repo, "config", "user.email", "fixture@localhost")
        self.write("app.py", "value = 1\n")
        self.write("tests/check.py", "assert value == 1\n")
        self.commit("baseline")
        self.base = run.git(self.repo, "rev-parse", "HEAD")

    def write(self, name, text):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message):
        run.git(self.repo, "add", ".")
        run.git(self.repo, "commit", "-m", message)

    def review_body(self, cmds=("true",), preface="", scratch=False):
        directory = self.root / "run"
        directory.mkdir()
        state = {"base": "main", "base_sha": self.base, "rounds": 1,
                 "executor": "executor", "reviewer": "reviewer", "round_summaries": [],
                 "scratch": scratch}
        body = "# Fixture task\n\n## Done when\n```bash\n" + "\n".join(cmds) + "\n```"
        lp = run.Loop({}, directory, state, {}, lambda text: None, self.repo, body,
                      list(cmds), body, [])
        lp.rnd = 1
        lp.validation = {} if scratch else run.commit_identity(self.repo)
        with patch.object(run, "review_providers", return_value=("provider-a", "provider-b")), \
                patch.object(run, "call_retrying",
                             return_value=(0, "VERDICT: PASS\n## Findings\n- none", None, False)) as call:
            self.assertEqual(run.review(lp, "Fixture summary", True,
                                        "$ true\n[exit 0]", preface), "PASS")
        call.assert_called_once()
        return call.call_args.args[2], body

    def check_lines(self, prompt):
        self.assertTrue(prompt.startswith("## Checks the executor changed\n```\n"), prompt)
        return prompt.split("```", 2)[1].strip().splitlines()

    def test_changed_test_file_is_listed_first_with_stat(self):
        self.write("tests/check.py", "assert value > 0\n")
        self.write("app.py", "value = 2\n")
        self.commit("change code and check")
        prompt, body = self.review_body(preface="Review after integration")
        lines = self.check_lines(prompt)
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^tests/check\.py\s+\|\s+2 \+-\s*$")
        self.assertLess(prompt.index("## Checks"), prompt.index("Review after integration"))
        self.assertLess(prompt.index("Review after integration"), prompt.index(body))
        self.assertIn("+value = 2", prompt)
        self.assertIn("## Executor summary\nFixture summary", prompt)
        self.assertIn("$ true\n[exit 0]", prompt)

    def test_file_named_in_done_when_is_listed_including_once(self):
        self.write("scripts/verify.sh", "exit 0\n")
        self.write("scripts/full check.sh", "exit 0\n")
        self.write("unrelated.py", "value = 2\n")
        self.commit("add command checks")
        prompt, _ = self.review_body(("bash ./scripts/verify.sh",
                                      "bash 'scripts/full check.sh' # once"))
        lines = self.check_lines(prompt)
        self.assertEqual(len(lines), 2)
        self.assertEqual({line.split("|", 1)[0].strip() for line in lines},
                         {"scripts/verify.sh", "scripts/full check.sh"})
        for line in lines:
            self.assertRegex(line, r"\|\s+1 \+\s*$")

    def test_nothing_is_added_when_no_check_changed(self):
        self.write("app.py", "value = 2\n")
        self.write("testing/check.py", "value = 3\n")
        self.commit("change only non-check files")
        prompt, body = self.review_body(("python3 tests/check.py",))
        self.assertNotIn("## Checks the executor changed", prompt)
        self.assertTrue(prompt.startswith(body + "\n\n## Diff"))

    def test_test_directories_and_filename_patterns(self):
        paths = ("test/check.sh", "pkg/tests/check.sh", "pkg/test/check.sh",
                 "test_root", "pkg/test_unit.py", "pkg/unit_test.js")
        for name in paths:
            self.write(name, "check\n")
        self.write("pkg/unit_test", "not a matching filename\n")
        self.commit("add checks in supported locations")
        prompt, _ = self.review_body()
        lines = self.check_lines(prompt)
        self.assertEqual({line.split("|", 1)[0].strip() for line in lines}, set(paths))
        self.assertEqual(len(lines), len(paths))

    def test_deleted_and_renamed_tests_stay_visible(self):
        (self.repo / "tests/check.py").rename(self.repo / "retired.py")
        self.commit("move check out of discovery")
        prompt, _ = self.review_body()
        lines = self.check_lines(prompt)
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^tests/check\.py\s+\|\s+1 -\s*$")

    def test_long_and_literal_paths_keep_their_full_stat_lines(self):
        name = "tests/" + "nested/" * 20 + "check[1].py"
        self.write(name, "check\n")
        self.commit("add deeply nested check")
        prompt, _ = self.review_body()
        lines = self.check_lines(prompt)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].split("|", 1)[0].strip(), name)
        self.assertRegex(lines[0], r"\|\s+1 \+\s*$")

    def test_scratch_review_does_not_add_checks(self):
        prompt, body = self.review_body(scratch=True)
        self.assertNotIn("## Checks the executor changed", prompt)
        self.assertTrue(prompt.startswith(body + "\n\n## Workspace"))

    def test_reviewer_preamble_carries_weakening_rule(self):
        sentence = ("A check the executor weakened, skipped or deleted is a FAIL unless "
                    "the task asked for exactly that.")
        self.assertEqual(worker.PREAMBLES["reviewer"].count(sentence), 1)


if __name__ == "__main__":
    unittest.main()
