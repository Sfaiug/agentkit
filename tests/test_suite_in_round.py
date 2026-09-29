"""The suite runs in the round alongside the review, and at landing only on overlap."""

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
from agentkit import config, run, worker

SUITE = "test -f AGENTS.md"


class SuiteInRound(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".suite-round-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            config.SESSION_ENV: "", config.RUN_DIR_ENV: "", "AK_RUN_DEPTH": "0",
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
        self.logs, self.gates, self.prompts = [], [], []
        for name, value in (("disk_pressure", False), ("launch_session", None),
                            ("collect_usage", {}), ("pick_models", ("opus", "astra"))):
            self.stack.enter_context(patch.object(run, name, return_value=value))
        self.stack.enter_context(patch.object(run.usage, "pick_order",
                                             return_value=["opus", "astra"]))
        self.stack.enter_context(patch.object(worker, "call", side_effect=self.worker))
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub")))
        self.stack.enter_context(patch.object(
            run, "merge", side_effect=lambda lp: run.final_check(lp, "origin/main")))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self, agents):
        (self.repo / "AGENTS.md").write_text(agents)
        self.git("add", "AGENTS.md")
        self.git("commit", "-q", "-m", "fixture")

    def worker(self, cfg, name, body, workspace, out_dir, role, session, **kwargs):
        self.prompts.append((role, body))
        text = ("VERDICT: PASS\n## Findings\n- none" if role.startswith("reviewer")
                else "## Summary\nFixture execution.")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "final.md").write_text(text)
        return 0, text, "fixture-session", False

    def launch(self, name, checks, rounds=1, gate=None):
        directory = config.RUNS / name
        directory.mkdir()
        task = directory / "task.md"
        task.write_text(f"---\nrepo: {self.repo}\nbase: main\nrounds: {rounds}\n---\n# Suite round\n\n"
                        "## Goal\nShip it.\n\n## Done when\n```bash\n"
                        + "\n".join(checks) + "\n```\n")
        real = run.run_done_when

        def record(cmds, cwd, log_path, *args, **kwargs):
            self.gates.append((Path(log_path).name, list(cmds)))
            if gate is not None:
                mocked = gate(cmds, cwd, log_path, *args, **kwargs)
                if mocked is not None:
                    return mocked
            return real(cmds, cwd, log_path, *args, **kwargs)

        with patch.object(run, "run_done_when", side_effect=record):
            state = run.loop(self.cfg, directory, task, self.opts, self.logs.append)
        return directory, state

    def test_suite_runs_in_the_round_and_landing_skips_on_a_still_target(self):
        self.commit(f"---\nusers: none\ntests: {SUITE}\n---\n# acme\n")
        directory, state = self.launch("in-round", ["true"])
        self.assertEqual(state["state"], "pass", self.logs)
        kinds = [name for name, _ in self.gates]
        self.assertIn("donewhen.log", kinds)
        self.assertIn("once.log", kinds)
        self.assertNotIn("final-check.log", kinds, self.gates)
        suites = [cmds for name, cmds in self.gates if name == "once.log"]
        self.assertEqual(suites, [[SUITE]])
        rounds = [cmds for name, cmds in self.gates if name == "donewhen.log"]
        self.assertTrue(all(SUITE not in cmds for cmds in rounds), self.gates)
        self.assertEqual(state["final_check"]["outcome"], "passed")
        self.assertEqual(state["final_check"]["where"], "round")
        self.assertEqual(state["final_check"]["round"], 1)
        result = (directory / "result.md").read_text()
        self.assertIn(f"{SUITE} (once, in round 1)", result)
        self.assertIn("final check: passed in round 1 on ", result)
        self.assertIn("in round 1", run.status_final_check(directory, state))
        log = "\n".join(self.logs)
        self.assertIn("suite: all passed", log)
        self.assertIn("already passed in round 1", log)

    def test_failing_suite_fails_the_round_and_reaches_the_fixer_with_findings(self):
        self.commit(f"---\ntests: {SUITE}\n---\n# acme\n")
        calls = []

        def gate(cmds, cwd, log_path, *args, **kwargs):
            if Path(log_path).name != "once.log":
                return None
            calls.append(list(cmds))
            if len(calls) == 1:
                return False, "$ test -f AGENTS.md\n[exit 1]\nFAIL 1 the suite broke"
            return None

        directory, state = self.launch("suite-fail", ["true"], rounds=2, gate=gate)
        self.assertEqual(state["state"], "pass", self.logs)
        self.assertEqual([e["verdict"] for e in state["round_summaries"]], ["FAIL", "PASS"])
        self.assertIn("the reviewer said PASS while the suite is failing", "\n".join(self.logs))
        fixers = [body for role, body in self.prompts if role == "fixer"]
        self.assertTrue(fixers, self.prompts)
        self.assertIn("## Reviewer findings to fix", fixers[0])
        self.assertIn("## The suite checks failed. Fix the root cause.", fixers[0])
        self.assertIn("FAIL 1 the suite broke", fixers[0])
        self.assertEqual(state["final_check"]["where"], "round")
        self.assertEqual(state["final_check"]["round"], 2)

    def test_reviewer_is_told_the_suite_runs_alongside(self):
        self.commit(f"---\ntests: {SUITE}\n---\n# acme\n")
        directory, state = self.launch("alongside", ["true"])
        self.assertEqual(state["state"], "pass", self.logs)
        reviews = [body for role, body in self.prompts if role.startswith("reviewer")]
        self.assertTrue(reviews)
        prompt = reviews[0]
        self.assertIn(f"runs alongside this review on the commit under review: {SUITE}", prompt)
        self.assertIn("These run alongside this review; their absence here is by design "
                      "and is never a finding.", prompt)
        self.assertNotIn(SUITE + "\n[exit", prompt)
        clause = "except the commands marked deferred, which run alongside your review"
        self.assertIn(clause, worker.PREAMBLES["reviewer"])
        self.assertIn(clause, worker.PREAMBLES["reviewer-scratch"])

    def test_landing_reruns_only_when_the_target_touched_branch_files(self):
        origin = self.root / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main", str(origin)],
                       check=True, capture_output=True, text=True)
        owner = self.root / "owner"
        subprocess.run(["git", "clone", "-q", str(origin), str(owner)], check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "-C", str(owner), "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", str(owner), "config", "user.email", "t@localhost"], check=True)
        (owner / "base.txt").write_text("base\n")
        subprocess.run(["git", "-C", str(owner), "add", "."], check=True)
        subprocess.run(["git", "-C", str(owner), "commit", "-q", "-m", "base"], check=True)
        subprocess.run(["git", "-C", str(owner), "push", "-q", "-u", "origin", "main"], check=True)
        counter = self.root / "counter"
        counter.write_text("")
        once = f"echo once >> {counter}  # once"

        def reviewed_run(name):
            wt = self.root / name
            subprocess.run(["git", "clone", "-q", str(origin), str(wt)], check=True,
                           capture_output=True, text=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.name", "t"], check=True)
            subprocess.run(["git", "-C", str(wt), "config", "user.email", "t@localhost"],
                           check=True)
            subprocess.run(["git", "-C", str(wt), "checkout", "-q", "-b", f"ak/{name}"],
                           check=True)
            (wt / "work.txt").write_text("work\n")
            subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
            subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", "work"], check=True)
            head = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True).stdout.strip()
            tree = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD^{tree}"],
                                  check=True, capture_output=True, text=True).stdout.strip()
            base = subprocess.run(["git", "-C", str(wt), "rev-parse", "origin/main^{commit}"],
                                  check=True, capture_output=True, text=True).stdout.strip()
            run_dir = config.RUNS / name
            run_dir.mkdir()
            (run_dir / "log.txt").touch()
            (run_dir / "round-1").mkdir(exist_ok=True)
            providers = run.review_providers(self.cfg, "opus", "astra")
            state = {"run_id": name, "title": name, "state": "running", "verdict": "PASS",
                     "review": {"executor": "opus", "executor_provider": providers[0],
                                "reviewer": "astra", "reviewer_provider": providers[1],
                                "returncode": 0, "verdict": "PASS", "done_when": True,
                                "head_sha": head, "tree_sha": tree},
                     "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                          "summary": "work", "head_sha": head,
                                          "tree_sha": tree}],
                     "rounds": 3, "base": "origin/main", "target": "origin/main",
                     "base_sha": base, "branch": f"ak/{name}", "worktree": str(wt),
                     "repo": str(wt), "executor": "opus", "reviewer": "astra",
                     "merge_method": "squash", "merged": False, "merge_failed": False,
                     "merge_note": None, "findings": "",
                     "final_check": {"outcome": "passed", "sha": head,
                                     "where": "round", "round": 1}}
            run.save_state(run_dir, state)
            lp = run.Loop(self.cfg, run_dir, state, {}, lambda m: None, wt,
                          "body", ["true", once], "context", [])
            return wt, run_dir, lp

        # still target: landing keeps the round's checks without re-running
        wt, run_dir, lp = reviewed_run("still")
        before = counter.read_text()
        with patch.object(run, "run_done_when",
                          wraps=run.run_done_when) as watched:
            self.assertTrue(run.land(lp, "origin/main",
                                    lambda: run.integrate(lp, "origin/main")
                                    and run.final_check(lp, "origin/main"), lambda: True))
            names = [Path(call.args[2]).name for call in watched.call_args_list]
        self.assertNotIn("final-check.log", names, names)
        self.assertNotIn("once.log", names, names)
        self.assertEqual(counter.read_text(), before)
        self.assertEqual(run.read_state(run_dir)["final_check"]["where"], "round")
        # overlapping move: the branch's own file, the suite runs again at landing
        wt2, run_dir2, lp2 = reviewed_run("touching")
        (owner / "work.txt").write_text("target side\n")
        subprocess.run(["git", "-C", str(owner), "add", "."], check=True)
        subprocess.run(["git", "-C", str(owner), "commit", "-q", "-m", "overlap"], check=True)
        subprocess.run(["git", "-C", str(owner), "push", "-q", "origin", "main"], check=True)
        with patch.object(run, "run_done_when",
                          wraps=run.run_done_when) as wrapped:
            # the overlap conflicts, so resolve it like a fixer would, then land
            with patch.object(run, "execute",
                              side_effect=lambda lp0, *a: (
                                  (wt2 / "work.txt").write_text("both\n"),
                                  run.git(wt2, "add", "work.txt"),
                                  run.git(wt2, "-c", "core.editor=true",
                                          "rebase", "--continue"),
                                  "## Summary\nResolved.")[3]):
                with patch.object(run, "call_retrying",
                                  return_value=(0, "VERDICT: PASS\n## Findings\n- none",
                                                None, False)):
                    self.assertTrue(run.land(
                        lp2, "origin/main",
                        lambda: run.integrate(lp2, "origin/main")
                        and run.final_check(lp2, "origin/main"), lambda: True))
            names = [Path(call.args[2]).name for call in wrapped.call_args_list]
        self.assertIn("final-check.log", names, names)
        self.assertEqual(run.read_state(run_dir2)["final_check"]["where"], "landing")
        run.write_result(run_dir2, run.read_state(run_dir2), ["true", once])
        text = (run_dir2 / "result.md").read_text()
        self.assertIn("(once, at landing)", text)
        self.assertIn("final check: passed at landing on ", text)


if __name__ == "__main__":
    unittest.main()
