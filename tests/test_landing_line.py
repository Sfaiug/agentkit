"""Waiting to land is a run record, followed until the lander ends it. Offline."""

from contextlib import redirect_stdout
import io
import os
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

from test_v4n import Sandbox
from agentkit import config, history, job as jobs, menu, record, run, watch


class LandingLine(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AGENTKIT_RUN_DIR": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AK_RUN_ROLE": "orchestrator", "AGENTKIT_SESSION": ""}))
        self.line = run.merge_turn_lock("https://github.com/acme/widget.git", "origin/main").name
        self.stack.enter_context(patch.object(record, "process_active", return_value=False))
        self.stack.enter_context(patch.object(run, "alive_line", return_value=""))
        self.stack.enter_context(patch.object(run.time, "time", return_value=200000))

    def member(self, name="fix-api", joined=100, **extra):
        return self.ended(name, state="waiting", base="main", target="main",
                          started_at=10, finished_at=1,
                          waiting_on={"line": self.line, "joined": joined}, **extra)

    def test_members_keep_going_without_an_ending_or_a_live_seat(self):
        directory = self.member()
        state = record.read_state(directory)
        for extra in ({}, {"finished_at": None}, {"finished_at": 300000},
                      {"handed_back": 9000}, {"recovery_notified": "discord"},
                      {"recovery_acknowledged_at": 9000}):
            with self.subTest(extra=extra):
                member = {**state, **extra}
                self.assertTrue(run.tick_admission(member, now=200000))
                self.assertTrue(run.going(member, now=200000))
                self.assertEqual(menu.run_state_word(member), "working")
                self.assertFalse(menu.v5o_needs_look(member, now=200000))

    def test_ticks_and_manual_resumes_leave_the_member_record_alone(self):
        directory = self.member()
        before = (directory / "run.json").read_bytes()
        with patch.object(run, "upstream_sha", side_effect=AssertionError("no fetch")), \
                patch.object(run, "spawn_bg", side_effect=AssertionError("no worker")), \
                patch.object(config, "load", side_effect=AssertionError("no replay")):
            for dry_run in (True, False):
                watch.resume_waiting(dry_run=dry_run, log=lambda _: self.fail("no tick note"))
                watch.resume_waiting(dry_run=dry_run, run=directory,
                                     log=lambda _: self.fail("no job resume"))
            for args in ([directory.name], [directory.name, "--bg"],
                         [directory.name, "--rounds", "3"]):
                with self.assertRaisesRegex(config.Error, "line to land"):
                    run.cmd_resume(args)
        self.assertEqual((directory / "run.json").read_bytes(), before)

    def test_tick_rechecks_membership_after_fetch(self):
        directory = self.ended("fix-api", state="waiting", worktree=str(self.root),
                               waiting_on={"ref": "origin/main", "sha": "0" * 40})
        joined = {"line": self.line, "joined": 100}

        def fetch(*_args):
            record.save_state(directory, {**record.read_state(directory), "waiting_on": joined})
            return "1" * 40

        with patch.object(run, "tick_admission", return_value=True), \
                patch.object(run, "upstream_sha", side_effect=fetch), \
                patch.object(run, "spawn_bg", side_effect=AssertionError("only the lander")):
            watch.resume_waiting(log=lambda _: self.fail("no tick note"))
        state = record.read_state(directory)
        self.assertEqual(state["waiting_on"], joined)
        self.assertNotIn("waiting_resume_at", state)

    def test_places_count_only_current_members_of_the_same_line_by_join_time(self):
        members = [self.member(f"fix-{25 - n:02}", joined=n) for n in range(1, 24)]
        self.ended("other-repo", state="waiting", waiting_on={
            "line": run.merge_turn_lock("https://github.com/acme/other.git", "origin/main").name,
            "joined": 0})
        self.ended("other-target", state="waiting", waiting_on={
            "line": run.merge_turn_lock("https://github.com/acme/widget.git", "origin/release").name,
            "joined": 0})
        self.ended("already-landed", merged=True, waiting_on={"line": self.line, "joined": 0})
        self.ended("conflict", state="waiting", waiting_on={"ref": "origin/main", "sha": "0" * 40})
        for position in ("1st", "2nd", "3rd", "11th", "12th", "13th", "21st", "22nd", "23rd"):
            state = record.read_state(members[int(position[:-2]) - 1])
            self.assertEqual(run.parked_line(state), f"waiting · {position} in line to land on main")
        record.save_state(members[1], {**record.read_state(members[1]), "state": "stopped"})
        self.assertEqual(run.parked_line(record.read_state(members[2])),
                         "waiting · 2nd in line to land on main")

    def test_status_and_menu_show_the_place_and_target(self):
        self.member("first", joined=10)
        self.member("second", joined=20)
        directory = self.member("third", joined=30, launched_session="seat")
        config.save_session(self.cfg, "seat", "fable", ["astra"])
        state = record.read_state(directory)
        sentence = "waiting · 3rd in line to land on main"
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(run.cmd_status([directory.name]), 0)
        self.assertIn(sentence, out.getvalue())
        session = {"name": "seat", "created": 1}
        answer = watch.session_state("seat", 200000, session=session, cfg=self.cfg,
                                     records=[(directory, state)], live={}, harness=None,
                                     auth_out={}, gh_out={}, token_out={}, previous={})
        self.assertEqual(answer["word"], "working")
        self.assertEqual(answer["reason"], sentence)
        with patch.object(menu, "seat_row_state", return_value=answer):
            info = menu.v5o_seat_info(self.cfg, 1, session, [(directory, state)], {}, {}, 200000)
        self.assertEqual(menu._last_text(info), sentence)
        self.assertEqual(menu.last_column("working", sentence, 1, 3), sentence)

    def test_job_follows_members_to_their_ending_including_after_merge(self):
        for after_merge in (False, True):
            for word, marks, expected in (
                    ("pass", {"merged": True}, "merged"),
                    ("pass", {"no_merge": True}, "passed"),
                    ("fail", {"verdict": "FAIL", "review": {}}, "failed"),
                    ("blocked", {"error": "cannot build this task", "review": {}}, "blocked"),
                    ("stopped", {"review": {}}, "stopped"),
                    ("not_needed", {"not_needed": "already fixed"}, "passed")):
                with self.subTest(after_merge=after_merge, ending=word):
                    directory = self.member(f"fix-{after_merge}-{expected}")
                    state = record.read_state(directory)
                    initial = {**state, "state": "pass", "merge_failed": True} if after_merge else state
                    record.save_state(directory, initial)
                    job_dir = config.JOBS / directory.name
                    job_dir.mkdir(parents=True)
                    task = {"name": "alpha", "state": "running", "run_id": directory.name}
                    job = {"tasks": [task], "opts": {}}

                    def finish(_seconds):
                        self.assertEqual(task["state"], "running")
                        self.assertNotIn("finished_at", task)
                        record.save_state(directory, {**state, "state": word, **marks})

                    def merge(_args):
                        record.save_state(directory, state)
                        return 1

                    with patch.object(jobs.time, "sleep", side_effect=finish) as sleep, \
                            patch.object(watch, "resume_waiting", side_effect=AssertionError("only the lander")), \
                            patch.object(run, "cmd_resume", side_effect=AssertionError("no replay")), \
                            patch.object(run, "cmd_merge", side_effect=merge):
                        jobs.job_ladder(self.cfg, job_dir, job, task, directory, initial, 1,
                                        lambda _: None, threading.Lock())
                    sleep.assert_called_once()
                    self.assertEqual(task["state"], expected)
                    self.assertNotIn("rerun_attempted", task)

    def test_after_dependency_waits_until_its_line_member_has_merged_and_settled(self):
        directory = self.member("alpha")
        job_dir = config.JOBS / "build-widget"
        job_dir.mkdir(parents=True)
        job = {"tasks": [{"name": "alpha", "state": "running", "run_id": directory.name}]}
        jobs.save_job(job_dir, job)
        dependant = self.ended("beta", state="running")
        lp = SimpleNamespace(run_dir=dependant, base_sha="tip", log=Mock(), write=Mock(),
                             state={"job_id": job_dir.name, "from_pass": {"task": "alpha", "tip": "tip"}})
        phases = []

        def land(_seconds):
            phases.append(1)
            if len(phases) == 1:
                record.save_state(directory, {**record.read_state(directory), "state": "pass", "merged": True})
            else:
                self.assertEqual(len(phases), 2, "dependant did not follow the job's result")
                job["tasks"][0]["state"] = "merged"
                jobs.save_job(job_dir, job)

        with patch.object(run.time, "sleep", side_effect=land), \
                patch.object(history, "close_step"), patch.object(history, "open_step"):
            self.assertTrue(run.wait_for_dependency(lp))
        self.assertEqual(len(phases), 2)
        self.assertNotIn("skipped_dep", lp.state)


if __name__ == "__main__":
    unittest.main(verbosity=2)
