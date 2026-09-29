"""ARCHITECTURE.md maps every module and every harness, and a new agent reads it in minutes.

A module under agentkit/ or a harness under adapters/ the map does not name is one a worker
meets with no summary of what it hides.  Offline: the files of this checkout.
"""

import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
