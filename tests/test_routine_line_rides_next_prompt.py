"""The answer key tests/test_key_routine_line_rides_next_prompt.py, run by this task's name."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_routine_line_rides_next_prompt import (  # noqa: F401
    CarriesItsMerge, EndsTheWait, Rides)

if __name__ == "__main__":
    unittest.main()
