"""The reviewer is picked in the owner's order of 21 Oct: the answer key in
tests/test_key_reviewer_other_provider_first.py, run here."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_reviewer_other_provider_first import (  # noqa: F401
    AnotherProviderFirst, TheWriterLast, TheWritersProviderNext)

if __name__ == "__main__":
    unittest.main()
