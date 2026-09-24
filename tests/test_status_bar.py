"""The session's status bar says its state and progress; the in-session menu renames it.

The bar is the menu row's own values -- the state function's word and `last_column` --
written through the one writer by the tick and every menu draw; the right side is the one
key. The overlay offers four keys, and `r` renames everything that carries the name.
Offline: fake seats, plan files and run records, `orch.tmux_out` patched.
"""

from contextlib import redirect_stdout
import io
import os
import time
import unittest
from unittest.mock import patch

from test_v4n import Sandbox
from agentkit import config, menu, notify, orch, run, terminal, watch

NOW = 1_800_000_000
DAY = 86400


class StatusBar(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        (config.CODE / "atoll" / ".git").mkdir(parents=True)
        self.repo = str(config.CODE / "atoll")
        self.seat = {"name": "herdr", "repo": self.repo, "path": self.repo,
                     "created": NOW - 5 * DAY, "attached": False, "exited": False,
                     "legacy": False, "resumable": False}
        config.save_session(self.cfg, "herdr", "fable", ["opus"],
                            {"repo": self.repo, "cwd": self.repo})
        self.options = {}
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[self.seat]))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(watch, "pane_text", return_value="$ "))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=NOW))

    def tmux(self, *args, **kwargs):
        if args[0] == "set-option" and "-u" not in args:
            self.options[args[args.index("-t") + 2]] = args[-1]
        return 0, ""

    def receipt(self, name, owner="herdr", **extra):
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        state = {"run_id": name, "title": f"Task {name}", "state": "pass", "verdict": "PASS",
                 "launched_session": owner, "reported": False, "repo": self.repo,
                 "executor": "opus", "reviewer": "astra", "rounds": 2, "round_summaries": [],
                 "finished_at": NOW - 1800, "started_at": NOW - 3600, **extra}
        run.save_state(directory, state)
        for path in list(directory.rglob("*")) + [directory]:
            try:
                os.utime(path, (NOW, NOW))
            except OSError:
                pass
        return directory

    def plan(self, name, done, total):
        lines = ["- [x] done"] * done + ["- [ ] todo"] * (total - done)
        (config.STATE / f"plan-{name}.md").write_text("\n".join(lines) + "\n")

    def test_bar_shows_working_with_plan(self):
        self.plan("herdr", 2, 5)
        self.receipt("20260101-0900-going", state="running", finished_at=None,
                     started_at=NOW - 600)
        found = watch.announce_state(self.seat, cfg=self.cfg)
        self.assertEqual(found["word"], "working")
        left = self.options["status-left"]
        self.assertIn("herdr · fable", left)
        self.assertIn("● working", left)
        self.assertIn("tasks ", left)
        self.assertIn("2/5", left)
        self.assertEqual(self.options["set-titles-string"], "herdr · working")
        self.assertNotIn("idle", left)

    def test_bar_shows_needs_you_with_reason(self):
        notify.record("herdr", "needs", "Merge the MOV helper before or after?")
        found = watch.announce_state(self.seat, cfg=self.cfg)
        self.assertEqual(found["word"], "needs you")
        left = self.options["status-left"]
        self.assertIn("! needs you", left)
        self.assertIn("Merge the MOV helper before or after?", left)
        self.assertEqual(self.options["set-titles-string"], "herdr · needs you")

    def test_bar_and_row_come_from_one_function(self):
        self.plan("herdr", 1, 4)
        records = menu.run_records()
        info = menu.v5o_seat_info(self.cfg, 1, self.seat, records, {}, {}, NOW)
        with patch.object(menu, "last_column", return_value="PATCHED") as patched:
            row = menu.v5o_format_seats([info], 100)
            watch.announce_state(self.seat, cfg=self.cfg)
        self.assertTrue(patched.called)
        self.assertIn("PATCHED", "\n".join(row))
        self.assertIn("PATCHED", self.options["status-left"])

    def test_right_side_is_the_single_hint(self):
        left, right, _ = orch.bar("herdr", "fable", "working", "tasks x 2/5")
        self.assertEqual(right, " Ctrl-b m  menu ")
        for hint in ("Ctrl-b d", "back to menu", "menu here", "close the menu"):
            self.assertNotIn(hint, right)
            self.assertNotIn(hint, left)
        orch.dress("herdr", "fable")
        self.assertEqual(self.options["status-right"], " Ctrl-b m  menu ")
        self.assertEqual(self.options["status-left"], " herdr · fable ")
        self.assertEqual(self.options["set-titles-string"], "herdr")
        # a reason carrying `#` is doubled, so tmux reads text and not a format
        _, _, title = orch.bar("herdr", "fable", "done", "Merged #75")
        left, _, _ = orch.bar("herdr", "fable", "done", "Merged #75")
        self.assertIn("Merged ##75", left)
        self.assertEqual(title, "herdr · done")

    def test_rename_moves_every_state_file_and_run_records(self):
        seats = [dict(self.seat)]

        def tmux(*args, **kwargs):
            if args[0] == "rename-session":
                seats[0]["name"] = args[-1]
            return self.tmux(*args, **kwargs)

        config.save_session(self.cfg, "herdr", "fable", ["opus"],
                            {"repo": self.repo, "cwd": self.repo})
        for path in (config.notify_path("herdr"), config.card_path("herdr"),
                     config.seat_state_path("herdr"), config.hook_facts_path("herdr"),
                     config.compact_path("herdr"), config.plan_path("herdr"),
                     config.stop_path("herdr")):
            path.write_text(" {}\n" if path.suffix == ".json" else "\n")
        self.receipt("20260101-0900-mine", state="running", finished_at=None,
                     started_at=NOW - 600)
        self.receipt("20260101-0900-theirs", owner="other", state="running",
                     finished_at=None, started_at=NOW - 600)
        with patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(orch, "sessions", side_effect=lambda: seats), \
                patch.object(orch, "listing",
                             side_effect=lambda *a, **k: seats + [{"name": "other"}]):
            self.assertEqual(orch.rename("herdr", "parser"), "parser")
        for path in (config.notify_path("parser"), config.card_path("parser"),
                     config.seat_state_path("parser"), config.hook_facts_path("parser"),
                     config.compact_path("parser"), config.plan_path("parser"),
                     config.stop_path("parser")):
            self.assertTrue(path.exists(), path)
        for path in (config.notify_path("herdr"), config.card_path("herdr"),
                     config.seat_state_path("herdr"), config.hook_facts_path("herdr"),
                     config.compact_path("herdr"), config.plan_path("herdr"),
                     config.stop_path("herdr")):
            self.assertFalse(path.exists(), path)
        self.assertEqual(run.read_state(config.RUNS / "20260101-0900-mine")["launched_session"],
                         "parser")
        self.assertEqual(run.read_state(config.RUNS / "20260101-0900-theirs")["launched_session"],
                         "other")
        # the record moved and the pointer stayed; the bar says the new name at once
        self.assertEqual(config.resolve_session("herdr"), "parser")
        self.assertIn("parser · fable", self.options["status-left"])
        self.assertNotIn("herdr · fable", self.options["status-left"])

    def test_overlay_lists_the_four_entries(self):
        self.assertEqual(menu.OVERLAY_KEYS,
                         "n start a session   r rename this session   "
                         "x stop this session   q close")
        entries = menu.OVERLAY_KEYS.split("   ")
        self.assertEqual(entries, ["n start a session", "r rename this session",
                                   "x stop this session", "q close"])
        with patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                patch.object(watch, "live_state",
                             return_value={"state": "at_prompt", "rule": "fixture"}), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, [self.seat], menu.OVERLAY_KEYS)
        screen = out.getvalue()
        for entry in entries:
            self.assertIn(entry, screen)
        for gone in ("c config", "i info", "close the menu", "stop one"):
            self.assertNotIn(gone, screen)

    def test_overlay_r_renames_x_stops_and_c_is_not_a_key(self):
        answers = iter(["r", "x", "c", "i", "q"])
        with patch.object(orch, "listing", return_value=[self.seat]), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu, "read", side_effect=lambda *_: next(answers)), \
                patch.object(menu, "rename_this_session") as renamed, \
                patch.object(menu, "stop_this_session") as stopped, \
                patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=30), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.loop(self.cfg, dry_run=True, overlay=True), 0)
        renamed.assert_called_once_with(True)
        stopped.assert_called_once_with(True)
        screen = out.getvalue()
        self.assertIn("not a key: 'c'", screen)
        self.assertIn("not a key: 'i'", screen)

    def test_rename_asks_with_current_and_validates(self):
        with patch.dict(os.environ, {config.SESSION_ENV: "herdr"}), \
                patch.object(orch, "taken_names", return_value={"herdr", "other"}), \
                patch.object(orch, "ask_name", return_value="parser") as asked, \
                patch.object(orch, "rename", return_value="parser") as renamed, \
                redirect_stdout(io.StringIO()) as out:
            menu.rename_this_session(True)
        asked.assert_called_once_with({"other"}, "herdr")
        renamed.assert_not_called()       # a dry run asks, then only says so
        self.assertIn("would rename herdr -> parser", out.getvalue())
        with patch.dict(os.environ, {config.SESSION_ENV: "herdr"}), \
                patch.object(orch, "taken_names", return_value={"herdr", "other"}), \
                patch.object(orch, "ask_name", return_value="parser"), \
                patch.object(orch, "rename", return_value="parser"), \
                redirect_stdout(io.StringIO()):
            menu.rename_this_session(False)
            self.assertEqual(os.environ[config.SESSION_ENV], "parser")

    def test_legacy_seat_keeps_no_bar(self):
        ghost = dict(self.seat, legacy=True)
        watch.announce_state(ghost, cfg=self.cfg)
        self.assertNotIn("status-left", self.options)
        self.assertNotIn("status-right", self.options)


if __name__ == "__main__":
    unittest.main(verbosity=2)
