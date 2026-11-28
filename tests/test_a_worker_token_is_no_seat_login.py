"""A saved worker token says nothing about a seat's login: the answer key in
tests/test_key_a_worker_token_is_no_seat_login.py, run here."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_a_worker_token_is_no_seat_login import AWorkerTokenIsNoSeatLogin  # noqa: F401

if __name__ == "__main__":
    unittest.main()
