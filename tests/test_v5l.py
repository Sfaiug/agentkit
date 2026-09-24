"""agentkit v5l: three rounds is the budget; a FAIL below it resumes only with more rounds.

Entirely offline fixture state."""

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
from agentkit import config, notify, run, worker


def fail(count, note="pattern"):
    """A reviewer answer with `count` findings listed under `## Findings`."""
    items = "\n".join(f"- file.py:{n} - {note} - why it matters" for n in range(1, count + 1))
    return f"VERDICT: FAIL\n\n## Findings\n{items}\n" if count else "VERDICT: FAIL\n"


PASS = "VERDICT: PASS\n\n## Findings\n- none\n"


def grouped(*counts):
    """A FAIL whose findings are grouped under `### <pattern>` subheadings, as asked for."""
    blocks = []
    for n, count in enumerate(counts, 1):
        items = "\n".join(f"- file{n}.py:{i} - pattern {n} - why it matters"
                           for i in range(1, count + 1))
        blocks.append(f"### Pattern {n}\n{items}\n")
    return "VERDICT: FAIL\n\n## Findings\n" + "\n".join(blocks)

# One fake harness for every model in the catalogue: it never leaves the fixture directory,
# records each prompt it was given, and answers reviews from a plan the test writes.
ADAPTER = '''import json, os, pathlib, sys
root = pathlib.Path(os.environ["V5L_FIXTURE"])
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
    if (root / "break-donewhen").exists():
        deliverable.unlink(missing_ok=True)
    else:
        deliverable.write_text("fixture work\\n")
    (out / "final.md").write_text("## Summary\\nFixture work.")
else:
    plan = json.loads((root / "reviews.json").read_text())
    answer = plan.pop(0) if len(plan) > 1 else plan[0]
    (root / "reviews.json").write_text(json.dumps(plan))
    (out / "final.md").write_text(answer)
    (out / "session_id").write_text("session-" + role)
    if answer.startswith("HTTP "):
        sys.exit(1)
(out / "session_id").write_text("session-" + role)
'''


