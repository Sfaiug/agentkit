"""The docs say what the product is, in the fewest words.

README.md is one page a stranger understands, docs/guide.md is under 400 lines and free of
every word for a state or a remedy that no longer exists, `ak --help` fits one screen, and
the README lists the menu's keys and says what each state means in the words the key line
says it in.  Offline: files and rendered text.
"""

import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agentkit import command_help, menu, terminal  # noqa: E402

README = REPO / "README.md"
GUIDE = REPO / "docs/guide.md"
DESIGN = REPO / "docs/cli-design.md"
# States, remedies and screens that are gone: a doc that names one describes an older product.
# The last is the personal account name, built without writing it, as test_open_gates builds it.
REMOVED = ("resumable", "starts fresh", "draft unsent", "needs a look", "press r",
           "".join(chr(c) for c in (83, 102, 97, 105, 117, 103)))
# The one place that name belongs: the README's install line, a clone a stranger can run as is.
CLONE = f"git clone https://github.com/{REMOVED[-1]}/agentkit ~/agentkit && ~/agentkit/install.sh\n"


def lines(path):
    return path.read_text().splitlines()


class Docs(unittest.TestCase):
    def assert_current(self, path, text=None):
        text = path.read_text() if text is None else text
        for word in REMOVED:
            self.assertNotIn(word, text, f"{path.name} still says {word!r}")

    def test_readme_is_one_page(self):
        self.assertLessEqual(len(lines(README)), 120)
        self.assertTrue(README.read_text().startswith("# agentkit\n"))

    def test_readme_names_no_removed_state_word(self):
        text = README.read_text()
        self.assertEqual(text.count(CLONE), 1, "README.md lacks the one real install line")
        self.assert_current(README, text.replace(CLONE, ""))

    def test_guide_is_short_and_current(self):
        self.assertLessEqual(len(lines(GUIDE)), 400)
        self.assert_current(GUIDE)
        self.assertTrue(GUIDE.read_text().startswith("# How agentkit works\n"))

    def test_design_doc_names_no_removed_state_word(self):
        self.assert_current(DESIGN)

    def test_help_fits_one_screen(self):
        proc = subprocess.run([sys.executable, str(REPO / "bin/ak"), "--help"],
                              capture_output=True, text=True, timeout=30,
                              env={**os.environ, "NO_COLOR": "1"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = proc.stdout
        self.assertLessEqual(len(text.splitlines()), 40)
        self.assertTrue(text.startswith("usage: ak "), text)
        self.assertIn("  ak       the menu\n", text)
        for name in command_help.ORCHESTRATOR:
            self.assertRegex(text, rf"(?m)^  {name} +\S")
        internal = [line for line in text.splitlines() if line.startswith("internal:")]
        self.assertEqual(len(internal), 1, text)
        for name in command_help.INTERNAL:
            self.assertIn(f" {name}", internal[0])
            self.assertNotIn(f"\n  {name} ", text)

    def test_readme_lists_the_keys_and_says_each_state_as_the_key_line_does(self):
        page = README.read_text()
        for key, _ in terminal.key_parts(menu.KEYS + "   s solo"):
            self.assertRegex(page, rf"(?m)^{re.escape(key)} +\S", f"README.md lacks `{key}`")
        self.assertNotRegex(page, r"(?m)^i +\S")
        for word in menu.STATE_ORDER:
            self.assertIn(menu.TIPS[word].split(": ", 1)[1], page, word)

    def test_superseded_evidence_is_gone(self):
        self.assertFalse((REPO / "docs/verification-v4l-2.md").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
