"""Passed runs leave a durable line position and no worker; callers follow the record. Offline."""

from contextlib import nullcontext, redirect_stdout
import copy
import fcntl
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, job, land, menu, record, run, watch
from test_merge_step import make_loop, make_repos
from test_v4n import Sandbox


class JoinLine(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1"}))
        _, self.owner, self.wt = make_repos(self.root)
        self.lp, self.directory, _ = make_loop(config.RUNS, self.wt)
        self.lp.state.update(run_id=self.directory.name, **record.process_owner())
        self.lp.write()
        (self.directory / "task.md").write_text(
            "# Fix API\n\n## Done when\n```bash\ntrue\n```\n")
        self.start = self.stack.enter_context(patch.object(land, "start_line", return_value=False))
        self.stack.enter_context(patch.object(run.shutil, "which", return_value="/fixture/gh"))
        self.rights = self.stack.enter_context(patch.object(
            run, "rights", return_value=("acme/widget", "WRITE")))
        self.stop = self.stack.enter_context(patch.object(run, "stop_run_tree"))
        self.stack.enter_context(patch.object(run.history, "Sampler"))
        self.stack.enter_context(patch.object(run.history, "sample_rss", return_value=None))

    def saved(self):
        return record.read_state(self.directory)

    def test_merge_joins_without_integrating_checking_or_delivering(self):
        before = copy.deepcopy(self.lp.state)
        with patch.object(run, "integrate", side_effect=AssertionError("integration")), \
                patch.object(run, "final_check", side_effect=AssertionError("suite")), \
                patch.object(run, "push", side_effect=AssertionError("push")), \
                patch.object(run, "merge_lock", side_effect=AssertionError("delivery lock")):
            self.assertFalse(run.merge(self.lp))
        state = self.saved()
        self.assertEqual(state["state"], "waiting")
        self.assertEqual(state["waiting_on"]["line"], run.turn_path(self.lp, "origin/main").name)
        self.assertIsInstance(state["waiting_on"]["joined"], (int, float))
        self.assertEqual(state["review"], before["review"])
        self.assertEqual(state["round_summaries"], before["round_summaries"])
        self.assertEqual(state["verdict"], "PASS")
        self.assertIsNone(state["finished_at"])
        self.start.assert_called_once()

    def test_drive_releases_the_worker_without_an_ending(self):
        def work():
            run.merge(self.lp)
            return self.lp.state

        with patch.object(run, "run_slot", return_value=nullcontext()), \
                patch.object(run, "finish", side_effect=AssertionError("ending")):
            self.assertEqual(run.drive(self.cfg, self.directory, {}, self.lp.log, job=work), 0)
        state = self.saved()
        self.assertEqual(state["state"], "waiting")
        self.assertFalse(record.process_active(state))
        self.stop.assert_called_once()
        self.assertIsNone(state["pid"])
        self.assertEqual(state["verdict"], "PASS")

    def test_released_member_keeps_its_seat_working_and_its_fix_open(self):
        self.lp.state.update(launched_session="acme", started_at=1)
        self.lp.write()
        run.merge(self.lp)
        run.release_line(self.directory, self.lp.log)
        state = self.saved()
        self.assertFalse(record.process_active(state))
        self.assertEqual(run.tick_admission(state), "in line to land")
        self.assertEqual(menu.run_state_word(state), "working")
        self.assertEqual(run.seat_tallies([state]), {"acme": (1, 0, 0)})
        self.assertTrue(run.followup_open(state))
        found = watch.session_state(
            "acme", now=3 * 86400, session={"name": "acme", "attached": False},
            cfg=self.cfg, records=[(self.directory, state)], live={}, harness="claude",
            auth_out={}, gh_out={}, token_out={}, previous={})
        self.assertEqual(found["word"], "working")

        with record.record(self.directory) as current:
            current["state"] = "stopped"
        stopped = self.saved()
        self.assertEqual(menu.run_state_word(stopped), "done")
        self.assertFalse(run.followup_open(stopped))

    def retry(self, pr=False):
        self.lp.state.update(state="pass", merge_failed=True, merge_note="push stopped")
        if pr:
            self.lp.state["pr"] = "https://github.com/acme/widget/pull/7"
        self.lp.write()
        info = {"headRefOid": self.lp.state["delivery_sha"], "baseRefName": "main", "state": "OPEN"}
        with patch.object(run, "pr_view", return_value=info), \
                patch.object(run, "finish", side_effect=AssertionError("ending")), \
                patch.object(run, "integrate", side_effect=AssertionError("integration")):
            self.assertEqual(run.cmd_merge([self.directory.name]), 0)
        self.assertEqual(self.saved()["state"], "waiting")
        self.assertIsNone(self.saved()["pid"])
        self.assertEqual(self.saved()["review"], self.lp.state["review"])

    def test_merge_retry_with_pr_joins(self):
        self.retry(pr=True)

    def test_merge_retry_without_pr_joins(self):
        self.retry()

    def test_fork_target_waits_keep_their_recovery_timestamp_in_loop_and_merge_retry(self):
        self.rights.return_value = ("acme/widget", "READ")
        self.lp.state.update(state="pass", merge_failed=True, pr="https://github.com/acme/widget/pull/7",
                             launched_session="acme")
        self.lp.write()
        config.session_path("acme").write_text("{}")
        before = copy.deepcopy(self.saved())
        info = {"headRefOid": before["delivery_sha"], "baseRefName": "main", "state": "OPEN"}

        def park(lp, upstream, verify, deliver):
            return run.park_waiting(lp, "the target changed since verification", upstream, "f" * 40)

        for attempt in ("loop", "merge"):
            with self.subTest(attempt=attempt):
                record.save_state(self.directory, copy.deepcopy(before))
                with patch.object(run, "land", side_effect=park), \
                        patch.object(run, "pr_view", return_value=info), \
                        patch.object(run, "collect_usage", return_value={}), \
                        patch.object(run, "rounds"), patch.object(run, "join_session_project"), \
                        patch.object(run, "finish", return_value=1):
                    if attempt == "loop":
                        run.loop(self.cfg, self.directory, self.directory / "task.md",
                                 {"--exec": None, "--review": None}, self.lp.log,
                                 prior=record.read_state(self.directory))
                    else:
                        self.assertEqual(run.cmd_merge([self.directory.name]), 1)
                state = self.saved()
                self.assertEqual(state["waiting_on"]["ref"], "origin/main")
                self.assertTrue(run.tick_admission(state))
                self.assertEqual(menu.run_state_word(state), "working")
                with patch.object(run, "upstream_sha", return_value="a" * 40), \
                        patch.object(run, "spawn_bg") as spawn:
                    watch.resume_waiting(log=self.lp.log, run=self.directory)
                spawn.assert_called_once()

    def test_foreground_merge_retry_follows_a_fast_success_or_failure(self):
        self.lp.state.update(state="pass", merge_failed=True, pr="https://github.com/acme/widget/pull/7")
        self.lp.write()
        before = copy.deepcopy(self.saved())
        info = {"headRefOid": before["delivery_sha"], "baseRefName": "main", "state": "OPEN"}
        for word, expected in (("pass", 0), ("error", 2)):
            with self.subTest(state=word):
                record.save_state(self.directory, copy.deepcopy(before))
                log = self.directory / "log.txt"
                log.write_text("Earlier attempt already shown\n")

                def land_now(*_args):
                    current = self.saved()
                    if current.get("state") == "waiting" and current.get("pid") is None:
                        with record.record(self.directory) as state:
                            state.update(state=word, merged=word == "pass")
                            state.pop("waiting_on")
                        with log.open("a") as output:
                            output.write(f"Delivery ending: {word}\n")

                def view(_url):
                    run.logger(self.directory)("Merge retry already shown")
                    return info

                with patch.object(sys, "argv", [str(REPO / "bin" / "ak"), "run", "merge",
                                               self.directory.name]), \
                        patch.object(run, "pr_view", side_effect=view), \
                        patch.object(land, "start_line", side_effect=land_now), \
                        redirect_stdout(io.StringIO()) as shown:
                    self.assertEqual(run.cmd_merge([self.directory.name]), expected)
                self.assertEqual(self.saved()["state"], word)
                self.assertIn(f"Delivery ending: {word}\n", shown.getvalue())
                self.assertNotIn("Earlier attempt already shown", shown.getvalue())
                self.assertEqual(shown.getvalue().count("Merge retry already shown"), 1)

    def test_resume_without_a_verdict_keeps_its_place_and_pass(self):
        run.merge(self.lp)
        wait = copy.deepcopy(self.saved()["waiting_on"])
        self.lp.state["state"] = "running"
        self.lp.write()
        self.assertFalse(run.merge(self.lp))
        self.assertEqual(self.saved()["waiting_on"], wait)
        self.assertEqual(self.saved()["verdict"], "PASS")

    def test_release_stops_old_children_before_a_new_owner_can_be_woken(self):
        run.merge(self.lp)
        events = []

        def stop(state, log):
            self.assertTrue(record.process_active(self.saved()))
            events.append("stop")

        def start(turn, *args):
            self.assertIsNone(self.saved()["pid"])
            events.append("start")

        with patch.object(run, "stop_run_tree", side_effect=stop), \
                patch.object(land, "start_line", side_effect=start):
            run.release_line(self.directory, self.lp.log)
        self.assertEqual(events, ["stop", "start"])

    def test_fork_delivers_without_joining(self):
        self.rights.return_value = ("acme/widget", "READ")
        with patch.object(run, "land", side_effect=lambda lp, upstream, verify, deliver: deliver()), \
                patch.object(run, "fork_and_pr", return_value=True) as fork:
            self.assertTrue(run.merge(self.lp))
        fork.assert_called_once_with(self.lp, "main", "acme/widget", "READ")
        self.assertNotIn("waiting_on", self.saved())
        self.start.assert_not_called()

    def test_review_pr_joins_without_taking_the_delivery_lock(self):
        self.lp.state["own_orchestrator"] = "opus"
        with patch.object(run, "gh", side_effect=AssertionError("delivery")), \
                patch.object(run, "merge_lock", side_effect=AssertionError("delivery lock")):
            self.assertFalse(run.merge_own_pr(self.lp, "https://github.com/acme/widget/pull/7",
                                              self.lp.state["review"]["head_sha"]))
        self.assertEqual(self.saved()["waiting_on"]["line"], run.turn_path(self.lp, "origin/main").name)
        self.assertFalse(list(config.RUNS.glob("*.wait")))

    def test_job_and_foreground_follow_the_processless_line_to_its_ending(self):
        run.merge(self.lp)
        run.release_line(self.directory, self.lp.log)
        polls = []

        def tick():
            polls.append(self.saved()["state"])
            if len(polls) == 2:
                with record.record(self.directory) as state:
                    state.update(state="pass", merged=True)
                    state.pop("waiting_on")
                with (self.directory / "log.txt").open("a") as log:
                    log.write("PASS, merged -> result.md\n")

        with patch.object(job.time, "sleep", side_effect=lambda _: tick()):
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(run.follow_run(self.directory, self.cfg), 0)
        self.assertEqual(polls, ["waiting", "waiting"])
        self.assertIn("PASS, merged -> result.md", output.getvalue())

    def test_foreground_cli_starts_the_worker_then_follows_its_record(self):
        task = self.directory / "task.md"
        task.write_text(f"---\nrepo: {self.wt}\n---\n# Fix API\n\n## Done when\n```bash\ntrue\n```\n")

        def prepare(directory, _opts, log, _cfg, **_kw):
            log("Preflight already shown")
            record.save_state(directory, {**self.saved(), "run_id": directory.name, "pid": None})

        def finish_now(directory, _args):
            with record.record(directory) as state:
                state.update(state="pass", merged=True)
            with (directory / "log.txt").open("a") as log:
                log.write("PASS, merged -> result.md\n")

        with patch.object(sys, "argv", [str(REPO / "bin" / "ak")]), \
                patch.object(run, "already_under_way", return_value=[]), \
                patch.object(run, "prepare", side_effect=prepare), \
                patch.object(run, "spawn_bg", side_effect=finish_now) as spawn, \
                patch.object(run, "place_here", side_effect=AssertionError("parent scope")), \
                redirect_stdout(io.StringIO()) as shown:
            self.assertEqual(run.main([str(task)]), 0)
        spawn.assert_called_once()
        self.assertEqual(shown.getvalue().count("Preflight already shown"), 1)
        self.assertEqual(shown.getvalue().count("PASS, merged -> result.md"), 1)

    def test_foreground_resume_starts_a_worker_and_follows_the_saved_place(self):
        run.merge(self.lp)
        run.release_line(self.directory, self.lp.log)
        with record.record(self.directory) as state:
            state["waiting_on"]["land"] = state["review"]["tree_sha"]
        before = self.saved()
        offset = (self.directory / "log.txt").stat().st_size
        with patch.object(sys, "argv", [str(REPO / "bin" / "ak")]), \
                patch.object(run, "spawn_bg") as spawn, \
                patch.object(run, "follow_run", return_value=0) as follow, \
                patch.object(run, "place_here", side_effect=AssertionError("parent scope")):
            self.assertEqual(run.resume_run([self.directory.name]), 0)
        spawn.assert_called_once_with(self.directory, ["resume", self.directory.name],
                                      expected=before)
        follow.assert_called_once_with(self.directory, self.cfg, offset)
        self.assertEqual(self.saved()["waiting_on"], before["waiting_on"])

    def test_foreground_resume_follows_only_new_lines_even_when_delivery_finishes_at_launch(self):
        run.merge(self.lp)
        run.release_line(self.directory, self.lp.log)
        with record.record(self.directory) as state:
            state["waiting_on"]["land"] = state["review"]["tree_sha"]
        log = self.directory / "log.txt"
        log.write_text("Earlier attempt already shown\n")

        def finish_now(directory, _args, **_kw):
            with record.record(directory) as state:
                state.update(state="pass", merged=True)
                state.pop("waiting_on")
            with log.open("a") as output:
                output.write("PASS, merged -> result.md\n")

        with patch.object(sys, "argv", [str(REPO / "bin" / "ak"), "run", "resume",
                                       self.directory.name]), \
                patch.object(run, "spawn_bg", side_effect=finish_now), \
                redirect_stdout(io.StringIO()) as shown:
            self.assertEqual(run.resume_run([self.directory.name]), 0)
        self.assertEqual(shown.getvalue(), "PASS, merged -> result.md\n")

    def test_detached_resumes_run_once_without_following_their_own_log(self):
        run.merge(self.lp)
        run.release_line(self.directory, self.lp.log)
        parked = self.saved()
        log = self.directory / "log.txt"
        for word in ("waiting", "exhausted", "waiting_login", "interrupted", "stalled", "error"):
            with self.subTest(state=word):
                state = {**copy.deepcopy(parked), "state": word}
                if word == "waiting":
                    state["waiting_on"]["land"] = "tree"
                else:
                    state.pop("waiting_on")
                record.save_state(self.directory, state)
                log.write_text("MARKER\n")
                with patch.object(sys, "argv", [str(REPO / "bin" / "ak"), "run", "resume",
                                               self.directory.name]), \
                        patch.object(run, "spawn_bg", side_effect=AssertionError("second worker")), \
                        patch.object(run, "follow_run", side_effect=AssertionError("follower")), \
                        patch.object(run, "place_here"), patch.object(run, "drive", return_value=0) as drive, \
                        log.open("a") as output, redirect_stdout(output):
                    self.assertEqual(run.resume_run([self.directory.name]), 0)
                drive.assert_called_once()
                contents = log.read_text()
                self.assertEqual(contents.count("MARKER"), 1)
                self.assertEqual(contents.count(f"resume {self.directory.name}:"), 1)

    def test_foreground_follow_preserves_noncompletion_exits_with_a_saved_pass(self):
        for word, expected in (("waiting", 1), ("exhausted", 1), ("waiting_login", 1),
                               ("interrupted", 1), ("stalled", 1), ("blocked", 1),
                               ("stopped", 1), ("error", 2), ("pass", 0), ("not_needed", 0)):
            with self.subTest(state=word):
                state = {**self.saved(), "state": word, "merge_failed": False}
                with patch.object(job, "job_await", return_value=state), redirect_stdout(io.StringIO()):
                    self.assertEqual(run.follow_run(self.directory, self.cfg), expected)

    def test_job_task_exits_and_the_ladder_follows_its_line(self):
        def work(*args, **_kw):
            run.merge(self.lp)
            run.release_line(self.directory, self.lp.log)
            return 0

        box = {}
        with patch.object(run, "drive", side_effect=work), \
                patch.object(job, "job_await", side_effect=AssertionError("task waits")):
            job.job_drive(self.cfg, self.directory, {}, box)
        self.assertEqual(box["state"]["state"], "waiting")
        self.assertEqual(box["rc"], 0)
        finished = {**box["state"], "state": "pass", "merged": True}
        finished.pop("waiting_on")
        with patch.object(job, "job_await", return_value=finished) as follow, \
                patch.object(job, "job_settle") as settle, \
                patch.object(run, "tick_admission", return_value=False):
            job.job_ladder(self.cfg, config.JOBS / "job", {}, {"name": "fix-api"},
                           self.directory, box["state"], box["rc"], lambda _: None, None)
        follow.assert_called_once_with(self.directory)
        self.assertEqual(settle.call_args.args[5], finished)


if __name__ == "__main__":
    unittest.main(verbosity=2)
