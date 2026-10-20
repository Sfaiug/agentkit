"""A trailing -free names a pricing tier: the model keeps its boards' rows without a benchmark.

Offline: the boards' rows and harness catalog are supplied, with an invented model and config.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, matrix


class FreeTierMatches(unittest.TestCase):
    def test_the_free_tier_carries_every_board_s_values_at_every_listed_effort(self):
        cfg = {"providers": {"acme": {}}, "models": {
            "acme-free": {"harness": "acme", "provider": "acme",
                          "model": "acme/acme-5-free", "effort": "max"}}}
        catalog = [{"id": model, "efforts": ["high", "max"]} for model in
                   ("acme/acme-5-free", "acme/acme-6-free", "acme/acme-5")]
        boards = {
            "artificialanalysis.ai": {"rows": [
                {"model": "Acme 5", "effort": "max", "values": {"aa.score": 70}},
                {"model": "Acme 5", "effort": "high", "values": {"aa.score": 60}}]},
            "arena.ai": {"rows": [
                {"model": "Acme-5", "effort": "max", "values": {"arena.agent_task_outcome_explicit": 0.3}},
                {"model": "Acme-5", "effort": "high", "values": {"arena.agent_task_outcome_explicit": 0.2}}]},
            "livebench.ai": {"rows": [
                {"model": "acme-5", "effort": None, "values": {"livebench.coding": 80}}]}}
        with patch.object(config, "catalog", return_value=catalog):
            rows = {(row["model"], row["effort"]): row
                    for row in matrix.rows(cfg, boards, ["acme"])}
        self.assertEqual(set(rows), {
            ("acme/acme-5-free", "max"), ("acme/acme-5-free", "high"),
            ("acme/acme-5", "max"), ("acme/acme-5", "high"), ("acme/acme-6-free", None)})
        for effort, aa, arena in (("max", 70, 0.3), ("high", 60, 0.2)):
            for model in ("acme/acme-5-free", "acme/acme-5"):
                with self.subTest(model=model, effort=effort):
                    row = rows[model, effort]
                    self.assertEqual(row["values"],
                                     {"aa.score": aa, "arena.agent_task_outcome_explicit": arena, "livebench.coding": 80})
                    self.assertEqual(row["matched"], {
                        "artificialanalysis.ai": {"model": "Acme 5", "effort": effort},
                        "arena.ai": {"model": "Acme-5", "effort": effort},
                        "livebench.ai": {"model": "acme-5", "effort": None}})
        self.assertEqual(rows["acme/acme-5-free", "max"]["name"], "acme-free")
        self.assertEqual(rows["acme/acme-6-free", None]["values"], {})
        self.assertEqual(rows["acme/acme-6-free", None]["matched"], {})

    def test_without_the_tier_the_model_keeps_its_version_and_qualifier_matches(self):
        for name, model in (("Acme Pro", "acme/acme-pro-1.0-free"),
                            ("Acme 5 (Default Fallback)", "acme/acme-5-free")):
            with self.subTest(name=name):
                hits = [{"model": name, "effort": "max", "values": {"aa.score": 70}}]
                self.assertEqual(matrix.found({matrix.normal(name): hits}, model), hits)


if __name__ == "__main__":
    unittest.main()
