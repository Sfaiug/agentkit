"""A trailing -free names a pricing tier: the model keeps its boards' rows.

Offline: the boards' rows are supplied, with invented models.
"""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import matrix


class FreeTierMatches(unittest.TestCase):
    def test_without_the_tier_the_model_keeps_its_name_version_and_qualifier_matches(self):
        for name, model in (("Acme 5", "acme/acme-5-free"), ("Acme Pro", "acme/acme-pro-1.0-free"),
                            ("Acme 5 (Default Fallback)", "acme/acme-5-free")):
            with self.subTest(name=name):
                hits = [{"model": name, "effort": "max", "values": {"aa.score": 70}}]
                self.assertEqual(matrix.found({matrix.normal(name): hits}, model), hits)


if __name__ == "__main__":
    unittest.main()
