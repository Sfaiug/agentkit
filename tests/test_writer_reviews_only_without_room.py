"""The writer reviews its own work only while no other marked reviewer has room: the answer
key in tests/test_key_writer_reviews_only_without_room.py, run here."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_writer_reviews_only_without_room import (  # noqa: F401
    CrossPairIsKept, NoOtherReviewerHasRoom, ResumeAfterPassedReview, ShortageEndsBeforeReview)

if __name__ == "__main__":
    unittest.main()
