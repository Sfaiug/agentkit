"""The merge step never ends a run that passed review.  Entirely offline.

Real throwaway git repos under a temp dir with a bare `origin`; no network, no real
harness.  Fixers are stubs that either resolve the conflict and finish the rebase or do
nothing at all, the reviewer is a stub verdict, and `gh` is a stub that can lose the race
to a merge to the target.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, run, usage

URL = "https://github.com/fixture/repo/pull/7"
BASE_RACE = ("GraphQL: Base branch was modified. Review and try the merge again. "
             "(mergePullRequest)")


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
    run.save_state(run_dir, state)
    lp = run.Loop(cfg, run_dir, state, {}, log, wt, "body", ["true"], "context", [])
    return lp, run_dir, lines


class MergeStep(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".merge-step-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        config.ensure_dirs()
        def checks(cmds, wt, out, *args, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            return True, "$ true\n[exit 0]\n"

        self.stack.enter_context(patch.object(run, "run_done_when", side_effect=checks))
        self.stack.enter_context(patch.object(run, "call_retrying", side_effect=self.review_call))

    def review_call(self, cfg, name, body, workspace, out, role, session, log, limit=None):
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
        state = run.read_state(run_dir)
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
        state = run.read_state(run_dir)
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

        with patch.object(run, "run_done_when", side_effect=checks), \
                patch.object(run, "execute", side_effect=fixer):
            self.assertFalse(run.final_check(lp, "origin/main"))
        self.assertEqual(turns, [("final-fixer", 3)] * 3)
        self.assertEqual(len(suites), 4)
        state = run.read_state(run_dir)
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

        def fake_review(cfg, name, body, workspace, out, role, session, log, limit=None):
            verdict = next(verdicts)
            answer = (f"VERDICT: {verdict}\n\n## Findings\n"
                      + ("- fix1.txt:1 - the fix skips the gate\n" if verdict == "FAIL"
                         else "- none\n"))
            out.mkdir(parents=True)
            (out / "final.md").write_text(answer)
            return 0, answer, session, False

        with patch.object(run, "run_done_when", side_effect=checks), \
                patch.object(run, "execute", side_effect=fixer), \
                patch.object(run, "call_retrying", side_effect=fake_review):
            self.assertTrue(run.final_check(lp, "origin/main"))
        self.assertEqual([(name, rnd) for name, rnd, _ in turns],
                         [("final-fixer", 1), ("executor", 2)])
        self.assertIn("## Reviewer findings to fix", turns[1][2])
        self.assertIn("fix1.txt:1 - the fix skips the gate", turns[1][2])
        state = run.read_state(run_dir)
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

        def fake_review(cfg, name, body, workspace, out, role, session, log, limit=None):
            answer = "VERDICT: FAIL\n\n## Findings\n- base.txt:1 - the gate is skipped\n"
            out.mkdir(parents=True)
            (out / "final.md").write_text(answer)
            return 0, answer, session, False

        with patch.object(run, "run_done_when", side_effect=checks), \
                patch.object(run, "execute", side_effect=fixer), \
                patch.object(run, "call_retrying", side_effect=fake_review):
            self.assertFalse(run.final_check(lp, "origin/main"))
        self.assertEqual(turns, [("final-fixer", 3)])
        state = run.read_state(run_dir)
        self.assertNotEqual(state["state"], "waiting")
        self.assertNotIn("waiting_on", state)
        self.assertEqual(state["verdict"], "FAIL")
        self.assertEqual(state["merge_note"],
                         "done-when or review after the final check did not pass")
        self.assertEqual(len(state["round_summaries"]), 3)   # the re-review spent none
        self.assertEqual(state["review"]["head_sha"], state["round_summaries"][-1]["head_sha"])
        state["state"] = "fail"         # what the run makes of a FAIL the merge step left
        run.save_state(run_dir, state)
        self.assertEqual(run.handback_reason(state), "after 3 rounds, open findings: "
                         "- base.txt:1 - the gate is skipped")
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

        def fake_review(cfg, name, body, workspace, out, role, session, log, limit=None):
            answer = "VERDICT: PASS\n\n## Findings\n- none\n"
            out.mkdir(parents=True)
            (out / "final.md").write_text(answer)
            return 1, answer, session, False

        with patch.object(run, "run_done_when", side_effect=checks), \
                patch.object(run, "execute", return_value="## Summary\nTried."), \
                patch.object(run, "call_retrying", side_effect=fake_review):
            self.assertFalse(run.final_check(lp, "origin/main"))
        state = run.read_state(run_dir)
        self.assertEqual(state["review"]["overridden"], "the reviewer said PASS but exited 1")
        state["state"] = "fail"
        self.assertEqual(run.handback_reason(state),
                         "after 1 rounds, the reviewer said PASS but exited 1; the final "
                         "check failed: `bash tests/smoke.sh` — FAIL  2 the gate")

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
                return True, "$ true\n[exit 0]\n\n$ bash tests/smoke.sh\n[exit 0]\n"
            gates.append(1)
            if len(gates) == 1:
                return False, "$ true\n[exit 1]\nlint: fix1.txt:1 trailing space"
            return True, "$ true\n[exit 0]\n"

        def fixer(lp2, role, text, name):
            turns.append((name, lp2.rnd, text))
            (wt / f"fix{len(turns)}.txt").write_text("fixed\n")
            run.git(wt, "add", ".")
            run.git(wt, "commit", "-m", "fix")
            return "## Summary\nFixed."

        with patch.object(run, "run_done_when", side_effect=checks), \
                patch.object(run, "execute", side_effect=fixer):
            self.assertTrue(run.final_check(lp, "origin/main"))
        self.assertEqual([(name, rnd) for name, rnd, _ in turns],
                         [("final-fixer", 1), ("executor", 2)])
        self.assertIn("## The done-when commands failed.", turns[1][2])
        self.assertIn("lint: fix1.txt:1 trailing space", turns[1][2])
        state = run.read_state(run_dir)
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
                                limit=None):
                    answer = "VERDICT: FAIL\n\n## Findings\n- shared:1 - drops the target side\n"
                    out.mkdir(parents=True)
                    (out / "final.md").write_text(answer)
                    return 0, answer, session, False

                with patch.object(run, "execute", side_effect=fixer), \
                        patch.object(run, "call_retrying", side_effect=fake_review):
                    self.assertFalse(run.integrate(lp, "origin/main"))
                state = run.read_state(run_dir)
                self.assertNotEqual(state["state"], "waiting")
                self.assertNotIn("waiting_on", state)
                self.assertEqual(state["verdict"], "FAIL")
                self.assertEqual(state["merge_note"],
                                 f"done-when or review after the {how} of origin/main did not pass")
                self.assertEqual(len(state["round_summaries"]), 2)
                state["state"] = "fail"
                self.assertEqual(run.handback_reason(state), "after 2 rounds, open findings: "
                                 "- shared:1 - drops the target side")

    def test_origin_moving_three_times_parks_waiting(self):
        _, owner, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt)
        real_out, laps = run.git_out, []

        def racing(cwd, *args, **kwargs):
            answer = real_out(cwd, *args, **kwargs)
            if args[:1] == ("rebase",):
                # origin moves again while every lap lands
                laps.append(run.git(cwd, "rev-parse", "HEAD"))
                (owner / f"move{len(laps)}.txt").write_text("moved\n")
                run.git(owner, "add", ".")
                run.git(owner, "commit", "-m", f"move {len(laps)}")
                run.git(owner, "push", "origin", "main")
            return answer

        with patch.object(run, "git_out", side_effect=racing), \
                patch.object(run, "current_review", return_value=True):
            self.assertFalse(run.integrate(lp, "origin/main"))
        self.assertEqual(len(laps), 3)
        state = run.read_state(run_dir)
        self.assertEqual(state["state"], "waiting")
        self.assertNotEqual(state["verdict"], "FAIL")
        self.assertFalse(state["merge_failed"])
        self.assertEqual(state["merge_note"], "origin/main moved three times during integration")
        # parked on the tip the last lap landed, which origin is already past: the tick's
        # next pass retries it rather than waiting for yet another merge
        self.assertEqual(state["waiting_on"]["ref"], "origin/main")
        self.assertEqual(state["waiting_on"]["sha"], run.git(owner, "rev-parse", "HEAD~1"))

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

        def fake_review(cfg, name, body, workspace, out, role, session, log, limit=None):
            verdict = next(verdicts)
            answer = (f"VERDICT: {verdict}\n\n## Findings\n"
                      + ("- shared:1 - the merged tree breaks\n" if verdict == "FAIL"
                         else "- none\n"))
            out.mkdir(parents=True)
            (out / "final.md").write_text(answer)
            return 0, answer, session, False

        with patch.object(run, "execute", side_effect=fixer), \
                patch.object(run, "call_retrying", side_effect=fake_review):
            self.assertTrue(run.integrate(lp, "origin/main"))
        findings = [text for name, text in turns if name == "executor"]
        self.assertEqual(len(findings), 1)
        self.assertIn("## Reviewer findings to fix", findings[0])
        self.assertIn("shared:1 - the merged tree breaks", findings[0])
        self.assertEqual(lp.rnd, 2)                          # the fixer round spent one
        state = run.read_state(run_dir)
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

        def call(cfg, name, body, workspace, out, role, session, log, limit=None):
            if role == "reviewer":
                return self.review_call(cfg, name, body, workspace, out, role, session, log, limit)
            asked.append((name, body))
            if len(asked) == 1:
                raise run.RanDry(name, "quota", 1, "", session, None,
                                 "usage limit reached", True)
            return 0, resolve(wt), session, False

        with patch.object(run, "call_retrying", side_effect=call), \
                patch.object(usage, "collect", return_value={}), \
                patch.object(usage, "pick_order", return_value=["opus", "astra", "spark"]):
            self.assertTrue(run.integrate(lp, "origin/main"))
        self.assertEqual([name for name, _ in asked], ["opus", lp.executor])
        self.assertNotEqual(lp.executor, "opus")              # handed over
        self.assertIn("Another model started this round", asked[1][1])
        self.assertIn(f"handing executor to {lp.executor}", self.log_text(run_dir))

    def test_a_clean_rebase_failed_review_uses_the_last_task_round(self):
        _, owner, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt, rounds=5, spent=3)
        # Main moved without a git conflict, but the done-when fails on the integrated
        # tree, so integration needs a new review at round 4 before the final fixer at 5.
        (owner / "other.txt").write_text("other\n")
        run.git(owner, "add", ".")
        run.git(owner, "commit", "-m", "other work on main")
        run.git(owner, "push", "origin", "main")
        findings = "VERDICT: FAIL\nThe integrated tree still needs fixed.txt.\n"
        answers = iter([findings, "VERDICT: PASS\n"])
        gates = iter([False, True])
        turns = []

        def checks(cmds, wt, out, *args, **kwargs):
            out.parent.mkdir(parents=True, exist_ok=True)
            ok = next(gates)
            return ok, f"$ check\n[exit {0 if ok else 1}]\n"

        def review_call(cfg, name, body, workspace, out, role, session, log, limit=None):
            answer = next(answers)
            out.mkdir(parents=True)
            (out / "final.md").write_text(answer)
            return 0, answer, session, False

        def fixer(lp2, role, text, name):
            turns.append((lp2.rnd, role, text))
            (wt / "fixed.txt").write_text("fixed\n")
            run.git(wt, "add", ".")
            run.git(wt, "commit", "-m", "fix findings")
            return "## Summary\nFixed the findings."

        with patch.object(run, "execute", side_effect=fixer), \
                patch.object(run, "call_retrying", side_effect=review_call), \
                patch.object(run, "run_done_when", side_effect=checks):
            self.assertTrue(run.integrate(lp, "origin/main"))
        self.assertEqual([(rnd, role) for rnd, role, _ in turns], [(5, "fixer")])
        self.assertIn(findings, turns[0][2])
        self.assertEqual([entry["round"] for entry in lp.state["round_summaries"]],
                         [1, 2, 3, 4, 5])
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
        saved = run.read_state(run_dir)
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
                patch.object(run, "stop_run_tree"):
            self.assertNotEqual(run.cmd_merge([run_dir.name]), 0)
        self.assertEqual(run.read_state(run_dir)["state"], "waiting")
        self.assertTrue((run_dir / "result.md").read_text().startswith("# WAITING:"))

    def test_a_base_race_verifies_and_pushes_the_new_head_before_retrying(self):
        _, owner, wt = make_repos(self.root)
        lp, run_dir, _ = make_loop(self.root, wt)
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
            raise AssertionError(args)

        def checks(lp2, url):
            head = lp2.state["delivery_sha"]
            self.assertEqual(run.git(wt, "rev-parse", "origin/ak/test"), head)
            events.append(("checks", head))
            return True

        with patch.object(run, "gh", side_effect=fake_gh), \
                patch.object(run, "wait_checks", side_effect=checks), \
                patch.object(run.time, "sleep"):
            self.assertTrue(run.do_merge(lp, URL, "origin/main"))
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
            self.assertFalse(run.do_merge(lp, URL, "origin/main"))
        self.assertEqual(len(merges), 4)                      # the first try and three retries
        # subprocess may also sleep briefly while reaping the fixture's git calls.
        self.assertEqual([call.args[0] for call in slept.call_args_list if call.args[0] >= 60],
                         [60, 300, 900])
        state = run.read_state(run_dir)
        self.assertEqual(state["state"], "waiting")
        self.assertNotEqual(state["verdict"], "FAIL")
        self.assertIn("modified base", state["merge_note"])
        self.assertEqual(state["waiting_on"]["ref"], "origin/main")

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
            self.assertTrue(run.do_merge(lp, URL, "origin/main"))
        self.assertEqual(seen, ["merge", "view", "view", "merge"])
        self.assertEqual([call.args[0] for call in slept.call_args_list if call.args[0] >= 60],
                         [60, 300])


if __name__ == "__main__":
    unittest.main(verbosity=2)
