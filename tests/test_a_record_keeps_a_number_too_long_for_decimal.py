"""A run's record keeps a POLICY number past the digits Python writes in decimal, as config.toml
takes one (`config.whole`), and the run holds to that number (`record.kept_policy`)."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentkit import config, record, transitions


class LongNumber(unittest.TestCase):
    def test_a_record_keeps_a_number_too_long_for_decimal_and_the_run_holds_to_it(self):
        # 4300, Python's own most (sys.get_int_max_str_digits), whatever this test's caller holds
        self.addCleanup(sys.set_int_max_str_digits, sys.get_int_max_str_digits())
        sys.set_int_max_str_digits(4300)
        held = 10 ** 4300
        numbers = config.host_policy({"extra_rounds": held, "rescope_findings": held})
        with tempfile.TemporaryDirectory() as tmp:
            record.save_state(Path(tmp), {"policy": numbers})
            state = record.read_state(Path(tmp))
        json.dumps(state)       # a screen's census of records writes each one again
        self.assertEqual(record.policy_of(state), numbers)
        state["round_summaries"] = [{"finding_count": 1}] * numbers["review_rounds"]
        self.assertIsNone(transitions.rescope(state, 10 ** 6))
        self.assertTrue(transitions.extra_round(state, numbers["review_rounds"] + 1))


if __name__ == "__main__":
    unittest.main()
