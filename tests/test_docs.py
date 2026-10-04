"""The docs say what the product is, in the fewest words.

README.md and docs/guide.md stay within origin/main's word limits and are free of every
word for a state or a remedy that no longer exists, `ak --help` fits one screen, and the
README lists the menu's keys and says what each state means in the words the key line
says it in. Offline: files and rendered text.
"""

import ast
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agentkit import command_help, menu, terminal  # noqa: E402

README = REPO / "README.md"
GUIDE = REPO / "docs/guide.md"
DESIGN = REPO / "docs/cli-design.md"
# Leave room for align-ak's ol1 and lv1 runs; its one-page README rewrite lowers this.
WORD_LIMITS = {"README.md": 6_200, "docs/guide.md": 15_300}
# States, remedies and screens that are gone: a doc that names one describes an older product.
# The last is the personal account name, built without writing it, as test_open_gates builds it.
REMOVED = ("resumable", "starts fresh", "draft unsent", "needs a look", "press r",
           "merge turn", "merge-turn", "merge queue", "first to merge",
           "".join(chr(c) for c in (83, 102, 97, 105, 117, 103)))
# The one place that name belongs: the README's install line, a clone a stranger can run as is.
CLONE = f"git clone https://github.com/{REMOVED[-1]}/agentkit ~/agentkit && ~/agentkit/install.sh\n"


def word_limits():
    # Main grants the budget; literal parsing keeps its test code out of this run.
    proc = subprocess.run(["git", "-C", str(REPO), "show", "origin/main:tests/test_docs.py"],
                          capture_output=True, text=True)
    if proc.returncode == 0:
        for node in ast.parse(proc.stdout).body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "WORD_LIMITS"
                    for target in node.targets):
                return WORD_LIMITS | ast.literal_eval(node.value)
    return WORD_LIMITS


class Docs(unittest.TestCase):
    def assert_word_limit(self, path):
        name = path.relative_to(REPO).as_posix()
        limit = word_limits()[name]
        self.assertLessEqual(len(path.read_text().split()), limit,
                             f"{name}: word limit {limit} (origin/main when present)")

    def assert_current(self, path, text=None):
        text = path.read_text() if text is None else text
        for word in REMOVED:
            self.assertNotIn(word, text, f"{path.name} still says {word!r}")

    def test_readme_is_one_page(self):
        self.assert_word_limit(README)
        self.assertTrue(README.read_text().startswith("# agentkit\n"))

    def test_readme_names_no_removed_state_word(self):
        text = README.read_text()
        self.assertEqual(text.count(CLONE), 1, "README.md lacks the one real install line")
        self.assert_current(README, text.replace(CLONE, ""))

    def test_guide_is_short_and_current(self):
        self.assert_word_limit(GUIDE)
        self.assert_current(GUIDE)
        self.assertTrue(GUIDE.read_text().startswith("# How agentkit works\n"))

    def test_design_doc_names_no_removed_state_word(self):
        self.assert_current(DESIGN)

    def test_design_doc_drops_removed_model_setting(self):
        self.assertFalse("Reviews its own company" in " ".join(DESIGN.read_text().split()),
                         "model screen still documents a removed self-review row")

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
            self.assertIn(terminal.TIPS[word].split(": ", 1)[1], page, word)

    def test_superseded_evidence_is_gone(self):
        self.assertFalse((REPO / "docs/verification-v4l-2.md").exists())


class DocsChecks(unittest.TestCase):
    def check(self, name, words, source="", limits=None):
        heading = "# agentkit\n" if name == "README.md" else "# How agentkit works\n"
        text = heading + "word " * (words - len(heading.split()))
        method = ("test_readme_is_one_page" if name == "README.md"
                  else "test_guide_is_short_and_current")
        proc = subprocess.CompletedProcess([], 0, source, "")
        result = unittest.TestResult()
        with patch.dict(globals(), WORD_LIMITS=WORD_LIMITS if limits is None else limits), \
                patch.object(Path, "read_text", return_value=text), \
                patch.object(subprocess, "run", return_value=proc) as git:
            Docs(method).run(result)
        return result, git

    def test_joining_lines_cannot_evade_word_limits(self):
        for name, limit in WORD_LIMITS.items():
            with self.subTest(doc=name):
                result, _ = self.check(name, limit + 1)
                self.assertEqual(result.errors, [])
                self.assertEqual(len(result.failures), 1, "a long doc with few lines passed")

    def test_raising_a_branch_limit_cannot_evade_main(self):
        for name, limit in WORD_LIMITS.items():
            with self.subTest(doc=name):
                source = f"raise AssertionError('target code ran')\nWORD_LIMITS = {WORD_LIMITS!r}\n"
                result, git = self.check(name, limit + 1, source,
                                         {**WORD_LIMITS, name: limit + 100})
                self.assertEqual(result.errors, [])
                self.assertEqual(len(result.failures), 1, "a raised branch limit passed")
                git.assert_called_once_with(
                    ["git", "-C", str(REPO), "show", "origin/main:tests/test_docs.py"],
                    capture_output=True, text=True)

    def test_raising_only_a_limit_passes(self):
        for name, limit in WORD_LIMITS.items():
            with self.subTest(doc=name):
                result, _ = self.check(name, limit, f"WORD_LIMITS = {WORD_LIMITS!r}\n",
                                       {**WORD_LIMITS, name: limit + 100})
                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)

    def test_a_limit_missing_on_main_uses_the_branch(self):
        for name, limit in WORD_LIMITS.items():
            with self.subTest(doc=name):
                other = {key: value for key, value in WORD_LIMITS.items() if key != name}
                source = f"WORD_LIMITS = {other!r}\n"
                result, _ = self.check(name, limit, source)
                self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
                result, _ = self.check(name, limit + 1, source)
                self.assertEqual(result.errors, [])
                self.assertEqual(len(result.failures), 1, "a new word limit was ignored")


if __name__ == "__main__":
    unittest.main(verbosity=2)
