"""The merge step never ends a run that passed review.  Entirely offline.

Real throwaway git repos under a temp dir with a bare `origin`; no network, no real
harness.  Fixers are stubs that either resolve the conflict and finish the rebase or do
nothing at all, the reviewer is a stub verdict, and `gh` is a stub that can lose the race
to a merge to the target.
"""

from contextlib import ExitStack, nullcontext
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.hand_in import submitting
from fixtures.landing import landing
from agentkit import gate, host, config, gc, land, run, usage
from agentkit import record

URL = "https://github.com/fixture/repo/pull/7"
BASE_RACE = ("GraphQL: Base branch was modified. Review and try the merge again. "
             "(mergePullRequest)")
HEAD_RACE = ("GraphQL: Head branch was modified. Review and try the merge again. "
             "(mergePullRequest)")
GITHUB_504 = ('non-200 OK status code: 504 Gateway Timeout body: "{\\"message\\": \\"We '
              "couldn't respond to your request in time. Sorry about that. Please try "
              'resubmitting your request and contact us if the problem persists.\\"}"')


def make_repos(root):
    """A bare origin, an owner clone that moves it, and a work clone on ak/test."""
    remote = root / "origin.git"
    run.git(root, "init", "--bare", "--initial-branch=main", str(remote))
    owner = root / "owner"
    run.git(root, "clone", str(remote), str(owner))
    for cwd in (owner,):
        run.git(cwd, "config", "user.name", "fixture")
        run.git(cwd, "config", "user.email", "fixture@localhost")
    (owner / "base.txt").write_text("base\n")
    run.git(owner, "add", ".")
    run.git(owner, "commit", "-m", "base")
    run.git(owner, "push", "origin", "main")
    wt = root / "wt"
    run.git(root, "clone", str(remote), str(wt))
    run.git(wt, "config", "user.name", "fixture")
    run.git(wt, "config", "user.email", "fixture@localhost")
    run.git(wt, "checkout", "-b", "ak/test")
    (wt / "work.txt").write_text("work\n")
    run.git(wt, "add", ".")
    run.git(wt, "commit", "-m", "work")
    return remote, owner, wt


def conflict(owner, wt):
    """`shared` changed on both sides, so the next rebase of ak/test stops on it."""
    (wt / "shared").write_text("branch intent\n")
    run.git(wt, "add", ".")
    run.git(wt, "commit", "-m", "branch shared")
    (owner / "shared").write_text("base\n")
    run.git(owner, "add", ".")
    run.git(owner, "commit", "-m", "base shared")
    run.git(owner, "push", "origin", "main")
    (owner / "shared").write_text("target intent\n")
    run.git(owner, "add", ".")
    run.git(owner, "commit", "-m", "target intent")
    run.git(owner, "push", "origin", "main")


def resolve(wt):
    """What a conflict fixer does: keep both sides' intent and finish the rebase."""
    (wt / "shared").write_text("both intents\n")
    run.git(wt, "add", "shared")
    run.git(wt, "-c", "core.editor=true", "rebase", "--continue")
    return "## Summary\nResolved both sides."


def make_loop(root, wt, rounds=3, spent=1, cfg=None):
    """A run that passed review on its last recorded round, `spent` of `rounds`."""
    run_dir = root / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "log.txt").touch()
    head = run.git(wt, "rev-parse", "HEAD")
    tree = run.git(wt, "rev-parse", "HEAD^{tree}")
    base_sha = run.git(wt, "rev-parse", "origin/main^{commit}")
    lines = []

    def log(msg):
        line = f"[00:00:00] {msg}"
        lines.append(line)
        print(line, flush=True)
        with (run_dir / "log.txt").open("a") as fh:
            fh.write(line + "\n")

    cfg = cfg or config.load()
    executor_provider, reviewer_provider = run.review_providers(cfg, "opus", "astra")
    state = {
        "run_id": "merge-step-test", "title": "merge step", "state": "running",
        "verdict": "PASS",
        "review": {"executor": "opus", "executor_provider": executor_provider, "reviewer": "astra",
                   "reviewer_provider": reviewer_provider, "returncode": 0, "verdict": "PASS",
                   "done_when": True, "head_sha": head, "tree_sha": tree},
        "round_summaries": [{"round": n, "verdict": "PASS", "done_when": True,
                             "summary": "work", "head_sha": head, "tree_sha": tree}
                            for n in range(1, spent + 1)],
        "rounds": rounds, "base": "origin/main", "target": "origin/main",
        "base_sha": base_sha, "branch": "ak/test", "worktree": str(wt),
        "repo": str(wt), "executor": "opus", "reviewer": "astra",
        "merge_method": "squash", "merged": False, "merge_failed": False,
        "merge_note": None, "findings": "", "delivery_sha": head,
    }
    record.save_state(run_dir, state)
    lp = run.Loop(cfg, run_dir, state, {}, log, wt, "body", ["true"], "context", [])
    return lp, run_dir, lines


