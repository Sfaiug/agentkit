"""ARCHITECTURE.md maps every module and every harness, and a new agent reads it in minutes.

A module under agentkit/ or a harness under adapters/ the map does not name is one a worker
meets with no summary of what it hides. Every mapped module must also exist as a file,
and its entry is at most 400 characters with whitespace collapsed.
Offline: the files of this checkout.
"""

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
MAP = REPO / "ARCHITECTURE.md"


class Architecture(unittest.TestCase):
    def test_every_module_is_on_the_map(self):
        text = MAP.read_text()
        modules = {path.name for path in (REPO / "agentkit").glob("*.py") if path.is_file()}
        mapped = set(re.findall(r"(?m)^- `([^`/]+\.py)`:", text))
        self.assertEqual(mapped, modules, "ARCHITECTURE.md must map exactly the agentkit/ modules")

    def test_every_harness_is_on_the_map(self):
        text = MAP.read_text()
        missing = [path.stem for path in sorted((REPO / "adapters").glob("*.toml"))
                   if f"`{path.stem}`" not in text]
        self.assertEqual(missing, [], "ARCHITECTURE.md does not map these adapters/ harnesses")

    def test_each_module_entry_is_short(self):
        # Markdown's lazy continuations belong to the bullet even without indentation.
        for entry in re.finditer(r"(?m)^- `([^`/]+\.py)`:[^\n]*"
                                 r"(?:\n(?![ \t]*$|[-*+](?:[ \t]|$)|#{1,6}(?:[ \t]|$))[^\n]+)*",
                                 MAP.read_text()):
            with self.subTest(module=entry[1]):
                self.assertLessEqual(len(" ".join(entry.group().split())), 400,
                                     f"{entry[1]} entry exceeds 400 characters")


class ArchitectureChecks(unittest.TestCase):
    def check(self, text, modules=("present.py",)):
        with tempfile.TemporaryDirectory(prefix=".ak-test-architecture-", dir=REPO) as tmp:
            repo = Path(tmp)
            (repo / "agentkit").mkdir()
            for name in modules:
                (repo / "agentkit" / name).touch()
            map_path = repo / "ARCHITECTURE.md"
            map_path.write_text(text)
            result = unittest.TestResult()
            with patch.dict(globals(), REPO=repo, MAP=map_path):
                unittest.defaultTestLoader.loadTestsFromTestCase(Architecture).run(result)
        return result

    def test_deleted_module_is_rejected(self):
        result = self.check("## agentkit/\n\n- `present.py`: present.\n"
                            "- `deleted.py`: stale entry.\n")
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.failures), 1, "a stale module entry passed")
        self.assertIn("deleted.py", result.failures[0][1])

    def test_a_401_character_entry_is_rejected(self):
        prefix = "- `present.py`: "
        for separator in (" ", "\n\t  ", "\n"):
            with self.subTest(separator=separator):
                result = self.check(prefix + "x" * (401 - len(prefix) - 2) + separator + "y\n")
                self.assertEqual(result.errors, [])
                self.assertEqual(len(result.failures), 1, "a 401-character entry passed")
                self.assertIn("present.py", result.failures[0][1])

    def test_400_characters_with_collapsed_whitespace_pass(self):
        prefix = "- `present.py`: "
        for separator in ("\n\t  ", "\n"):
            with self.subTest(separator=separator):
                result = self.check(prefix + "é" * (400 - len(prefix) - 2) + separator + "y\n")
                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)

    def test_other_blocks_do_not_extend_a_module_entry(self):
        for boundary in ("\n\n", "\n## Other\n", "\n- Other: ", "\n* Other: ", "\n+ Other: "):
            with self.subTest(boundary=boundary):
                result = self.check("- `present.py`: short." + boundary + "x" * 600 + "\n")
                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)

    def test_many_short_entries_can_exceed_8_kb(self):
        modules = tuple(f"module_{number}.py" for number in range(30))
        text = "\n".join(f"- `{name}`: " + "x" * 280 for name in modules)
        self.assertGreater(len(text.encode()), 8 * 1024)
        result = self.check(text, modules)
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)


if __name__ == "__main__":
    unittest.main(verbosity=2)
