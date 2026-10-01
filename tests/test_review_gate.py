"""A review fails a round only for what blocks; three rounds is the budget.

Entirely offline fixture state: one fake harness per model in the catalogue answers
reviews from a plan the test writes, and the PR is opened through a stubbed `gh`.
"""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, run, task, worker


def fail(count, note="pattern"):
    """A reviewer answer with `count` blocking findings under `## Findings`."""
    items = "\n".join(f"- file.py:{n} - {note} - why it matters" for n in range(1, count + 1))
    return f"VERDICT: FAIL\n\n## Findings\n{items}\n" if count else "VERDICT: FAIL\n"


PASS = "VERDICT: PASS\n\n## Findings\n- none\n"

PASS_FOLLOWUPS = """VERDICT: PASS

## Findings
- none

## Follow-ups
- a.py:1 - empty input crashes - base abc123: `parse([])` raises IndexError
- b.py:2 - zero divisor crashes - base abc123: `ratio(0)` raises ZeroDivisionError
"""

# One fake harness for every model in the catalogue: it never leaves the fixture directory,
# records each prompt it was given, and answers reviews from a plan the test writes.
ADAPTER = '''import json, os, pathlib, sys
root = pathlib.Path(os.environ["GATE_FIXTURE"])
if sys.argv[1] == "usage":
    print(json.dumps({"meters": [{"name": "weekly", "used": 0}]}))
    sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available":0}')
    sys.exit(0)
assert sys.argv[1] == "run", sys.argv
out = pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
role = "reviewer" if prompt.startswith("You are the reviewer") else "executor"
with (root / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"role": role, "prompt": prompt, "session": sys.argv[7:]}) + "\\n")
deliverable = pathlib.Path(sys.argv[4], "deliverable")
if role == "executor":
    disputed = root / "fixer-summary.md"
    if prompt.startswith("You are the executor, continuing") and disputed.exists():
        (out / "final.md").write_text(disputed.read_text())
    else:
        deliverable.write_text("fixture work\\n")
        (out / "final.md").write_text("## Summary\\nFixture work.")
else:
    plan = json.loads((root / "reviews.json").read_text())
    answer = plan.pop(0) if len(plan) > 1 else plan[0]
    (root / "reviews.json").write_text(json.dumps(plan))
    (out / "final.md").write_text(answer)
    (out / "session_id").write_text("session-" + role)
(out / "session_id").write_text("session-" + role)
'''


