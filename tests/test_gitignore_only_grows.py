"""No `.gitignore` pattern on origin/main goes: a removed pattern leaves its matches untracked
on every live checkout, where they stop `go_live` pulling.  Compared with where the change left
origin/main, as `test_boundaries.py` compares its maxima; an unreadable target skips it.
Offline: git over this checkout.
"""

import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def removed(before, after):
    """The patterns `before` holds and `after` does not; comments and blank lines are none."""
    def patterns(text):
        return {line.strip() for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("#")}
    return sorted(patterns(before) - patterns(after))


class GitignoreOnlyGrows(unittest.TestCase):
    def test_a_removed_pattern_is_named_and_a_moved_or_added_one_is_not(self):
        self.assertEqual(removed("# build\n*.pyc\n.ak-test-*\n", ".ak-test-*\n# kept\n*.pyc\n.cache/\n"), [])
        self.assertEqual(removed("*.pyc\n.ak-test-*\n", "*.pyc\n"), [".ak-test-*"])

    def test_no_pattern_on_origin_main_is_removed(self):
        base = subprocess.run(["git", "-C", str(REPO), "merge-base", "HEAD", "origin/main"],
                              capture_output=True, text=True).stdout.strip() or "origin/main"
        proc = subprocess.run(["git", "-C", str(REPO), "show", f"{base}:.gitignore"],
                              capture_output=True, text=True)
        if proc.returncode:
            print("origin/main:.gitignore is not readable; skipping the comparison")
            self.skipTest("origin/main is not readable")
        gone = removed(proc.stdout, (REPO / ".gitignore").read_text())
        self.assertEqual(gone, [], "a .gitignore pattern on origin/main was removed; its matches "
                                   "would turn untracked on every live checkout and stop its pulls: keep it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
