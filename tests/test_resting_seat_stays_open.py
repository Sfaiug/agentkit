"""A seat stays open until the owner closes it, and one an older ak put to sleep comes back on its
own conversation and takes what is owed it: the answer key in
tests/test_key_a_resting_seat_stays_open.py, run here."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_a_resting_seat_stays_open import RestingSeatStaysOpen  # noqa: F401

if __name__ == "__main__":
    unittest.main()
