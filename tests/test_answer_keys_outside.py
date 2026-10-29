"""Answer keys judge the program `AK_BIN` names from outside, so they outlive the Python they
were written against.  A key whose text, or a test module or fixture it imports, holds an import
of an agentkit module, its own or in code it hands a Python, tests Python ak's insides even under
Go.  `MAX` counts those keys on the day this was written, and only goes down.  Offline: tests/.
"""

import ast
import re
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
MAX = 9
IMPORT = re.compile(r"\b(from agentkit[ .]|import agentkit\b)")


def read(path, package):
    """Whether `path` holds an agentkit import in its text, and the modules it imports."""
    text, found = path.read_text(), set()
    for node in ast.walk(ast.parse(text, str(path))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = ".".join(filter(None, [package if node.level else "", node.module or ""]))
            found.update([base, *(f"{base}.{alias.name}" for alias in node.names)])
    return bool(IMPORT.search(text)), found


class AnswerKeysOutside(unittest.TestCase):
    def test_no_more_keys_than_max_run_python_aks_insides(self):
        files = {path.stem: read(path, "") for path in TESTS.glob("*.py")}
        files.update({f"fixtures.{path.stem}": read(path, "fixtures")
                      for path in (TESTS / "fixtures").glob("*.py")})
        def inside(name, seen):
            holds, imports = files[name]
            seen.add(name)
            return holds or any(inside(dep, seen) for dep in imports
                                if dep in files and dep not in seen)

        found = sorted(name for name in files
                       if name.startswith("test_key_") and inside(name, set()))
        self.assertLessEqual(len(found), MAX, "keys running Python ak's insides: "
                             + ", ".join(found))
        if len(found) < MAX:
            print(f"{len(found)} keys run Python ak's insides: lower MAX to {len(found)}")


if __name__ == "__main__":
    unittest.main()
