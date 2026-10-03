"""A merge starts its own seat's follow-ups through ordinary admission and landing.

Temporary HOME, local git remote, fake gh and fake models; no detached run is started.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_review_gate as gate
import test_proof_weighed as proof
from agentkit import host, browser, config, gc, job as jobs, menu, notify, orch, run, task, watch, worker
from agentkit import record
from fixtures.landing import landing


DEFECT = "broken.py:1 - empty input crashes - base abc123: `first([])` raises IndexError"
OTHER = "other.py:2 - zero divisor crashes - base abc123: `ratio(0)` raises ZeroDivisionError"

ADAPTER = r'''import json, os, pathlib, subprocess, sys
root = pathlib.Path(os.environ["GATE_FIXTURE"])
if sys.argv[1] == "usage":
    print('{"meters": [{"name": "weekly", "used": 0}]}')
    sys.exit(0)
if sys.argv[1] == "reset-status":
    print('{"available": 0}')
    sys.exit(0)
assert sys.argv[1] == "run", sys.argv
wt, out = pathlib.Path(sys.argv[4]), pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
role = "reviewer" if prompt.startswith("You are the reviewer") else "executor"
with (root / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"role": role, "prompt": prompt}) + "\n")
if role == "reviewer":
    answer = (root / "review.md").read_text()
    if "## Follow-ups" in answer:
        ak = root.parent / "bin/ak"
        subprocess.run([sys.executable, str(ak), "hand-in", "follow-up", "other.py:2",
                        "zero divisor crashes", "base abc123: `ratio(0)` raises ZeroDivisionError",
                        "--run", "python3 -c 'from other import ratio; ratio(0)'",
                        "--before", "return 1 / value"], check=True)
        answer = answer.split("## Follow-ups", 1)[0]
else:
    mode = (root / "mode").read_text()
    if mode == "gone":
        answer = "not needed: target already fixes empty input"
    elif mode == "duplicate":
        answer = "## Summary\n\nnot needed: another open run fixes this site"
    elif mode == "blocked":
        answer = "## Blocked\nShould empty input return None or raise ValueError?"
    elif mode == "bullets":
        answer = ("## Summary\n\nnot needed: target already fixes empty input\n"
                  "- checked origin/main, first([]) returns None\n- no open run at this site")
    elif mode == "evidence":
        answer = ("not needed: another open run fixes this site\n"
                  "verified in run.json: a queued run fixes broken.py:1")
    elif mode == "preamble":
        answer = ("I fetched origin/main and ran first([]); it returns None there.\n\n"
                  "## Summary\n\nnot needed: target already fixes empty input")
    else:
        test = wt / "test_empty.py"
        test.write_text("from broken import first\nassert first([]) is None\n")
        before = subprocess.run([sys.executable, str(test)], cwd=wt, capture_output=True)
        assert before.returncode != 0, before
        (out / "before.log").write_bytes(before.stderr)
        (wt / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        subprocess.run([sys.executable, str(test)], cwd=wt, check=True)
        (out.parents[1] / "regression.sh").write_text("python3 test_empty.py\n")
        subprocess.run(["git", "add", "."], cwd=wt, check=True)
        subprocess.run(["git", "commit", "-qm", "Handle empty input"], cwd=wt, check=True)
        answer = "## Summary\nRegression test failed with IndexError before; passed after."
(out / "final.md").write_text(answer)
(out / "session_id").write_text("fixture-" + role)
'''


class FollowupRuns(unittest.TestCase):
    script = gate.ReviewGate.script

    def setUp(self):
        gate.ReviewGate.setUp(self)
        self.real_announce = run.announce
        self.logs, self.spawns, self.gh_calls, self.endings = [], [], [], []
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            self.script(self.root / "adapters" / f"{harness}.sh", ADAPTER)
        (self.root / "mode").write_text("fix")
        (self.root / "review.md").write_text("VERDICT: PASS\n")
        self.repo = self.root / "acme"
        self.repo.mkdir()
        self.remote = self.root / "origin.git"
        self.git(self.repo, "init", "-qb", "main")
        self.git(self.repo, "config", "user.name", "Fixture")
        self.git(self.repo, "config", "user.email", "fixture@example.invalid")
        self.git(self.root, "init", "--bare", "-q", str(self.remote))
        self.git(self.repo, "remote", "add", "origin", str(self.remote))
        (self.repo / "broken.py").write_text("def first(items):\n    return items[0]\n")
        (self.repo / "other.py").write_text("def ratio(value):\n    return 1 / value\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "Existing defect")
        self.git(self.repo, "push", "-qu", "origin", "main")
        self.stack.enter_context(patch.object(run, "gh", side_effect=self.gh))
        self.stack.enter_context(patch.object(run.landing, "start_line"))
        self.stack.enter_context(patch.object(run, "join_line", side_effect=lambda lp, upstream, deliver:
                                            landing(lp, deliver)))
        self.stack.enter_context(patch.object(orch, "start_in_slice", side_effect=self.spawn))
        self.stack.enter_context(patch.object(orch, "set_runs"))
        self.stack.enter_context(patch.object(orch, "stop_scope"))
        self.stack.enter_context(patch.object(worker, "kill_marked"))
        self.stack.enter_context(patch.object(worker, "marked_pids", return_value=[]))
        self.stack.enter_context(patch.object(run, "marker_pids", return_value=[]))
        self.stack.enter_context(patch.object(run, "pickup_new_code", return_value=False))
        self.stack.enter_context(patch.object(gc, "disk_pressure", return_value=False))
        self.stack.enter_context(patch.object(browser, "close_owned"))
        self.stack.enter_context(patch.object(run, "announce", side_effect=lambda s, d, *a:
                                              self.endings.append(run.handback_line(s, d, self.cfg))))
        config.save_session(self.cfg, "seat", self.executor,
                            [self.executor, self.reviewer], {"cwd": str(self.repo)})

    def git(self, cwd, *args):
        result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def spawn(self, argv, unit, env, log_path, **kwargs):
        self.spawns.append((argv, env, Path(log_path).parent))
        kwargs["placement"].update(scope="none", scope_reason="fixture")
        return os.getpid()

    def gh(self, cwd, *args, **kwargs):
        self.gh_calls.append(args)
        if args[:2] == ("repo", "view"):
            return 0, json.dumps({"nameWithOwner": "acme/widget", "viewerPermission": "WRITE"})
        if args[:2] == ("pr", "create"):
            self.pr_branch = args[args.index("--head") + 1]
            self.pr_base = args[args.index("--base") + 1]
            return 0, "https://github.com/acme/widget/pull/1"
        if args[:2] == ("pr", "merge"):
            head = self.git(self.repo, "rev-parse", self.pr_branch)
            self.git(self.repo, "push", "-q", "origin", f"{head}:refs/heads/{self.pr_base}")
            return 0, "merged"
        if args[:2] == ("pr", "view"):
            return 0, json.dumps({"state": "OPEN", "mergeable": "MERGEABLE",
                                  "headRefOid": self.git(self.repo, "rev-parse", self.pr_branch),
                                  "baseRefName": self.pr_base})
        if args[0] == "api":
            if "graphql" in args:
                return 0, json.dumps({"data": {"repository": {"ref": {"branchProtectionRule": None}}}})
            return 0, "[]"
        self.fail(f"unexpected gh {args}")

    def source(self, name="source", **extra):
        directory = config.RUNS / name
        directory.mkdir()
        state = {"run_id": name, "state": "pass", "verdict": "PASS", "merged": True,
                 "launched_session": "seat", "workers": [self.executor, self.reviewer],
                 "repo": str(self.repo), "target": "main", "base": "origin/main",
                 "followups": [DEFECT], **extra}
        record.save_state(directory, state)
        return directory, state

    def start(self, directory, state):
        run.start_followups(state, directory, self.logs.append, self.cfg)
        return [config.RUNS / name for name in state.get("followup_runs", [])]

    def drive(self, directory, mode="fix", *, prior=None):
        (self.root / "mode").write_text(mode)
        opts = record.read_state(directory)["launch_opts"]
        code = run.drive(self.cfg, directory, opts, self.logs.append, prior=prior)
        return code, record.read_state(directory)

    def test_merge_launches_each_item_with_evidence_and_the_session_workers(self):
        directory, state = self.source(followups=[DEFECT + "\nreproduction details", OTHER])
        config.save_session(self.cfg, "seat", self.executor, [self.reviewer])
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "", "AK_RUN_DEPTH": "1",
                                    "AGENTKIT_RUN": "parent", "AK_PARENT_RUN": "parent",
                                    "AGENTKIT_UNATTENDED": "1", "AK_RUN_ROLE": "worker"}):
            children = self.start(directory, state)
        self.assertEqual(len(children), 2)
        for child, item, (_, env, _) in zip(children, state["followups"], self.spawns):
            receipt = record.read_state(child)
            self.assertEqual(receipt["launched_session"], "seat")
            self.assertEqual(receipt["workers"], [self.reviewer])
            self.assertEqual(receipt["run_depth"], 0)
            self.assertIsNone(receipt["parent_run"])
            self.assertEqual(env["AGENTKIT_SESSION"], "seat")
            self.assertEqual(env["AK_RUN_DEPTH"], "0")
            for key in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AGENTKIT_UNATTENDED", "AK_RUN_ROLE"):
                self.assertNotIn(key, env)
            self.assertIn(item, (child / "task.md").read_text())
            self.assertIn("base: origin/main", (child / "task.md").read_text())
            self.assertEqual(receipt["followup"]["run"], directory.name)
            self.assertIn(child.name, run.handback_line(state, directory, self.cfg))
        self.assertFalse((config.HOME / "followups").exists())
        self.start(directory, record.read_state(directory))
        self.assertEqual(len(self.spawns), 2)

    def test_fix_run_takes_session_current_lists_and_discovering_ones_only_without_a_record(self):
        directory, state = self.source("lists", reviewers=[self.executor])
        config.update_session("seat", workers=[self.reviewer], reviewers=[self.reviewer])
        # The discovering run loaded its config before the session's new model was added.
        stale = {**self.cfg, "models": {name: entry for name, entry in self.cfg["models"].items()
                                        if name != self.reviewer}}
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "seat"}):
            run.start_followups(state, directory, self.logs.append, stale)
        receipt = record.read_state(config.RUNS / state["followup_runs"][0])
        self.assertEqual(receipt["workers"], [self.reviewer])
        self.assertEqual(receipt["reviewers"], [self.reviewer])
        parent = record.read_state(directory)
        self.assertEqual(run.run_workers(self.cfg, parent), [self.executor, self.reviewer])
        self.assertEqual(run.run_reviewers(self.cfg, parent), [self.executor])
        config.session_path("seat").unlink()   # a seat made by hand: a pane, no record
        directory, state = self.source("no-record", reviewers=[self.executor], followups=[OTHER])
        with patch.object(orch, "find", return_value={"name": "seat"}):
            receipt = record.read_state(self.start(directory, state)[0])
        self.assertEqual(receipt["workers"], state["workers"])
        self.assertEqual(receipt["reviewers"], [self.executor])

    def test_long_first_line_still_fits_github_pr_title_limit(self):
        long_item = "x" * 256 + "\nreproduction details"
        directory, state = self.source("long-title", followups=[long_item])
        child = self.start(directory, state)[0]
        heading = task.parse_task(child / "task.md")[2]
        self.assertTrue(heading.startswith("Fix "))
        self.assertLessEqual(len(heading), 256)
        self.assertIn(long_item, (child / "task.md").read_text())

    def test_exclusions_and_closed_session_start_nothing(self):
        for index, changes in enumerate(({"merged": False}, {"launched_session": None},
                                         {"scratch": True}, {"followups": []},
                                         {"review_pr": "url", "own_pr": False})):
            directory, state = self.source(f"excluded-{index}", **changes)
            self.assertEqual(self.start(directory, state), [])
        directory, state = self.source("closed")
        watch.seat_write("seat", stopped_at=1, closed_by_owner=True)
        self.assertEqual(self.start(directory, state), [])
        self.assertEqual(self.spawns, [])

    def test_own_pr_and_fix_runs_start_their_followups(self):
        directory, state = self.source(own_pr=True, review_pr="url")
        child = self.start(directory, state)[0]
        fixed = record.read_state(child)
        fixed.update(state="pass", merged=True, followups=[OTHER], target="main")
        record.save_state(child, fixed)
        grandchild = self.start(child, fixed)[0]
        self.assertEqual(record.read_state(grandchild)["followup"]["run"], child.name)
        self.assertEqual(record.read_state(grandchild)["launched_session"], "seat")

    def test_same_site_suppressed_only_for_an_open_fix_in_the_same_session(self):
        directory, state = self.source()
        child = self.start(directory, state)[0]
        second, later = self.source("later", followups=["`./broken.py:01` - different words"])
        self.assertEqual(self.start(second, later), [])
        receipt = record.read_state(child)
        receipt.update(state="not_needed", not_needed="already fixed")
        record.save_state(child, receipt)
        third, next_state = self.source("next")
        self.assertEqual(len(self.start(third, next_state)), 1)
        config.save_session(self.cfg, "other-seat", self.executor, state["workers"])
        fourth, other = self.source("other-seat-source", launched_session="other-seat")
        self.assertEqual(len(self.start(fourth, other)), 1)

    def test_simultaneous_merges_do_not_launch_the_same_fix_twice(self):
        first = self.source("first")
        second = self.source("second")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: self.start(*pair), (first, second)))
        self.assertEqual(sum(map(len, results)), 1)
        self.assertEqual(len(self.spawns), 1)

    def test_ordinary_admission_keeps_the_seat_working_and_stop_owns_the_children(self):
        directory, state = self.source(followups=[DEFECT, OTHER])
        readings = {"free_mb": 0, "mem_total_mb": 16384, "load": 0, "cpus": 8}
        with patch.dict(os.environ, {"AK_MAX_RUNS": "1"}), \
                patch.object(host, "host_readings", return_value=readings), \
                patch.object(config, "min_free_mb", return_value=1024):
            children = self.start(directory, state)
        receipts = [record.read_state(child) for child in children]
        self.assertTrue(all(s["state"] == "queued" and s["slot_waiting"] for s in receipts))
        self.assertEqual(run.seat_tallies(receipts)["seat"][0], 2)
        with patch.object(run, "cmd_stop") as stop:
            run.stop_owned_runs("seat")
        self.assertEqual({call.args[0][0] for call in stop.call_args_list}, {c.name for c in children})

    def test_target_is_fetched_after_admission_and_the_fix_is_checked_reviewed_and_landed(self):
        directory, state = self.source()
        child = self.start(directory, state)[0]
        (self.repo / "merged.txt").write_text("the discovering task merged\n")
        self.git(self.repo, "add", ".")
        self.git(self.repo, "commit", "-qm", "Merge discovering task")
        merged = self.git(self.repo, "rev-parse", "HEAD")
        self.git(self.repo, "push", "-q", "origin", "main")
        self.git(self.repo, "update-ref", "refs/remotes/origin/main", f"{merged}~1")
        (self.root / "review.md").write_text(f"VERDICT: PASS\n\n## Follow-ups\n- {OTHER}\n")
        code, fixed = self.drive(child)
        self.assertEqual(code, 0, "\n".join(self.logs))
        self.assertTrue(fixed["merged"])
        self.assertEqual(fixed["final_check"]["where"], "landing")
        self.assertTrue(run.review_pass(fixed, self.cfg))
        self.assertEqual(fixed["base_sha"], merged)
        self.assertEqual(self.git(self.repo, "show", "origin/main:merged.txt"),
                         "the discovering task merged")
        self.assertIn("if items else None", self.git(self.repo, "show", "origin/main:broken.py"))
        self.assertIn("IndexError", next(child.glob("round-1/executor*/before.log")).read_text())
        self.assertIn("[exit 0]", (child / "round-1/donewhen.log").read_text())
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertEqual([c["role"] for c in calls], ["executor", "reviewer"])
        self.assertIn("First fetch the target branch", calls[0]["prompt"])
        self.assertIn("another open run of session seat", calls[0]["prompt"])
        self.assertEqual(len(fixed["followup_runs"]), 1)
        self.assertIn(fixed["followup_runs"][0], self.endings[-1])
        grandchild = record.read_state(config.RUNS / fixed["followup_runs"][0])
        self.assertEqual(grandchild["launched_session"], "seat")
        self.assertEqual(grandchild["workers"], state["workers"])
        self.assertEqual(grandchild["followup"]["text"].splitlines()[0], OTHER)
        self.assertIn("ZeroDivisionError", grandchild["followup"]["text"])
        self.assertIn(f"Commit {merged}", grandchild["followup"]["text"])
        self.assertIn("Before the task: return 1 / value", grandchild["followup"]["text"])

    def test_not_needed_is_done_without_checks_review_or_pr(self):
        for index, mode in enumerate(("gone", "duplicate")):
            directory, state = self.source(f"source-{index}")
            child = self.start(directory, state)[0]
            with patch.object(run, "verify_work", side_effect=AssertionError("checked")), \
                    patch.object(run, "review", side_effect=AssertionError("reviewed")):
                code, ended = self.drive(child, mode)
            self.assertEqual(code, 0, "\n".join(self.logs))
            self.assertEqual(ended["state"], "not_needed")
            self.assertEqual(menu.run_state_word(ended), "done")
            self.assertFalse(menu.v5o_needs_look(ended))
            self.assertFalse(run.needs_recovery({**ended, "recovery_pending": True}))
            self.assertEqual(jobs.job_classify(ended, self.cfg), "passed")
            self.assertFalse(run.review_pass(ended, self.cfg))
            self.assertIsNone(ended["pr"])
            self.assertIn("not needed: ", (child / "result.md").read_text())
            self.assertIn("finished DONE: not needed:", self.endings[-1])
        self.assertEqual(self.gh_calls, [])

    def test_owner_question_ends_blocked_and_reaches_the_session(self):
        directory, state = self.source()
        child = self.start(directory, state)[0]
        code, ended = self.drive(child, "blocked")
        self.assertEqual(code, 1)
        self.assertEqual(ended["state"], "blocked")
        self.assertIn("Should empty input", self.endings[-1])
        self.assertIn("finished BLOCKED", self.endings[-1])
        self.assertEqual(self.gh_calls, [])

    def test_not_needed_with_bullets_or_evidence_ends_quietly(self):
        for index, mode in enumerate(("bullets", "evidence")):
            directory, state = self.source(f"summary-{index}")
            child = self.start(directory, state)[0]
            with patch.object(run, "verify_work", side_effect=AssertionError("checked")), \
                    patch.object(run, "review", side_effect=AssertionError("reviewed")):
                code, ended = self.drive(child, mode)
            self.assertEqual(code, 0, "\n".join(self.logs))
            self.assertEqual(ended["state"], "not_needed")
            self.assertIsNone(ended["pr"])
            self.assertIn("finished DONE: not needed:", self.endings[-1])
        self.assertEqual(self.gh_calls, [])

    def test_not_needed_with_preamble_before_summary_ends_quietly(self):
        directory, state = self.source("summary-preamble")
        child = self.start(directory, state)[0]
        with patch.object(run, "verify_work", side_effect=AssertionError("checked")), \
                patch.object(run, "review", side_effect=AssertionError("reviewed")):
            code, ended = self.drive(child, "preamble")
        self.assertEqual(code, 0, "\n".join(self.logs))
        self.assertEqual(ended["state"], "not_needed")
        self.assertIsNone(ended["pr"])
        self.assertIn("finished DONE: not needed:", self.endings[-1])
        self.assertEqual(self.gh_calls, [])

    def test_not_needed_under_gone_seat_neither_revives_nor_cards(self):
        directory = config.RUNS / "quiet"
        directory.mkdir()
        state = {"run_id": "quiet", "state": "not_needed", "not_needed": "already fixed",
                 "launched_session": "seat", "started_at": 1, "finished_at": 2,
                 "title": "Fix broken.py:1"}
        record.save_state(directory, state)
        with patch.object(run, "launcher_world", return_value=nullcontext(False)), \
                patch.object(watch, "revive", side_effect=AssertionError("revived")), \
                patch.object(notify, "shaped", side_effect=AssertionError("card")):
            self.real_announce(dict(state), directory, self.logs.append, self.cfg)
        ended = record.read_state(directory)
        self.assertTrue(ended["reported"])
        self.assertNotIn("handback_pending", ended)
        self.assertNotIn("notification_pending", ended)

    def test_open_followup_only_while_running_queued_live_or_self_resuming(self):
        directory, state = self.source("parent")
        child_dir = config.RUNS / "fix"
        child_dir.mkdir()
        wt = self.root / "wt-fix"
        wt.mkdir()
        base = {"run_id": "fix", "followup": {"run": "parent", "text": DEFECT,
                                              "place": run.followup_place(DEFECT)},
                "launched_session": "seat", "repo": str(self.repo)}
        blocking = [
            {"state": "running", "pid": "dead"},
            {"state": "queued", "pid": "live"},
            {"state": "queued", "pid": "dead", "slot_waiting": True},
            {"state": "exhausted", "quota_dry": True},
            {"state": "waiting_login", "waiting_for": "claude"},
            {"state": "interrupted", "worktree": str(wt),
             "deaths": [{"at": 1, "pid": 1, "reason": "loop gone"}]},
        ]
        quiet = [
            {"state": "queued", "pid": "dead"},
            {"state": "queued", "pid": "dead", "slot_waiting": False},
            {"state": "interrupted"},
            {"state": "interrupted", "worktree": str(wt),
             "deaths": [{"at": 1, "pid": 1, "reason": "loop gone", "parked": True}]},
            {"state": "interrupted",
             "deaths": [{"at": 1, "pid": 1, "reason": "loop gone"}]},
            {"state": "exhausted", "error": "tool stopped"},
            {"state": "stalled"},
            {"state": "not_needed", "not_needed": "gone"},
            {"state": "pass"},
            {"state": "pass", "merged": True},
            {"state": "pass", "merge_failed": True},
            {"state": "fail"},
            {"state": "blocked"},
            {"state": "stopped"},
        ]
        with patch.object(record, "process_active", side_effect=lambda s: s.get("pid") == "live"):
            for extra in blocking:
                record.save_state(child_dir, {**base, **extra})
                self.assertEqual(run.open_followup(state, DEFECT), "fix", extra)
            for extra in quiet:
                record.save_state(child_dir, {**base, **extra})
                self.assertIsNone(run.open_followup(state, DEFECT), extra)

    def test_finish_still_ends_when_followups_fail_to_start(self):
        for index, exc in enumerate((config.Error("boom"), OSError("disk gone"),
                                     record.StopRequested("stopped"))):
            self.logs.clear()
            self.endings.clear()
            directory, state = self.source(f"broken-{index}")
            with patch.object(run, "start_followups", side_effect=exc):
                run.finish(dict(state), directory, self.logs.append, self.cfg)
            self.assertTrue(any("could not start" in line for line in self.logs), exc)
            self.assertTrue(self.endings, exc)
        self.logs.clear()
        directory, state = self.source("merge-fail")
        child = self.start(directory, state)[0]
        with patch.object(run, "start_followups", side_effect=config.Error("boom")) as started, \
                patch.object(run, "stop_run_tree", wraps=run.stop_run_tree) as stopped:
            code, fixed = self.drive(child)
        self.assertEqual(code, 0, "\n".join(self.logs))
        self.assertTrue(fixed["merged"])
        self.assertTrue(started.called)
        self.assertTrue(stopped.called)
        self.assertTrue(any("could not start" in line for line in self.logs))
        self.assertIn("finished PASS", self.endings[-1])
        self.assertFalse(Path(fixed["worktree"]).exists())

    def test_start_followups_logs_item_failure_and_continues_or_stops(self):
        directory, state = self.source("items", followups=[DEFECT, OTHER])
        calls = []
        real_prepare = run.prepare

        def flaky_prepare(d, o, log, cfg, *args, **kwargs):
            calls.append(d.name)
            if len(calls) == 1:
                raise OSError("disk gone")
            return real_prepare(d, o, log, cfg, *args, **kwargs)

        with patch.object(run, "prepare", side_effect=flaky_prepare):
            children = self.start(directory, state)
        self.assertEqual(len(children), 1)
        self.assertTrue(any("could not start" in line for line in self.logs))
        self.logs.clear()
        mkdir_calls = []
        real_mkdir = Path.mkdir

        def flaky_mkdir(self, *args, **kwargs):
            if self.parent == config.RUNS and len(mkdir_calls) == 0:
                mkdir_calls.append(str(self))
                raise OSError("disk gone")
            return real_mkdir(self, *args, **kwargs)

        second = [DEFECT.replace("broken.py:1", "second.py:1"),
                  OTHER.replace("other.py:2", "second.py:2")]
        directory, state = self.source("mkdir", followups=second)
        with patch.object(Path, "mkdir", flaky_mkdir):
            children = self.start(directory, state)
        self.assertEqual(len(children), 1)
        self.assertTrue(any("could not start" in line for line in self.logs))
        self.logs.clear()
        third = [DEFECT.replace("broken.py:1", "third.py:1"),
                 OTHER.replace("other.py:2", "third.py:2")]
        directory, state = self.source("stopped", followups=third)
        with patch.object(run, "prepare", side_effect=record.StopRequested("stopped")):
            children = self.start(directory, state)
        self.assertEqual(children, [])
        self.assertTrue(any("could not start" in line for line in self.logs))


class FollowupEvidence(unittest.TestCase):
    setUp = proof.ProofWeighed.setUp
    commit = proof.ProofWeighed.commit
    review = proof.ProofWeighed.review
    assert_restored = proof.ProofWeighed.assert_restored

    def followup(self, command=None, before=None, site="api.py:2"):
        return proof.finding(site, "old defect", command or self.fails, kind="follow-up",
                             before=before if before is not None else f"base {self.base}")

    def test_followup_only_reviews_replay_the_proof_and_accept_real_base_commits_or_quotes(self):
        self.assertEqual(self.review(*(self.followup(before=before) for before in
                                     (self.base, f"base {self.base[:7]}: old defect", "old_bug = True"))),
                         "PASS")
        self.assertEqual(len(self.lp.state["followups"]), 3)
        self.assertEqual(self.lp.state["notes"], [])
        for text in self.lp.state["followups"]:
            self.assertIn(f"Commit {self.base}", text)
            self.assertIn("proof on base", text)
            self.assertNotIn("proof on branch", text)

    def test_a_followup_that_passes_on_base_is_dropped_and_published_as_a_note(self):
        self.assertEqual(self.review(self.followup(command=self.regression)), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        note = self.lp.state["notes"][0]
        self.assertIn("[exit 0]", note)
        self.assertIn("Dropped follow-up: the command did not fail on base", note)
        self.assertTrue(any("Dropped follow-up api.py:2" in text for text in self.logs))
        run.write_result(self.directory, self.lp.state, ["true"], cfg=self.cfg)
        for text in ((self.directory / "result.md").read_text(), run.pr_body(self.lp.state)):
            self.assertIn("## Notes", text)
            self.assertIn("Dropped follow-up", text)
            self.assertNotIn("## Follow-ups", text)

    def test_before_must_name_the_recorded_base_or_a_quote_in_its_file(self):
        before = ("base deadbeef", f"base {self.head}", 'mode = "branch"',
                  "invented quote", "reviewer_only = True")
        self.assertEqual(self.review(*(self.followup(before=text, site="api.py:1") for text in before),
                                     edits={"api.py": "reviewer_only = True\n"}), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertEqual(len(self.lp.state["notes"]), len(before))
        for note in self.lp.state["notes"]:
            self.assertIn("--before names no base commit or quote present at base", note)

    def test_a_quote_in_an_overlaid_test_is_not_a_quote_at_base(self):
        self.assertEqual(self.review(self.followup(
            site="tests/proof [1].py:5", before='assert api.mode == "base"')), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertIn("--before names no base commit or quote present at base", self.lp.state["notes"][0])

    def test_a_followup_whose_command_cannot_run_on_base_is_dropped(self):
        commands = ("./absent", "./keep.txt", "python3 absent.py")
        self.assertEqual(self.review(*(self.followup(command=command) for command in commands)), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertEqual(len(self.lp.state["notes"]), 3)
        for note in self.lp.state["notes"]:
            self.assertIn("Dropped follow-up", note)

    def test_a_followup_must_finish_on_base(self):
        self.lp.done_when_limit = 0.05
        prefix = "if grep -q branch api.py; then exit 7; fi; "
        self.assertEqual(self.review(self.followup(command=prefix + "sleep 10"),
                                     self.followup(command=prefix + "kill -TERM $$")), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertTrue(all("Dropped follow-up" in note and "did not finish" in note
                            for note in self.lp.state["notes"]))

    def test_a_quote_without_a_failing_run_is_dropped_even_with_valid_before(self):
        row = proof.finding("api.py:2", "old quote", quote="old_bug = True",
                            kind="follow-up", before=self.base)
        self.assertEqual(self.review(row), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertIn("needs a --run proof", self.lp.state["notes"][0])


if __name__ == "__main__":
    unittest.main()
