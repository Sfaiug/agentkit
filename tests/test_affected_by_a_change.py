"""tests/affected.py lists the tests a change can affect.

Offline: it chooses on a temporary repository of stand-in modules, test files and a smoke
script, the change one commit or more over its target; no suite runs.
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import affected
from suite_shares import SETUP, STATIC_CHECKS

SMOKE = affected.SMOKE
STATIC = [f"tests/{name}.py" for name in STATIC_CHECKS]
# The repository's root is the package acme.
BASE = {
    "__init__.py": "",
    "paybook.py": "def total(n):\n    return n * 2\n\n\ndef pay_slip():\n    return 0\n",
    "ledger.py": "from paybook import total\n",
    "install.sh": "echo installed\n",
    # Nothing names discount, only the function it holds.
    "discount.py": "def markdown(n):\n    return n\n",
    "tests/test_paybook.py": "print('TESTS_RUN=1')\n",
    "tests/test_invoice.py": "from acme.paybook import total\n",
    "tests/test_ledger.py": "import ledger\n",
    "tests/test_pay_book_screen.py": "# bin/acme draws the screen\n",
    "tests/test_receipt.py": "# the receipt adds up to its total\n",
    "tests/test_payslip.py": "# payslip() says nothing\n",
    "tests/test_install.py": "# install.sh in a sandbox HOME\n",
    "tests/test_unrelated.py": "print('TESTS_RUN=1')\n",
    "tests/test_sale.py": "# a sale takes markdown() off\n",
    # 1 is a live check, which the landing suite never runs.
    SMOKE: f"REPO=.\n{SETUP}# --- 1: the live paybook\nbin/acme paybook\n"
           '# --- 7: invoices\npython3 "$REPO/tests/test_invoice.py"\n'
           "# --- acme: the paybook\nbin/acme paybook\n# --- 9: sale\necho markdown\n"
           "# --- 27: install roles\nbash install.sh --client\n# --- fix_api: other\necho fine\n",
}


class AffectedByAChange(unittest.TestCase):
    def chosen(self, *commits, target="target"):
        """What `affected.selection` lists for `commits`, each a commit's edits, over BASE."""
        tmp = tempfile.TemporaryDirectory(prefix="ak-test-affected-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "acme"
        root.mkdir()
        git = lambda *args: subprocess.run(
            ["git", "-c", "user.name=acme", "-c", "user.email=acme@example.invalid",
             "-c", "commit.gpgsign=false", *args], cwd=root, check=True, capture_output=True)
        git("init", "-q")
        for files in (BASE, *commits):
            for path, text in files.items():
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text(text)
            git("add", "-A")
            git("commit", "-q", "-m", "change")
            if files is BASE:
                git("branch", "target")
        return affected.selection(root, {path for files in commits for path in files}, target)

    def test_a_changed_module_selects_its_tests_importers_and_mentioners(self):
        for edits, chosen in (
                # test_ledger.py calls `total` through ledger.py; smoke.sh's 7 runs
                # test_invoice.py.
                ({"paybook.py": BASE["paybook.py"].replace("n * 2", "n * 3")}, [
                    "tests/test_invoice.py", "tests/test_ledger.py",
                    "tests/test_pay_book_screen.py", "tests/test_paybook.py",
                    "tests/test_receipt.py", f"{SMOKE}#7", f"{SMOKE}#acme"]),
                ({"__init__.py": '"""The acme shop."""\n'}, [
                    "tests/test_invoice.py", "tests/test_pay_book_screen.py", f"{SMOKE}#7",
                    f"{SMOKE}#acme"]),
                ({"discount.py": BASE["discount.py"].replace("n\n", "n - 1\n")},
                 ["tests/test_sale.py", f"{SMOKE}#9"])):
            with self.subTest(edits):
                self.assertEqual(self.chosen(edits), STATIC + chosen)

    def test_a_changed_leaf_test_selects_itself_and_the_static_checks(self):
        for edits, chosen in (
                # Nothing loads names from a test file: test_ledger.py's `ledger` is another
                # one.
                ({"tests/test_receipt.py": "ledger = 'its total, rounded'\n"},
                 ["tests/test_receipt.py"]),
                ({SMOKE: BASE[SMOKE].replace("echo fine", "echo finer")}, [f"{SMOKE}#fix_api"]),
                # Every block runs after the shared setup.
                ({SMOKE: BASE[SMOKE].replace("REPO=.", "REPO=$PWD")},
                 [f"{SMOKE}#{check}" for check in ("27", "7", "9", "acme", "fix_api")])):
            with self.subTest(edits):
                self.assertEqual(self.chosen(edits), STATIC + chosen)

    def test_a_path_no_module_holds_selects_the_tests_mentioning_it(self):
        self.assertEqual(self.chosen({"install.sh": "echo installed twice\n"}),
                         STATIC + ["tests/test_install.py", f"{SMOKE}#27"])

    def test_the_suite_s_machinery_or_no_base_selects_everything(self):
        for path in sorted(affected.MACHINERY):
            with self.subTest(path):
                self.assertIsNone(self.chosen({path: "# changed\n"}))
        self.assertIsNone(self.chosen({"install.sh": "echo\n"}, target="no-such-target"))

    def test_a_name_changed_in_an_earlier_commit_is_still_found(self):
        # test_payslip.py writes `pay_slip` as one word.
        self.assertEqual(self.chosen(
            {"paybook.py": BASE["paybook.py"].replace("return 0", "return 1")},
            {"tests/test_unrelated.py": "# changed\n"}), STATIC + [
            "tests/test_invoice.py", "tests/test_pay_book_screen.py", "tests/test_paybook.py",
            "tests/test_payslip.py", "tests/test_unrelated.py", f"{SMOKE}#7", f"{SMOKE}#acme"])


if __name__ == "__main__":
    unittest.main()
