"""Every screen test keeps its unittest name."""

import ast
import importlib
from pathlib import Path
import unittest

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
            if names:
                suite = unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(path.stem))
                names = [case.id().split(".", 1)[1] for group in suite for case in group
                         if case.id().split(".", 1)[1] in NAMES]
            self.assertLessEqual(len(names), 1, str(path))
            found.extend(names)
        self.assertCountEqual(found, NAMES)


if __name__ == "__main__":
    unittest.main()
