"""ARCHITECTURE.md maps every module and every harness, and a new agent reads it in minutes.

A module under agentkit/ or a harness under adapters/ the map does not name is one a worker
meets with no summary of what it hides.  Offline: the files of this checkout.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
MAP = REPO / "ARCHITECTURE.md"


class Architecture(unittest.TestCase):
    def test_every_module_is_on_the_map(self):
        text = MAP.read_text()
        missing = [path.name for path in sorted((REPO / "agentkit").glob("*.py"))
                   if f"`{path.name}`" not in text]
        self.assertEqual(missing, [], "ARCHITECTURE.md does not map these agentkit/ modules")

    def test_every_harness_is_on_the_map(self):
        text = MAP.read_text()
        missing = [path.stem for path in sorted((REPO / "adapters").glob("*.toml"))
                   if f"`{path.stem}`" not in text]
        self.assertEqual(missing, [], "ARCHITECTURE.md does not map these adapters/ harnesses")

    def test_the_map_is_under_8_kb(self):
        self.assertLessEqual(len(MAP.read_bytes()), 8 * 1024)


class ArchitectureChecks(unittest.TestCase):
    def test_deleted_module_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix=".ak-test-architecture-", dir=REPO) as tmp:
            repo = Path(tmp)
            (repo / "agentkit").mkdir()
            (repo / "agentkit" / "present.py").touch()
            map_path = repo / "ARCHITECTURE.md"
            map_path.write_text("## agentkit/\n\n- `present.py`: present.\n"
                                "- `deleted.py`: stale entry.\n")
            result = unittest.TestResult()
            with patch.dict(globals(), REPO=repo, MAP=map_path):
                unittest.defaultTestLoader.loadTestsFromTestCase(Architecture).run(result)
            self.assertEqual(result.errors, [])
            self.assertEqual(len(result.failures), 1, "a stale module entry passed")
            self.assertIn("deleted.py", result.failures[0][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
