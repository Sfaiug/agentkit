"""A parked run consumes its lander's verdict, lands itself, or repairs and rejoins.

Offline: local Git, invented GitHub replies and workers, and an isolated HOME.
"""

from contextlib import nullcontext
import copy
import fcntl
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, gc, land, record, run, usage, watch
from fixtures.hand_in import submitting
from test_merge_step import conflict, make_loop, make_repos, resolve
from test_v4n import Sandbox

URL = "https://github.com/acme/widget/pull/7"
SUITE = "test ! -f broken.txt"


class LanderWakes(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        self.remote, self.owner, self.wt = make_repos(self.root)
        (self.owner / "AGENTS.md").write_text(f"---\ntests: {SUITE}\n---\n")
        self.commit(self.owner, "declare suite")
        run.git(self.owner, "push", "origin", "main")
        run.git(self.wt, "fetch", "origin")
        run.git(self.wt, "rebase", "origin/main")
        self.lp, self.directory, _ = make_loop(config.RUNS, self.wt, spent=3)
        self.lp.state["run_id"] = self.directory.name
        (self.directory / "task.md").write_text(
            f"---\nrepo: {self.wt}\n---\n# Land work\n\n## Done when\n```bash\ntrue\n```\n")
        self.turn = run.turn_path(self.lp, "origin/main")
        self.events, self.commands, self.merges = [], [], []
        self.verdicts = iter(["PASS"])
        self.fix = True
        self.check_result = (True, "")
        self.stack.enter_context(patch.object(record, "process_active", return_value=False))
        self.wake = self.stack.enter_context(patch.object(watch, "launch_resume", return_value=999))
        self.stack.enter_context(patch.object(run, "execute", side_effect=self.fixer))
        self.stack.enter_context(patch.object(run, "call_retrying", side_effect=submitting(self.reviewer)))
        self.stack.enter_context(patch.object(run, "rights", return_value=("acme/widget", "WRITE")))
        self.stack.enter_context(patch.object(run, "checks", side_effect=lambda *a: self.check_result))
        self.stack.enter_context(patch.object(run, "gh", side_effect=self.gh))
        self.stack.enter_context(patch.object(run, "merge_turn", side_effect=AssertionError("queue lock")))
        self.stack.enter_context(patch.object(run, "pickup_new_code"))
        self.stack.enter_context(patch.object(run, "launcher_world", return_value=nullcontext(True)))
        self.stack.enter_context(patch.object(run, "place_here", return_value=None))
        self.stack.enter_context(patch.object(run, "stop_run_tree"))
        self.stack.enter_context(patch.object(run, "hand_back", return_value=True))
        self.stack.enter_context(patch.object(run.notify, "shaped", side_effect=AssertionError("notification")))
        self.stack.enter_context(patch.object(run.history, "Sampler"))
        self.stack.enter_context(patch.object(run.history, "sample_rss", return_value=None))
        self.stack.enter_context(patch.object(usage, "collect", return_value={}))
        self.stack.enter_context(patch.object(usage, "pick_order", return_value=["opus", "astra"]))
        self.stack.enter_context(patch.object(gc, "disk_pressure", return_value=False))
        real_check = gate.run_done_when

        def checks(cmds, cwd, *args, **kw):
            self.commands.append(list(cmds))
            if Path(cwd) == self.wt:
                self.assert_free()
                self.assertNotIn(SUITE, cmds, "only the lander repeats the suite")
            return real_check(cmds, cwd, *args, **kw)

        self.stack.enter_context(patch.object(gate, "run_done_when", side_effect=checks))

    def commit(self, cwd, message):
        run.git(cwd, "add", "-A")
        run.git(cwd, "commit", "-m", message)

    def assert_free(self, free=True):
        with self.turn.open("a") as probe:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.assertFalse(free, "fixing or reviewing while holding the merge lock")
            else:
                self.assertTrue(free, "delivery did not hold the merge lock")

    def gh(self, cwd, *args, **_kw):
        self.assert_free(False)
        if args[:2] == ("pr", "create"):
            return 0, URL
        if args[:2] == ("pr", "edit"):
            return 0, ""
        if args[:2] == ("api", "graphql"):
            return 0, json.dumps("Reviewed work\n\nCo-authored-by: Fixture <fixture@localhost>")
        if args[:2] == ("pr", "merge"):
            self.merges.append(args)
            return 0, "merged"
        raise AssertionError(args)

    def fixer(self, lp, role, text, name, **_kw):
        self.assert_free()
        self.events.append((name, lp.rnd))
        self.assertEqual(role, "fixer")
        if name == "rebase-fixer":
            return resolve(self.wt)
        if name == "merge-fixer":
            (self.wt / "shared").write_text("both intents\n")
            run.git(self.wt, "add", "shared")
            run.git(self.wt, "commit", "--no-edit")
        elif self.fix:
            if (self.wt / "broken.txt").exists():
                (self.wt / "broken.txt").unlink()
            else:
                (self.wt / "fixed.txt").write_text("fixed\n")
            self.commit(self.wt, "fix landing check")
        if name == "final-fixer":
            self.assertIn("Fix the root cause", text)
        return "## Summary\nFixed landing."

    def reviewer(self, cfg, name, body, workspace, out, role, session, log, **_kw):
        self.assert_free()
        self.events.append(("reviewer", out.parent.name))
        verdict = next(self.verdicts)
        if isinstance(verdict, Exception):
            raise verdict
        finding = "- work.txt:1 - the repair drops intent\n" if verdict == "FAIL" else "- none\n"
        answer = f"VERDICT: {verdict}\n\n## Findings\n{finding}"
        out.mkdir(parents=True)
        (out / "final.md").write_text(answer)
        return 0, answer, session, False

    def park(self, method="squash", spent=3, broken=False):
        if broken:
            (self.wt / "broken.txt").write_text("broken\n")
            self.commit(self.wt, "broken work")
        identity = run.commit_identity(self.wt)
        self.lp.state["review"].update(identity)
        self.lp.state["round_summaries"] = self.lp.state["round_summaries"][:spent]
        self.lp.state.update(state="waiting", merge_method=method,
                             waiting_on={"line": self.turn.name, "joined": 10})
        self.lp.save()
        self.history = copy.deepcopy(self.lp.state["round_summaries"])
        land.check_line(self.turn)
        self.wake.assert_called_once()
        return record.read_state(self.directory)["waiting_on"]

    def assert_rounds(self, state):
        self.assertEqual(state["round_summaries"], self.history)
        self.assertEqual(state["rounds"], 3)

    def assert_green(self, method):
        (self.owner / "tip.txt").write_text("target moved\n")
        self.commit(self.owner, "move target")
        run.git(self.owner, "push", "origin", "main")
        old_head = run.git(self.wt, "rev-parse", "HEAD")
        wait = self.park(method)
        self.assertIn("land", wait)
        commands = copy.deepcopy(self.commands)
        with patch.object(run, "finish", wraps=run.finish) as finish:
            self.assertEqual(run.cmd_resume([self.directory.name]), 0)
        finish.assert_called_once()
        state = record.read_state(self.directory)
        self.assertEqual(state["state"], "pass")
        self.assertTrue(state["merged"])
        self.assertNotIn("waiting_on", state)
        self.assertEqual(state["final_check"]["tree_sha"], wait["land"])
        self.assertEqual(self.commands, commands)
        self.assertEqual(self.events, [])
        self.assert_rounds(state)
        self.assertEqual(len(self.merges), 1)
        args = self.merges[0]
        self.assertIn(f"--{method}", args)
        trailer = f"Suite-Passed-Tree: {wait['land']}"
        if method == "rebase":
            self.assertIn(trailer, run.git(self.wt, "show", "-s", "--format=%B", "HEAD"))
        else:
            self.assertIn(trailer, args[args.index("--body") + 1])
        if method == "merge":
            self.assertTrue(run.integrated(self.wt, old_head))
            self.assertEqual(len(run.git(self.wt, "show", "-s", "--format=%P", "HEAD").split()), 2)
        self.assert_free()

    def test_green_squash_lands_and_finishes(self):
        self.assert_green("squash")

    def test_green_rebase_keeps_the_suite_trailer(self):
        self.assert_green("rebase")

    def test_green_merge_integrates_without_flattening_or_skipping(self):
        self.assert_green("merge")

    def test_changed_tree_rejoins_at_the_same_place(self):
        wait = self.park()
        (self.owner / "other.txt").write_text("external move\n")
        self.commit(self.owner, "another target move")
        run.git(self.owner, "push", "origin", "main")
        commands = copy.deepcopy(self.commands)
        self.assertEqual(run.cmd_resume([self.directory.name]), 1)
        state = record.read_state(self.directory)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(state["waiting_on"], {"line": self.turn.name, "joined": wait["joined"]})
        self.assertEqual(self.commands, commands)
        self.assertEqual(self.events, [])
        self.assertEqual(self.merges, [])
        self.assert_rounds(state)
        land.check_line(self.turn)
        self.assertEqual(run.cmd_resume([self.directory.name]), 0)

    def test_red_repairs_outside_the_lock_and_rejoins_at_the_back(self):
        wait = self.park(broken=True)
        self.assertIn("fix", wait)
        other = config.RUNS / "other"
        other.mkdir()
        original = {**record.read_state(self.directory), "run_id": other.name,
                    "waiting_on": {"line": self.turn.name, "joined": 20}}
        record.save_state(other, original)
        self.assertEqual(run.cmd_resume([self.directory.name]), 1)
        state = record.read_state(self.directory)
        self.assertEqual(state["state"], "waiting")
        self.assertGreater(state["waiting_on"]["joined"], 20)
        self.assertNotIn("fix", state["waiting_on"])
        self.assertNotIn("land", state["waiting_on"])
        self.assertEqual(self.events, [("final-fixer", 3), ("reviewer", "round-3")])
        self.assertEqual(state["landing_reds"], 1)
        self.assertEqual([directory.name for directory, _ in land.line(self.turn)], ["other", "run"])
        self.assertEqual(record.read_state(other), original)
        self.assert_rounds(state)
        self.assertEqual(self.merges, [])

    def test_failed_re_review_ends_with_findings_even_with_rounds_left(self):
        self.verdicts = iter(["FAIL"])
        self.park(spent=1, broken=True)
        self.assertEqual(run.cmd_resume([self.directory.name]), 1)
        state = record.read_state(self.directory)
        self.assertEqual(state["state"], "fail")
        self.assertEqual(state["review"]["verdict"], "FAIL")
        self.assertIn("the repair drops intent", state["findings"])
        self.assertNotIn("waiting_on", state)
        self.assertEqual(self.events, [("final-fixer", 1), ("reviewer", "round-1")])
        self.assert_rounds(state)

    def test_required_pr_check_failure_is_red(self):
        self.check_result = (False, "required checks failed: unit")
        self.park()
        self.assertEqual(run.cmd_resume([self.directory.name]), 1)
        state = record.read_state(self.directory)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(state["pr"], URL)
        self.assertEqual(state["landing_reds"], 1)
        self.assertIn("required checks failed: unit", (self.directory / "pr-checks.log").read_text())
        self.assertEqual(self.events, [("final-fixer", 3), ("reviewer", "round-3")])
        self.assertEqual(self.merges, [])
        self.assert_rounds(state)

    def test_fourth_red_hands_back_its_last_failure_without_a_fourth_fixer(self):
        self.fix = False
        self.verdicts = iter(["PASS"] * 3)
        self.park(broken=True)
        for red in range(1, 5):
            with patch.object(run.time, "time", return_value=10000 + red):
                self.assertEqual(run.cmd_resume([self.directory.name]), 1)
            state = record.read_state(self.directory)
            self.assertEqual(state["landing_reds"], red)
            self.assert_rounds(state)
            if red < 4:
                self.assertEqual(state["state"], "waiting")
                land.check_line(self.turn)
        self.assertNotEqual(state["state"], "waiting")
        self.assertTrue(state["merge_failed"])
        self.assertIn("landing failed four times", state["merge_note"])
        self.assertIn(SUITE, state["merge_note"])
        self.assertIn("lander.log", state["merge_note"])
        self.assertEqual(len(self.events), 6)

    def assert_conflict(self, method):
        conflict(self.owner, self.wt)
        wait = self.park(method)
        self.assertIn("fix", wait)
        self.assertEqual(run.cmd_resume([self.directory.name]), 1)
        state = record.read_state(self.directory)
        self.assertEqual(state["state"], "waiting")
        how = "merge" if method == "merge" else "rebase"
        self.assertEqual(self.events, [(f"{how}-fixer", 3), ("reviewer", "round-3")])
        self.assert_rounds(state)
        self.assertFalse(run.in_progress(self.wt, how))
        self.assertTrue(run.integrated(self.wt, "origin/main"))

    def test_conflict_uses_the_existing_rebase_fixer(self):
        self.assert_conflict("squash")

    def test_merge_conflict_uses_the_existing_merge_fixer(self):
        self.assert_conflict("merge")

    def test_interrupted_re_review_keeps_its_red_count_and_task_round(self):
        self.verdicts = iter([run.Exhausted("review interrupted"), "PASS"])
        self.park(broken=True)
        self.assertEqual(run.cmd_resume([self.directory.name]), 1)
        saved = record.read_state(self.directory)
        self.assertEqual(saved["state"], "exhausted")
        self.assertEqual(saved["landing_reds"], 1)
        self.assertIs(saved["review_pending"]["record"], False)
        self.assertEqual(run.cmd_resume([self.directory.name]), 1)
        state = record.read_state(self.directory)
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(state["landing_reds"], 1)
        self.assertEqual(sum(name == "final-fixer" for name, _ in self.events), 1)
        self.assert_rounds(state)

    def test_target_waiter_tick_leaves_line_members_to_the_lander(self):
        self.park()
        state = record.read_state(self.directory)
        with patch.object(run, "upstream_sha", side_effect=AssertionError("target probe")):
            watch.resume_waiting(run=self.directory)
        self.assertEqual(record.read_state(self.directory), state)


if __name__ == "__main__":
    unittest.main(verbosity=2)
