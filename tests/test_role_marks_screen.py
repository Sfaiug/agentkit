"""The role marks stay independent, save atomically, and refuse only what no run could start from. Offline."""

import copy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, run, terminal, usage
from test_v4n import Sandbox
from test_config_matrix import Screen as ConfigScreen, row
from test_new_session_screen import Screen, RIGHT, LEFT, DOWN, ENTER, SPACE, highlighted, marks


class RoleMarks(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AGENTKIT_SESSION": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))

    def test_without_a_session_no_marks_are_drawn_and_nothing_is_written(self):
        config.save(self.cfg)
        path = config.HOME / config.CONFIG_NAME
        before = path.read_bytes()
        with patch.object(terminal, "layout_width", return_value=80):
            lines, places = menu.config_body(self.cfg, "fixture")
        self.assertEqual(lines[0].split(), ["effort"])
        for number, (model, cells) in places.items():
            if model[0] == "model":
                self.assertEqual(marks(lines[number]), "")
                self.assertEqual([cell[2] for cell in cells], [-1, 3])
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn("reviewers", self.cfg["defaults"])

    def test_only_a_pair_no_run_could_start_from_is_refused(self):
        # Nothing runnable refuses, without touching the groups.
        down = usage.Readings({})
        down.harnesses = {"claude": "claude is not logged in",
                          "codex": "codex is not logged in"}
        selected = {"orchestrator": "opus", "workers": ["opus"],
                    "reviewers": ["opus", "astra"]}
        kept, note = orch.role_mark(self.cfg, selected, "astra", 2, down)
        self.assertEqual(note, "no allowed executor/reviewer pair")
        self.assertEqual(kept, selected)

    def test_pair_check_matches_launch_for_aliases_and_only_refuses_the_unrunnable(self):
        self.cfg["models"]["copy"] = dict(self.cfg["models"]["opus"])
        self.cfg["models"]["fable"]["reviews_own_provider"] = False  # a stale key, ignored
        selected = {"orchestrator": "opus", "workers": ["opus"]}
        for reviewer in ("opus", "copy", "fable", "astra"):
            selected["reviewers"] = [reviewer]
            # Any of these could start -- the executor's own review is the last choice,
            # never a refusal -- so the screens allow what the launch allows.
            self.assertEqual(orch.role_refusal(self.cfg, selected, {}), "")
            self.assertIsNone(run.pair_refusal(self.cfg, {}, ["opus"], reviewers=[reviewer]))
        self.cfg["models"]["fable"]["reviews_own_provider"] = True
        selected["reviewers"] = ["fable"]
        self.assertEqual(orch.role_refusal(self.cfg, selected, {}), "")
        # Nothing runnable refuses, on the screens as on the launch.
        down = usage.Readings({})
        down.harnesses = {"claude": "claude is not logged in",
                          "codex": "codex is not logged in"}
        for reviewer in ("opus", "astra"):
            selected["reviewers"] = [reviewer]
            self.assertEqual(orch.role_refusal(self.cfg, selected, down),
                             "no allowed executor/reviewer pair")
            self.assertTrue(run.pair_refusal(self.cfg, down, ["opus"], reviewers=[reviewer]))

    def test_create_records_the_screen_reviewers_and_they_are_what_n_starts_from(self):
        self.cfg["defaults"]["reviewers"] = ["astra"]
        before = copy.deepcopy(self.cfg)
        with patch.object(orch, "fresh_command", return_value=(["fake"], None)), \
                patch.object(orch, "launch"), patch.object(orch.shutil, "which", return_value="fake"), \
                patch.object(orch, "refuse_held"), patch.object(orch, "alias_names", return_value=set()):
            orch.create(self.cfg, "fix-api", self.root, unnamed=True,
                        selection=({}, ("opus", "selected", ["opus"], ["fable"])))
        self.assertEqual(config.load_session(self.cfg, "fix-api")["reviewers"], ["fable"])
        chosen = {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["fable"]}
        self.assertEqual(self.cfg["defaults"], chosen)
        self.assertEqual(config.load()["defaults"], chosen)
        self.assertEqual({**self.cfg, "defaults": before["defaults"]}, before)

    def test_ascii_and_phone_keep_three_columns_and_click_targets(self):
        selected = {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["astra"]}
        notes = {name: "" for name in config.offered(self.cfg)}
        with patch.object(terminal, "utf8", return_value=False):
            lines, rows, cells = orch.picker_lines(self.cfg, notes, selected, 1, 2, 40)
        self.assertEqual(lines[0].split(), ["orch", "exec", "review"])
        self.assertTrue(all(terminal.cells(line) <= 40 for line in lines))
        self.assertTrue(all([cell[2] for cell in own] == [0, 1, 2] for own in cells))
        self.assertIn("[.]", lines[rows[1].start])

    def test_click_chooses_its_column_instead_of_the_previous_column(self):
        selected = {"orchestrator": "opus", "workers": ["opus", "astra"],
                    "reviewers": ["opus", "astra"]}
        notes = {name: "" for name in config.offered(self.cfg)}
        names = list(notes)
        with patch.object(terminal, "layout_width", return_value=80):
            _, rows, cells = orch.picker_lines(self.cfg, notes, selected, 1, 0, 80)
            for name, column, before, expected in (
                    ("fable", 0, 2, ("fable", ["opus", "astra"], ["opus", "astra"])),
                    ("opus", 1, 0, ("opus", ["astra"], ["opus", "astra"])),
                    ("astra", 2, 0, ("opus", ["opus", "astra"], ["opus"]))):
                for edge in (0, 1):     # the whole column is clickable, including its padding
                    at = names.index(name)
                    click = terminal.Key("click", col=cells[at][column][edge],
                                         row=rows[at].start + 3)
                    keys = [*[terminal.Key("right")] * before, click, terminal.Key("enter")]
                    with self.subTest(column=column, edge=edge), \
                            patch.object(terminal, "read_key", side_effect=keys), \
                            redirect_stdout(io.StringIO()):
                        self.assertEqual(orch._picking(self.cfg, {}, notes, selected), expected)

    def test_an_empty_role_falls_back_to_an_allowed_fresh_pair(self):
        for workers, reviewers, expected in (
                (["opus"], ["fable"], (["astra"], ["spark"])),
                (["opus"], ["astra"], (["spark"], ["astra"])),
                (["astra"], ["opus"], (["astra"], ["spark"])),
                (["astra"], ["spark"], (["astra"], ["spark"]))):
            self.cfg["defaults"].update(workers=workers, reviewers=reviewers)
            with self.subTest(workers=workers, reviewers=reviewers), \
                    patch.object(orch, "spent_note", side_effect=lambda cfg, name, providers:
                                 "" if name in ("astra", "spark") else "spent"), \
                    patch.object(terminal, "Keyboard"), \
                    patch.object(terminal, "read_key", side_effect=[terminal.Key("enter")]), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(orch.pick(self.cfg, {}, "astra"), ("astra", *expected))


class RoleMarksScreen(unittest.TestCase):
    def test_scrolling_keeps_headings_and_clicks_use_the_scrolled_row(self):
        screen = Screen(self, rows=12, cols=40)
        screen.menu()
        screen.send(b"n" + ENTER)
        screen.picker()
        screen.send(DOWN * 20)
        lines = screen.picker(lambda lines: "Mimo" in highlighted(lines))
        self.assertEqual(lines[2].split(), ["orch", "exec", "review"])
        self.assertLessEqual(len(lines), 11)
        self.assertTrue(all(terminal.cells(line) <= 40 for line in lines))
        row = lines.index(highlighted(lines)) + 1
        col = lines[2].index("review") + 3
        screen.send(f"\x1b[<0;{col};{row}M\x1b[<0;{col};{row}m".encode())
        lines = screen.picker(lambda lines: "Mimo" in highlighted(lines)
                              and marks(highlighted(lines)) == "○□■")
        row = next(number for number, line in enumerate(lines, 1) if "⏎ start" in line)
        col = lines[row - 1].index("⏎") + 1
        screen.send(f"\x1b[<0;{col};{row}M\x1b[<0;{col};{row}m".encode())
        screen.saw("<created new opus opus,astra opus,astra,mimo>")
        screen.leave()

    def test_config_reviewer_click_saves_self_pair_and_last_one_is_one_line(self):
        screen = ConfigScreen(self, workers=["opus"], cols=40, rows=24)
        lines = screen.frame()
        number, line = row(lines, "astra")
        first = lines[2].index("review") + 1
        lines = screen.click(first, number,
                             lambda lines: marks(row(lines, "astra")[1]) == "○□■")
        self.assertEqual(screen.record()["reviewers"], ["opus", "astra"])
        # Opus reviewing itself could start, so removing Astra saves.
        lines = screen.click(first, number,
                             lambda lines: marks(row(lines, "astra")[1]) == "○□□")
        self.assertEqual(screen.record()["reviewers"], ["opus"])
        self.assertFalse(any("no allowed" in line for line in lines))
        before = screen.session.read_bytes()
        number, line = row(lines, "opus")
        lines = screen.click(first + 4, number,
                             lambda lines: any("needs one model" in line for line in lines))
        self.assertEqual([line.strip() for line in lines if "needs one model" in line],
                         ["review needs one model"])
        self.assertEqual(screen.session.read_bytes(), before)
        screen.leave()

    def test_new_session_copies_explicit_defaults_and_creates_with_changed_reviewers(self):
        screen = Screen(self, reviewers=["astra"])
        screen.menu()
        screen.send(b"n" + ENTER)
        lines = screen.picker()
        self.assertEqual(marks(highlighted(lines)), "●■□")
        screen.send(RIGHT * 2 + SPACE)          # Opus joins reviewers
        lines = screen.picker(lambda lines: marks(highlighted(lines)) == "●■■")
        number = next(number for number, line in enumerate(lines, 1) if "Astra" in line)
        col = lines[2].index("review") + 5
        screen.send(LEFT * 2)                  # the click must move from orch to review
        screen.send(f"\x1b[<0;{col};{number}M\x1b[<0;{col};{number}m".encode())
        screen.picker(lambda lines: "Astra" in highlighted(lines)
                      and marks(highlighted(lines)) == "○■□")
        screen.send(LEFT + SPACE)              # Opus reviewing itself could start, so it goes
        lines = screen.picker(lambda lines: "Astra" in highlighted(lines)
                              and marks(highlighted(lines)) == "○□□")
        self.assertFalse(any("no allowed" in line for line in lines))
        screen.send(ENTER)
        screen.saw("<created new opus opus opus>")
        record = json.loads((screen.home / ".agentkit/state/session-new.json").read_text())
        self.assertEqual(record["reviewers"], ["opus"])
        screen.leave()


if __name__ == "__main__":
    unittest.main(verbosity=2)
