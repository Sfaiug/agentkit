"""Finding 2: successful review by an eligible model is required. Entirely offline fixture state."""

from contextlib import ExitStack, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import call, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, usage


class ReviewContract(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".review-contract-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.stack.enter_context(patch.dict(os.environ, {
            # No inherited run marker: a sweep outside a run context would otherwise take the
            # caller's processes -- the worker running this test -- for the fixture run's own.
            "HOME": str(self.root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AGENTKIT_RUN": "",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(sockets), "PYTHONDONTWRITEBYTECODE": "1",
            # a top-level launch, whoever runs this: a run's own done-when is depth 1, which
            # skips the slot gate whose one poll the sleeps below are counted against
            "AK_RUN_DEPTH": "0", "REVIEW_FIXTURE": str(self.root)}))
        os.environ.pop("AK_MAX_RUNS", None)
        config.ensure_dirs()
        self.cfg = config.load()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {"PATH": f"{self.bin}:{os.environ['PATH']}"}))
        # No real tmux or external delivery process can be reached by this program.
        self.script(self.bin / "tmux", '''import sys
assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv
sys.exit(1)
''')
        self.script(self.bin / "gh", 'raise AssertionError("unexpected external delivery")\n')
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub call")))
        self.stack.enter_context(patch.object(run.notify, "shaped",
                                             side_effect=AssertionError("notification")))
        self.sleep = self.stack.enter_context(patch.object(run.time, "sleep"))
        # The fixtures rewrite a delivered scratch run into an interrupted or older record, and
        # such a record always still has its workspace: settling the delivery must not take it.
        self.stack.enter_context(patch.object(run, "drop_checkout", return_value=False))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        self.providers = {}
        self.eligible = config.offered(self.cfg)
        self.stack.enter_context(patch.object(usage, "collect", side_effect=lambda cfg: self.providers))
        self.stack.enter_context(patch.object(config, "workers", side_effect=lambda cfg: self.eligible))
        self.available("anthropic", "openai", "meta")
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}))
        # Model/provider/effort definitions come only from ~/.agentkit/config.toml.
        (self.root / "models.json").write_text(json.dumps({entry["model"]: name
                                                        for name, entry in self.cfg["models"].items()}))
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            self.script(adapters / f"{harness}.sh", '''import json, os, pathlib, sys
assert sys.argv[1] == "run", sys.argv
root = pathlib.Path(os.environ["REVIEW_FIXTURE"])
name = json.loads((root / "models.json").read_text())[sys.argv[2]]
out = pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
role = "reviewer" if prompt.startswith("You are the reviewer") else "executor"
with (root / "calls.jsonl").open("a") as f:
    f.write(json.dumps({"model": name, "role": role, "out": str(out),
                        "session": sys.argv[7:]}) + "\\n")
if role == "executor":
    pathlib.Path(sys.argv[4], "deliverable").write_text("fixture work\\n")
    row = {"code": 0, "text": "## Summary\\nProduced the fixture."}
else:
    plan = json.loads((root / "responses.json").read_text())
    rows = plan.get(name, [{"code": 0, "text": "VERDICT: PASS\\n## Findings\\n- none"}])
    row = rows.pop(0) if len(rows) > 1 else rows[0]
    (root / "responses.json").write_text(json.dumps(plan))
(out / "final.md").write_text(row["text"])
(out / "stderr.log").write_text("diagnostic for " + name)
(out / "session_id").write_text("session-" + name)
sys.exit(row["code"])
''')
        self.respond({})
        self.task = self.root / "task.md"
        self.task.write_text("---\nrepo: none\nrounds: 1\n---\n# Review contract\n\n"
                             "## Done when\n```bash\ntest -f deliverable\n```\n")
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def available(self, *providers):
        self.providers = {p: {"resets": 0, "meters": [
            {"name": "weekly_all", "used": 0 if p in providers else 100,
             "pace": None, "exhausted": p not in providers}]} for p in self.cfg["providers"]}

    def respond(self, responses):
        (self.root / "responses.json").write_text(json.dumps(responses))

    def calls(self, role=None):
        path = self.root / "calls.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [row for row in rows if role is None or row["role"] == role]

    def launch(self, *flags):
        before = set(run.run_dirs())
        code = run.main([str(self.task), *flags])
        dirs = set(run.run_dirs()) - before
        self.assertEqual(len(dirs), 1)
        directory = dirs.pop()
        return code, directory, run.read_state(directory)

    def assert_undelivered(self, state):
        self.assertFalse(run.review_pass(state, self.cfg))
        self.assertEqual(run.delivery(state), "FAIL")
        self.assertFalse(state.get("merged"))
        self.assertFalse(state.get("pr"))

    def loop_for(self, directory, state, spares=()):
        lp = run.Loop(self.cfg, directory, state, {}, lambda s: None, Path(state["worktree"]),
                      "Fixture review", ["test -f deliverable"], "Fixture", list(spares))
        lp.rnd = 1
        return lp

    def legacy(self, reviewer="astra", status="interrupted"):
        code, directory, state = self.launch("--exec", "opus", "--review", "astra")
        self.assertEqual(code, 0)
        state.update(state=status, reviewer=reviewer, review_session="old-review-session")
        state.pop("review")
        run.save_state(directory, state)
        return directory, state

    def test_explicit_same_provider_is_rejected_before_any_adapter_call(self):
        self.available("anthropic")
        for reviewer in ("opus", "fable"):
            with self.subTest(reviewer=reviewer), patch.object(usage, "collect") as collect:
                reason = "same model" if reviewer == "opus" else "reviews_own_provider"
                with self.assertRaisesRegex(config.Error, reason):
                    run.main([str(self.task), "--exec", "opus", "--review", reviewer])
                collect.assert_not_called()
            self.assertEqual(self.calls(), [])
        for directory in run.run_dirs():
            self.assert_undelivered(run.read_state(directory))

    def test_only_anthropic_waits_and_can_resume_when_another_provider_recovers(self):
        self.available("anthropic")
        for eligible in (["opus"], ["opus", "fable"]):
            self.eligible = eligible
            self.assertEqual(usage.pick_order(self.cfg, self.providers), eligible)
            for executor in (None, "opus"):
                if executor is None and "fable" in eligible:
                    self.assertEqual(run.pick_models(self.cfg, self.providers, None, None,
                                                     lambda s: None), ("fable", "opus"))
                    continue
                with self.assertRaisesRegex(run.Exhausted, "no eligible reviewer"):
                    run.pick_models(self.cfg, self.providers, executor, None, lambda s: None)
            code, directory, state = self.launch("--exec", "opus")
            self.assertEqual(code, 1)
            self.assertEqual(state["state"], "exhausted")
            self.assertIn("no eligible reviewer", state["error"])
            self.assert_undelivered(state)
        self.assertEqual(self.calls(), [])
        self.available("anthropic", "openai")
        self.eligible = list(self.cfg["defaults"]["workers"])
        self.assertEqual(run.cmd_resume([directory.name]), 0)
        state = run.read_state(directory)
        self.assertTrue(run.review_pass(state, self.cfg))
        self.assertEqual(run.delivery(state), "PASS, delivered")
        self.assertEqual([r["model"] for r in self.calls()], ["opus", "astra"])

    def test_nonzero_pass_never_delivers_and_keeps_the_output(self):
        self.respond({"astra": [{"code": 1, "text": "VERDICT: PASS\npartial review"}]})
        code, directory, state = self.launch("--exec", "opus", "--review", "astra")
        self.assertEqual(code, 1)
        self.assertEqual(state["verdict"], "FAIL")
        self.assertEqual(state["review"]["returncode"], 1)
        self.assert_undelivered(state)
        self.assertIn("partial review", state["findings"])
        self.assertEqual((directory / "round-1/reviewer/final.md").read_text(),
                         "VERDICT: PASS\npartial review")
        self.assertEqual((directory / "round-1/reviewer/stderr.log").read_text(), "diagnostic for astra")
        # subprocess polls a child's exit through the same patched sleep; only the run's waits count
        self.assertEqual([c for c in self.sleep.call_args_list if c.args[0] > 0.05],
                         [call(run.SLOT_POLL)])

    def test_bounded_transient_retry_can_succeed_without_losing_diagnostics(self):
        self.respond({"astra": [{"code": 1, "text": "HTTP 503\nVERDICT: PASS"},
                                 {"code": 0, "text": "VERDICT: PASS"}]})
        code, directory, state = self.launch("--exec", "opus", "--review", "astra")
        self.assertEqual(code, 0)
        self.assertTrue(run.review_pass(state, self.cfg))
        self.assertEqual([r["session"] for r in self.calls("reviewer")], [[], ["session-astra"]])
        waits = [c.args[0] for c in self.sleep.call_args_list
                 if c.args and c.args[0] in run.TRANSIENT_BACKOFF]
        self.assertEqual(waits, [run.TRANSIENT_BACKOFF[0]])
        self.assertIn("HTTP 503", (directory / "round-1/reviewer/final.md").read_text())
        self.assertTrue((directory / "round-1/reviewer-retry1/stderr.log").exists())

    def test_successful_alternative_provider_records_the_actual_reviewer(self):
        self.respond({"astra": [{"code": 1, "text": "You've hit your usage limit."}]})
        code, directory, state = self.launch("--exec", "opus", "--review", "astra")
        self.assertEqual(code, 0)
        self.assertEqual([r["model"] for r in self.calls("reviewer")], ["astra", "spark"])
        self.assertTrue(run.review_pass(state, self.cfg))
        self.assertEqual(state["review"]["reviewer"], "spark")
        self.assertEqual(state["review"]["reviewer_provider"],
                         config.model(self.cfg, "spark")["provider"])
        self.assertEqual(self.calls("reviewer")[-1]["session"], [])
        waits = [c.args[0] for c in self.sleep.call_args_list
                 if c.args and c.args[0] in run.TRANSIENT_BACKOFF]
        self.assertEqual(waits, [])

    def test_exhausted_reviewers_wait_and_resume_review_without_reexecuting(self):
        self.respond({"astra": [{"code": 1, "text": "You've hit your usage limit."}],
                      "spark": [{"code": 1, "text": "usage limit reached"}]})
        code, directory, state = self.launch("--exec", "opus", "--review", "astra")
        self.assertEqual(code, 1)
        self.assertEqual(state["state"], "exhausted")
        self.assert_undelivered(state)
        self.assertEqual([r["model"] for r in self.calls("reviewer")], ["astra", "spark"])
        waits = [c.args[0] for c in self.sleep.call_args_list
                 if c.args and c.args[0] in run.TRANSIENT_BACKOFF]
        self.assertEqual(waits, [])
        artifacts = {p: p.read_text() for p in directory.glob("round-1/reviewer*/final.md")}
        self.assertEqual(len(artifacts), 2)
        self.respond({})
        self.assertEqual(run.cmd_resume([directory.name]), 0)
        self.assertEqual(len(self.calls("executor")), 1)
        self.assertTrue(run.review_pass(run.read_state(directory), self.cfg))
        self.assertTrue(all(p.read_text() == text for p, text in artifacts.items()))

    def test_fable_executor_resumes_review_from_its_seat_with_more_rounds(self):
        self.eligible = ["opus", "astra", "spark", "fable"]
        config.save_session(self.cfg, "fable-seat", "fable", self.eligible)
        self.providers["anthropic"]["meters"] = [
            {"name": "weekly_all", "used": 80, "pace": 30, "exhausted": False},
            {"name": "weekly_scoped", "used": 53, "pace": 3, "exhausted": False}]
        failed = {"astra": [{"code": 1, "text": "You've hit your usage limit."}],
                  "spark": [{"code": 1, "text": "usage limit reached"}],
                  "opus": [{"code": 1, "text": "Usage limit reached"}]}
        # Same-company Opus is now a fallback too; silence every legal reviewer.
        self.respond(failed)
        with patch.dict(os.environ, {config.SESSION_ENV: "fable-seat"}), \
                patch.object(run, "launch_session", return_value=None):
            code, directory, state = self.launch()
            self.assertEqual(code, 1)
            self.assertEqual(state["state"], "exhausted")
            self.assertEqual(state["executor"], "fable")
            self.assertIn("fable", config.active_session(self.cfg)["workers"])
            self.assertEqual([r["model"] for r in self.calls("executor")], ["fable"])
            # The preference is gone by resume; the existing executor must keep its work.
            self.providers["anthropic"]["meters"][1]["used"] = 80
            self.respond({state["reviewer"]: [
                {"code": 0, "text": "VERDICT: FAIL\nFix the remaining finding."},
                {"code": 0, "text": "VERDICT: PASS"}]})
            self.assertEqual(run.cmd_resume([directory.name, "--rounds", "2"]), 0)
            state = run.read_state(directory)
            self.assertEqual(state["executor"], "fable")
            self.assertEqual(state["rounds"], 2)
            self.assertIn(state["reviewer"], ("astra", "spark", "opus"))
            self.assertEqual([r["model"] for r in self.calls("executor")], ["fable", "fable"])
            self.assertEqual(self.calls("executor")[1]["session"], ["session-fable"])
            self.assertTrue(run.review_pass(state, self.cfg))

    def test_legacy_pass_waits_without_delivery_then_gets_fresh_cross_provider_review(self):
        for reviewer in ("opus", "fable", "astra"):
            for status in ("interrupted", "pass"):
                with self.subTest(reviewer=reviewer, status=status):
                    self.available("anthropic", "openai", "meta")
                    directory, state = self.legacy(reviewer, status)
                    self.assert_undelivered(state)
                    count = len(self.calls())
                    self.available("anthropic")
                    self.assertEqual(run.cmd_resume([directory.name]), 1)
                    self.assertEqual(len(self.calls()), count)
                    self.assert_undelivered(run.read_state(directory))
                    self.available("anthropic", "openai")
                    self.assertEqual(run.cmd_resume([directory.name]), 0)
                    self.assertEqual([r["role"] for r in self.calls()[count:]], ["reviewer"])
                    state = run.read_state(directory)
                    self.assertTrue(run.review_pass(state, self.cfg))
                    self.assertEqual(state["reviewer"], "astra")
                    if reviewer != "astra":
                        self.assertEqual(self.calls()[-1]["session"], [])

    def test_saved_success_skips_workers_but_mismatched_evidence_does_not(self):
        code, directory, state = self.launch("--exec", "opus", "--review", "astra")
        self.assertEqual(code, 0)
        for field, value in (("returncode", 1), ("reviewer_provider", "anthropic"),
                             ("reviewer", "spark"), ("executor", "spark"), ("done_when", False)):
            invalid = copy.deepcopy(state)
            invalid["review"][field] = value
            self.assert_undelivered(invalid)
        changed = copy.deepcopy(self.cfg)
        changed["models"]["astra"]["provider"] = config.model(self.cfg, "opus")["provider"]
        self.assertFalse(run.review_pass(state, changed))
        state["state"] = "interrupted"
        run.save_state(directory, state)
        count = len(self.calls())
        self.available("anthropic")
        self.assertEqual(run.cmd_resume([directory.name]), 0)
        self.assertEqual(len(self.calls()), count)

    def test_merge_entry_points_reject_legacy_pass_before_delivery(self):
        directory, state = self.legacy()
        state.update(scratch=False, state="pass", pr="https://github.com/fixture/repo/pull/1")
        run.save_state(directory, state)
        lp = self.loop_for(directory, state)
        with self.assertRaisesRegex(config.Error, "successful reviewer"):
            run.cmd_merge([directory.name])
        with self.assertRaisesRegex(run.Exhausted, "successful reviewer"):
            run.merge(lp)
        with self.assertRaisesRegex(run.Exhausted, "successful reviewer"):
            run.do_merge(lp, state["pr"], "origin/main")

    def test_repository_run_cannot_reach_merge_without_successful_review(self):
        repo = self.root / "repo"
        repo.mkdir()
        run.git(repo, "init", "-b", "main")
        run.git(repo, "config", "user.name", "fixture")
        run.git(repo, "config", "user.email", "fixture@localhost")
        run.git(repo, "commit", "--allow-empty", "-m", "fixture base")
        self.task.write_text(f"---\nrepo: {repo}\nbase: main\nrounds: 1\n---\n# Repo review\n\n"
                             "## Done when\n```bash\ntest -f deliverable\n```\n")
        with patch.object(run, "merge") as merge:
            self.available("anthropic")
            code, directory, state = self.launch("--exec", "opus", "--no-worktree")
            self.assertEqual(code, 1)
            self.assertEqual(self.calls(), [])
            self.assert_undelivered(state)
            self.available("anthropic", "openai")
            self.respond({"astra": [{"code": 1, "text": "VERDICT: PASS"}]})
            self.assertEqual(run.cmd_resume([directory.name]), 1)
            state = run.read_state(directory)
            self.assertEqual(state["verdict"], "FAIL")
            self.assert_undelivered(state)
            merge.assert_not_called()

    def test_review_rechecks_saved_pairs_and_filters_same_provider_spares(self):
        directory, state = self.legacy("fable")
        lp = self.loop_for(directory, state)
        count = len(self.calls())
        with self.assertRaisesRegex(config.Error, "shares provider"):
            run.review(lp, "saved work", True, "passed")
        self.assertEqual(len(self.calls()), count)
        lp.reviewer = "astra"
        lp.spares = ["opus", "fable", "spark"]
        self.respond({"astra": [{"code": 1, "text": "You've hit your usage limit."}]})
        self.assertEqual(run.review(lp, "saved work", True, "passed"), "PASS")
        self.assertEqual([r["model"] for r in self.calls()[count:]], ["astra", "spark"])

    def test_done_when_failure_still_overrides_successful_review(self):
        directory, state = self.legacy()
        lp = self.loop_for(directory, state)
        self.assertEqual(run.review(lp, "saved work", False, "failed"), "FAIL")
        self.assert_undelivered(state)

    def test_review_only_also_requires_a_zero_exit(self):
        directory, state = self.legacy()
        state.update(executor=None, review_pr="https://github.com/fixture/repo/pull/1")
        lp = self.loop_for(directory, state)
        self.respond({"astra": [{"code": 1, "text": "VERDICT: PASS"}]})
        self.assertEqual(run.review(lp, "foreign PR", True, "passed"), "FAIL")
        self.assertFalse(run.review_pass(state, self.cfg))


if __name__ == "__main__":
    unittest.main()
