"""A seat's row says how many tasks it has going, after its plan's count.

The owner, 11 Nov 2026: the count stays the plan's outcomes, as a task mostly builds a plan
line, and the row adds the tasks in flight, `3 of 8 · 2 tasks`, the ones `menu.own_tasks` finds,
whose squares open under the row.  Short of room the line gives way first, then the tasks.
Offline: a temporary HOME, a fake plan and run records, `orch.tmux_out` patched.
"""

import os
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, menu, orch, record, statusbar, terminal, watch
from agentkit.guard import commands

NOW = 1_800_000_000


class RowCountsTasksGoing(Sandbox):
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
        config.save_session(self.cfg, "fix-api", "fable", ["opus"],
                            {"repo": self.repo, "cwd": self.repo})
        self.seat = {"name": "fix-api", "repo": self.repo, "path": self.repo,
                     "created": NOW - 86400, "attached": False, "exited": False,
                     "legacy": False, "resumable": False}
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[self.seat]))

    def tmux(self, *args, **_kw):
        for command in commands(args):
            if command[0] == "set-option" and "-u" not in command:
                self.options[command[command.index("-t") + 2]] = command[-1]
        return 0, ""

    def going(self, *runs, state="running"):
        """Runs the seat launched, each still building -- its tasks in flight -- or ended."""
        for run_id in runs:
            (config.RUNS / run_id).mkdir(parents=True, exist_ok=True)
            record.save_state(config.RUNS / run_id, {
                "run_id": run_id, "title": f"Task {run_id}", "state": state,
                "step": "executor", "launched_session": "fix-api", "repo": self.repo,
                "started_at": NOW - 600, "finished_at": None if state == "running" else NOW})

    def info(self):
        return menu.v5o_seat_info(self.cfg, 1, self.seat, menu.run_records(), {}, {}, NOW)

    def row(self):
        """The seat's word and its row, as the menu draws it 100 cells wide."""
        info = self.info()
        return info["word"], terminal.plain(menu.v5o_seat_blocks([info], 100)[0][0])

    def test_a_working_seat_counts_its_plan_then_its_tasks_in_flight(self):
        config.plan_path("fix-api").write_text("- [x] done\n" * 3 + "- [ ] todo\n" * 5)
        self.going("20261111-0900-one", "20261111-0901-two")
        word, row = self.row()
        self.assertEqual(word, "working")
        self.assertRegex(row, r"● working [━╸]+─+ 3 of 8 · 2 tasks$")
        self.assertEqual(len(self.info()["tasks"]), 2)       # the squares under it, as many
        # the seat's own bar leaves its tasks to the squares it draws
        watch.announce_state(self.seat, cfg=self.cfg)
        self.assertRegex(self.options[statusbar.TOP], r" 3 of 8(?! · )")
        self.going("20261111-0901-two", state="fail")
        self.assertRegex(self.row()[1], r"● working [━╸]+─+ 3 of 8 · 1 task$")
        self.going("20261111-0900-one", state="fail")
        self.assertRegex(self.row()[1], r"[━╸]+─+ 3 of 8$")

    def test_a_working_seat_without_a_plan_counts_its_tasks_in_flight(self):
        self.going("20261111-0900-one", "20261111-0901-two", "20261111-0902-three")
        word, row = self.row()
        self.assertEqual(word, "working")
        self.assertRegex(row, r"● working ─+ no plan yet · 3 tasks$")

    def test_short_of_room_the_line_goes_first_then_the_tasks(self):
        config.plan_path("fix-api").write_text("- [x] done\n" * 3 + "- [ ] todo\n" * 5)
        self.going("20261111-0900-one", "20261111-0901-two")
        info = self.info()
        drawn = {cells: terminal.plain(menu._last_text(info, cells, narrow=True))
                 for cells in (18, 17, 16, 15, 6)}
        self.assertRegex(drawn[18], r"^[━╸] 3 of 8 · 2 tasks$")
        self.assertEqual(drawn[17], "3 of 8 · 2 tasks")
        self.assertEqual(drawn[16], "3 of 8 · 2 tasks")
        self.assertEqual(drawn[15], "3 of 8")
        self.assertEqual(drawn[6], "3 of 8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
