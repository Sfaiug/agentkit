"""A task's files: limits its own branch diff, including leftovers. Offline, with real Git."""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from agentkit import config, run


class FilesScope(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-files-scope-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.object(tempfile, "tempdir", str(self.root)))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
            "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "off"}))
        config.ensure_dirs()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        run.git(self.repo, "init", "-b", "main")
        run.git(self.repo, "config", "user.name", "fixture")
        run.git(self.repo, "config", "user.email", "fixture@localhost")
        self.write("src/api.py")
        self.write("notes.txt")
        self.commit("baseline")
        self.base = run.git(self.repo, "rev-parse", "HEAD")
        run.git(self.repo, "checkout", "-b", "ak/fix-api")

    def write(self, name, text="fixture\n"):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message):
        run.git(self.repo, "add", "-A")
        run.git(self.repo, "commit", "-m", message)

    def loop(self, front="", cmds=("true",)):
        directory = config.RUNS / "scope"
        directory.mkdir()
        body = "# Fix the api\n\n## Done when\n```bash\n" + "\n".join(cmds) + "\n```\n"
        (directory / "task.md").write_text(f"---\n{front}---\n{body}" if front else body)
        state = {"base": "main", "base_sha": self.base, "rounds": 1,
                 "executor": "opus", "reviewer": "astra", "round_summaries": []}
        lp = run.Loop(config.load(), directory, state, {}, lambda text: None,
                      self.repo, body, list(cmds), body, [])
        return lp

    def verify(self, lp, rnd=1):
        lp.rnd = rnd
        lp.round_dir.mkdir(exist_ok=True)
        return run.verify_work(lp)

    def test_in_scope_commits_and_leftovers_pass(self):
        lp = self.loop("files: :(glob)src/*.py, tests/\n")
        self.write("src/api.py", "changed\n")
        self.commit("fix api")
        self.write("tests/check.py")
        ok, text = self.verify(lp)
        self.assertTrue(ok, text)
        self.assertNotIn("outside files:", text)
        self.assertEqual(run.git(self.repo, "status", "--porcelain"), "")
        self.assertIn("tests/check.py", run.git(self.repo, "show", "--name-only", "HEAD"))

    def test_repeated_lines_keep_every_spec(self):
        lp = self.loop("files: src/, tests/\nfiles: docs/*.md  # also docs\n")
        for name in ("src/api.py", "tests/check.py", "docs/guide.md"):
            self.write(name, "changed\n")
        ok, text = self.verify(lp)
        self.assertTrue(ok, text)

    def test_outside_path_fails_and_is_saved_even_when_commands_pass(self):
        lp = self.loop("files: src/\n")
        self.write("src/api.py", "changed\n")
        self.write("notes.txt", "outside\n")
        ok, text = self.verify(lp)
        self.assertFalse(ok, text)
        self.assertIn("[exit 0]", text)
        self.assertEqual(text.splitlines()[-1], "outside files: notes.txt")
        self.assertEqual(run.first_failure(text), "outside files: notes.txt")
        self.assertEqual((lp.round_dir / "donewhen.log").read_text(), text)
        lp.state["step"] = "reviewer"
        self.assertEqual(run.settled_gate(lp), (False, text))

    def test_no_files_means_no_limit(self):
        lp = self.loop()
        self.write("notes.txt", "outside any proposed scope\n")
        self.write("other/new.txt")
        ok, text = self.verify(lp)
        self.assertTrue(ok, text)
        self.assertNotIn("outside files:", text)

    def test_rebase_counts_only_the_branchs_own_paths(self):
        lp = self.loop("files: src/\n")
        self.write("src/api.py", "changed\n")
        self.commit("fix api")
        run.git(self.repo, "checkout", "main")
        self.write("target.txt")
        self.commit("target moves")
        run.git(self.repo, "checkout", "ak/fix-api")
        run.git(self.repo, "rebase", "main")
        run.set_base(lp, "main")
        self.assertIn("target.txt", run.git(self.repo, "diff", "--name-only", f"{self.base}...HEAD"))
        ok, text = self.verify(lp)
        self.assertTrue(ok, text)
        self.write("notes.txt", "outside\n")
        ok, text = self.verify(lp)
        self.assertFalse(ok, text)
        self.assertEqual(text.splitlines()[-1], "outside files: notes.txt")

    def test_a_rename_counts_the_removed_and_added_paths(self):
        lp = self.loop("files: retired.py\n")
        (self.repo / "src/api.py").rename(self.repo / "retired.py")
        ok, text = self.verify(lp)
        self.assertFalse(ok, text)
        self.assertEqual(text.splitlines()[-1], "outside files: src/api.py")

    def test_git_literal_specs_preserve_whitespace_and_unicode_paths(self):
        lp = self.loop("files: :(literal) leading ü[1].txt\n")
        self.write(" leading ü[1].txt")
        self.commit("add literal path")
        ok, text = self.verify(lp)
        self.assertTrue(ok, text)
        self.write(" leading ü1.txt")
        self.commit("add outside path")
        ok, text = self.verify(lp)
        self.assertFalse(ok, text)
        self.assertEqual(text.splitlines()[-1], "outside files:  leading ü1.txt")

    def test_fixer_gets_the_line_and_reviewer_pass_is_overridden(self):
        lp = self.loop("files: src/\n")
        fixes = []

        def execute(lp, role, text, name, **_kw):
            lp.round_dir.mkdir(exist_ok=True)
            if role == "executor":
                self.assertIn("files: src/", text)
                self.write("src/api.py", "changed\n")
                self.write("notes.txt", "outside\n")
            else:
                fixes.append(text)
            return "## Summary\nFixture changes."

        with patch.object(run, "execute", side_effect=execute), \
                patch.object(run, "pickup_new_code", return_value=False), \
                patch.object(run, "call_retrying", side_effect=submitting((0, "VERDICT: PASS", None, False))), \
                patch.object(run, "review_providers", return_value=("provider-a", "provider-b")):
            run.rounds(lp)
        self.assertEqual(len(fixes), 1)
        self.assertIn("outside files: notes.txt", fixes[0])
        self.assertEqual(lp.state["verdict"], "FAIL")
        self.assertFalse(lp.state["review"]["done_when"])
        self.assertIn("overridden", lp.state["review"])

    def test_scope_note_does_not_hide_progress_on_a_failing_check(self):
        cmd = "cat src/message; false"
        lp = self.loop("files: src/\n", cmds=(cmd,))
        self.write("notes.txt", "outside\n")
        for rnd, message in enumerate(("AssertionError: first", "AssertionError: second"), 1):
            self.write("src/message", message + "\n")
            ok, text = self.verify(lp, rnd)
            self.assertFalse(ok, text)
            run.same_failure(lp, ok, text)
        self.assertEqual(run.failing_checks(text), [[cmd, message]])
        self.assertEqual(run.first_failure(text), f"`{cmd}` — {message}")

    def test_changed_outside_paths_do_not_hide_an_unchanged_check_failure(self):
        cmd = "cat src/message; false"
        lp = self.loop("files: src/\n", cmds=(cmd,))
        self.write("src/message", "AssertionError: unchanged\n")
        self.write("notes.txt", "outside\n")
        ok, text = self.verify(lp)
        run.same_failure(lp, ok, text)
        self.write("extra.txt", "also outside\n")
        ok, text = self.verify(lp, 2)
        self.assertFalse(ok, text)
        self.assertIn("outside files: extra.txt, notes.txt", text)
        with self.assertRaises(run.Blocked) as caught:
            run.same_failure(lp, ok, text)
        self.assertIn("AssertionError: unchanged", caught.exception.section)
        self.assertNotIn("outside files:", caught.exception.section)


if __name__ == "__main__":
    unittest.main(verbosity=2)
