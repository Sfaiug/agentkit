"""Go's tick has Python's passes, under Python's names and in Python's order, and lacks no more
of them than it did.

A pass missing from Go's table is neither run by a Go tick nor handed to Python: the tick skips it
without a word, and a pass Python gains later is skipped the same way.
"""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent
# Python's passes Go's table lacks, at most: a milestone that adds one lowers it; it never rises.
MISSING = 6


def rows(path, start, end, pattern):
    text = (ROOT / path).read_text(encoding="utf-8")
    body = text[text.index(start):]
    return re.findall(pattern, body[:body.index(end)], re.MULTILINE)


class GoTickRows(unittest.TestCase):
    def test_go_has_pythons_passes_in_order_and_lacks_no_more_of_them(self):
        python = rows("agentkit/watch.py", "def local_passes(", "\n    )\n",
                      r'^        \("([^"]+)"')
        go = rows("go/internal/tick/passes.go", "func table(", "\n}\n", r'^\t\t\{"([^"]+)"')
        self.assertGreater(len(go), 1, "no rows read from Go's table")
        self.assertEqual(go, [name for name in python if name in go],
                         "each of Go's rows is a pass of Python's, in Python's order")
        missing = [name for name in python if name not in go]
        self.assertLessEqual(len(missing), MISSING, f"Go's tick lacks {missing}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
