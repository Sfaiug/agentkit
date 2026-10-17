"""The live contract's resume reads the filename bare, in backticks or as a Markdown link's text."""

from pathlib import Path
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import check_harness_contract as contract


class RecalledTest(unittest.TestCase):
    def test_names_the_file(self):
        for reply in ("hello-1.txt", "`hello-1.txt`", "[hello-1.txt](file:///x/hello-1.txt)",
                      "\n[hello-1.txt](file:///x/hello-1.txt)\n"):
            with self.subTest(reply=reply):
                self.assertTrue(contract.recalled(reply, "hello-1.txt"))

    def test_names_another_file_or_none(self):
        for reply in ("hello-2.txt", "", "  \n", "`hello-1.txt", "hello-1xtxt",
                      "[hello-2.txt](file:///x/hello-1.txt)", "hello-1.txt.bak"):
            with self.subTest(reply=reply):
                self.assertFalse(contract.recalled(reply, "hello-1.txt"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
