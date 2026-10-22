"""`ak fetch` prints the path a model reads a file at: one already on this host, at once.

A file dragged into a session reaches the model as the Mac terminal wrote it: plain, quoted, or
with the shell's backslashes before each space.  When that names a file on this host, fetch
prints its absolute path and asks the Mac for nothing.  A Mac path the bridge never answers fails
after `AK_FETCH_TIMEOUT` with a sentence saying why, leaves no request behind for a bridge that
wakes later, and the other paths of the same call are still printed.  A path no file can have
(tabs, newlines, nothing) and a timeout that is not a number are refused in plain words.
Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, and
this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

MAC_FILE = "/Users/acme/Desktop/report.pdf"
NO_ANSWER = (f"ak fetch: {MAC_FILE}: no answer from the Mac bridge in 0s; the Mac may be asleep "
             "or offline, or ak macbridge is not running there (open ak on the Mac)\n")
BAD_PATH = "ak fetch: a file path must be non-empty and contain no tabs or newlines\n"
BAD_TIMEOUT = "ak fetch: AK_FETCH_TIMEOUT must be a finite, non-negative number\n"


def files(root):
    """Every file under `root` with what it holds."""
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


class Fetch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.cwd = cls.home.path / "code" / "acme"
        cls.report = cls.home.write("code/acme/a dir/r e.pdf", "%PDF-1.4\n")

    def fetch(self, *paths, env=None):
        return self.home.ak("fetch", *paths, env=env, cwd=self.cwd)

    def test_a_file_here_prints_its_absolute_path_however_it_was_quoted(self):
        for typed in ("a dir/r e.pdf", f"'{self.report}'",
                      str(self.report).replace(" ", "\\ ")):
            with self.subTest(typed=typed):
                before = files(self.home.path)
                done = self.fetch(typed)
                self.assertEqual((done.code, done.out, done.err), (0, f"{self.report}\n", ""))
                self.assertEqual(files(self.home.path), before)

    def test_a_path_with_a_tab_or_a_newline_or_nothing_is_refused(self):
        for typed in ("a\tb", "a dir\nr e.pdf", ""):
            with self.subTest(typed=typed):
                done = self.fetch(typed)
                self.assertEqual((done.code, done.out, done.err), (1, "", BAD_PATH))

    def test_a_mac_file_nobody_answers_for_fails_leaves_no_request_and_others_still_print(self):
        before = files(self.home.path)
        done = self.fetch(MAC_FILE, "a dir/r e.pdf", env={"AK_FETCH_TIMEOUT": "0"})
        self.assertEqual((done.code, done.out, done.err), (1, f"{self.report}\n", NO_ANSWER))
        self.assertEqual(files(self.home.path), before)

    def test_a_timeout_that_is_not_a_finite_non_negative_number_is_refused_before_any_path(self):
        for timeout in ("abc", "-1", "inf", "nan", ""):
            with self.subTest(timeout=timeout):
                before = files(self.home.path)
                done = self.fetch(MAC_FILE, "a dir/r e.pdf", env={"AK_FETCH_TIMEOUT": timeout})
                self.assertEqual((done.code, done.out, done.err), (2, "", BAD_TIMEOUT))
                self.assertEqual(files(self.home.path), before)


if __name__ == "__main__":
    unittest.main()
