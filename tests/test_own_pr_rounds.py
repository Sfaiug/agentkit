"""Own PRs carry findings across pushes, while other PRs get one review. Offline.

Real git commits in a temporary acme checkout; GitHub, reviewer turns, seats and
processes are fakes. A fake sleep pushes the next head or closes the PR.
"""

from contextlib import ExitStack, nullcontext, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, run, watch, worker

URL = "https://github.com/acme/widget/pull/7"


class OwnPrRounds(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-own-pr-rounds-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": "fix-api",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "NO_COLOR": "1"}))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        config.ensure_dirs()
        self.cfg = config.load()
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"])
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@localhost")
        (self.repo / "AGENTS.md").write_text("---\nusers: none\ntests: test -f fence.txt\n---\n# acme\n")
        (self.repo / "fence.txt").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-qm", "Base")
        self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "HEAD"))
        self.git("checkout", "-qb", "fix-api")
        self.heads = []
        for n in range(1, 4):
            (self.repo / "fence.txt").write_text(f"fix {n}\n")
            self.git("commit", "-qam", f"Fix {n}")
            self.heads.append(self.git("rev-parse", "HEAD"))
        self.pr = {"state": "OPEN", "title": "Mend the fence", "author": "owner",
                   "baseRefName": "main", "headRefOid": self.heads[0], "body": "Fix the fence"}
        self.run_dir = config.RUNS / "own-pr-rounds"
        self.run_dir.mkdir()
        (self.run_dir / "log.txt").touch()
        run.capture_launch(self.run_dir, {"--review-pr": URL})
        self.prompts, self.notices, self.events, self.merges, self.waits = [], [], [], [], []
        self.verdicts = []
        self.close = False
        for name, value in (("viewer_login", "owner"), ("checkout_for", self.repo),
                            ("fetch", (0, "")), ("disk_pressure", False),
                            ("collect_usage", {}), ("checks", (True, "")),
                            ("process_active", True), ("scope_alive", None)):
            self.stack.enter_context(patch.object(run, name, return_value=value))
        self.stack.enter_context(patch.object(run, "pr_view", side_effect=lambda *_: dict(self.pr)))
        self.stack.enter_context(patch.object(run, "gh_json", side_effect=lambda *a, **k: (dict(self.pr), "")))
        self.stack.enter_context(patch.object(run, "gh", side_effect=self.gh))
        self.stack.enter_context(patch.object(run, "merge_turn", side_effect=lambda *a, **k: nullcontext()))
        self.stack.enter_context(patch.object(worker, "call", side_effect=self.reviewer))
        clock = self.stack.enter_context(patch.object(run, "time", wraps=time))
        clock.sleep.side_effect = self.push
        self.stack.enter_context(patch.object(run, "launcher_world", side_effect=lambda *a, **k: nullcontext(True)))
        self.stack.enter_context(patch.object(orch, "find", return_value={"name": "fix-api"}))
        self.stack.enter_context(patch.object(watch, "type_at_prompt", side_effect=self.tell))
        self.stack.enter_context(patch.object(watch, "frozen_cgroup", return_value=None))
        self.stack.enter_context(patch.object(watch, "step_for_run", return_value=("none", "no child", None, [])))
        self.kill = self.stack.enter_context(patch.object(watch, "kill_tree"))
        self.resume = self.stack.enter_context(patch.object(watch, "launch_resume"))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def gh(self, cwd, *args, **_kw):
        if args[:2] == ("pr", "merge"):
            self.merges.append(args)
        if args[0] == "api":
            self.events.append(args[args.index("-f") + 3])
        return 0, ""

    def tell(self, seat, line, *args, **_kw):
        self.notices.append(line)
        return True

    def reviewer(self, cfg, name, body, workspace, out_dir, role, session, **_kw):
        self.prompts.append(body)
        n = len(self.prompts)
        self.assertLessEqual(n, len(self.verdicts), "reviewed a head twice")
        self.assertEqual(run.git(workspace, "rev-parse", "HEAD"), self.pr["headRefOid"])
        verdict = self.verdicts[n - 1]
        text = (f"## Findings\n- fence.txt:1 - defect {n} - wrong edge outcome\n"
                if verdict == "FAIL" else "## Findings\n- none\n") + f"VERDICT: {verdict}\n"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "final.md").write_text(text)
        return 0, text, f"review-{n}", False

    def push(self, seconds):
        if seconds != run.SLOT_POLL:
            return
        state = run.read_state(self.run_dir)
        self.waits.append(state)
        self.assertEqual(state["state"], "running")
        self.assertIsNone(state.get("finished_at"))
        self.assertFalse(state.get("handed_back"))
        self.assertTrue(self.notices, "the seat must receive findings before waiting for its push")
        self.assertIn(f"defect {len(self.prompts)}", self.notices[-1])
        out = io.StringIO()
        with redirect_stdout(out):
            run.cmd_status([self.run_dir.name])
        self.assertIn("waiting for", out.getvalue())
        self.assertIn("push", out.getvalue())
        with patch.object(watch, "run_last_write", return_value=time.time() - 7200):
            watch.recover_runs(self.cfg, log=lambda _: None)
        self.kill.assert_not_called()
        self.resume.assert_not_called()
        if self.close:
            self.pr["state"] = "CLOSED"
        else:
            self.pr["headRefOid"] = self.heads[len(self.prompts)]

    def review(self, verdicts):
        self.verdicts = verdicts
        return run.review_pr(self.cfg, self.run_dir, URL,
                             {"--review": None, "--review-pr": URL}, lambda _: None)

    def test_fail_push_pass_in_round_two_merges(self):
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(state["state"], "pass")
        self.assertEqual([s["verdict"] for s in state["round_summaries"]], ["FAIL", "PASS"])
        self.assertEqual(len(self.waits), 1)
        self.assertIn("defect 1", self.prompts[1])
        self.assertIn("first rule on each previous finding", self.prompts[1])
        self.assertEqual(self.events, ["event=COMMENT", "event=COMMENT"])
        self.assertEqual(len(self.merges), 1)
        self.assertEqual(self.merges[0][-1], self.heads[1])

    def test_three_fails_end_with_the_last_findings(self):
        state = self.review(["FAIL", "FAIL", "FAIL"])
        self.assertEqual(state["state"], "fail")
        self.assertEqual(len(state["round_summaries"]), 3)
        self.assertEqual(len(self.waits), 2)
        self.assertIn("defect 2", self.prompts[2])
        self.assertFalse(state["merged"])
        self.assertEqual(self.merges, [])
        result = (self.run_dir / "result.md").read_text()
        self.assertIn("defect 3", result)
        self.assertNotIn("defect 1", result)
        run.announce(state, self.run_dir, lambda _: None, self.cfg)
        self.assertIn("defect 3", self.notices[-1])
        self.assertIn("three rounds spent", self.notices[-1])

    def test_closed_pr_ends_the_run(self):
        self.close = True
        state = self.review(["FAIL"])
        self.assertEqual(state["state"], "fail")
        self.assertEqual(len(self.waits), 1)
        self.assertEqual(len(self.prompts), 1)
        self.assertIsNotNone(state["finished_at"])
        self.assertIn("closed", state["error"].lower())
        self.assertIn("defect 1", (self.run_dir / "result.md").read_text())
        self.assertEqual(self.merges, [])

    def test_other_pr_fail_keeps_its_single_review(self):
        self.pr["author"] = "contributor"
        state = self.review(["FAIL"])
        self.assertEqual(state["state"], "fail")
        self.assertEqual(state["rounds"], 1)
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.waits, [])
        self.assertEqual(self.events, ["event=REQUEST_CHANGES"])

    def test_wait_resumes_without_repeating_the_round_or_notice(self):
        clock = run.time

        def die(seconds):
            if seconds == run.SLOT_POLL:
                raise InterruptedError("fixture: loop died while waiting")

        clock.sleep.side_effect = die
        with self.assertRaises(InterruptedError):
            self.review(["FAIL", "PASS"])
        saved = run.read_state(self.run_dir)
        self.assertEqual(saved["own_pr_round_told"], 1)
        saved.update(state="queued", pid=999999991)
        run.save_state(self.run_dir, saved)
        clock.sleep.side_effect = self.push
        state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(len(self.prompts), 2)
        self.assertEqual(len(self.notices), 1)
        self.assertEqual(len(self.waits), 1)

    def test_busy_seat_gets_the_findings_once_before_the_push(self):
        sends = []

        def busy(seat, line, *args, **kw):
            sends.append(kw.get("typed"))
            if len(sends) == 1:
                kw["receipt"]({"fixture": "typed"})
                return False
            return self.tell(seat, line)

        def wait(seconds):
            if len(sends) > 1:
                self.push(seconds)

        run.time.sleep.side_effect = wait
        with patch.object(watch, "type_at_prompt", side_effect=busy):
            state = self.review(["FAIL", "PASS"])
        self.assertTrue(state["merged"])
        self.assertEqual(sends, [None, {"fixture": "typed"}])
        self.assertEqual(len(self.notices), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
