"""Every screen test keeps its unittest name; every Go claim runs in exactly one slice."""

import ast
import importlib
from pathlib import Path
import unittest
from unittest.mock import patch

import test_go_keys as go

HERE = Path(__file__).resolve().parent
NAMES = (
    "RunsAtRestCostAnOpenScreenLittle.test_1_the_runs_add_less_than_a_few_plain_looks_a_minute",
    "RunsAtRestCostAnOpenScreenLittle.test_2_a_run_at_rest_that_changes_still_shows",
    "RunsAtRestCostAnOpenScreenLittle.test_3_a_new_run_shows_at_once_and_goes_with_its_directory",
    "RunsAtRestCostAnOpenScreenLittle.test_4_a_symlink_that_moved_shows_by_a_full_read_and_a_changed_record_at_once",
    "RunsAtRestCostAnOpenScreenLittle.test_5_a_seat_renamed_shows_its_runs_under_its_new_name",
    "SeatLookReadsTheRunsOnce.test_a_still_minute_lists_the_runs_fewer_times_than_its_seats_are_owed_endings",
    "SeatLookReadsTheRunsOnce.test_a_still_minute_opens_no_unchanged_notice_and_a_changed_one_shows",
    "IdleScreenReadsOnlyWhatChanged.test_1_an_idle_minute_reads_less_than_the_files_hold",
    "IdleScreenReadsOnlyWhatChanged.test_2_a_changed_seat_or_run_file_shows_at_the_next_refresh",
    "IdleScreenReadsOnlyWhatChanged.test_3_runs_waiting_to_land_and_endings_owed_read_less_than_they_hold",
)


class SplitKeys(unittest.TestCase):
    def test_each_screen_test_has_a_file_of_its_own(self):
        found = []
        for path in HERE.glob("test_*.py"):
            tree = ast.parse(path.read_text())
            names = [f"{cls.name}.{method.name}" for cls in tree.body
                     if isinstance(cls, ast.ClassDef) for method in cls.body
                     if isinstance(method, ast.FunctionDef)
                     and f"{cls.name}.{method.name}" in NAMES]
            self.assertLessEqual(len(names), 1, str(path))
            found.extend(names)
        self.assertCountEqual(found, NAMES)

    def test_go_claims_run_once_across_proper_slices(self):
        listed = [line.split() for line in (go.REPO / "go/keys.txt").read_text().splitlines()]
        claimed = []
        for path in [HERE / "test_go_keys.py", *sorted(HERE.glob("test_go_keys_part_*.py"))]:
            module = importlib.import_module(path.stem)
            with patch.object(go.shutil, "copytree"), \
                    patch.dict(go.os.environ, {"AK_BIN": "/bin/true"}), \
                    patch.object(go.sys, "argv", [str(path)]), \
                    patch.object(go.subprocess, "run", return_value=go.subprocess.CompletedProcess(
                        [], 0, "", "Ran 1 test in 0.0s\n\nOK\n")) as run:
                module.Claims("test_each_claim_passes").test_each_claim_passes()
            commands = [call.args[0][1:] for call in run.call_args_list
                        if call.args[0][0] == go.sys.executable]
            self.assertTrue(commands, str(path))
            self.assertLess(len(commands), len(listed), str(path))
            claimed.extend(commands)
        self.assertCountEqual(claimed, [[f"tests/{name}.py", *parts] for name, *parts in listed])


if __name__ == "__main__":
    unittest.main()
