"""Every working seat draws its tasks bar -- renamed, or without a plan -- and never `N running`.

The menu row and the seat's own status bar both read `menu.seat_progress`: the plan under the
seat's name or any name its rename pointers lead from, the newest written winning, else the
tasks of its unfinished jobs, else nothing at all. Offline: a temporary HOME, fake plans, jobs,
run records and rename pointers, `orch.tmux_out` patched; no tmux seat is ever started.
"""

import json
import os
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import config, menu, orch, run, terminal, watch

NOW = 1_800_000_000
DAY = 86400


class SeatBar(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        (config.CODE / "acme" / ".git").mkdir(parents=True)
        self.repo = str(config.CODE / "acme")
        self.options = {}
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(watch, "pane_text", return_value="$ "))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=NOW))

    def tmux(self, *args, **kwargs):
        if args[0] == "set-option" and "-u" not in args:
            self.options[args[args.index("-t") + 2]] = args[-1]
        return 0, ""

    def seat(self, name, was=None):
        """A seat by that name; `was` is the name it had before `ak orch rename`."""
        config.save_session(self.cfg, was or name, "fable", ["opus"],
                            {"repo": self.repo, "cwd": self.repo})
        if was:
            config.rename_session(was, name)
        seat = {"name": name, "repo": self.repo, "path": self.repo, "created": NOW - 5 * DAY,
                "attached": False, "exited": False, "legacy": False, "resumable": False}
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[seat]))
        return seat

    def going(self, run_id, owner):
        """A run the seat launched, still going: what keeps a seat working."""
        directory = config.RUNS / run_id
        directory.mkdir(parents=True)
        run.save_state(directory, {"run_id": run_id, "title": f"Task {run_id}", "state": "running",
                                   "verdict": None, "launched_session": owner, "reported": False,
                                   "repo": self.repo, "executor": "opus", "reviewer": "astra",
                                   "rounds": 2, "round_summaries": [], "finished_at": None,
                                   "started_at": NOW - 600})

    def plan(self, name, done, total, at=None):
        path = config.plan_path(name)
        path.write_text("".join(["- [x] done\n"] * done + ["- [ ] todo\n"] * (total - done)))
        if at is not None:
            os.utime(path, (at, at))

    def job(self, job_id, seat, states, finished_at=None):
        directory = config.HOME / "jobs" / job_id
        directory.mkdir(parents=True)
        (directory / "job.json").write_text(json.dumps(
            {"job_id": job_id, "seat": seat, "started_at": NOW - DAY, "finished_at": finished_at,
             "tasks": [{"name": f"task-{n}.md", "state": state} for n, state in enumerate(states)]}))

    def drawn(self, seat):
        """(word, the row's last column, the whole row, the status bar's left half)."""
        info = menu.v5o_seat_info(self.cfg, 1, seat, menu.run_records(), {}, {}, NOW)
        watch.announce_state(seat, cfg=self.cfg)
        row = "\n".join(terminal.plain(line) for line in menu.v5o_format_seats([info], 100))
        return info["word"], menu._last_text(info), row, self.options["status-left"]

    def test_a_renamed_seats_plan_under_its_old_name_draws_its_bar(self):
        seat = self.seat("fix-api", was="api-fix")
        self.going("20260101-0900-going", "api-fix")
        # the orchestrator inside still carries the old name, and goes on writing under it
        self.plan("api-fix", 3, 7)
        word, last, row, bar = self.drawn(seat)
        self.assertEqual(word, "working")
        self.assertEqual(last, f"tasks {terminal.progress_bar(3, 7)}")
        self.assertIn(last, row)
        self.assertIn(last, bar)
        self.assertEqual(watch.plan_progress("fix-api"), (3, 7))
        self.assertEqual(menu.seat_progress("fix-api"), (3, 7))

    def test_b_the_newer_of_two_plans_wins(self):
        seat = self.seat("fix-api", was="api-fix")
        self.going("20260101-0900-going", "fix-api")
        self.plan("fix-api", 1, 4, at=NOW - 3600)         # moved over by the rename, then left
        self.plan("api-fix", 5, 6, at=NOW - 60)           # written since, under the old name
        _, last, row, bar = self.drawn(seat)
        self.assertIn("5/6", last)
        self.assertIn(last, row)
        self.assertIn(last, bar)
        self.plan("fix-api", 2, 4, at=NOW)                # now the new name's is the newer
        self.assertEqual(watch.plan_progress("fix-api"), (2, 4))
        _, last, row, bar = self.drawn(seat)
        self.assertIn("2/4", last)
        self.assertIn(last, bar)

    def test_c_without_a_plan_the_unfinished_jobs_draw_the_bar(self):
        seat = self.seat("fix-api", was="api-fix")
        self.going("20260101-0900-going", "fix-api")
        self.job("job-new", "fix-api", ["merged", "passed", "running", "queued"])
        self.job("job-old-name", "api-fix", ["skipped", "failed", "waiting"])   # resolves here
        self.job("job-finished", "fix-api", ["merged"] * 5, finished_at=NOW - DAY)
        # another seat's job is never this one's, even in a directory named after it
        self.job("fix-api", "web-portal", ["merged", "queued"])
        word, last, row, bar = self.drawn(seat)
        self.assertEqual(word, "working")
        # merged, passed and skipped are done, of every task of the two unfinished jobs
        self.assertRegex(last, r"^tasks [█░]+ 3/7$")
        self.assertEqual(last, f"tasks {terminal.progress_bar(3, 7)}")
        self.assertIn(last, row)
        self.assertIn(last, bar)
        self.assertEqual(menu.seat_progress("web-portal"), (1, 2))
        # a plan, once there is one, is what the bar reads
        self.plan("fix-api", 1, 2)
        self.assertIn("1/2", self.drawn(seat)[1])

    def test_d_going_runs_never_read_running(self):
        seat = self.seat("fix-api")
        for run_id in ("20260101-0900-one", "20260101-0901-two"):
            self.going(run_id, "fix-api")
        word, last, row, bar = self.drawn(seat)
        self.assertEqual(word, "working")
        self.assertNotIn("running", last)
        self.assertNotIn("running", row)
        self.assertNotIn("running", bar)
        self.job("job-new", "fix-api", ["merged", "running"])
        word, last, row, bar = self.drawn(seat)
        self.assertEqual(last, f"tasks {terminal.progress_bar(1, 2)}")
        self.assertNotIn("running", row)
        self.assertNotIn("running", bar)

    def test_e_nothing_to_show_is_an_empty_column(self):
        seat = self.seat("fix-api")
        self.going("20260101-0900-going", "fix-api")
        self.job("job-finished", "fix-api", ["merged"], finished_at=NOW - DAY)
        self.job("fix-api", "web-portal", ["queued"])      # its directory's name is no owner
        word, last, row, bar = self.drawn(seat)
        self.assertEqual(word, "working")
        self.assertEqual(last, "")
        self.assertTrue(row.rstrip().endswith("● working"), row)
        self.assertTrue(bar.rstrip().endswith("● working"), bar)
        self.assertEqual(menu.seat_progress("fix-api"), (0, 0))
        # `needs you` and `done` keep their reason, a bar or not
        self.assertEqual(menu.last_column("needs you", "Merge first?", 3, 7), "Merge first?")
        self.assertEqual(menu.last_column("done", "Shipped", 0, 0), "Shipped")


if __name__ == "__main__":
    unittest.main(verbosity=2)
