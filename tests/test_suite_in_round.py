"""The suite runs in the round alongside the review, and at landing only on overlap."""

from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, watch, worker

SUITE = "test -f AGENTS.md"


def fresh_id():
    """A marker no other run -- and no other test -- can be carrying."""
    return f"test-suite-round-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def wait_gone(pid, timeout=5):
    """True once that pid is gone or a zombie; zombies are the parent's to reap."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError):
            return True
        if state in ("Z", "X"):
            return True
        time.sleep(0.05)
    return False


def _reap(proc):
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        pass


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

    def test_reviewer_starts_before_the_suite_finishes(self):
        self.commit("---\ntests: sleep 3; test -f AGENTS.md\n---\n# acme\n")
        marks = {}
        real_worker = worker.call
        real_gate = run.run_done_when

        def timed_worker(cfg, name, body, workspace, out_dir, role, session, **kwargs):
            if role.startswith("reviewer") and "reviewer" not in marks:
                marks["reviewer"] = time.monotonic()
            return self.worker(cfg, name, body, workspace, out_dir, role, session,
                               **kwargs)

        def timed_gate(cmds, cwd, log_path, *args, **kwargs):
            if Path(log_path).name == "once.log" and "suite_start" not in marks:
                marks["suite_start"] = time.monotonic()
                try:
                    return real_gate(cmds, cwd, log_path, *args, **kwargs)
                finally:
                    marks["suite_end"] = time.monotonic()
            return real_gate(cmds, cwd, log_path, *args, **kwargs)

        with patch.object(worker, "call", side_effect=timed_worker):
            with patch.object(run, "run_done_when", side_effect=timed_gate):
                directory = config.RUNS / "alongside-timing"
                directory.mkdir()
                task = directory / "task.md"
                task.write_text(f"---\nrepo: {self.repo}\nbase: main\nrounds: 1\n---\n"
                                "# Timing\n\n## Goal\nShip.\n\n## Done when\n```bash\n"
                                "true\n```\n")
                state = run.loop(self.cfg, directory, task, self.opts, self.logs.append)
        self.assertEqual(state["state"], "pass", self.logs)
        self.assertIn("reviewer", marks, marks)
        self.assertIn("suite_end", marks, marks)
        self.assertLess(marks["reviewer"] - marks["suite_start"], 3, marks)

    def test_disjoint_target_move_lands_on_the_round_checks(self):
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
        self.assertNotIn("final-check.log", names, names)
        self.assertNotIn("once.log", names, names)
        self.assertNotIn("donewhen.log", names, names)
        self.assertEqual(counter.read_text(), before)
        self.assertEqual(run.read_state(run_dir)["final_check"]["where"], "round")
        self.assertIn("landing on the round's checks", "\n".join(logs))

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

    def test_scratch_result_says_where_the_suite_ran(self):
        state = {"final_check": {"outcome": "passed", "sha": "", "where": "round",
                                 "round": 1}}
        self.assertEqual(run.final_check_line(state, ["test -d .  # once"]),
                         "final check: passed in round 1")
        self.assertIn("(once, in round 1)",
                      run.result_done_when(["test -d .  # once"], state)[0])

    def test_suite_thread_marks_its_processes_apart(self):
        from types import SimpleNamespace
        seen = {}

        def fake_verify(lp):
            env = run.run_child_env()
            seen["run"] = env.get("AGENTKIT_RUN")
            seen["parent"] = env.get("AK_PARENT_RUN")
            return True, ""

        previous = getattr(run._RUN_CONTEXT, "state", {})
        run._RUN_CONTEXT.state = {"run_id": "acme-probe-1", "run_depth": 0}
        try:
            with patch.object(run, "verify_once", side_effect=fake_verify):
                thread, _ = run.start_suite(SimpleNamespace(rnd=1))
                thread.join(timeout=30)
                self.assertFalse(thread.is_alive())
            self.assertEqual(run.run_child_env().get("AGENTKIT_RUN"), "acme-probe-1")
        finally:
            run._RUN_CONTEXT.state = previous
        self.assertEqual(seen.get("run"), "acme-probe-1/suite")
        self.assertEqual(seen.get("parent"), "acme-probe-1")

    def spawn_marked(self, marker):
        """A detached sleeper carrying that marker, with a SIGKILL safety net."""
        proc = subprocess.Popen(
            ["setsid", "sleep", "100"], start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "AGENTKIT_RUN": marker})
        self.addCleanup(_reap, proc)
        return proc

    def test_run_end_sweep_covers_the_suite_marker(self):
        rid = fresh_id()
        self.spawn_marked(rid)
        self.spawn_marked(f"{rid}/suite")
        time.sleep(0.5)
        found = worker.marked_pids(rid)
        self.assertEqual(len(found), 2)
        suite_only = worker.marked_pids(f"{rid}/suite")
        self.assertEqual(len(suite_only), 1)
        self.assertIn(suite_only[0], found)
        with patch.object(worker, "kill_marked",
                          wraps=worker.kill_marked) as swept, \
                patch.object(run.orch, "stop_scope"):
            run.stop_run_tree({"run_id": rid, "scope": None},
                              log=lambda m: None)
        self.assertEqual(swept.call_count, 1)
        self.assertEqual(swept.call_args.args[0], rid)
        for pid in found:
            self.assertTrue(wait_gone(pid), f"{pid} outlived the run-end sweep")

    def test_stall_ladder_ends_the_suite_processes(self):
        # A stalled reviewer killed mid-suite: the ladder's marker sweep ends the
        # suite's detached processes too, not only the run's own marker, with one
        # sweep -- the tree fallback never reaches what left the loop's tree.
        rid = fresh_id()
        self.spawn_marked(rid)
        self.spawn_marked(f"{rid}/suite")
        loop = subprocess.Popen(
            ["sleep", "100"], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(_reap, loop)
        time.sleep(0.5)
        found = worker.marked_pids(rid)
        self.assertEqual(len(found), 2)
        state = {"run_id": rid, "scope": None}
        with patch.object(worker, "kill_marked",
                          wraps=worker.kill_marked) as swept:
            if not watch.stop_run_scope(state, log=lambda m: None):
                watch.kill_tree(loop.pid, log=lambda m: None)
        self.assertEqual(swept.call_count, 1)
        for pid in found:
            self.assertTrue(wait_gone(pid), f"{pid} outlived the stall kill")

    def test_exact_sweep_leaves_the_suite_alone(self):
        rid = fresh_id()
        self.spawn_marked(rid)
        self.spawn_marked(f"{rid}/suite")
        time.sleep(0.5)
        own = worker.marked_pids(rid, exact=True)
        self.assertEqual(len(own), 1)
        self.assertTrue(worker.kill_marked(rid, exact=True))
        for pid in own:
            self.assertTrue(wait_gone(pid), f"{pid} outlived the exact sweep")
        left = worker.marked_pids(f"{rid}/suite")
        self.assertEqual(len(left), 1)
        self.assertTrue(worker.kill_marked(f"{rid}/suite"))
        for pid in left:
            self.assertTrue(wait_gone(pid), f"{pid} outlived its own sweep")

    def test_kill_group_leaves_the_suite_alone(self):
        rid = fresh_id()
        victim = subprocess.Popen(
            ["sleep", "100"], start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        self.addCleanup(_reap, victim)
        self.spawn_marked(rid)
        self.spawn_marked(f"{rid}/suite")
        time.sleep(0.5)
        own = worker.marked_pids(rid, exact=True)
        self.assertEqual(len(own), 1)
        worker.kill_group(victim, rid)
        self.assertTrue(wait_gone(victim.pid), "victim outlived its group kill")
        for pid in own:
            self.assertTrue(wait_gone(pid), f"{pid} outlived the turn cleanup")
        left = worker.marked_pids(f"{rid}/suite")
        self.assertEqual(len(left), 1)
        self.assertTrue(worker.kill_marked(f"{rid}/suite"))
        for pid in left:
            self.assertTrue(wait_gone(pid), f"{pid} outlived its own sweep")

    def test_transient_reviewer_failure_leaves_the_suite_running(self):
        # A reviewer hiccup mid-suite: the retry's turn-level sweep ends only the
        # turn's own marker, so the suite runs once instead of dying into a bogus
        # flaky re-run (one hiccup) or failing the round (two).
        counter = self.root / "suite-counter"
        counter.write_text("")
        suite = f"echo run >> {counter}; sleep 4; test -f AGENTS.md"
        self.commit(f"---\ntests: {suite}\n---\n# acme\n")
        failed = []

        def flaky(cfg, name, body, workspace, out_dir, role, session, **kwargs):
            if role.startswith("reviewer") and not failed:
                # fail only once the suite is provably in its sleep: an instant
                # failure can sweep before the suite spawns anything, which would
                # pass even with the wide match.
                deadline = time.monotonic() + 30
                while counter.read_text() == "" and time.monotonic() < deadline:
                    time.sleep(0.05)
                failed.append(True)
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "final.md").write_text("")
                return 1, "", "review-sid-1", False
            return self.worker(cfg, name, body, workspace, out_dir, role, session,
                               **kwargs)

        # as run_slot sets it: without a run context the loop's children are
        # unmarked and every sweep is a no-op on None, wide or exact alike.
        previous = getattr(run._RUN_CONTEXT, "state", {})
        run._RUN_CONTEXT.state = {"run_id": "reviewer-hiccup", "run_depth": 0}
        try:
            with patch.object(worker, "call", side_effect=flaky), \
                    patch.object(run, "transient_wait"):
                directory, state = self.launch("reviewer-hiccup", ["true"])
        finally:
            run._RUN_CONTEXT.state = previous
        self.assertTrue(failed)
        self.assertEqual(state["state"], "pass", self.logs)
        self.assertEqual(counter.read_text().splitlines(), ["run"])
        self.assertNotIn("flaky:", "\n".join(self.logs))


if __name__ == "__main__":
    unittest.main()
