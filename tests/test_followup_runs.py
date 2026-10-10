"""A merge starts its own seat's follow-ups through ordinary admission and landing.

Temporary HOME, local git remote, fake gh and fake models; no detached run is started.
"""

from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import nullcontext
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

import test_review_gate as gate
import test_proof_weighed as proof
from agentkit import host, browser, config, gc, job as jobs, menu, notify, orch, run, stop, task, watch, worker
from agentkit import plan, record
from fixtures.hand_in import stateful
from fixtures.landing import landing


DEFECT = "broken.py:1 - empty input crashes - base abc123: `first([])` raises IndexError"
CHECK = "python3 -c 'from broken import first; first([])'"
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
with (root / "harness/calls.jsonl").open("a") as fh:
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
        try:
            (out.parents[1] / "regression/regression.sh").write_text("python3 test_empty.py\n")
        except OSError as error:
            answer = f"## Blocked\nregression.sh: {error}"
        else:
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
            # The run directory stays read-only to its turns, as on a real host.
            stateful(self.root / "adapters" / f"{harness}.sh", self.root / "harness")
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
        self.stack.enter_context(patch.object(orch, "stop_scope"))
        self.stack.enter_context(patch.object(worker, "kill_marked"))
        self.stack.enter_context(patch.object(worker, "marked_pids", return_value=[]))
        self.stack.enter_context(patch.object(stop, "marker_pids", return_value=[]))
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

    def spawn(self, argv, unit, env, log_path, log=None, **kwargs):
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
                 "base_sha": self.git(self.repo, "rev-parse", "origin/main"),
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
            self.assertEqual(receipt["base_proof"], "regression.sh")   # its own probe proves it
            self.assertIn(child.name, (directory / "result.md").read_text())
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

    def test_a_review_followup_becomes_a_checked_line_in_its_seats_plan_not_a_run(self):
        check = "python3 -c 'from broken import first; first([])'"
        flaky = "flaky: python3 -m unittest passed only on its re-run"
        directory, state = self.source(followups=[DEFECT, flaky], followup_checks={DEFECT: check})
        children = self.start(directory, state)
        self.assertEqual(len(children), 1)
        self.assertIn(flaky, (children[0] / "task.md").read_text())
        text = config.plan_path("seat").read_text()
        self.assertEqual(text.count("- [ ] "), 1)
        self.assertIn(f"- [ ] Fix {DEFECT} · check: `{check}` · {plan.named(self.repo)} · written ", text)
        # it names the commit its check failed on: the review's base
        self.assertEqual(plan.LINE.match(text.strip())["base"], state["base_sha"][:12])
        ending = (directory / "result.md").read_text()
        self.assertIn("now in your plan, yours to build: Fix broken.py:1", ending)
        self.assertIn("until `ak plan check N` puts your fix's own test in its place", ending)
        self.start(directory, record.read_state(directory))
        found_again = DEFECT + "\nfound again by a later review"
        later, again = self.source("later", followups=[found_again],
                                   followup_checks={found_again: check})
        self.assertEqual(self.start(later, again), [])
        self.assertEqual(config.plan_path("seat").read_text(), text)
        self.assertEqual(len(self.spawns), 1)

    def test_a_followup_its_plan_refuses_is_named_for_the_seat_to_judge(self):
        directory, state = self.source(followup_checks={DEFECT: "false\nfalse"})
        self.assertEqual(self.start(directory, state), [])
        self.assertFalse(config.plan_path("seat").exists())
        self.assertIn("your plan refused, yours to judge: Fix broken.py:1",
                      (directory / "result.md").read_text())
        self.assertEqual(self.spawns, [])

    def test_a_seat_with_no_executors_still_gets_its_review_followups_in_its_plan(self):
        config.update_session("seat", workers=[])
        flaky = "flaky: python3 -m unittest passed only on its re-run"
        directory, state = self.source(followups=[DEFECT, flaky], followup_checks={DEFECT: CHECK})
        red = {"command": "false", "check": "false", "sha": state["base_sha"],
               "text": "The target fails its check"}
        self.assertIsNone(run.start_followups(state, directory, self.logs.append, self.cfg,
                                              repair=red))   # a repair is not the merge's list
        self.assertEqual(self.start(directory, record.read_state(directory)), [])
        self.assertIn(f"- [ ] Fix {DEFECT} · check: `{CHECK}` · {plan.named(self.repo)} · ",
                      config.plan_path("seat").read_text())
        self.assertEqual(self.spawns, [])

    def test_a_handoff_cut_off_before_its_receipt_hands_its_list_on_again(self):
        flaky = "flaky: python3 -m unittest passed only on its re-run"
        directory, state = self.source(followups=[DEFECT, flaky], followup_checks={DEFECT: CHECK})
        for step in ("main_checkout", "report_config"):   # before anything, after the plan line
            with patch.object(run, step, side_effect=KeyboardInterrupt), \
                    self.assertRaises(KeyboardInterrupt):
                self.start(directory, record.read_state(directory))
        real = run.report_config

        def marked(cfg):
            with record.record(directory) as current:
                current["handed_back"] = True   # the ending delivered meanwhile
            return real(cfg)

        with patch.object(run, "report_config", side_effect=marked):
            children = self.start(directory, record.read_state(directory))
        self.assertEqual(len(children), 1)
        self.assertEqual(config.plan_path("seat").read_text().count("- [ ] "), 1)
        ended = record.read_state(directory)
        self.assertTrue(ended["handed_back"])
        self.assertIn("now in your plan, yours to build: Fix broken.py:1",
                      (directory / "result.md").read_text())
        self.start(directory, ended)
        self.assertEqual(len(self.spawns), 1)

    def test_a_delivery_marked_while_the_receipt_is_written_stays_marked(self):
        directory, state = self.source(followup_checks={DEFECT: CHECK})
        real, marked = record._write_state, []
        delivery = threading.Thread(target=lambda: marked.append(run.mark_delivery(
            directory, record.read_state(directory), handed_back=123)))

        def write(run_dir, current, *args):
            if run_dir == directory and "followup_runs" in current and not delivery.ident:
                delivery.start()     # the tick hands the ending back while the receipt is written
                delivery.join(1)
            return real(run_dir, current, *args)

        with patch.object(record, "_write_state", side_effect=write):
            self.start(directory, state)
            delivery.join(10)
        self.assertEqual(marked, [True])
        ended = record.read_state(directory)
        self.assertEqual(ended["handed_back"], 123)
        self.assertEqual(len(ended["followup_plan"]), 1)

    def test_a_fix_stopped_before_a_cut_off_receipt_is_not_started_again(self):
        directory, state = self.source(followups=["flaky: python3 -m unittest passed only on its re-run"])
        real = run.spawn_bg

        def stopped_then_cut(child, *args, **kwargs):
            real(child, *args, **kwargs)
            with record.record(child) as current:
                current.update(state="stopped", verdict="STOPPED")
            raise KeyboardInterrupt

        with patch.object(run, "spawn_bg", side_effect=stopped_then_cut), \
                self.assertRaises(KeyboardInterrupt):
            self.start(directory, state)
        self.start(directory, record.read_state(directory))
        self.assertEqual(len(self.spawns), 1)

    def cut_off_before_its_launch(self, step):
        flaky = "flaky: python3 -m unittest passed only on its re-run"
        directory, state = self.source(followups=[flaky])
        real = getattr(run, step)

        def cut(*args, **kwargs):
            real(*args, **kwargs)
            raise KeyboardInterrupt

        with patch.object(run, step, side_effect=cut), self.assertRaises(KeyboardInterrupt):
            self.start(directory, state)
        [child] = [d for d in record.run_dirs() if d != directory]
        with patch.object(record, "process_active", return_value=False):
            left = run.reap(child, record.read_state(child))   # a look at `ak run status`
            self.assertEqual((left["state"], left["slot_waiting"]), ("queued", True))
            self.assertEqual(self.start(directory, record.read_state(directory)), [child])
            self.assertEqual(self.start(*self.source("again", followups=[flaky])), [])
            self.assertEqual(self.spawns, [])          # the site is the waiting fix's
            watch.resume_dead_loops(self.cfg, log=self.logs.append, now=left["started_at"] + 3600)
            self.assertEqual([where for _, _, where in self.spawns], [child])
            self.assertEqual(run.resume_run([child.name]), 0)     # what the tick started
        self.assertEqual(record.read_state(child)["verdict"], "PASS")

    def test_a_fix_cut_off_at_its_first_record_waits_for_its_slot_and_the_tick_starts_it(self):
        self.cut_off_before_its_launch("capture_launch")

    def test_a_fix_cut_off_after_its_preflight_waits_for_its_slot_and_the_tick_starts_it(self):
        self.cut_off_before_its_launch("prepare")

    def test_a_followup_line_ticks_once_its_fix_is_on_the_default_branch(self):
        self.git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        config.update_session("seat", repo=str(self.repo))      # `ak orch project acme`
        self.start(*self.source(followup_checks={DEFECT: CHECK}))
        (self.repo / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        self.git(self.repo, "commit", "-qam", "Fix the planned follow-up")
        self.git(self.repo, "push", "-q", "origin", "main")
        with patch.dict(os.environ, {config.SESSION_ENV: "seat"}):
            self.assertEqual(plan.main([]), 0)
        [line] = plan.lines("seat")
        self.assertRegex(line, r"^- \[x\] Fix .* · done [0-9a-f]{12} Fix the planned follow-up$")

    def test_a_followup_line_names_the_reviewed_history_whatever_is_checked_out(self):
        self.git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        config.update_session("seat", repo=str(self.repo))
        directory, state = self.source(followup_checks={DEFECT: CHECK})
        self.git(self.repo, "checkout", "-q", "--orphan", "gh-pages")   # another history
        self.git(self.repo, "commit", "-qm", "Pages")
        self.start(directory, state)
        fixer = self.root / "fixer"
        self.git(self.root, "clone", "-q", str(self.remote), str(fixer))
        (fixer / "broken.py").write_text("def first(items):\n    return items[0] if items else None\n")
        self.git(fixer, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qam", "Fix the planned follow-up")
        self.git(fixer, "push", "-q", "origin", "main")
        with patch.dict(os.environ, {config.SESSION_ENV: "seat"}):
            self.assertEqual(plan.main([]), 0)
        [line] = plan.lines("seat")
        self.assertRegex(line, r"^- \[x\] Fix .* · done [0-9a-f]{12} Fix the planned follow-up$")

    def test_the_same_check_in_another_project_is_a_line_of_its_own(self):
        self.start(*self.source(followup_checks={DEFECT: CHECK}))
        other = self.root / "other-project"
        self.git(self.root, "clone", "-q", str(self.repo), str(other))
        self.start(*self.source("other", repo=str(other), followup_checks={DEFECT: CHECK}))
        self.assertEqual([line.split(" · ")[2] for line in plan.lines("seat")],
                         [plan.named(self.repo), plan.named(other)])

    def test_a_followup_written_while_the_plan_is_being_edited_is_kept(self):
        directory, state = self.source(followup_checks={DEFECT: CHECK})
        with ThreadPoolExecutor(max_workers=1) as pool:
            with plan.held("seat"):
                merge = pool.submit(self.start, directory, state)
                self.assertFalse(wait([merge], timeout=1).done)
                plan.write("seat", [*plan.lines("seat"), f"- [ ] by hand · your eye · {plan.named(self.repo)} · written 2026-10-04 21:00"])
            merge.result(timeout=30)
        self.assertEqual(len(plan.lines("seat")), 2)

    def test_a_maintainer_merge_that_puts_work_in_the_plan_tells_the_seat(self):
        url = "https://github.com/acme/widget/pull/1"
        directory, _ = self.source(merged=False, pr=url, followup_checks={DEFECT: CHECK})
        sent = []
        with patch.object(orch, "find", return_value={"name": "seat"}), \
                patch.object(watch, "type_into",
                             side_effect=lambda seat, line, log: sent.append(line) or True):
            self.assertTrue(watch.say(False, self.logs.append, "PR #1: merged by the maintainer",
                                      url, "seat", merged=True))
        # the seat now owes the follow-up, so the merge is no routine ending (`routine_ending`)
        self.assertEqual(len(sent), 1)
        self.assertIn("PR #1: merged by the maintainer", sent[0])
        self.assertIn("now in your plan, yours to build: Fix broken.py:1",
                      (directory / "result.md").read_text())

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
        with patch.object(stop, "cmd_stop") as stopped:
            stop.stop_owned_runs("seat")
        self.assertEqual({call.args[0][0] for call in stopped.call_args_list}, {c.name for c in children})

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
        calls = [json.loads(line) for line in (self.root / "harness/calls.jsonl").read_text().splitlines()]
        self.assertEqual([c["role"] for c in calls], ["executor", "reviewer"])
        self.assertIn("First fetch the target branch", calls[0]["prompt"])
        self.assertIn("another open run of session seat", calls[0]["prompt"])
        self.assertEqual(fixed["followup_runs"], [])
        found = fixed["followups"][0]
        self.assertEqual(found.splitlines()[0], OTHER)
        self.assertIn("ZeroDivisionError", found)
        self.assertIn(f"Commit {merged}", found)
        self.assertIn("Before the task: return 1 / value", found)
        self.assertIn(f"- [ ] Fix {OTHER} · check: `python3 -c 'from other import ratio; ratio(0)'` "
                      f"· {plan.named(self.repo)} · written ", config.plan_path("seat").read_text())
        self.assertIn("now in your plan, yours to build: Fix other.py:2",
                      (child / "result.md").read_text())

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

    def test_before_accepts_ancestor_commits_but_replays_on_the_recorded_base(self):
        ancestor = self.base
        run.git(self.wt, "tag", "old-base", ancestor)
        run.git(self.wt, "checkout", "-q", "main")
        (self.wt / "keep.txt").write_text("keep\na later base\n")
        self.commit("Advance the base")
        self.base = run.git(self.wt, "rev-parse", "HEAD")
        self.lp.state["base_sha"] = self.base
        run.git(self.wt, "checkout", "-q", "ak/fix-api")
        before = (ancestor, f"base {ancestor[:7]}: old defect", "old-base")
        self.assertEqual(self.review(*(self.followup(before=text) for text in before),
                                     self.followup(before=self.head)), "PASS")
        self.assertEqual(len(self.lp.state["followups"]), len(before))
        for text in self.lp.state["followups"]:
            self.assertIn(f"Commit {self.base}", text)
            self.assertIn("proof on base", text)
        self.assertEqual(len(self.lp.state["notes"]), 1)
        self.assertIn("--before names no commit in base's history", self.lp.state["notes"][0])

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

    def test_before_must_name_a_commit_in_base_history_or_a_quote_in_its_file(self):
        before = ("base deadbeef", f"base {self.head}", 'mode = "branch"',
                  "invented quote", "reviewer_only = True")
        self.assertEqual(self.review(*(self.followup(before=text, site="api.py:1") for text in before),
                                     edits={"api.py": "reviewer_only = True\n"}), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertEqual(len(self.lp.state["notes"]), len(before))
        for note in self.lp.state["notes"]:
            self.assertIn("--before names no commit in base's history or quote present at base", note)

    def test_a_quote_in_an_overlaid_test_is_not_a_quote_at_base(self):
        self.assertEqual(self.review(self.followup(
            site="tests/proof [1].py:5", before='assert api.mode == "base"')), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertIn("--before names no commit in base's history or quote present at base", self.lp.state["notes"][0])

    def test_a_followup_whose_command_cannot_run_on_base_is_dropped(self):
        commands = ("./absent", "./keep.txt")
        self.assertEqual(self.review(*(self.followup(command=command) for command in commands)), "PASS")
        self.assertEqual(self.lp.state["followups"], [])
        self.assertEqual(len(self.lp.state["notes"]), len(commands))
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
