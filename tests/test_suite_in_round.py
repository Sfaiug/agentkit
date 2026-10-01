"""Rounds run only task checks and review; the suite runs once at landing."""

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
from agentkit import config, gc, run, worker

SUITE = "test -f AGENTS.md"


class SuiteInRound(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-suite-round-", dir=REPO)
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
        self.logs, self.gates, self.prompts = [], [], []
        for module, name, value in ((gc, "disk_pressure", False), (run, "launch_session", None),
                                    (run, "collect_usage", {}), (run, "pick_models", ("opus", "astra"))):
            self.stack.enter_context(patch.object(module, name, return_value=value))
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

    def launch(self, name, checks, rounds=1, gate=None, scratch=False):
        directory = config.RUNS / name
        directory.mkdir()
        task = directory / "task.md"
        repo = "none" if scratch else self.repo
        task.write_text(f"---\nrepo: {repo}\nbase: main\nrounds: {rounds}\n---\n# Suite round\n\n"
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

    def test_two_rounds_run_suite_only_once_at_landing(self):
        counter = self.root / "suite-counter"
        suite = f"echo suite >> {counter}"
        self.commit(f"---\ntests: {suite}\n---\n# acme\n")
        reviews = []

        def worker_call(cfg, name, body, workspace, out_dir, role, session, **kwargs):
            code, text, sid, dead = self.worker(
                cfg, name, body, workspace, out_dir, role, session, **kwargs)
            if role.startswith("reviewer"):
                reviews.append(role)
                if len(reviews) == 1:
                    text = "VERDICT: FAIL\n## Findings\n- AGENTS.md:4 - fixture finding"
                    (out_dir / "final.md").write_text(text)
            return code, text, sid, dead

        with patch.object(worker, "call", side_effect=worker_call):
            directory, state = self.launch("two-rounds", ["true", suite], rounds=2)
        self.assertEqual(state["state"], "pass", self.logs)
        self.assertEqual([entry["verdict"] for entry in state["round_summaries"]],
                         ["FAIL", "PASS"])
        self.assertEqual([(name, cmds) for name, cmds in self.gates if suite in cmds],
                         [("final-check.log", [suite])])
        self.assertEqual(counter.read_text().splitlines(), ["suite"])
        self.assertEqual([cmds for name, cmds in self.gates if name == "donewhen.log"],
                         [["true"], ["true"]])
        self.assertFalse(list(directory.glob("round-*/once.log")))
        self.assertIn("at landing", run.status_final_check(directory, state))
        self.assertEqual(state["final_check"]["where"], "landing")
        self.assertIn("final check: passed at landing on ",
                      (directory / "result.md").read_text())

    def test_suite_runs_once_at_landing_on_a_still_target(self):
        self.commit(f"---\nusers: none\ntests: {SUITE}\n---\n# acme\n")
        directory, state = self.launch("in-round", ["true"])
        self.assertEqual(state["state"], "pass", self.logs)
        kinds = [name for name, _ in self.gates]
        self.assertIn("donewhen.log", kinds)
        self.assertNotIn("once.log", kinds)
        self.assertIn("final-check.log", kinds, self.gates)
        suites = [cmds for name, cmds in self.gates if SUITE in cmds]
        self.assertEqual(suites, [[SUITE]])
        rounds = [cmds for name, cmds in self.gates if name == "donewhen.log"]
        self.assertTrue(all(SUITE not in cmds for cmds in rounds), self.gates)
        self.assertEqual(state["final_check"]["outcome"], "passed")
        self.assertEqual(state["final_check"]["where"], "landing")
        self.assertNotIn("round", state["final_check"])
        result = (directory / "result.md").read_text()
        self.assertIn(f"{SUITE} (once, at landing)", result)
        self.assertIn("final check: passed at landing on ", result)
        self.assertIn("at landing", run.status_final_check(directory, state))
        log = "\n".join(self.logs)
        self.assertIn("final check: all passed", log)

    def test_retry_on_the_same_landing_commit_reuses_the_suite(self):
        self.commit(f"---\ntests: {SUITE}\n---\n# acme\n")

        def land_twice(lp):
            self.assertTrue(run.final_check(lp, "origin/main"))
            return run.final_check(lp, "origin/main")

        with patch.object(run, "merge", side_effect=land_twice):
            _directory, state = self.launch("retry-landing", ["true"])
        self.assertEqual(state["state"], "pass", self.logs)
        self.assertEqual([cmds for _, cmds in self.gates if SUITE in cmds], [[SUITE]])
        self.assertIn("already passed at landing", "\n".join(self.logs))

    def test_rounds_without_landing_never_run_the_suite(self):
        self.commit(f"---\ntests: {SUITE}\n---\n# acme\n")
        self.opts["--no-merge"] = True
        directory, state = self.launch("no-landing", ["true  # once", SUITE])
        self.assertEqual(state["state"], "pass", self.logs)
        self.assertEqual(self.gates, [("donewhen.log", ["true"])])
        self.assertNotIn("final_check", state)
        self.assertEqual(run.status_final_check(directory, state),
                         "final check: none (no once-commands)")
        self.assertNotIn("runs these once at landing", "\n".join(body for _, body in self.prompts))
        self.assertNotIn(SUITE, (directory / "result.md").read_text())

    def test_scratch_runs_task_once_checks_in_the_round(self):
        directory, state = self.launch("scratch-once", ["true", "false  # once"],
                                       scratch=True)
        self.assertEqual(state["verdict"], "FAIL", self.logs)
        self.assertEqual(self.gates, [("donewhen.log", ["true", "false"])])
        self.assertFalse(state["round_summaries"][0]["done_when"])
        self.assertNotIn("final_check", state)
        self.assertNotIn("run once at landing", "\n".join(body for _, body in self.prompts))
        self.assertIn("false", (directory / "result.md").read_text())
        self.assertEqual(run.status_final_check(directory, state),
                         "final check: none (no once-commands)")

    def test_reviewer_is_told_the_suite_runs_at_landing(self):
        self.commit(f"---\ntests: {SUITE}\n---\n# acme\n")
        directory, state = self.launch("landing-context", ["true"])
        self.assertEqual(state["state"], "pass", self.logs)
        reviews = [body for role, body in self.prompts if role.startswith("reviewer")]
        self.assertTrue(reviews)
        prompt = reviews[0]
        self.assertIn(f"runs once at landing on the commit to be merged: {SUITE}", prompt)
        self.assertIn("These run at landing; their absence here is by design "
                      "and is never a finding.", prompt)
        self.assertNotIn(SUITE + "\n[exit", prompt)
        clause = "except the commands marked deferred, which run once at landing"
        self.assertIn(clause, worker.PREAMBLES["reviewer"])
        self.assertNotIn("landing", worker.PREAMBLES["reviewer-scratch"])
        self.assertNotIn("deferred", worker.PREAMBLES["reviewer-scratch"])

    def test_landing_runs_the_suite_on_still_and_overlapping_targets(self):
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

        # Legacy round evidence must not skip the landing suite.
        wt, run_dir, lp = reviewed_run("still")
        before = counter.read_text()
        with patch.object(run, "run_done_when",
                          wraps=run.run_done_when) as watched:
            self.assertTrue(run.land(lp, "origin/main",
                                    lambda: run.integrate(lp, "origin/main")
                                    and run.final_check(lp, "origin/main"), lambda: True))
            names = [Path(call.args[2]).name for call in watched.call_args_list]
        self.assertIn("final-check.log", names, names)
        self.assertNotIn("once.log", names, names)
        self.assertEqual(counter.read_text(), before + "once\n")
        self.assertEqual(run.read_state(run_dir)["final_check"]["where"], "landing")
        # An overlapping move checks the resolved commit at landing.
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

    def test_disjoint_target_move_runs_the_suite_at_landing(self):
        origin = self.root / "disjoint-origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main", str(origin)],
                       check=True, capture_output=True, text=True)
        owner = self.root / "disjoint-owner"
        subprocess.run(["git", "clone", "-q", str(origin), str(owner)], check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "-C", str(owner), "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", str(owner), "config", "user.email", "t@localhost"],
                       check=True)
        (owner / "base.txt").write_text("base\n")
        subprocess.run(["git", "-C", str(owner), "add", "."], check=True)
        subprocess.run(["git", "-C", str(owner), "commit", "-q", "-m", "base"], check=True)
        subprocess.run(["git", "-C", str(owner), "push", "-q", "-u", "origin", "main"], check=True)
        counter = self.root / "disjoint-counter"
        counter.write_text("")
        once = f"echo once >> {counter}  # once"
        wt = self.root / "disjoint-wt"
        subprocess.run(["git", "clone", "-q", str(origin), str(wt)], check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "-C", str(wt), "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", str(wt), "config", "user.email", "t@localhost"], check=True)
        subprocess.run(["git", "-C", str(wt), "checkout", "-q", "-b", "ak/disjoint"], check=True)
        (wt / "work.txt").write_text("work\n")
        subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
        subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", "work"], check=True)
        head = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
        tree = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD^{tree}"],
                              check=True, capture_output=True, text=True).stdout.strip()
        base = subprocess.run(["git", "-C", str(wt), "rev-parse", "origin/main^{commit}"],
                              check=True, capture_output=True, text=True).stdout.strip()
        (owner / "other.txt").write_text("other\n")
        subprocess.run(["git", "-C", str(owner), "add", "."], check=True)
        subprocess.run(["git", "-C", str(owner), "commit", "-q", "-m", "other"], check=True)
        subprocess.run(["git", "-C", str(owner), "push", "-q", "origin", "main"], check=True)
        run_dir = config.RUNS / "disjoint"
        run_dir.mkdir()
        (run_dir / "log.txt").touch()
        (run_dir / "round-1").mkdir(exist_ok=True)
        providers = run.review_providers(self.cfg, "opus", "astra")
        state = {"run_id": "disjoint", "title": "disjoint", "state": "running",
                 "verdict": "PASS",
                 "review": {"executor": "opus", "executor_provider": providers[0],
                            "reviewer": "astra", "reviewer_provider": providers[1],
                            "returncode": 0, "verdict": "PASS", "done_when": True,
                            "head_sha": head, "tree_sha": tree},
                 "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                      "summary": "work", "head_sha": head,
                                      "tree_sha": tree}],
                 "rounds": 3, "base": "origin/main", "target": "origin/main",
                 "base_sha": base, "branch": "ak/disjoint", "worktree": str(wt),
                 "repo": str(wt), "executor": "opus", "reviewer": "astra",
                 "merge_method": "squash", "merged": False, "merge_failed": False,
                 "merge_note": None, "findings": "",
                 "final_check": {"outcome": "passed", "sha": head,
                                 "where": "round", "round": 1}}
        run.save_state(run_dir, state)
        logs = []
        lp = run.Loop(self.cfg, run_dir, state, {}, logs.append, wt,
                      "body", ["true", once], "context", [])
        before = counter.read_text()
        with patch.object(run, "run_done_when", wraps=run.run_done_when) as watched:
            self.assertTrue(run.land(lp, "origin/main",
                                    lambda: run.integrate(lp, "origin/main")
                                    and run.final_check(lp, "origin/main"), lambda: True))
            names = [Path(call.args[2]).name for call in watched.call_args_list]
        self.assertIn("final-check.log", names, names)
        self.assertNotIn("once.log", names, names)
        self.assertNotIn("donewhen.log", names, names)
        self.assertEqual(counter.read_text(), before + "once\n")
        self.assertEqual(run.read_state(run_dir)["final_check"]["where"], "landing")
        self.assertIn("reusing done-when and review evidence", "\n".join(logs))

    def test_status_names_the_declared_suite_before_it_runs(self):
        self.commit("---\ntests: bash tests/smoke.sh\n---\n# acme\n")
        directory = config.RUNS / "status-suite"
        directory.mkdir()
        (directory / "task.md").write_text("---\nrepo: %s\nbase: main\n---\n# T\n\n## Goal\nG\n\n"
                                           "## Done when\n```bash\ntrue\n```\n" % self.repo)
        wt = self.root / "status-wt"
        subprocess.run(["git", "clone", "-q", str(self.repo), str(wt)], check=True,
                       capture_output=True, text=True)
        state = {"worktree": str(wt), "target": "origin/main", "base": "main"}
        line = run.status_final_check(directory, state)
        self.assertEqual(line, "final check: not run")


if __name__ == "__main__":
    unittest.main()
