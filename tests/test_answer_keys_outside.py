"""Answer keys judge the program `AK_BIN` names from outside, so they outlive the Python they
were written against.  A key that imports an agentkit module, through a test module or fixture
it imports (their package's initializer included) or in a string it may hand a Python, tests
Python ak's insides even under Go.  `MAX` is the count of those keys: a key that stops lowers it,
and it never rises above `MAX` where the change left origin/main, as `test_boundaries.py`
compares its maxima; an unreadable target skips that comparison.  Offline: tests/ and git.
"""

import ast
import re
import unittest
from pathlib import Path

from test_boundaries import where_change_left_main

TESTS = Path(__file__).resolve().parent
MAX = 9
# Python code a key hands a Python as a string, which parsing the key reads as text only
IMPORT = re.compile(r"\b(from\s+agentkit[\s.]|import\s+([\w.]+\s*,\s*)*agentkit\b)")


def read(path, package):
    """Whether `path` imports agentkit, in its code or a string, and each module its imports
    run: importing `a.b.c` runs `a` and `a.b` first."""
    tree, found = ast.parse(path.read_text(), str(path)), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = ".".join(filter(None, [package if node.level else "", node.module or ""]))
            names = [f"{base}.{alias.name}" for alias in node.names]
        else:
            continue
        found.update(".".join(name.split(".")[:end]) for name in names
                     for end in range(1, name.count(".") + 2))
    handed = any(isinstance(node, ast.Constant) and isinstance(node.value, str)
                 and IMPORT.search(node.value) for node in ast.walk(tree))
    return "agentkit" in found or handed, found


class AnswerKeysOutside(unittest.TestCase):
    def test_max_keys_run_python_aks_insides(self):
        files = {path.stem: read(path, "") for path in TESTS.glob("*.py")}
        files.update({f"fixtures.{path.stem}".removesuffix(".__init__"): read(path, "fixtures")
                      for path in (TESTS / "fixtures").glob("*.py")})
        def inside(name, seen):
            holds, imports = files[name]
            seen.add(name)
            return holds or any(inside(dep, seen) for dep in imports
                                if dep in files and dep not in seen)

        found = sorted(name for name in files
                       if name.startswith("test_key_") and inside(name, set()))
        self.assertEqual(len(found), MAX, f"{len(found)} keys run Python ak's insides, MAX {MAX}: "
                         "a key judges ak from outside, and one that stops lowers MAX: "
                         + ", ".join(found))

    def test_max_never_rises_above_origin_main(self):
        source = where_change_left_main(self, "tests/test_answer_keys_outside.py")
        for node in ast.parse(source).body:
            if isinstance(node, ast.Assign) and any(getattr(target, "id", "") == "MAX"
                                                    for target in node.targets):
                self.assertLessEqual(MAX, ast.literal_eval(node.value),
                                     "MAX exceeds the MAX where this change left origin/main; "
                                     "it only goes down")


if __name__ == "__main__":
    unittest.main()
