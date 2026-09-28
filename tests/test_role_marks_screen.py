"""The role marks stay independent, save atomically, and admit only launchable pairs. Offline."""

import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, run, terminal
from test_v4n import Sandbox
from test_config_matrix import Screen as ConfigScreen, row
from test_new_session_screen import Screen, RIGHT, LEFT, ENTER, SPACE, highlighted, marks


class RoleMarks(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AGENTKIT_SESSION": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))

    def test_reading_legacy_defaults_does_not_write_and_both_roles_match(self):
        config.save(self.cfg)
        path = config.HOME / config.CONFIG_NAME
        before = path.read_bytes()
        with patch.object(terminal, "layout_width", return_value=80):
            lines, places = menu.config_body(self.cfg, "fixture")
        self.assertEqual(lines[0].split(), ["orch", "exec", "review", "effort"])
        for number, (model, cells) in places.items():
            if model[0] == "model":
                self.assertEqual(marks(lines[number])[1:],
                                 "■■" if model[1] in self.cfg["defaults"]["workers"] else "□□")
                self.assertEqual([cell[2] for cell in cells], [-1, 0, 1, 2, 3])
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn("reviewers", self.cfg["defaults"])

    def test_first_executor_flip_snapshots_reviewers_before_the_change(self):
        self.assertEqual(menu.config_mark(self.cfg, "opus", 1), "")
        saved = config.load()["defaults"]
        self.assertEqual(saved["workers"], ["astra"])
        self.assertEqual(saved["reviewers"], ["opus", "astra"])
        self.assertEqual(menu.config_mark(self.cfg, "astra", 2), "")
        self.assertEqual(config.load()["defaults"]["reviewers"], ["opus"])
        self.assertEqual(self.cfg["defaults"]["workers"], ["astra"])

    def test_first_reviewer_or_orchestrator_flip_materializes_reviewers(self):
        for name, column in (("opus", 2), ("astra", 0)):
            with self.subTest(column=column):
                self.cfg["defaults"] = {"orchestrator": "opus", "workers": ["opus", "astra"]}
                self.assertEqual(menu.config_mark(self.cfg, name, column), "")
                self.assertEqual(config.load()["defaults"]["workers"], ["opus", "astra"])
                self.assertEqual(config.load()["defaults"]["reviewers"],
                                 ["astra"] if column == 2 else ["opus", "astra"])

    def test_last_member_and_save_failure_leave_both_groups_unchanged(self):
        self.cfg["defaults"].update(workers=["opus"], reviewers=["astra"])
        config.save(self.cfg)
        before = copy.deepcopy(self.cfg)
        for name, column in (("opus", 1), ("astra", 2)):
            self.assertIn("need one model", menu.config_mark(self.cfg, name, column))
            self.assertEqual(self.cfg, before)
        with patch.object(config, "save", side_effect=OSError("read only")):
            self.assertEqual(menu.config_mark(self.cfg, "fable", 2), "config: read only")
        self.assertEqual(self.cfg, before)
        self.assertEqual(config.load()["defaults"], before["defaults"])
        self.cfg["defaults"].pop("reviewers")
        with patch.object(config, "save", side_effect=OSError("read only")):
            menu.config_mark(self.cfg, "astra", 1)
        self.assertNotIn("reviewers", self.cfg["defaults"])

    def test_invalid_pair_is_refused_without_a_save(self):
        self.cfg["defaults"].update(workers=["opus"], reviewers=["opus", "astra"])
        before = copy.deepcopy(self.cfg)
        with patch.object(config, "save") as save:
            self.assertEqual(menu.config_mark(self.cfg, "astra", 2),
                             "no allowed executor/reviewer pair")
            save.assert_not_called()
        self.assertEqual(self.cfg, before)

    def test_pair_check_matches_launch_for_aliases_and_company_policy(self):
        self.cfg["models"]["copy"] = dict(self.cfg["models"]["opus"])
        self.cfg["models"]["fable"]["reviews_own_provider"] = False
        selected = {"orchestrator": "opus", "workers": ["opus"]}
        for reviewer in ("opus", "copy", "fable", "astra"):
            selected["reviewers"] = [reviewer]
            self.assertEqual(bool(orch.role_refusal(self.cfg, selected, {})), reviewer != "astra")
            self.assertEqual(bool(orch.role_refusal(self.cfg, selected, {})), bool(
                run.pair_refusal(self.cfg, {}, ["opus"], reviewers=[reviewer])))
        self.cfg["models"]["fable"]["reviews_own_provider"] = True
        selected["reviewers"] = ["fable"]
        self.assertEqual(orch.role_refusal(self.cfg, selected, {}), "")

    def test_create_records_the_screen_reviewers_without_changing_defaults(self):
        self.cfg["defaults"]["reviewers"] = ["astra"]
        before = copy.deepcopy(self.cfg)
        with patch.object(orch, "fresh_command", return_value=(["fake"], None)), \
                patch.object(orch, "launch"), patch.object(orch.shutil, "which", return_value="fake"), \
                patch.object(orch, "refuse_held"), patch.object(orch, "alias_names", return_value=set()):
            orch.create(self.cfg, "fix-api", self.root, unnamed=True,
                        selection=({}, ("opus", "selected", ["opus"], ["fable"])))
        self.assertEqual(config.load_session(self.cfg, "fix-api")["reviewers"], ["fable"])
        self.assertEqual(self.cfg, before)

    def test_ascii_and_phone_keep_three_columns_and_click_targets(self):
        selected = {"orchestrator": "opus", "workers": ["opus"], "reviewers": ["astra"]}
        notes = {name: "" for name in config.offered(self.cfg)}
        with patch.object(terminal, "utf8", return_value=False):
            lines, rows, cells = orch.picker_lines(self.cfg, notes, selected, 1, 2, 40)
        self.assertEqual(lines[0].split(), ["orch", "exec", "review"])
        self.assertTrue(all(terminal.cells(line) <= 40 for line in lines))
        self.assertTrue(all([cell[2] for cell in own] == [0, 1, 2] for own in cells))
        self.assertIn("[.]", lines[rows[1].start])


class RoleMarksScreen(unittest.TestCase):
    def test_config_reviewer_click_saves_and_refusal_is_one_line_on_a_phone(self):
        text = (REPO / "config.default.toml").read_text().replace(
            'workers = ["opus", "astra"]', 'workers = ["opus"]\nreviewers = ["opus", "astra"]')
        screen = ConfigScreen(self, text=text, cols=40, rows=24)
        lines = screen.frame()
        number, line = row(lines, "astra")
        first = lines[2].index("review") + 1
        before = screen.path.read_bytes()
        lines = screen.click(first, number, lambda lines: any("no allowed" in line for line in lines))
        self.assertEqual([line.strip() for line in lines if "no allowed" in line],
                         ["no allowed executor/reviewer pair"])
        self.assertEqual(screen.path.read_bytes(), before)
        number, line = row(lines, "opus")
        screen.click(first + 4, number, lambda lines: marks(row(lines, "opus")[1]) == "●■□")
        self.assertEqual(screen.saved()["defaults"]["reviewers"], ["astra"])
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
        screen.send(f"\x1b[<0;{col};{number}M\x1b[<0;{col};{number}m".encode())
        screen.picker(lambda lines: "Astra" in highlighted(lines)
                      and marks(highlighted(lines)) == "○■□")
        screen.send(LEFT + SPACE)              # Removing the only pair must leave Astra executing
        screen.picker(lambda lines: any("no allowed" in line for line in lines))
        screen.send(ENTER)
        screen.saw("<created new opus opus,astra opus>")
        record = json.loads((screen.home / ".agentkit/state/session-new.json").read_text())
        self.assertEqual(record["reviewers"], ["opus"])
        screen.leave()


if __name__ == "__main__":
    unittest.main(verbosity=2)
