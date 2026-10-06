"""A session's models live on `c`: a role flip saves to the session's record at once,
reviewers keep one model, and a choice leaving no allowed pair is refused in one line.

Offline: `menu.session_mark` flips against session records in a throwaway HOME, proving the
run boundary -- a run launched next reads the new groups, one already going keeps the groups
its receipt saved -- and `menu.config_body` and a dry run of `menu.show_config` draw a
session's marks.  The screen itself is read on a pty in tests/test_config_matrix.py and
tests/test_one_config_screen.py.  Nothing here starts a seat or a tmux server.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from fixtures.sandbox import Sandbox
from agentkit import gate, config, menu, run, terminal, update, usage
from agentkit import record as run_record


def marks(line):
    return "".join(char for char in terminal.plain(line) if char in "●○■□")


class SessionModels(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AGENTKIT_SESSION": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"],
                            {"reviewers": ["astra"], "cwd": str(self.root), "created": 100})
        config.save_session(self.cfg, "old", "opus", ["opus", "astra"],
                            {"cwd": str(self.root), "created": 100})

    def selected(self, name):
        record = config.load_session(self.cfg, name)
        found = {"orchestrator": record["orchestrator"], "workers": list(record["workers"])}
        if "reviewers" in record:
            found["reviewers"] = list(record["reviewers"])
        return found

    def test_a_flip_saves_to_the_session_record_at_once(self):
        selected = self.selected("fix-api")
        self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "fable", 1, {}), "")
        self.assertEqual(selected["workers"], ["opus", "astra", "fable"])
        record = config.load_session(self.cfg, "fix-api")
        self.assertEqual(record["workers"], ["opus", "astra", "fable"])
        self.assertEqual(record["reviewers"], ["astra"])
        self.assertEqual(record["orchestrator"], "opus")
        selected = self.selected("fix-api")
        self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "opus", 2, {}), "")
        self.assertEqual(config.load_session(self.cfg, "fix-api")["reviewers"],
                         ["astra", "opus"])

    def test_a_flip_on_a_screen_open_across_a_rename_saves_to_the_renamed_record(self):
        for column, model, field, expected in ((1, "fable", "workers", ["opus", "astra", "fable"]),
                                               (2, "opus", "reviewers", ["astra", "opus"])):
            with self.subTest(column=column):
                config.save_session(self.cfg, "fix-api", "opus", ["opus", "astra"],
                                    {"reviewers": ["astra"], "cwd": str(self.root), "created": 100})
                selected = self.selected("fix-api")
                config.rename_session("fix-api", "ship-api")
                note = menu.session_mark(self.cfg, "fix-api", selected, model, column, {})
                self.assertEqual(note, "")
                self.assertEqual(selected[field], expected)
                self.assertEqual(config.load_session(self.cfg, "ship-api")[field], expected)
                config.session_path("ship-api").unlink()

    def rows(self, lines):
        return {terminal.plain(line).lstrip("› ").split()[0]: marks(line)
                for line in lines if marks(line)}

    def test_a_legacy_record_shows_workers_in_both_columns_until_the_first_flip(self):
        self.assertNotIn("reviewers", config.load_session(self.cfg, "old"))
        with patch.object(terminal, "layout_width", return_value=100):
            lines, places = menu.config_body(self.cfg, "fixture", selected=self.selected("old"))
        self.assertEqual(lines[0].split(), ["orch", "exec", "review", "effort"])
        self.assertEqual(self.rows(lines)["opus"], "●■■")
        self.assertEqual(self.rows(lines)["fable"], "○□□")
        cells = next(cells for row, cells in places.values() if row == ("model", "opus"))
        self.assertEqual([cell[2] for cell in cells], [-1, 0, 1, 2, 3])
        selected = self.selected("old")
        self.assertEqual(menu.session_mark(self.cfg, "old", selected, "opus", 1, {}), "")
        record = config.load_session(self.cfg, "old")
        self.assertEqual(record["workers"], ["astra"])
        self.assertEqual(record["reviewers"], ["opus", "astra"])

    def test_reviewers_keep_one_model_executors_may_go_and_no_pair_is_refused_without_a_save(self):
        config.save_session(self.cfg, "solo", "opus", ["opus"], {"reviewers": ["astra"]})
        selected = self.selected("solo")
        with patch.object(usage, "unready", return_value=""):
            self.assertEqual(menu.session_mark(self.cfg, "solo", selected, "opus", 1, {}), "")
        self.assertEqual(menu.session_mark(self.cfg, "solo", selected, "astra", 2, {}),
                         "review needs one model")
        self.assertEqual(config.load_session(self.cfg, "solo")["workers"], [])
        config.save_session(self.cfg, "tight", "opus", ["opus"],
                            {"reviewers": ["opus", "astra"]})
        selected = self.selected("tight")
        # Opus reviewing itself could start, so removing Astra saves.
        self.assertEqual(menu.session_mark(self.cfg, "tight", selected, "astra", 2, {}),
                         "")
        self.assertEqual(selected["reviewers"], ["opus"])
        self.assertEqual(config.load_session(self.cfg, "tight")["reviewers"], ["opus"])
        # Nothing runnable refuses, without touching the saved groups.
        down = usage.Readings({})
        down.harnesses = {"claude": "claude is not logged in",
                          "codex": "codex is not logged in"}
        with patch.object(config, "update_session") as saved:
            self.assertEqual(menu.session_mark(self.cfg, "tight", selected, "fable", 2,
                                               down),
                             "no allowed executor/reviewer pair")
            saved.assert_not_called()
        self.assertEqual(selected["reviewers"], ["opus"])
        self.assertEqual(config.load_session(self.cfg, "tight")["reviewers"], ["opus"])
        selected = self.selected("fix-api")
        before = dict(selected)
        with patch.object(config, "update_session", side_effect=OSError("read only")):
            self.assertEqual(menu.session_mark(self.cfg, "fix-api", selected, "fable", 1,
                                               {}), "session: read only")
        self.assertEqual(selected, before)

    def test_a_flip_after_its_model_was_removed_is_one_line_and_no_save(self):
        selected = self.selected("fix-api")
        config.remove_model(self.cfg, "astra")
        with patch.object(config, "update_session") as saved:
            self.assertIn("unknown model 'astra'",
                          menu.session_mark(self.cfg, "fix-api", selected, "fable", 1, {}))
            saved.assert_not_called()
        self.assertEqual(selected["workers"], ["opus", "astra"])

    def test_runs_launched_next_read_the_new_groups_and_going_runs_keep_theirs(self):
        selected = self.selected("fix-api")
        menu.session_mark(self.cfg, "fix-api", selected, "fable", 1, {})
        with patch.dict(os.environ, {"AGENTKIT_SESSION": "fix-api"}), \
                patch.object(run, "redress_seat"), \
                patch.object(run, "history_start"), patch.object(gate, "claim_slot"):
            directory = config.RUNS / "next-run"
            directory.mkdir()
            run.capture_launch(directory, cfg=self.cfg)
            state = run_record.read_state(directory)
        self.assertEqual(state["workers"], ["opus", "astra", "fable"])
        self.assertEqual(state["reviewers"], ["astra"])
        going = {"run_id": "going", "launched_session": "fix-api",
                 "workers": ["opus", "astra"], "reviewers": ["astra"]}
        selected = self.selected("fix-api")
        menu.session_mark(self.cfg, "fix-api", selected, "spark", 2, {})
        self.assertEqual(run.run_workers(self.cfg, going), ["opus", "astra"])
        self.assertEqual(run.run_reviewers(self.cfg, going), ["astra"])

    def test_the_body_holds_the_current_groups_and_a_spent_note(self):
        spent = usage.Readings({"anthropic": {"meters": [{
            "name": "weekly_all", "used": 100, "exhausted": True, "resets_at": 10000 + 86400}]}})
        with patch.object(terminal, "layout_width", return_value=100):
            lines, _ = menu.config_body(self.cfg, "fixture", ("model", "opus"), 1,
                                        self.selected("fix-api"), spent)
        self.assertEqual(self.rows(lines)["opus"], "●■□")
        self.assertEqual(self.rows(lines)["astra"], "○■■")
        row = next(terminal.plain(line) for line in lines if "opus" in terminal.plain(line))
        self.assertIn("spent · resets", row)
        self.assertNotIn("spent", next(terminal.plain(line) for line in lines
                                       if "astra" in terminal.plain(line)))
        with patch.object(terminal, "layout_width", return_value=40):
            lines, _ = menu.config_body(self.cfg, "fixture", None, 0, self.selected("fix-api"),
                                        spent)
        self.assertTrue(all(terminal.cells(line) <= 40 for line in lines))
        self.assertTrue(any("spent · resets" in terminal.plain(line) for line in lines))

    def test_a_dry_run_draws_the_sessions_marks_and_a_seat_without_a_record_only_efforts(self):
        with patch.object(update, "agentkit_version", return_value="fixture"), \
                patch.object(usage, "collect", return_value=usage.Readings({})), \
                patch.object(terminal, "layout_width", return_value=100), \
                redirect_stdout(io.StringIO()) as out:
            menu.show_config(dry_run=True, session="fix-api")
        screen = terminal.ANSI.sub("", out.getvalue())
        self.assertIn("agentkit · config · fix-api", screen)
        self.assertEqual(self.rows(screen.splitlines())["astra"], "○■■")
        self.assertIn("esc back", screen)
        with patch.object(update, "agentkit_version", return_value="fixture"), \
                redirect_stdout(io.StringIO()) as out:
            menu.show_config(dry_run=True, session="nobody")
        screen = terminal.ANSI.sub("", out.getvalue())
        self.assertNotIn("nobody", screen)
        self.assertEqual(self.rows(screen.splitlines()), {})

    def test_no_key_line_or_sentence_offers_m(self):
        self.assertEqual(menu.KEYS, "n new   x stop   c config   esc leave")
        self.assertEqual([key for key in terminal.TIPS if key.startswith("m ")], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
