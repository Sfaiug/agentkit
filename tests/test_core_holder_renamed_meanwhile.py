"""A seat renamed while `ak run status` reads who holds a core is named once, not under both names."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import cores


class ACoreHolderRenamedMeanwhile(unittest.TestCase):
    def test_two_scopes_of_one_seat_renamed_between_them_are_one_row(self):
        state = {"seat_cores": {
            "agentkit-seat-fix-api-89abcdef.scope": {"at": 720, "since": 180},
            "agentkit-seat-fix-api-0123abcd.scope": {"at": 720, "since": 360}}}
        with patch.object(cores.front, "seat_now", side_effect=["fix-api", "parser"]):
            held = cores.holding(state)
        self.assertEqual(held, [("fix-api", 540)])


if __name__ == "__main__":
    unittest.main()