class ReviewGate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-review-gate-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, key, self.root / key.lower()))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "PATH": f"{self.bin}:{os.environ['PATH']}",
            "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(sockets), "TMUX": "", "NO_COLOR": "1",
            "PYTHONDONTWRITEBYTECODE": "1", config.ADAPTER_DIR_ENV: str(adapters),
            "GATE_FIXTURE": str(self.root)}))
        # Nothing outside the fixture is reachable: no tmux server, harness, GitHub or Discord.
        self.script(self.bin / "tmux", '''import sys
assert sys.argv[1:3] == ["-L", "agentkit-test"], sys.argv
sys.exit(1)
''')
        for executable in ("gh", "claude", "codex", "muse"):
            self.script(self.bin / executable, 'raise AssertionError("external call forbidden")\n')
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub call")))
        self.stack.enter_context(patch.object(notify, "post", side_effect=AssertionError("Discord")))
        self.stack.enter_context(patch.object(notify, "shaped", return_value=0))
        config.ensure_dirs()
        self.cfg = config.load()
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            self.script(adapters / f"{harness}.sh", ADAPTER)
        workers = self.cfg["defaults"]["workers"]
        self.executor = workers[0]
        self.reviewer = next(name for name in workers if config.model(self.cfg, name)["provider"] !=
                             config.model(self.cfg, self.executor)["provider"])
        self.task = self.root / "task.md"
        self.stack.enter_context(redirect_stdout(io.StringIO()))

    def script(self, path, body):
        path.write_text(f"#!{sys.executable}\n{body}")
        path.chmod(0o755)

    def reviews(self, *answers):
        (self.root / "reviews.json").write_text(json.dumps(list(answers)))

    def launch(self, rounds=None, *flags):
        """One scratch run, so the loop is the only thing under test: no repo, branch or PR."""
        front = f"---\nrepo: none\n{'' if rounds is None else f'rounds: {rounds}'}\n---\n"
        self.task.write_text(f"{front}# Budget fixture\n\n"
                             "## Done when\n```bash\ntest -f deliverable\n```\n")
        before = set(run.run_dirs())
        code = run.main([str(self.task), "--exec", self.executor, "--review", self.reviewer, *flags])
        directory = (set(run.run_dirs()) - before).pop()
        return code, directory, run.read_state(directory)

    def test_preamble_names_the_four_blocking_classes_and_the_follow_ups_heading(self):
        for role in ("reviewer", "reviewer-pr", "reviewer-scratch"):
            with self.subTest(role=role):
                text = worker.PREAMBLES[role].format(workspace=self.root)
                for words in ("a correctness defect in the task's outcome",
                              "a safety or data-loss risk",
                              "a check the executor weakened or skipped",
                              "a scope violation (work the task did not ask for, "
                              "or asked-for work missing)",
                              "## Follow-ups", "`path:line - what - why it matters`",
                              "never a reason to fail",
                              "however long the follow-ups list is",
                              "for blocking findings only"):
                    self.assertIn(words, text)
        for role in ("executor", "fixer"):
            with self.subTest(role=role):
                text = worker.PREAMBLES[role].format(workspace=self.root)
                self.assertIn("`## Blocked` is only for a task that cannot be completed as written; "
                              "never for a transient provider failure, a capacity refusal, or a check "
                              "the loop runs later such as the `# once` suite.", text)

    def test_pass_follow_ups_are_recorded_by_the_loop(self):
        self.reviews(PASS_FOLLOWUPS)
        code, directory, state = self.launch(rounds=1)
        self.assertEqual(code, 0, (directory / "log.txt").read_text())
        self.assertEqual(state["followups"],
                         ["a.py:1 - empty input crashes - base abc123: `parse([])` raises IndexError",
                          "b.py:2 - zero divisor crashes - base abc123: `ratio(0)` raises ZeroDivisionError"])

    def test_every_reviewer_requires_evidence_and_rules_on_disputes_first(self):
        for role in ("reviewer", "reviewer-pr", "reviewer-scratch"):
            with self.subTest(role=role):
                text = worker.PREAMBLES[role].format(workspace=self.root)
                self.assertIn("A blocking finding must include evidence: a command that fails, "
                              "a reproduction, or quoted diff lines that show the defect.", text)
                self.assertIn("In a re-review, first rule on each disputed finding: upheld or "
                              "dropped, and why; then say which earlier findings are fixed and "
                              "which are not, then anything new.", text)

    def test_every_fixer_may_dispute_with_evidence_and_must_fix_the_rest(self):
        for role, work in (("fixer", "the diff"), ("fixer-scratch", "the workspace")):
            with self.subTest(role=role):
                text = worker.PREAMBLES[role].format(workspace=self.root)
                self.assertIn("You may dispute a finding instead of changing code: list the "
                              "finding and evidence that it is wrong under `## Disputed` "
                              "in your summary.", text)
                self.assertIn("For every undisputed finding, fix every instance of that pattern "
                              f"in {work}", text)
                self.assertNotIn("Fix every finding below", text)
                self.assertIn("re-run the per-round done-when commands", text)

    def test_dispute_without_changes_reaches_re_review_in_the_executor_summary(self):
        finding = "- deliverable:1 - empty file - no output delivered"
        summary = ("## Summary\nNo changes needed; `test -s deliverable` exits 0.\n\n"
                   "## Disputed\n" + finding + "\n"
                   "Evidence: `test -s deliverable` exits 0; it contains `fixture work`.\n")
        (self.root / "fixer-summary.md").write_text(summary)
        self.reviews("VERDICT: FAIL\n\n## Findings\n" + finding,
                     "Dropped: deliverable is nonempty, as the fixer's command shows.\n" + PASS)
        code, directory, state = self.launch(rounds=2)
        self.assertEqual(code, 0, (directory / "log.txt").read_text())
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        fixer = [call["prompt"] for call in calls if call["role"] == "executor"][1]
        reviews = [call["prompt"] for call in calls if call["role"] == "reviewer"]
        self.assertIn(finding, fixer)
        self.assertEqual(len(reviews), 2)
        self.assertNotIn("## Executor summary\n" + summary, reviews[0])
        self.assertIn("## Executor summary\n" + summary, reviews[1])
        self.assertEqual([entry["verdict"] for entry in state["round_summaries"]], ["FAIL", "PASS"])

    def test_pass_follow_ups_land_in_pr_body_without_a_followups_file(self):
        repo = self.root / "repo"
        repo.mkdir()
        wt = self.root / "checkout"
        wt.mkdir()
        run_dir = config.RUNS / "20260922-0000-gate"
        run_dir.mkdir(parents=True)
        state = {"run_id": run_dir.name, "title": "gate fixture", "verdict": "PASS",
                 "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                      "summary": "did the work"}],
                 "rounds": 3, "base": "origin/main", "base_sha": "abc", "branch": "ak/gate",
                 "worktree": str(wt), "repo": str(repo), "executor": "opus", "reviewer": "astra",
                 "findings": "",
                 "followups": ["a.py:1 - empty input crashes - base abc123: `parse([])` raises IndexError",
                               "b.py:2 - zero divisor crashes - base abc123: `ratio(0)` raises ZeroDivisionError"],
                 "pr": None, "merge_method": "squash"}
        lp = run.Loop(self.cfg, run_dir, state, {}, lambda s: None, wt, "body", ["true"],
                      "context", [])
        url = "https://github.com/fixture/repo/pull/7"
        with patch.object(run, "gh", return_value=(0, f"opened {url}")):
            self.assertEqual(run.open_pr(lp, "main"), url)
        body = (run_dir / "pr-body.md").read_text()
        self.assertIn("## Follow-ups", body)
        self.assertIn("- a.py:1 - empty input crashes - base abc123: `parse([])` raises IndexError", body)
        self.assertIn("- b.py:2 - zero divisor crashes - base abc123: `ratio(0)` raises ZeroDivisionError", body)
        self.assertFalse((config.HOME / "followups").exists())

    def test_second_round_replaces_the_follow_ups(self):
        first = ("VERDICT: FAIL\n\n## Findings\n- a.py:1 - wrong answer - correctness\n\n"
                 "## Follow-ups\n- b.py:2 - empty input crashes - base abc123: IndexError\n")
        second = ("VERDICT: PASS\n\n## Findings\n- none\n\n"
                  "## Follow-ups\n- b.py:2 - empty input crashes - base abc123: `parse([])` raises IndexError\n"
                  "- c.py:3 - zero divisor crashes - base abc123: `ratio(0)` raises ZeroDivisionError\n")
        self.reviews(first, second)
        code, directory, state = self.launch(rounds=3)
        self.assertEqual(code, 0, (directory / "log.txt").read_text())
        self.assertEqual(state["followups"],
                         ["b.py:2 - empty input crashes - base abc123: `parse([])` raises IndexError",
                          "c.py:3 - zero divisor crashes - base abc123: `ratio(0)` raises ZeroDivisionError"])

    def test_default_budget_is_three_rounds_with_no_extension(self):
        self.reviews(fail(2), fail(2), fail(2))
        code, directory, state = self.launch()      # the task names no rounds of its own
        self.assertEqual(code, 1, (directory / "log.txt").read_text())
        self.assertEqual((state["state"], state["rounds"]), ("fail", 3))
        self.assertEqual(len(state["round_summaries"]), 3)
        self.assertNotIn("extended", state)
        self.assertNotIn("converging", (directory / "log.txt").read_text())
        self.assertFalse(hasattr(run, "extend"))
        self.assertFalse(hasattr(run, "EXTENSIONS"))

    def test_third_fail_hands_back_with_the_blocking_findings(self):
        blocking = ("VERDICT: FAIL\n\n## Findings\n"
                    "- a.py:1 - off-by-one in the gate - wrong outcome for edge input\n"
                    "- b.py:2 - drops the error - silent data loss\n\n"
                    "## Follow-ups\n- c.py:3 - rename this - clarity\n")
        self.reviews(fail(1), fail(1), blocking)
        code, directory, state = self.launch()
        self.assertEqual((code, state["state"]), (1, "fail"))
        self.assertEqual(run.handback_reason(state), "after 3 rounds, open findings: "
                         "- a.py:1 - off-by-one in the gate - wrong outcome for edge input "
                         "- b.py:2 - drops the error - silent data loss")
        line = run.handback_line(state, directory)
        self.assertIn("finished FAIL: after 3 rounds, open findings: - a.py:1 - off-by-one", line)
        self.assertIn("Decide the next step.", line)
        result = (directory / "result.md").read_text()
        self.assertIn("## Reviewer findings", result)
        self.assertIn("off-by-one in the gate", result)
        self.assertIn("drops the error", result)

    def test_rounds_five_is_refused_before_any_round(self):
        self.reviews(PASS)
        with self.assertRaisesRegex(config.Error, r"^--rounds 5 is over the budget: 3 rounds, then "
                                    r"a run goes back to its orchestrator to split or re-scope$"):
            self.launch(None, "--rounds", "5")
        self.assertEqual(run.run_dirs(), [])
        self.assertFalse((self.root / "calls.jsonl").exists())

    def test_task_template_defaults_to_three_rounds(self):
        path = REPO / "templates" / "task.md"
        meta, _, _ = task.parse_task(path)
        self.assertEqual(int(meta.get("rounds") or 3), 3)
        self.assertIn("`rounds` defaults to 3", path.read_text())

    def test_existing_pr_refreshes_pr_body_without_a_followups_file(self):
        repo = self.root / "repo"
        repo.mkdir()
        wt = self.root / "checkout"
        wt.mkdir()
        run_dir = config.RUNS / "20260922-0000-refresh"
        run_dir.mkdir(parents=True)
        state = {"run_id": run_dir.name, "title": "refresh fixture", "verdict": "PASS",
                 "round_summaries": [{"round": 1, "verdict": "PASS", "done_when": True,
                                      "summary": "did the work"}],
                 "rounds": 3, "base": "origin/main", "base_sha": "abc", "branch": "ak/refresh",
                 "worktree": str(wt), "repo": str(repo), "executor": "opus", "reviewer": "astra",
                 "findings": "", "followups": ["a.py:1 - empty input crashes - base abc123: `parse([])` raises IndexError"],
                 "pr": None, "merge_method": "squash"}
        lp = run.Loop(self.cfg, run_dir, state, {}, lambda s: None, wt, "body", ["true"],
                      "context", [])
        url = "https://github.com/fixture/repo/pull/7"
        with patch.object(run, "gh", return_value=(0, f"opened {url}")) as gh:
            self.assertEqual(run.open_pr(lp, "main"), url)
            # A re-review replaces the list even after the PR already exists.
            state["followups"] = ["b.py:2 - zero divisor crashes - base abc123: `ratio(0)` raises ZeroDivisionError"]
            self.assertEqual(run.open_pr(lp, "main"), url)
        self.assertEqual(gh.call_args.args[1:4], ("pr", "edit", url))
        body = (run_dir / "pr-body.md").read_text()
        self.assertIn("- b.py:2 - zero divisor crashes - base abc123: `ratio(0)` raises ZeroDivisionError", body)
        self.assertNotIn("- a.py:1", body)
        self.assertFalse((config.HOME / "followups").exists())


if __name__ == "__main__":
    unittest.main()
