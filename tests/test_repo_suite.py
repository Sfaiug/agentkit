"""A repository's `tests:` suite runs once at landing."""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from agentkit import gate as check_gate, config, gc, host, run, worker

SUITE = 'test -f AGENTS.md && printf "piece %s\\n" "${AK_SHARD:-all}"'


class RepoSuite(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-repo-suite-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), config.SESSION_ENV: "", config.RUN_DIR_ENV: "", "AK_RUN_DEPTH": "0",
            "AK_MAX_RUNS": "0", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        config.ensure_dirs()
        self.cfg = config.load()
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Suite test")
        self.git("config", "user.email", "suite@localhost")
        self.opts = {"--rounds": None, "--exec": None, "--review": None,
                     "--no-worktree": False, "--no-merge": False}
        self.logs, self.gates = [], []
        self.pieces = []
        self.stack.enter_context(patch.object(host, "host_readings", return_value={
            "cpus": 4, "load": 0, "free_mb": 820}))
        limited = worker.boxed
        def command(cmd, limit, **kw):
            if cmd == ["bash", "-c", SUITE]:
                self.pieces.append(kw["env"].get("AK_SHARD"))
            return limited(cmd, limit, **kw)
        self.stack.enter_context(patch.object(worker, "boxed", side_effect=command))
        for module, name, value in ((gc, "disk_pressure", False), (run, "launch_session", None),
                                    (run, "collect_usage", {}), (run, "pick_models", ("opus", "astra"))):
            self.stack.enter_context(patch.object(module, name, return_value=value))
        self.stack.enter_context(patch.object(run.usage, "pick_order",
                                             return_value=["opus", "astra"]))
        self.stack.enter_context(patch.object(worker, "call", side_effect=submitting(self.worker)))
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub")))
        # delivery is only its final check here: no remote, no PR
        self.stack.enter_context(patch.object(
            run, "merge", side_effect=lambda lp: run.final_check(lp, "origin/main")))
        gate = check_gate.run_done_when

        def record(cmds, cwd, log_path, *args, **kwargs):
            self.gates.append((Path(log_path).name, list(cmds)))
            return gate(cmds, cwd, log_path, *args, **kwargs)
        self.stack.enter_context(patch.object(check_gate, "run_done_when", side_effect=record))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, agents):
        (self.repo / "AGENTS.md").write_text(agents)
        self.git("add", "AGENTS.md")
        self.git("commit", "-q", "-m", "fixture")

    def add_origin(self):
        origin = self.root / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True,
                       capture_output=True, text=True)
        self.git("remote", "add", "origin", str(origin))

    def worker(self, cfg, name, body, workspace, out_dir, role, session, **kwargs):
        text = ("VERDICT: PASS\n## Findings\n- none" if role.startswith("reviewer")
                else "## Summary\nFixture execution.")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "final.md").write_text(text)
        return 0, text, "fixture-session", False

    def launch(self, name, checks, front="base: main\n", from_branch="", expected="pass"):
        directory = config.RUNS / name
        directory.mkdir()
        task = directory / "task.md"
        task.write_text(f"---\nrepo: {self.repo}\n{front}from: {from_branch}\nrounds: 1\n---\n# Suite once\n\n"
                        "## Goal\nShip it.\n\n## Done when\n```bash\n"
                        + "\n".join(checks) + "\n```\n")
        state = run.loop(self.cfg, directory, task, self.opts, self.logs.append)
        self.assertEqual(state["state"], expected, self.logs)
        return state

    def rounds(self):
        return [cmds for name, cmds in self.gates if name == "donewhen.log"]

    def finals(self):
        return [cmds for name, cmds in self.gates if name == "final-check.log"]

    def test_declared_suite_runs_at_landing(self):
        self.commit(f"---\nusers: none\ntests: {SUITE}\n---\n# acme\n")
        state = self.launch("declared", ["true"])
        self.assertTrue(self.rounds())
        self.assertTrue(all(SUITE not in cmds for cmds in self.rounds()), self.gates)
        self.assertNotIn("once.log", [name for name, _ in self.gates])
        self.assertEqual(self.finals(), [["true"], [SUITE]], self.gates)
        self.assertCountEqual(self.pieces, ["1/2", "2/2"])
        self.assertEqual(state["final_check"]["outcome"], "passed")
        self.assertEqual(state["final_check"]["where"], "landing")

    def test_rebased_landing_replaces_the_loaded_suite(self):
        task_once = "test -d ."
        for mode in ("landing", "probe"):
            with self.subTest(mode=mode):
                old_suite = f"echo old suite {mode}"
                self.gates.clear()
                self.pieces.clear()
                self.commit(f"---\ntests: {old_suite}\n---\n# acme\n")
                base = self.git("rev-parse", "HEAD")
                self.git("update-ref", "refs/remotes/origin/main", base)
                suite = SUITE + (" && test ! -f broken.txt" if mode == "probe" else "")

                def rebased_check(lp):
                    self.assertEqual(lp.every, ["true"])
                    self.assertEqual(lp.once, [task_once, old_suite])
                    (lp.wt / "work.txt").write_text("work\n")
                    run.git(lp.wt, "add", "work.txt")
                    run.git(lp.wt, "commit", "-q", "-m", "work")
                    before = run.git(lp.wt, "rev-parse", "HEAD")
                    if mode == "probe":
                        (self.repo / "broken.txt").write_text("broken\n")
                        self.git("add", "broken.txt")
                    self.commit(f"---\ntests: {suite}\n---\n# acme\n")
                    tip = self.git("rev-parse", "HEAD")
                    self.git("update-ref", "refs/remotes/origin/main", tip)
                    run.git(lp.wt, "rebase", "origin/main")
                    self.assertNotEqual(run.git(lp.wt, "rev-parse", "HEAD"), before)
                    self.assertEqual(run.declared_suite(lp.wt, lp.target), suite)
                    self.assertEqual(run.final_check(lp, "origin/main"), mode != "probe")
                    self.assertEqual(lp.every, ["true"])
                    self.assertEqual(lp.once, [task_once, suite])

                with patch.object(run, "merge", side_effect=rebased_check), \
                        patch.object(run, "start_followups", return_value=None):
                    state = self.launch(f"rebased-{mode}", ["true", f"{task_once}  # once"],
                                        expected="waiting" if mode == "probe" else "pass")
                self.assertEqual(self.finals(), [["true"], [task_once, suite]], self.gates)
                ran = [cmd for _, cmds in self.gates for cmd in cmds]
                self.assertNotIn(old_suite, ran)
                self.assertEqual(ran.count(suite), 1)
                if mode == "probe":
                    text = (config.RUNS / "rebased-probe" / "target-probe.log").read_text()
                    self.assertIn(f"$ {suite} (on origin/main ", text)
                    self.assertIn("--- AK_SHARD=2/2 ---", text)
                    self.assertNotIn(old_suite, text)
                else:
                    self.assertCountEqual(self.pieces, ["1/2", "2/2"])
                    self.assertEqual(state["final_check"]["outcome"], "passed")

    def test_done_when_line_identical_to_the_suite_runs_once(self):
        self.commit(f"---\ntests: {SUITE}\n---\n# acme\n")
        for name, line in (("plain", SUITE), ("marked", f"{SUITE}  # once")):
            with self.subTest(line=line):
                self.gates.clear()
                state = self.launch(name, ["true", line])
                ran = [cmd for _, cmds in self.gates for cmd in cmds]
                self.assertEqual(ran.count(SUITE), 1, self.gates)
                self.assertNotIn("once.log", [name for name, _ in self.gates])
                self.assertEqual(self.finals(), [["true"], [SUITE]], self.gates)
                self.assertEqual(state["final_check"]["where"], "landing")

    def test_repository_without_tests_runs_exactly_its_done_when(self):
        self.commit("# acme\n\nNo front matter here.\n")
        self.launch("undeclared", ["true", "test -d .  # once"])
        self.assertTrue(self.rounds())
        self.assertTrue(all(cmds == ["true"] for cmds in self.rounds()), self.gates)
        self.assertEqual(self.finals(), [["true"], ["test -d ."]], self.gates)

    def test_checkout_without_tests_falls_back_to_origin_main(self):
        self.add_origin()
        self.commit(f"---\ntests: {SUITE}\n---\n# acme\n")
        self.git("push", "-q", "-u", "origin", "main")
        self.git("fetch", "-q", "origin")
        self.commit("# acme\n\nNo front matter here.\n")
        # Fresh runs start at origin/main; resume the local commit to exercise fallback.
        for name, line in (("fallback-plain", SUITE),
                           ("fallback-marked", f"{SUITE}  # once")):
            with self.subTest(line=line):
                self.gates.clear()
                self.launch(name, ["true", line], from_branch="main")
                ran = [cmd for _, cmds in self.gates for cmd in cmds]
                self.assertEqual(ran.count(SUITE), 1, self.gates)
                self.assertTrue(all(SUITE not in cmds for cmds in self.rounds()),
                                self.gates)
                self.assertNotIn("once.log", [name for name, _ in self.gates])
                self.assertEqual(self.finals(), [["true"], [SUITE]], self.gates)

    def test_checkout_tests_wins_over_origin_main(self):
        origin_suite = "test -d ."
        self.add_origin()
        self.commit(f"---\ntests: {origin_suite}\n---\n# acme\n")
        self.git("push", "-q", "-u", "origin", "main")
        # a run is cut from its base as origin has it, so the checkout's own line is its
        # base branch's, and its target's is another
        self.git("checkout", "-q", "-b", "feature")
        self.commit(f"---\ntests: {SUITE}\n---\n# acme\n")
        self.git("push", "-q", "-u", "origin", "feature")
        self.launch("own-wins", ["true"], front="base: feature\ntarget: main\n")
        self.assertTrue(self.rounds())
        self.assertTrue(all(SUITE not in cmds for cmds in self.rounds()), self.gates)
        self.assertNotIn("once.log", [name for name, _ in self.gates])
        self.assertEqual(self.finals(), [["true"], [SUITE]], self.gates)
        ran = [cmd for _, cmds in self.gates for cmd in cmds]
        self.assertNotIn(origin_suite, ran, self.gates)

    def test_review_pr_still_runs_declared_tests(self):
        self.commit(f"---\ntests: {SUITE}\n---\n# acme\n")
        head = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", head)
        directory = config.RUNS / "pr-review"
        directory.mkdir()
        info = {"state": "OPEN", "headRefOid": head, "baseRefName": "main",
                "title": "Suite once", "author": "fixture", "body": "Fixture PR description"}
        with patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "checkout_for", return_value=self.repo), \
                patch.object(run, "fetch", return_value=(0, "")), \
                patch.object(run, "post_review", return_value=True), \
                patch.object(run, "checks", return_value=(False, "fixture: no merge")), \
                patch.object(run, "gh_json", return_value=(info, "")):
            state = run.review_pr(self.cfg, directory, "https://github.com/acme/acme/pull/1",
                                  {**self.opts, "--no-merge": True}, self.logs.append)
        self.assertEqual(state["state"], "pass", self.logs)
        self.assertEqual(self.rounds(), [[SUITE]])
        self.assertEqual(self.finals(), [])


if __name__ == "__main__":
    unittest.main()