class BudgetRuns(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5l-", dir=REPO)
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
            "AGENTKIT_DISCORD_WEBHOOK": "off", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(sockets), "TMUX": "", "NO_COLOR": "1",
            "PYTHONDONTWRITEBYTECODE": "1", config.ADAPTER_DIR_ENV: str(adapters),
            "V5L_FIXTURE": str(self.root)}))
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
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        self.stack.enter_context(patch.object(run, "SLOT_POLL", .01))
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

    def launch(self, rounds=3, *flags):
        """One scratch run, so the loop is the only thing under test: no repo, branch or PR."""
        self.task.write_text(f"---\nrepo: none\nrounds: {rounds}\n---\n# Budget fixture\n\n"
                             "## Done when\n```bash\ntest -f deliverable\n```\n")
        before = set(run.run_dirs())
        code = run.main([str(self.task), "--exec", self.executor, "--review", self.reviewer, *flags])
        directory = (set(run.run_dirs()) - before).pop()
        return code, directory, run.read_state(directory)

    def calls(self, role=None):
        path = self.root / "calls.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [row for row in rows if role is None or row["role"] == role]

    def log(self, directory):
        return (directory / "log.txt").read_text()

    def extensions(self, directory):
        """The log lines that granted another round, in order: always none now."""
        return [line.split("] ", 1)[-1] for line in self.log(directory).splitlines()
                if "round budget" in line]

    def status(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(run.cmd_status(list(argv)), 0)
        return out.getvalue()

    # --- (a) a shrinking last round buys nothing ----------------------------

    def test_v5l_shrinking_findings_at_the_last_round_do_not_extend_the_budget(self):
        self.reviews(fail(4), fail(3), fail(2), PASS)
        code, directory, state = self.launch(rounds=3)
        self.assertEqual(code, 1, self.log(directory))
        self.assertEqual(state["state"], "fail")
        self.assertEqual(state["rounds"], 3)
        self.assertNotIn("extended", state)
        self.assertEqual(len(state["round_summaries"]), 3)
        self.assertEqual([entry["finding_count"] for entry in state["round_summaries"]],
                         [4, 3, 2])
        self.assertEqual(self.extensions(directory), [])
        self.assertEqual(len(self.calls("executor")), 3)
        self.assertTrue(run.failed_at_budget(state))
        self.assertEqual(run.continue_line(state), "")    # past three: split or re-scope

    # --- (b) no extension is granted, ever ----------------------------------

    def test_v5l_no_extension_is_granted_and_the_run_fails_at_its_budget(self):
        self.reviews(fail(5), fail(4), fail(3), fail(2), fail(1))
        code, directory, state = self.launch(rounds=3)
        self.assertEqual(code, 1, self.log(directory))
        self.assertEqual(state["state"], "fail")
        self.assertEqual(state["rounds"], 3)
        self.assertNotIn("extended", state)
        self.assertEqual(len(state["round_summaries"]), 3)
        self.assertEqual(self.extensions(directory), [])
        self.assertEqual([entry["finding_count"] for entry in state["round_summaries"]],
                         [5, 4, 3])
        self.assertTrue(run.failed_at_budget(state))
        self.assertEqual(run.continue_line(state), "")    # past three: split or re-scope

    # --- (c) standing still, and a failing done-when, earn nothing ---------

    def test_v5l_findings_that_do_not_shrink_do_not_extend_the_budget(self):
        self.reviews(fail(3), fail(2), fail(2))
        code, directory, state = self.launch(rounds=3)
        self.assertEqual(code, 1, self.log(directory))
        self.assertEqual((state["state"], state["rounds"]), ("fail", 3))
        self.assertNotIn("extended", state)
        self.assertEqual(len(state["round_summaries"]), 3)
        self.assertEqual(self.extensions(directory), [])

    def test_v5l_a_failing_done_when_does_not_extend_the_budget(self):
        # The check here can never pass, and v5ay calls that the task's defect once a fix
        # round has left it saying exactly the same thing: the run ends `blocked` at round 2
        # instead of spending its third.  Only the final state moved; a failing done-when
        # still buys no round, which `extend` itself is held to below.
        (self.root / "break-donewhen").touch()
        self.reviews(fail(3), fail(2), fail(1))
        code, directory, state = self.launch(rounds=3)
        self.assertEqual(code, 1, self.log(directory))
        self.assertEqual((state["state"], state["rounds"]), ("blocked", 3))
        self.assertEqual(state["error"], run.BLOCKED_SAME)
        self.assertNotIn("extended", state)
        self.assertEqual([entry["done_when"] for entry in state["round_summaries"]], [False])
        self.assertEqual(self.extensions(directory), [])
        self.assertEqual([entry["finding_count"] for entry in state["round_summaries"]], [3])

    def test_v5l_there_is_no_converging_extension_to_grant(self):
        """The budget is the budget: no function grows it and no constant sizes the growth."""
        self.assertFalse(hasattr(run, "extend"))
        self.assertFalse(hasattr(run, "EXTENSIONS"))

    def test_v5l_a_reviewer_that_listed_nothing_before_does_not_extend_the_budget(self):
        self.reviews(fail(2), fail(0), fail(0))
        code, directory, state = self.launch(rounds=3)
        self.assertEqual(code, 1, self.log(directory))
        self.assertEqual((state["state"], state["rounds"]), ("fail", 3))
        self.assertNotIn("extended", state)
        self.assertEqual([entry["finding_count"] for entry in state["round_summaries"]], [2, 0, 0])
        self.assertEqual(self.extensions(directory), [])

    # --- (d)/(e) a FAIL at the budget resumes, with more rounds and only so -

    def exhausted_run(self):
        """A run that ended `fail` with its whole budget spent and its work still there."""
        self.reviews(fail(3), fail(2), PASS)
        code, directory, state = self.launch(rounds=2)
        self.assertEqual((code, state["state"], state["rounds"]), (1, "fail", 2))
        return directory, state

    def test_v5l_resume_with_a_larger_budget_continues_a_fail_at_its_next_round(self):
        directory, state = self.exhausted_run()
        findings = state["findings"]
        self.assertEqual(run.cmd_resume([directory.name, "--rounds", "3"]), 0, self.log(directory))
        after = run.read_state(directory)
        self.assertEqual(after["state"], "pass")
        self.assertEqual(after["rounds"], 3)
        self.assertEqual(len(after["round_summaries"]), 3)
        self.assertEqual(after["round_summaries"][-1]["round"], 3)
        self.assertIn("resuming at round 3/3", self.log(directory))
        self.assertIn("--- round 3/3:", self.log(directory))
        # the third executor turn is a fixer, handed the findings of the round before it
        fixer = self.calls("executor")[2]
        self.assertTrue(fixer["prompt"].startswith("You are the executor, continuing"))
        self.assertIn("## Reviewer findings to fix", fixer["prompt"])
        self.assertIn(findings.strip(), fixer["prompt"])
        self.assertEqual(fixer["session"], ["session-executor"])
        self.assertEqual(self.calls("reviewer")[2]["session"], ["session-reviewer"])
        self.assertTrue(run.review_pass(after, self.cfg))
        self.assertEqual(run.delivery(after), "PASS, delivered")
        # the delivered workspace stays with its run: the resumed work is there,
        # and result.md links it
        self.assertEqual((Path(after["worktree"]) / "deliverable").read_text(), "fixture work\n")
        self.assertIn("- [deliverable](", (directory / "result.md").read_text())
        self.assertFalse(run.failed_at_budget(after))
        self.assertEqual(run.continue_line(after), "")

    def test_v5l_resume_without_a_larger_budget_is_refused_and_names_the_saved_one(self):
        directory, state = self.exhausted_run()
        spent = len(self.calls())
        for argv in ([directory.name], [directory.name, "--rounds", "2"]):
            with self.subTest(argv=argv):
                with self.assertRaisesRegex(
                        config.Error,
                        rf"{directory.name} FAILed at its round budget \(2\); "
                        r"give --rounds N above it, at most 3, to continue"):
                    run.cmd_resume(argv)
        self.assertEqual(len(self.calls()), spent)       # refused before any model call
        self.assertEqual(run.read_state(directory)["state"], "fail")
        # a FAIL with rounds still to spend is not one of these, and keeps the older message
        run.save_state(directory, {**state, "rounds": 3})
        with self.assertRaisesRegex(config.Error, "is 'fail', not interrupted or exhausted"):
            run.cmd_resume([directory.name, "--rounds", "3"])

    # --- (f) the way on is printed ----------------------------------------

    def test_v5l_a_fail_at_the_budget_prints_how_to_continue_and_a_merged_run_does_not(self):
        directory, state = self.exhausted_run()
        wanted = f"continue: ak run resume {directory.name} --rounds 3"
        self.assertTrue((directory / "result.md").read_text().rstrip().endswith(wanted),
                        (directory / "result.md").read_text()[-400:])
        self.assertIn(wanted, self.status(directory.name))
        merged = config.RUNS / "20260101-1000-merged"
        merged.mkdir()
        run.save_state(merged, {**state, "run_id": merged.name, "state": "pass", "verdict": "PASS",
                                "merged": True, "no_merge": False})
        run.write_result(merged, run.read_state(merged), ["test -f deliverable"])
        self.assertNotIn("continue: ak run resume", (merged / "result.md").read_text())
        self.assertNotIn("continue: ak run resume", self.status(merged.name))
        self.assertEqual(run.continue_line(run.read_state(merged)), "")

    def test_v5l_status_shows_a_spent_budget_with_no_extension(self):
        self.reviews(fail(4), fail(3), fail(2), PASS)
        _, directory, state = self.launch(rounds=3)
        self.assertNotIn("extended", state)
        line = next(row for row in self.status(directory.name).splitlines()
                    if row.startswith(directory.name))
        self.assertIn("round 3/3", line)
        self.assertNotIn("(+", line)
        self.assertNotIn("continue: ak run resume", self.status(directory.name))

    # --- (g) what the workers are told ------------------------------------

    def test_v5l_preambles_tell_workers_about_notify_patterns_and_one_pass(self):
        self.reviews(fail(2), PASS)
        _, directory, _ = self.launch(rounds=3)
        executor, fixer = self.calls("executor")[0], self.calls("executor")[1]
        self.assertTrue(executor["prompt"].startswith("You are the executor."))
        for prompt in (executor["prompt"], fixer["prompt"]):
            self.assertIn("`ak notify` is not available in this session", prompt)
            self.assertIn("goes into your `## Summary`", prompt)
        self.assertIn("fix every instance of that pattern", fixer["prompt"])
        self.assertIn("list the sites you changed in your summary", fixer["prompt"])
        reviewer = self.calls("reviewer")[0]["prompt"]
        self.assertTrue(reviewer.startswith("You are the reviewer"))
        self.assertIn("Report every finding you can establish in this one pass", reviewer)
        self.assertIn("grouped by pattern with every site listed", reviewer)
        self.assertIn("say first which earlier findings are fixed and which are not", reviewer)
        self.assertIn("`VERDICT: PASS` or `VERDICT: FAIL`", reviewer)
        self.assertIn("`## Findings` as a list of `path:line - issue - why it matters`", reviewer)
        self.assertNotIn("ak notify", reviewer)
        # every role keeps its opener, which is what the fixtures and adapters route on
        openers = {"executor": "You are the executor.", "fixer": "You are the executor, continuing",
                   "reviewer": "You are the reviewer.",
                   "reviewer-pr": "You are the reviewer of a pull request by another author.",
                   "executor-scratch": "You are the executor.",
                   "fixer-scratch": "You are the executor, continuing",
                   "reviewer-scratch": "You are the reviewer."}
        self.assertEqual(set(openers), set(worker.PREAMBLES))
        for role, opener in openers.items():
            with self.subTest(role=role):
                text = worker.PREAMBLES[role].format(workspace=self.root)
                self.assertTrue(text.startswith(opener), text[:80])
                if role.startswith("reviewer"):
                    self.assertIn("Report every finding you can establish in this one pass", text)
                    self.assertNotIn("ak notify", text)
                else:
                    self.assertIn("`ak notify` is not available in this session", text)
                if role.startswith("fixer"):
                    self.assertIn("fix every instance of that pattern", text)

    def test_v5l_findings_grouped_by_pattern_do_not_converge(self):
        """The reviewer is asked to group by pattern; those subheadings are inside the list."""
        self.reviews(grouped(3, 2), grouped(2, 1), grouped(1, 1), PASS)
        code, directory, state = self.launch(rounds=3)
        self.assertEqual(code, 1, self.log(directory))
        self.assertEqual([entry["finding_count"] for entry in state["round_summaries"]],
                         [5, 3, 2])
        self.assertEqual(self.extensions(directory), [])
        self.assertEqual(state["state"], "fail")

    # --- the findings a resumed round is handed ---------------------------

    def test_v5l_a_resumed_fixer_is_handed_the_whole_review_not_the_saved_tail(self):
        """run.json keeps a bounded tail; the fixer that continues gets the file itself."""
        first = "first-pattern-site-that-the-tail-drops"
        wide = fail(2, note=first) + "\n" + fail(40, note="x" * 300).split("## Findings\n", 1)[1]
        self.assertGreater(len(wide), 8000)
        self.reviews(wide, wide, PASS)
        directory, state = None, None
        code, directory, state = self.launch(rounds=2)
        self.assertEqual((code, state["state"]), (1, "fail"))
        self.assertNotIn(first, state["findings"])        # the tail alone has lost it
        self.assertIn(first, self.calls("executor")[1]["prompt"])
        self.assertEqual(run.cmd_resume([directory.name, "--rounds", "3"]), 0, self.log(directory))
        resumed = self.calls("executor")[2]["prompt"]
        self.assertIn(first, resumed)
        self.assertIn(wide.strip(), resumed)
        state = run.read_state(directory)
        self.assertEqual(state["findings_file"],
                         str(directory / "round-3" / "reviewer" / "final.md"))
        # with the round directory gone, the bounded tail is still better than nothing
        # a `findings_file` that does not match the tail is repaired from the round's answers
        whole = run.read_answer(state["findings_file"])
        state["findings_file"] = str(directory / "round-9" / "reviewer" / "final.md")
        self.assertEqual(run.saved_findings(directory, state), whole)
        # with the answers gone as well, the bounded tail is still better than nothing
        self.assertEqual(run.saved_findings(directory, {**state, "round_summaries": []}),
                         state["findings"])

    def test_v5l_a_reviewer_retry_records_the_answer_it_returned_not_the_error(self):
        """`call_retrying` gives each retry its own directory; the answer is in the last one."""
        first = "first-pattern-site-that-the-tail-drops"
        wide = fail(2, note=first) + "\n" + fail(40, note="y" * 300).split("## Findings\n", 1)[1]
        # the last round of the budget is the one whose reviewer had to be retried
        self.reviews(fail(42, note="earlier"), "HTTP 503 Service Unavailable\n", wide, PASS)
        with patch.object(run.time, "sleep"):
            code, directory, state = self.launch(rounds=2)
        self.assertEqual((code, state["state"]), (1, "fail"), self.log(directory))
        self.assertIn("retrying in", self.log(directory))
        second = directory / "round-2"
        self.assertEqual((second / "reviewer" / "final.md").read_text(),
                         "HTTP 503 Service Unavailable\n")
        self.assertEqual(state["round_summaries"][1]["finding_count"], 42)
        # the review the round recorded is what the next fixer gets, not the error beside it
        self.assertEqual(run.cmd_resume([directory.name, "--rounds", "3"]), 0, self.log(directory))
        resumed = self.calls("executor")[2]["prompt"]
        self.assertIn(first, resumed)
        self.assertNotIn("HTTP 503", resumed)
        self.assertEqual(run.written_answer(second / "reviewer", wide),
                         second / "reviewer-retry1" / "final.md")

    # --- what a run saved before this change still carries ----------------

    def existing_format(self, directory, **changes):
        """The same run with everything this change added to run.json taken back out."""
        state = run.read_state(directory)
        for entry in state["round_summaries"]:
            entry.pop("finding_count", None)
        state.pop("findings_file", None)
        state.pop("extended", None)
        state.update(changes)
        run.save_state(directory, state)
        return state

    def test_v5l_an_existing_run_recovers_its_whole_review_from_the_round_directory(self):
        first = "first-pattern-site-that-the-tail-drops"
        wide = fail(2, note=first) + "\n" + fail(40, note="z" * 300).split("## Findings\n", 1)[1]
        self.reviews(wide, wide, PASS)
        _, directory, state = self.launch(rounds=2)
        state = self.existing_format(directory)
        self.assertNotIn(first, state["findings"])
        self.assertEqual(run.cmd_resume([directory.name, "--rounds", "3"]), 0, self.log(directory))
        self.assertIn(first, self.calls("executor")[2]["prompt"])
        self.assertEqual(run.saved_findings(directory, state), wide)

    def test_v5l_an_existing_conflict_fail_drops_its_obsolete_pending_review(self):
        self.reviews(fail(2), fail(2), PASS)
        _, directory, state = self.launch(rounds=2)
        summaries = run.read_state(directory)["round_summaries"]
        # what a conflict at the cap left behind before the abort dropped it
        state = self.existing_format(directory, state="fail", verdict="FAIL", merge_failed=True,
                                     merge_note="the rebase of origin/main conflicted",
                                     review_pending={"round": 3, "summary": summaries[-1]["summary"],
                                                     "reason": "Re-review after the rebase."})
        self.assertEqual(run.cmd_resume([directory.name, "--rounds", "3"]), 0, self.log(directory))
        after = run.read_state(directory)
        self.assertNotIn("review_pending", after)
        # the delivery note of the attempt this one replaces goes with it
        self.assertFalse(after["merge_failed"])
        self.assertIsNone(after["merge_note"])
        self.assertEqual([entry["round"] for entry in after["round_summaries"]], [1, 2, 3])
        self.assertIn("--- round 3/3: executor", self.log(directory))
        # round 3 was a fixer round, not a bare re-review
        self.assertEqual(len(self.calls("executor")), 3)
        self.assertIn("## Reviewer findings to fix", self.calls("executor")[2]["prompt"])
        self.assertEqual(after["state"], "pass")

    def test_v5l_an_existing_run_spends_a_resumed_round_without_converging(self):
        self.reviews(fail(3), fail(2), fail(1), PASS)
        _, directory, _ = self.launch(rounds=2)
        state = self.existing_format(directory)
        self.assertFalse(any("finding_count" in e for e in state["round_summaries"]))
        self.assertEqual(run.cmd_resume([directory.name, "--rounds", "3"]), 1, self.log(directory))
        after = run.read_state(directory)
        # round 3 found one where round 2 found two, and bought nothing with it
        self.assertEqual(self.extensions(directory), [])
        self.assertEqual((after["state"], after["rounds"]), ("fail", 3))
        self.assertNotIn("extended", after)
        self.assertEqual(len(after["round_summaries"]), 3)

    # --- an aborted integration leaves nothing pending --------------------

    def test_v5l_an_aborted_conflict_leaves_no_pending_review_for_the_resume(self):
        """`integrate` records the pending re-review before git rewrites HEAD; an abort undoes it."""
        for rnd, why in ((2, "with the round budget spent"), (1, "with a round left")):
            with self.subTest(why=why):
                self.reviews(PASS)
                _, directory, state = self.launch(rounds=2)
                lp = run.Loop(self.cfg, directory, run.read_state(directory), {},
                              lambda line: None, Path(state["worktree"]), "body", ["true"],
                              "context", [])
                lp.rnd = rnd
                run.pending_review(lp, "Re-review after the rebase of origin/main.")
                self.assertIn("review_pending", run.read_state(directory))
                calls = []
                with patch.object(run, "git", return_value=""), \
                        patch.object(run, "git_out",
                                     side_effect=lambda wt, *a, **k: (calls.append(a), (0, ""))[1]):
                    self.assertFalse(run.resolve_conflicts(lp, "origin/main", "conflicted", "rebase"))
                self.assertIn(("rebase", "--abort"), calls)
                after = run.read_state(directory)
                self.assertNotIn("review_pending", after)
                # what the abandoned integration invalidated stays invalidated, and the
                # spent budget is no cap on a conflict round: the run parks `waiting`
                # with the reason rather than ending FAIL
                self.assertIsNone(after["verdict"])
                self.assertIsNone(after["review"])
                self.assertEqual(after["state"], "waiting")
                self.assertFalse(after["merge_failed"])

    # --- a second FAIL, at three rounds, is refused for good ---------------

    def test_v5l_a_resumed_fail_at_its_new_budget_is_refused_without_more_rounds(self):
        directory, _ = self.exhausted_run()
        self.reviews(fail(2), fail(2))
        self.assertEqual(run.cmd_resume([directory.name, "--rounds", "3"]), 1, self.log(directory))
        state = run.read_state(directory)
        self.assertEqual((state["state"], state["rounds"]), ("fail", 3))
        self.assertTrue(state["recovery_pending"])        # the resume records one of its own
        self.assertTrue(run.needs_recovery(state))
        spent = len(self.calls())
        for argv in ([directory.name], [directory.name, "--rounds", "3"], [directory.name, "--bg"]):
            with self.subTest(argv=argv):
                with self.assertRaisesRegex(config.Error, r"FAILed at its round budget \(3\); "
                                                          r"3 rounds is the budget, so split or "
                                                          r"re-scope the task"):
                    run.cmd_resume(argv)
        self.assertEqual(len(self.calls()), spent)
        self.assertEqual(run.read_state(directory)["state"], "fail")
        self.assertNotIn("continue: ak run resume", (directory / "result.md").read_text())

    # --- a review finished on a resume buys no extra round ------------------

    def test_v5l_a_review_finished_on_a_resume_buys_no_extra_round(self):
        self.reviews(fail(4), fail(3), fail(2), PASS)
        _, directory, state = self.launch(rounds=3)
        self.assertEqual((state["state"], state["rounds"]), ("fail", 3))
        # rewind to the shape an exhausted reviewer leaves: round 3 reviewed, nothing recorded
        state = run.read_state(directory)
        summaries = state["round_summaries"]
        state.update(state="exhausted", verdict=None, review=None, rounds=3,
                     error="reviewer died on API errors; waiting for review",
                     round_summaries=summaries[:2],
                     review_pending={"round": 3, "summary": summaries[1]["summary"],
                                     "reason": "Resume the unfinished review."})
        run.save_state(directory, state)
        self.reviews(fail(2), PASS)
        self.assertEqual(run.cmd_resume([directory.name]), 1, self.log(directory))
        after = run.read_state(directory)
        self.assertEqual(after["state"], "fail")
        self.assertEqual(after["rounds"], 3)
        self.assertNotIn("extended", after)
        self.assertEqual([entry["round"] for entry in after["round_summaries"]], [1, 2, 3])
        self.assertEqual(self.extensions(directory), [])

    # --- how many findings a round found ----------------------------------

    def test_v5l_findings_are_counted_the_same_way_for_every_round(self):
        cases = [("VERDICT: FAIL\n## Findings\n- a\n- b\n- c\n", 3),
                 # grouped by pattern, as every reviewer is now asked to do
                 ("VERDICT: FAIL\n## Findings\n### One pattern\n- a\n- b\n"
                  "### Another\n- c\n", 3),
                 ("VERDICT: FAIL\n# Findings\n## a pattern\n- a\n# Appendix\n- skipped\n", 1),
                 ("VERDICT: FAIL\n\n## Findings\n\n1. a\n2) b\n", 2),
                 ("VERDICT: FAIL\n## Findings\n* a\n  - a nested site\n+ b\n", 3),
                 ("VERDICT: FAIL\n## Findings\n- a\n\n## Notes\n- not a finding\n", 1),
                 ("VERDICT: FAIL\n## findings (2 patterns)\n- a\n- b\n", 2),
                 ("VERDICT: FAIL\n## Findings\nnothing listed here\n", 0),
                 ("VERDICT: FAIL\nno findings section at all\n", 0),
                 ("", 0)]
        for text, want in cases:
            with self.subTest(text=text[:40]):
                self.assertEqual(run.finding_count(text), want)


if __name__ == "__main__":
    unittest.main(verbosity=2)