class MergeStep(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-merge-step-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        self.stack.enter_context(patch.object(host, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()
        self.stack.enter_context(patch.object(land, "start_line"))
        def checks(cmds, wt, out, *args, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            return True, "$ true\n[exit 0]\n"

        self.stack.enter_context(patch.object(gate, "run_done_when", side_effect=checks))
        self.stack.enter_context(patch.object(run, "call_retrying", side_effect=submitting(self.review_call)))
        # every failing gate here is the branch's own: the target is green, so the
        # red-target probe never parks (tests/test_red_target.py covers a red tip)
        self.stack.enter_context(patch.object(run, "target_fails", return_value=False))

    def review_call(self, cfg, name, body, workspace, out, role, session, log, limit=None, **kwargs):
        self.assertEqual(role, "reviewer")
        answer = "VERDICT: PASS\n\n## Findings\n- none\n"
        out.mkdir(parents=True)
        (out / "final.md").write_text(answer)
        return 0, answer, session, False

    def log_text(self, run_dir):
        return (run_dir / "log.txt").read_text()

    def test_a_conflict_round_does_not_consume_the_budget(self):
        # a run that passed at 2 of 2 -- the round budget is spent by the task's own
        # rounds -- meets a conflicted rebase at the merge: the conflict round runs
        # anyway and none of it is spent from a budget that is not its own
        _, owner, wt = make_repos(self.root)
        conflict(owner, wt)
        lp, run_dir, _ = make_loop(self.root, wt, rounds=2, spent=2)

        def fixer(lp2, role, text, name):
            return resolve(wt)

        with patch.object(run, "execute", side_effect=fixer):
            self.assertTrue(run.integrate(lp, "origin/main"))
        state = record.read_state(run_dir)
        self.assertEqual(len(state["round_summaries"]), 2)   # still 2 of 2
        self.assertEqual(state["rounds"], 2)
        self.assertTrue(run.current_review(lp))
        self.assertNotIn("round budget", self.log_text(run_dir))

    def test_three_conflict_rounds_park_waiting(self):
        # no fixer finishes the conflicted rebase: three conflict rounds work it, and
        # the run parks `waiting` with the reason rather than ending FAIL -- the tick
        # retries it after the next merge to the branch it waits on
        _, owner, wt = make_repos(self.root)
        conflict(owner, wt)
        lp, run_dir, _ = make_loop(self.root, wt)
        turns = []

        def fixer(lp2, role, text, name):
            turns.append(name)
            return "## Summary\nCould not resolve."

        with patch.object(run, "execute", side_effect=fixer):
            self.assertFalse(run.integrate(lp, "origin/main"))
        self.assertEqual(turns, ["rebase-fixer"] * 3)
        state = record.read_state(run_dir)
        self.assertEqual(state["state"], "waiting")
        self.assertNotEqual(state["verdict"], "FAIL")
        self.assertEqual(state["waiting_on"]["ref"], "origin/main")
        self.assertTrue(state["waiting_on"]["sha"])
        self.assertIn("did not finish the rebase of origin/main", state["merge_note"])
        self.assertFalse(state["merge_failed"])
        self.assertEqual(len(state["round_summaries"]), 1)   # no conflict round counted
        self.assertFalse(run.in_progress(wt, "rebase"))

    def test_a_failing_final_check_spends_no_task_round_and_parks_waiting(self):
        # every review passed and the budget is spent; the once suite keeps failing on the
        # account, not the work: three fixer rounds of its own, re-reviewed but never counted
        # as task rounds, then a wait the tick retries -- never a FAIL, never `--rounds`
        _, owner, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt, rounds=3, spent=3)
        lp.once = ["bash tests/smoke.sh"]
        suites, turns = [], []

        def checks(cmds, cwd, out, *args, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            if "bash tests/smoke.sh" not in cmds:
                return True, "$ true\n[exit 0]\n"
            suites.append(1)
            return False, ("$ true\n[exit 0]\n\n$ bash tests/smoke.sh\n[exit 1]\n"
                           "PASS  3 the menu draws\nFAIL  4 ak run: no delete_repo scope\n"
                           f"acceptance: FAILED (see /tmp/smoke-{len(suites)})")

        def fixer(lp2, role, text, name):
            turns.append((name, lp2.rnd))
            (wt / f"try{len(turns)}.txt").write_text("tried\n")
            run.git(wt, "add", ".")
            run.git(wt, "commit", "-m", "try the final check")
            return "## Summary\nTried."

        with patch.object(gate, "run_done_when", side_effect=checks), \
                patch.object(run, "execute", side_effect=fixer):
            self.assertFalse(run.final_check(lp, "origin/main"))
        self.assertEqual(turns, [("final-fixer", 3)] * 3)
        self.assertEqual(len(suites), 4)
        state = record.read_state(run_dir)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(state["verdict"], "PASS")
        self.assertFalse(state["merge_failed"])
        self.assertEqual(len(state["round_summaries"]), 3)   # still 3 of 3
        self.assertEqual(state["waiting_on"], {"ref": "origin/main",
                                               "sha": run.git(owner, "rev-parse", "HEAD")})
        # one line, however the suite spaced it
        self.assertEqual(state["merge_note"], "the final check still fails after 3 fixer "
                         "rounds: `bash tests/smoke.sh` — FAIL 4 ak run: no delete_repo scope")
        self.assertNotIn("round budget", self.log_text(run_dir))

    def test_a_final_check_re_review_fail_with_rounds_left_runs_a_fixer(self):
        # the re-review after a final-check fix FAILs with rounds left: a fixer round on its
        # findings spends a task round, the final-check fixer round before it none
        _, owner, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt, rounds=3, spent=1)
        lp.once = ["bash tests/smoke.sh"]
        suite = iter([False, True])
        turns = []

        def checks(cmds, cwd, out, *args, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            if "bash tests/smoke.sh" in cmds and not next(suite):
                return False, "$ bash tests/smoke.sh\n[exit 1]\nFAIL  2 the gate"
            return True, "$ true\n[exit 0]\n"

        def fixer(lp2, role, text, name):
            turns.append((name, lp2.rnd, text))
            (wt / f"fix{len(turns)}.txt").write_text("fixed\n")
            run.git(wt, "add", ".")
            run.git(wt, "commit", "-m", "fix")
            return "## Summary\nFixed."

        verdicts = iter(["FAIL", "PASS"])

        def fake_review(cfg, name, body, workspace, out, role, session, log, limit=None, **kwargs):
            verdict = next(verdicts)
            answer = (f"VERDICT: {verdict}\n\n## Findings\n"
                      + ("- fix1.txt:1 - the fix skips the gate\n" if verdict == "FAIL"
                         else "- none\n"))
            out.mkdir(parents=True)
            (out / "final.md").write_text(answer)
            return 0, answer, session, False

        with patch.object(gate, "run_done_when", side_effect=checks), \
                patch.object(run, "execute", side_effect=fixer), \
                patch.object(run, "call_retrying", side_effect=submitting(fake_review)):
            self.assertTrue(run.final_check(lp, "origin/main"))
        self.assertEqual([(name, rnd) for name, rnd, _ in turns],
                         [("final-fixer", 1), ("executor", 2)])
        self.assertIn("## Reviewer findings to fix", turns[1][2])
        self.assertIn("fix1.txt:1 - the fix skips the gate", turns[1][2])
        state = record.read_state(run_dir)
        self.assertEqual([entry["round"] for entry in state["round_summaries"]], [1, 2])
        self.assertEqual(state["final_check"]["outcome"], "passed")
        self.assertTrue(run.current_review(lp))

    def test_a_final_check_re_review_fail_at_the_budget_is_a_review_fail(self):
        # the re-review after a final-check fix FAILs with the budget spent: no fixer is
        # left to run, and the run hands back a review FAIL with its findings, never a wait.
        # The fixer changed nothing, so the last round's PASS judged this very commit: the
        # resume must still take the FAIL to a fixer round, never put that PASS back
        _, owner, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt, rounds=3, spent=3)
        lp.once = ["bash tests/smoke.sh"]
        turns = []

        def checks(cmds, cwd, out, *args, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            if "bash tests/smoke.sh" in cmds:
                return False, "$ bash tests/smoke.sh\n[exit 1]\nFAIL  2 the gate"
            return True, "$ true\n[exit 0]\n"

        def fixer(lp2, role, text, name):
            turns.append((name, lp2.rnd))
            return "## Summary\nNothing to change."

        def fake_review(cfg, name, body, workspace, out, role, session, log, limit=None, **kwargs):
            answer = "VERDICT: FAIL\n\n## Findings\n- work.txt:1 - the gate is skipped\n"
            out.mkdir(parents=True)
            (out / "final.md").write_text(answer)
            return 0, answer, session, False

        with patch.object(gate, "run_done_when", side_effect=checks), \
                patch.object(run, "execute", side_effect=fixer), \
                patch.object(run, "call_retrying", side_effect=submitting(fake_review)):
            self.assertFalse(run.final_check(lp, "origin/main"))
        self.assertEqual(turns, [("final-fixer", 3)])
        state = record.read_state(run_dir)
        self.assertNotEqual(state["state"], "waiting")
        self.assertNotIn("waiting_on", state)
        self.assertEqual(state["verdict"], "FAIL")
        self.assertEqual(state["merge_note"],
                         "done-when or review after the final check did not pass")
        self.assertEqual(len(state["round_summaries"]), 3)   # the re-review spent none
        self.assertEqual(state["review"]["head_sha"], state["round_summaries"][-1]["head_sha"])
        state["state"] = "fail"         # what the run makes of a FAIL the merge step left
        record.save_state(run_dir, state)
        self.assertTrue(run.handback_reason(state).startswith("after 3 rounds, open findings: "
                        "- work.txt:1 - the gate is skipped - fixture defect"))
        self.assertFalse(run.integration_note(state, run_dir))
        self.assertTrue(run.failed_at_budget(state))

    def test_a_pass_the_loop_overrode_at_the_budget_says_why(self):
        # the reviewer printed PASS after the final-check fix, then exited 1: the loop's FAIL
        # at the budget hands back why, not "no reason was recorded"
        _, owner, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt, rounds=1, spent=1)
        lp.once = ["bash tests/smoke.sh"]

        def checks(cmds, cwd, out, *args, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            if "bash tests/smoke.sh" in cmds:
                return False, "$ bash tests/smoke.sh\n[exit 1]\nFAIL  2 the gate"
            return True, "$ true\n[exit 0]\n"

        def fake_review(cfg, name, body, workspace, out, role, session, log, limit=None, **kwargs):
            answer = "VERDICT: PASS\n\n## Findings\n- none\n"
            out.mkdir(parents=True)
            (out / "final.md").write_text(answer)
            return 1, answer, session, False

        with patch.object(gate, "run_done_when", side_effect=checks), \
                patch.object(run, "execute", return_value="## Summary\nTried."), \
                patch.object(run, "call_retrying", side_effect=submitting(fake_review)):
            self.assertFalse(run.final_check(lp, "origin/main"))
        state = record.read_state(run_dir)
        self.assertEqual(state["review"]["overridden"], "the reviewer said PASS but exited 1")
        state["state"] = "fail"
        self.assertEqual(run.handback_reason(state),
                         "after 1 rounds, the reviewer said PASS but exited 1; the final "
                         "check failed at landing: `bash tests/smoke.sh` — FAIL  2 the gate")

    def test_a_gate_overridden_final_check_review_gets_a_fixer_on_the_gate(self):
        # after a final-check fix a done-when command fails and the reviewer still says PASS:
        # with rounds left a fixer round works from the failing output, never a wait
        _, owner, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt, rounds=3, spent=1)
        lp.once = ["bash tests/smoke.sh"]
        suites, gates, turns = [], [], []

        def checks(cmds, cwd, out, *args, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            if "bash tests/smoke.sh" in cmds:
                suites.append(1)
                if len(suites) == 1:
                    return False, "$ bash tests/smoke.sh\n[exit 1]\nFAIL  2 the gate"
                return True, "$ bash tests/smoke.sh\n[exit 0]\n"
            gates.append(1)
            if len(gates) == 2:
                return False, "$ true\n[exit 1]\nlint: fix1.txt:1 trailing space"
            return True, "$ true\n[exit 0]\n"

        def fixer(lp2, role, text, name):
            turns.append((name, lp2.rnd, text))
            (wt / f"fix{len(turns)}.txt").write_text("fixed\n")
            run.git(wt, "add", ".")
            run.git(wt, "commit", "-m", "fix")
            return "## Summary\nFixed."

        with patch.object(gate, "run_done_when", side_effect=checks), \
                patch.object(run, "execute", side_effect=fixer):
            self.assertTrue(run.final_check(lp, "origin/main"))
        self.assertEqual([(name, rnd) for name, rnd, _ in turns],
                         [("final-fixer", 1), ("executor", 2)])
        self.assertIn("## The done-when commands failed.", turns[1][2])
        self.assertIn("lint: fix1.txt:1 trailing space", turns[1][2])
        state = record.read_state(run_dir)
        self.assertNotEqual(state["state"], "waiting")
        self.assertEqual([entry["round"] for entry in state["round_summaries"]], [1, 2])
        self.assertEqual(state["final_check"]["outcome"], "passed")

    def test_a_conflict_re_review_fail_at_the_budget_is_a_review_fail(self):
        # a rebase or merge conflict resolved with the budget spent, and its re-review FAILs:
        # a review FAIL handed back with its findings, never a wait
        for how in ("rebase", "merge"):
            with self.subTest(how=how):
                root = self.root / how
                root.mkdir()
                _, owner, wt = make_repos(root)
                conflict(owner, wt)
                lp, run_dir, _ = make_loop(root, wt, rounds=2, spent=2)
                if how == "merge":
                    lp.state["merge_method"] = "merge"

                def fixer(lp2, role, text, name):
                    self.assertEqual(name, f"{how}-fixer")
                    if how == "rebase":
                        return resolve(wt)
                    (wt / "shared").write_text("both intents\n")
                    run.git(wt, "add", "shared")
                    run.git(wt, "commit", "--no-edit")
                    return "## Summary\nResolved both sides."

                def fake_review(cfg, name, body, workspace, out, role, session, log,
                                limit=None, **kwargs):
                    answer = "VERDICT: FAIL\n\n## Findings\n- shared:1 - drops the target side\n"
                    out.mkdir(parents=True)
                    (out / "final.md").write_text(answer)
                    return 0, answer, session, False

                with patch.object(run, "execute", side_effect=fixer), \
                        patch.object(run, "call_retrying", side_effect=submitting(fake_review)):
                    self.assertFalse(run.integrate(lp, "origin/main"))
                state = record.read_state(run_dir)
                self.assertNotEqual(state["state"], "waiting")
                self.assertNotIn("waiting_on", state)
                self.assertEqual(state["verdict"], "FAIL")
                self.assertEqual(state["merge_note"],
                                 f"done-when or review after the {how} of origin/main did not pass")
                self.assertEqual(len(state["round_summaries"]), 2)
                state["state"] = "fail"
                self.assertTrue(run.handback_reason(state).startswith("after 2 rounds, open findings: "
                                "- shared:1 - drops the target side - fixture defect"))


    def test_a_post_rebase_review_fail_with_rounds_left_runs_a_fixer(self):
        # the re-review after the merge-time rebase FAILs with rounds left: a fixer
        # round carries its findings like any failed review, then review again
        _, owner, wt = make_repos(self.root)
        conflict(owner, wt)
        lp, run_dir, _ = make_loop(self.root, wt, rounds=3, spent=1)
        turns = []

        def fixer(lp2, role, text, name):
            turns.append((name, text))
            return resolve(wt) if name == "rebase-fixer" else "## Summary\nFixed the findings."

        verdicts = iter(["FAIL", "PASS"])

        def fake_review(cfg, name, body, workspace, out, role, session, log, limit=None, **kwargs):
            verdict = next(verdicts)
            answer = (f"VERDICT: {verdict}\n\n## Findings\n"
                      + ("- shared:1 - the merged tree breaks\n" if verdict == "FAIL"
                         else "- none\n"))
            out.mkdir(parents=True)
            (out / "final.md").write_text(answer)
            return 0, answer, session, False

        with patch.object(run, "execute", side_effect=fixer), \
                patch.object(run, "call_retrying", side_effect=submitting(fake_review)):
            self.assertTrue(run.integrate(lp, "origin/main"))
        findings = [text for name, text in turns if name == "executor"]
        self.assertEqual(len(findings), 1)
        self.assertIn("## Reviewer findings to fix", findings[0])
        self.assertIn("shared:1 - the merged tree breaks", findings[0])
        self.assertEqual(lp.rnd, 2)                          # the fixer round spent one
        state = record.read_state(run_dir)
        self.assertEqual(state["verdict"], "PASS")
        self.assertEqual([entry["round"] for entry in state["round_summaries"]], [1, 2])
        self.assertNotEqual(state["state"], "fail")

    def test_a_dry_provider_on_a_conflict_fixer_hands_over(self):
        # the conflict fixer's provider is dry: the turn goes to the next eligible
        # worker exactly as an executor turn does, with the handover note and all
        _, owner, wt = make_repos(self.root)
        conflict(owner, wt)
        lp, run_dir, _ = make_loop(self.root, wt, cfg=config.load())
        asked = []

        def call(cfg, name, body, workspace, out, role, session, log, limit=None, **kwargs):
            if role == "reviewer":
                return self.review_call(cfg, name, body, workspace, out, role, session, log, limit)
            asked.append((name, body))
            if len(asked) == 1:
                raise run.RanDry(name, "quota", 1, "", session, None,
                                 "usage limit reached", True)
            return 0, resolve(wt), session, False

        with patch.object(run, "call_retrying", side_effect=submitting(call)), \
                patch.object(usage, "collect", return_value={}), \
                patch.object(usage, "pick_order", return_value=["opus", "astra", "spark"]):
            self.assertTrue(run.integrate(lp, "origin/main"))
        self.assertEqual([name for name, _ in asked], ["opus", lp.executor])
        self.assertNotEqual(lp.executor, "opus")              # handed over
        self.assertIn("Another model started this round", asked[1][1])
        self.assertIn(f"handing executor to {lp.executor}", self.log_text(run_dir))

    def assert_stopped_conflict_fixer_resumes(self, stop, parked, how="rebase"):
        _, owner, wt = make_repos(self.root)
        conflict(owner, wt)
        lp, run_dir, _ = make_loop(config.RUNS, wt, rounds=3, spent=3)
        history = [dict(entry) for entry in lp.state["round_summaries"]]
        head = run.git(wt, "rev-parse", "HEAD")
        tip = run.git(owner, "rev-parse", "HEAD")
        lp.state["state"] = "exhausted"
        if how == "merge":
            lp.state["merge_method"] = "merge"
        lp.save()
        (run_dir / "task.md").write_text(
            f"---\nrepo: {wt}\nrounds: 3\n---\n# Conflict retry\n\n"
            "## Done when\n```bash\ntrue\n```\n")
        binaries = self.root / "bin"
        binaries.mkdir()
        tmux = binaries / "tmux"
        tmux.write_text("#!/bin/sh\nexit 1\n")
        tmux.chmod(0o755)
        turns = []

        def fixer(lp, role, text, name, **_kw):
            self.assertEqual((role, name), ("fixer", f"{how}-fixer"))
            turns.append(lp.rnd)
            if how == "rebase":
                return resolve(wt)
            (wt / "shared").write_text("both intents\n")
            run.git(wt, "add", "shared")
            run.git(wt, "commit", "--no-edit")
            return "## Summary\nResolved both sides."

        def deliver(lp, **_kw):
            if run.integrate(lp, "origin/main"):
                self.assertTrue(run.current_review(lp))
                self.assertTrue(run.integrated(wt, tip))
                lp.state["merged"] = True

        with patch.dict(os.environ, {"PATH": f"{binaries}:{os.environ['PATH']}",
                                     "AGENTKIT_DISCORD_WEBHOOK": "off"}), \
                patch.object(usage, "collect", return_value={}), \
                patch.object(usage, "pick_order", return_value=["opus", "astra"]), \
                patch.object(gc, "disk_pressure", return_value=False), \
                patch.object(run, "launcher_world", return_value=nullcontext(True)), \
                patch.object(run, "hand_back", return_value=True), \
                patch.object(run.notify, "shaped", side_effect=AssertionError("notification")), \
                patch.object(run, "stop_run_tree"), \
                patch.object(run.history, "Sampler"), \
                patch.object(run.history, "sample_rss", return_value=None), \
                patch.object(run, "merge", side_effect=deliver), \
                patch.object(run, "execute", side_effect=fixer):
            with patch.object(run, "execute", side_effect=stop):
                self.assertEqual(run.cmd_resume([run_dir.name]), 1)
            saved = record.read_state(run_dir)
            self.assertEqual(saved["state"], parked)
            self.assertEqual(run.git(wt, "rev-parse", "HEAD"), head)
            self.assertFalse(run.in_progress(wt, how))
            code = run.cmd_resume([run_dir.name])
        state = record.read_state(run_dir)
        print(f"{type(stop).__name__} ({how}): stopped={saved['state']} "
              f"review_pending={saved.get('review_pending')}; resumed={code} "
              f"state={state['state']} merged={state['merged']}", flush=True)
        self.assertEqual(code, 0)
        self.assertEqual(saved["review_pending"]["round"], 3)
        self.assertIs(saved["review_pending"]["record"], False)
        self.assertEqual(turns, [3])
        self.assertEqual(state["round_summaries"], history)
        self.assertEqual(state["rounds"], 3)
        self.assertEqual(state["state"], "pass")
        self.assertTrue(state["merged"])
        self.assertNotIn("review_pending", state)

    def test_an_exhausted_conflict_fixer_keeps_the_last_round_resumable(self):
        self.assert_stopped_conflict_fixer_resumes(run.QuotaDry("provider spent"), "exhausted")

    def test_an_expired_login_on_a_conflict_fixer_keeps_the_last_round_resumable(self):
        self.assert_stopped_conflict_fixer_resumes(
            run.worker.LoginExpired("claude", "sign in again"), "waiting_login")

    def test_a_killed_conflict_fixer_keeps_the_last_round_resumable(self):
        self.assert_stopped_conflict_fixer_resumes(run.Killed("signal 15"), "interrupted")

    def test_an_expired_login_on_a_merge_conflict_fixer_keeps_the_last_round_resumable(self):
        self.assert_stopped_conflict_fixer_resumes(
            run.worker.LoginExpired("claude", "sign in again"), "waiting_login", how="merge")

    def test_a_killed_merge_conflict_fixer_keeps_the_last_round_resumable(self):
        self.assert_stopped_conflict_fixer_resumes(
            run.Killed("signal 15"), "interrupted", how="merge")

    def test_a_clean_rebase_failed_gate_spends_no_task_round(self):
        _, owner, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt, rounds=3, spent=3)
        # The work already spent its task budget; a failed landing gate gets a
        # fixer before any reviewer, and both stay on the last task round.
        (owner / "other.txt").write_text("other\n")
        run.git(owner, "add", ".")
        run.git(owner, "commit", "-m", "other work on main")
        run.git(owner, "push", "origin", "main")
        gates = iter([False, True])
        turns, reviews = [], []
        failure = "$ check\n[exit 1]\nThe integrated tree still needs fixed.txt.\n"

        def checks(cmds, wt, out, *args, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            ok = next(gates)
            return (True, "$ check\n[exit 0]\n") if ok else (False, failure)

        def review_call(cfg, name, body, workspace, out, role, session, log, limit=None, **kwargs):
            self.assertTrue((wt / "fixed.txt").exists(), "reviewed a failing gate")
            reviews.append(out.parent.name)
            return self.review_call(cfg, name, body, workspace, out, role, session, log,
                                    limit, **kwargs)

        def fixer(lp2, role, text, name):
            turns.append((lp2.rnd, role, text))
            (wt / "fixed.txt").write_text("fixed\n")
            run.git(wt, "add", ".")
            run.git(wt, "commit", "-m", "fix findings")
            return "## Summary\nFixed the findings."

        with patch.object(run, "execute", side_effect=fixer), \
                patch.object(run, "call_retrying", side_effect=submitting(review_call)), \
                patch.object(gate, "run_done_when", side_effect=checks):
            self.assertTrue(run.integrate(lp, "origin/main"))
        self.assertEqual([(rnd, role) for rnd, role, _ in turns], [(3, "fixer")])
        self.assertIn(failure, turns[0][2])
        self.assertEqual(reviews, ["round-3"])
        self.assertEqual([entry["round"] for entry in lp.state["round_summaries"]],
                         [1, 2, 3])
        self.assertTrue(run.current_review(lp))

    def test_an_interrupted_conflict_review_resumes_without_spending_a_round(self):
        _, owner, wt = make_repos(self.root)
        conflict(owner, wt)
        lp, run_dir, _ = make_loop(self.root, wt, rounds=2, spent=2)
        with patch.object(run, "execute", side_effect=lambda *a: resolve(wt)), \
                patch.object(run, "call_retrying", side_effect=run.QuotaDry("reviewer dry")), \
                patch.object(usage, "collect", return_value={}), \
                patch.object(usage, "pick_order", return_value=[]):
            with self.assertRaises(run.Exhausted):
                run.integrate(lp, "origin/main")
        saved = record.read_state(run_dir)
        self.assertFalse(saved["review_pending"]["record"])
        resumed = run.Loop(lp.cfg, run_dir, saved, {}, lp.log, wt, "body", ["true"], "context", [])
        with patch.object(run, "execute", side_effect=AssertionError("unexpected fixer")):
            run.rounds(resumed)
        self.assertEqual(len(resumed.state["round_summaries"]), 2)
        self.assertTrue(run.current_review(resumed))

    def test_cmd_merge_keeps_a_conflict_waiting(self):
        _, owner, wt = make_repos(self.root)
        conflict(owner, wt)
        lp, run_dir, _ = make_loop(config.RUNS, wt, rounds=1, spent=1)
        lp.state.update(state="pass", pr=URL)
        lp.save()
        (run_dir / "task.md").write_text("# Merge fixture\n\n## Done when\n```bash\ntrue\n```\n")
        info = {"headRefOid": lp.state["delivery_sha"], "baseRefName": "main", "state": "OPEN"}
        with patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "execute", return_value="## Summary\nUnresolved."), \
                patch.object(run, "stop_run_tree"), \
                patch.object(run, "rights", return_value=("acme/widget", "WRITE")):
            self.assertEqual(run.cmd_merge([run_dir.name]), 0)
            lp.state = record.read_state(run_dir)
            self.assertFalse(landing(lp, lambda: run.do_merge(lp, URL, "origin/main")))
        self.assertEqual(record.read_state(run_dir)["state"], "waiting")
        self.assertTrue((run_dir / "result.md").read_text().startswith("# WAITING:"))

    def test_a_base_race_verifies_and_pushes_the_new_head_before_retrying(self):
        _, owner, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt)
        lp.state["pr"] = URL
        old = lp.state["delivery_sha"]
        events = []

        def fake_gh(cwd, *args, **kwargs):
            if args[:2] == ("pr", "merge"):
                events.append(("merge", args[-1]))
                if len(events) == 1:
                    (owner / "moved.txt").write_text("main moved\n")
                    run.git(owner, "add", ".")
                    run.git(owner, "commit", "-m", "main moved")
                    run.git(owner, "push", "origin", "main")
                    return 1, BASE_RACE
                self.assertTrue(run.current_review(lp))
                self.assertNotEqual(args[-1], old)
                self.assertEqual(events[-2], ("checks", args[-1]))
                return 0, ""
            if args[:2] == ("pr", "view"):
                events.append(("view", old))
                return 0, json.dumps({"state": "OPEN", "mergeable": "MERGEABLE",
                                      "headRefOid": old, "baseRefName": "main"})
            if args[:2] == ("pr", "edit"):
                self.assertEqual(args[2:4], (URL, "--body-file"))
                self.assertEqual(Path(args[4]).read_text(), run.pr_body(lp.state))
                return 0, ""
            raise AssertionError(args)

        def checks(lp2, url):
            head = lp2.state["delivery_sha"]
            self.assertEqual(run.git(wt, "rev-parse", "origin/ak/test"), head)
            events.append(("checks", head))
            return True

        def deliver():
            if run.git(wt, "rev-parse", "HEAD") != lp.state["delivery_sha"]:
                if not (run.push(lp) and checks(lp, URL) and run.refresh_pr_body(lp)):
                    return False
            return run.do_merge(lp, URL, "origin/main")

        with patch.object(run, "gh", side_effect=fake_gh), \
                patch.object(run, "wait_checks", side_effect=checks), \
                patch.object(run.time, "sleep"):
            self.assertFalse(landing(lp, deliver))
            place = lp.state["waiting_on"]["joined"]
            self.assertTrue(landing(lp, deliver))
            self.assertTrue(place)
        self.assertTrue(lp.state["merged"])
        self.assertEqual([name for name, _ in events], ["merge", "view", "checks", "merge"])

    def test_a_merge_that_loses_the_base_race_retries_then_parks_waiting(self):
        # `gh pr merge` answering `Base branch was modified` is a race, not an ending:
        # re-fetch, re-check the PR is still mergeable, try again -- three times, with a
        # growing wait -- and only then park `waiting` with the reason
        _, owner, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt)
        merges = []

        def fake_gh(cwd, *args, **kwargs):
            if args[:2] == ("pr", "merge"):
                merges.append(args)
                return 1, BASE_RACE
            if args[:2] == ("pr", "view"):
                return 0, json.dumps({"state": "OPEN", "mergeable": "MERGEABLE",
                                      "headRefOid": lp.state["delivery_sha"], "baseRefName": "main"})
            raise AssertionError(f"unexpected gh: {args[:4]}")

        with patch.object(run, "gh", side_effect=fake_gh), \
                patch.object(run.time, "sleep") as slept:
            self.assertFalse(landing(lp, lambda: run.do_merge(lp, URL, "origin/main")))
        self.assertEqual(len(merges), 4)                      # the first try and three retries
        # subprocess may also sleep briefly while reaping the fixture's git calls.
        self.assertEqual([call.args[0] for call in slept.call_args_list if call.args[0] >= 60],
                         [60, 300, 900])
        state = record.read_state(run_dir)
        self.assertEqual(state["state"], "waiting")
        self.assertNotEqual(state["verdict"], "FAIL")
        self.assertIn("base branch was modified", state["merge_note"])
        self.assertEqual(state["waiting_on"]["line"], run.turn_path(lp, "origin/main").name)

    def test_a_base_race_waits_for_known_mergeability_before_retrying(self):
        _, _, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt)
        seen = []

        def fake_gh(cwd, *args, **kwargs):
            seen.append(args[1])
            if args[:2] == ("pr", "merge"):
                return (1, BASE_RACE) if len(seen) == 1 else (0, "merged")
            if args[:2] == ("pr", "view"):
                return 0, json.dumps({"state": "OPEN", "headRefOid": lp.state["delivery_sha"],
                                      "baseRefName": "main", "mergeable":
                                      "UNKNOWN" if seen.count("view") == 1 else "MERGEABLE"})
            raise AssertionError(args)

        with patch.object(run, "gh", side_effect=fake_gh), patch.object(run.time, "sleep") as slept:
            self.assertTrue(landing(lp, lambda: run.do_merge(lp, URL, "origin/main")))
        self.assertEqual(seen, ["merge", "view", "view", "merge"])
        self.assertEqual([call.args[0] for call in slept.call_args_list if call.args[0] >= 60],
                         [60, 300])

    def test_a_github_5xx_on_the_merge_is_rechecked_and_a_merge_it_made_counts(self):
        # GitHub's own 504 may have merged anyway: the re-check finds it merged, and the run
        # lands rather than ending with a CLEAN PR left open
        _, _, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt)
        seen = []

        def fake_gh(cwd, *args, **kwargs):
            seen.append(args[1])
            if args[:2] == ("pr", "merge"):
                return 1, GITHUB_504
            if args[:2] == ("pr", "view"):
                return 0, json.dumps({"state": "MERGED", "headRefOid": lp.state["delivery_sha"],
                                      "baseRefName": "main", "mergeable": "UNKNOWN"})
            raise AssertionError(args)

        with patch.object(run, "gh", side_effect=fake_gh), patch.object(run.time, "sleep") as slept:
            self.assertTrue(landing(lp, lambda: run.do_merge(lp, URL, "origin/main")))
        self.assertEqual(seen, ["merge", "view"])
        self.assertTrue(record.read_state(run_dir)["merged"])
        self.assertEqual([call.args[0] for call in slept.call_args_list if call.args[0] >= 60],
                         [60])

    def test_a_github_5xx_on_the_merge_is_tried_again(self):
        _, _, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt)
        seen = []

        def fake_gh(cwd, *args, **kwargs):
            seen.append(args[1])
            if args[:2] == ("pr", "merge"):
                return (1, GITHUB_504) if len(seen) == 1 else (0, "merged")
            if args[:2] == ("pr", "view"):
                return 0, json.dumps({"state": "OPEN", "headRefOid": lp.state["delivery_sha"],
                                      "baseRefName": "main", "mergeable": "MERGEABLE"})
            raise AssertionError(args)

        with patch.object(run, "gh", side_effect=fake_gh), patch.object(run.time, "sleep") as slept:
            self.assertTrue(landing(lp, lambda: run.do_merge(lp, URL, "origin/main")))
        self.assertEqual(seen, ["merge", "view", "merge"])
        self.assertTrue(record.read_state(run_dir)["merged"])

    def test_a_merge_racing_its_own_push_is_tried_again_unless_the_head_moved(self):
        # GitHub can answer `Head branch was modified` for a head it has not yet taken in from
        # the delivery's own push: the re-check finds the pushed head and the merge goes
        # through; a head that really is another commit still ends the run
        for head, merged in (("delivered", True), ("0" * 40, False)):
            with self.subTest(head=head):
                root = self.root / head[:4]
                root.mkdir()
                _, _, wt = make_repos(root)
                lp, run_dir, _ = make_loop(root, wt)
                seen = []

                def fake_gh(cwd, *args, **kwargs):
                    seen.append(args[1])
                    if args[:2] == ("pr", "merge"):
                        return (1, HEAD_RACE) if len(seen) == 1 else (0, "merged")
                    if args[:2] == ("pr", "view"):
                        sha = lp.state["delivery_sha"] if merged else head
                        return 0, json.dumps({"state": "OPEN", "headRefOid": sha,
                                              "baseRefName": "main", "mergeable": "MERGEABLE"})
                    raise AssertionError(args)

                with patch.object(run, "gh", side_effect=fake_gh), patch.object(run.time, "sleep"):
                    self.assertEqual(bool(landing(lp, lambda: run.do_merge(lp, URL, "origin/main"))),
                                     merged)
                self.assertEqual(seen, ["merge", "view", "merge"] if merged else ["merge", "view"])
                state = record.read_state(run_dir)
                self.assertEqual(bool(state.get("merged")), merged)
                if not merged:
                    self.assertIn("PR head or target changed since PASS", state["merge_note"])

    def test_an_own_pr_merge_asks_again_after_a_github_5xx(self):
        _, _, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt)
        lp.state["own_orchestrator"] = "opus"
        merges = []

        def fake_gh(cwd, *args, **kwargs):
            if args[:2] == ("api", "repos/fixture/repo/pulls/7"):
                return 0, json.dumps({"state": "open", "head": {"sha": lp.state["delivery_sha"]},
                                      "base": {"ref": "main"}})
            if args[:2] == ("pr", "merge"):
                merges.append(args)
                return (1, GITHUB_504) if len(merges) == 1 else (0, "merged")
            if args[:2] == ("pr", "view"):
                return 0, json.dumps({"state": "OPEN", "headRefOid": lp.state["delivery_sha"],
                                      "baseRefName": "main", "mergeable": "MERGEABLE"})
            raise AssertionError(args)

        with patch.object(run, "gh", side_effect=fake_gh), \
                patch.object(run, "checks", return_value=(True, "")), \
                patch.object(run, "join_line", side_effect=lambda lp, _upstream, deliver:
                             landing(lp, deliver=deliver)), \
                patch.object(run, "merge_lock", lambda lp, upstream: nullcontext()), \
                patch.object(run.time, "sleep") as slept:
            self.assertTrue(run.merge_own_pr(lp, URL, lp.state["delivery_sha"]))
        self.assertEqual(len(merges), 2)
        self.assertTrue(record.read_state(run_dir)["merged"])
        self.assertEqual([call.args[0] for call in slept.call_args_list if call.args[0] >= 60],
                         [60])

    def test_a_merge_github_made_on_the_last_5xx_counts(self):
        # every attempt answers 504 and GitHub merged on the last one: no re-check followed
        # that attempt inside the loop, so the one before parking finds it merged
        _, _, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt)
        merges = []

        def fake_gh(cwd, *args, **kwargs):
            if args[:2] == ("pr", "merge"):
                merges.append(args)
                return 1, GITHUB_504
            if args[:2] == ("pr", "view") and "-q" in args:
                return 0, "MERGED"
            if args[:2] == ("pr", "view"):
                return 0, json.dumps({"state": "OPEN", "headRefOid": lp.state["delivery_sha"],
                                      "baseRefName": "main", "mergeable": "MERGEABLE"})
            raise AssertionError(args)

        with patch.object(run, "gh", side_effect=fake_gh), patch.object(run.time, "sleep"):
            self.assertTrue(landing(lp, lambda: run.do_merge(lp, URL, "origin/main")))
        self.assertEqual(len(merges), run.MERGE_RETRIES + 1)
        state = record.read_state(run_dir)
        self.assertTrue(state["merged"])
        self.assertNotEqual(state.get("state"), "waiting")

    def test_an_own_pr_merge_stops_when_its_recheck_stops(self):
        for answer in ((None, "timed out"), (1, "fatal: terminal prompts disabled")):
            with self.subTest(answer=answer):
                root = Path(tempfile.mkdtemp(dir=self.root))
                _, _, wt = make_repos(root)
                lp, run_dir, _ = make_loop(root, wt)
                lp.state["own_orchestrator"] = "opus"
                merges = []

                def fake_gh(cwd, *args, **kwargs):
                    if args[:2] == ("api", "repos/fixture/repo/pulls/7"):
                        return 0, json.dumps({"state": "open", "head": {"sha": lp.state["delivery_sha"]},
                                              "base": {"ref": "main"}})
                    if args[:2] == ("pr", "merge"):
                        merges.append(args)
                        return 1, GITHUB_504
                    if args[:2] == ("pr", "view"):
                        return answer
                    raise AssertionError(args)

                with patch.object(run, "gh", side_effect=fake_gh), \
                        patch.object(run, "checks", return_value=(True, "")), \
                        patch.object(run, "join_line", side_effect=lambda lp, _upstream, deliver:
                                     landing(lp, deliver=deliver)), \
                        patch.object(run, "merge_lock", lambda lp, upstream: nullcontext()), \
                        patch.object(run.time, "sleep"):
                    with self.assertRaises(run.Stopped):
                        run.merge_own_pr(lp, URL, lp.state["delivery_sha"])
                self.assertEqual(len(merges), 1)
                state = record.read_state(run_dir)
                self.assertFalse(state["merged"])
                self.assertIn("line", state["waiting_on"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
