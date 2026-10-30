"""A history row left running after its run ended is brought up to date by the tick itself: the
answer key in tests/test_key_history_rows_agree_with_records.py, run here."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_history_rows_agree_with_records import HistoryRowsAgreeWithRecords  # noqa: F401

if __name__ == "__main__":
    unittest.main()
