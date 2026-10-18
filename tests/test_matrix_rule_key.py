"""A stored matrix computed by another version of matrix.py is computed again.

`matrix.refresh` reads the matrix as stored only while its `rule`, the hash of matrix.py that
computed it, is the running module's; after an upgrade that scores or reads the boards
differently the next pass recomputes it, so no pick or screen reads scores of a rule that is
gone, while the same module keeps the stored rows even where they differ from a fresh
computation, since the harness catalogs a computation asks take time."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures.sandbox import Sandbox
from agentkit import matrix
from test_model_rows import prepare

OTHER = {role: {"score": 1.0, "measures": 1} for role in matrix.ROLES}


class MatrixRuleKey(Sandbox):
    def setUp(self):
        super().setUp()
        prepare(self)

    def store_other_scores(self, **fields):
        """The stored matrix with every row scored 1.0, as another rule might, and `fields`."""
        cache = json.loads(matrix.cache_path().read_text())
        cache["matrix"].update(fields)
        for row in cache["matrix"]["rows"]:
            row["scores"] = dict(OTHER)
        matrix.cache_path().write_text(json.dumps(cache))

    def test_a_matrix_another_version_computed_is_computed_again(self):
        matrix.refresh(self.cfg, now=10000)
        self.assertEqual(matrix.stored()["rule"], matrix.rule())
        self.store_other_scores(rule="0" * 12)
        _, rows = matrix.refresh(self.cfg, now=20000)
        self.assertEqual(matrix.stored()["computed_at"], 20000)
        self.assertEqual(matrix.stored()["rule"], matrix.rule())
        self.assertTrue(any(found and found != OTHER["execute"]
                            for row in rows for found in (row.get("scores") or {}).values()))

    def test_the_same_version_reads_the_matrix_as_stored(self):
        matrix.refresh(self.cfg, now=10000)
        self.store_other_scores()
        _, rows = matrix.refresh(self.cfg, now=20000)
        self.assertEqual(matrix.stored()["computed_at"], 10000)
        self.assertTrue(all(row["scores"] == OTHER for row in rows))


if __name__ == "__main__":
    unittest.main()
