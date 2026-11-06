"""A part of a test file keeps the seconds a check printed for it, `PASS  <file>::<part> (<s>s)`
(tests/every_file.py), in the record that cuts the next suite while the checkout has the file;
`ak run status --tests` lists it.  Black-box: `AK_BIN` runs through tests/fixtures/akbin.py, on
a project from gitrig.py, with scripted harnesses from fakeadapter.py.
"""

import shlex
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

PRINTED = ("PASS  tests/test_acme.py (3.0s)", "PASS  tests/test_acme.py::fix_api (12.0s)",
           "PASS  tests/test_gone.py::widget (5.0s)")


class PartTimesKept(unittest.TestCase):
    def test_a_part_of_a_file_the_checkout_has_is_kept_and_listed(self):
        with Home() as home:
            rig = Rig(home, "widgets", files={"tests/test_acme.py": 'print("TESTS_RUN=1")\n'})
            akconfig.write(home, ["opus", "astra"])
            fakeadapter.install(home, claude="work", codex="pass")
            task = taskfile.write(home, rig.path, done_when=(
                "test -f retry.txt", f"printf '%s\\n' {shlex.join(PRINTED)}"))
            done = home.ak("run", str(task), "--no-merge", timeout=300)
            self.assertEqual(done.code, 0, done.out + done.err)
            listed = home.ak("run", "status", "--tests", cwd=rig.path, env={"COLUMNS": "120"})
            self.assertEqual(listed.code, 0, listed.err)
            rows = {cells[0]: cells[1] for line in listed.out.splitlines()
                    if (cells := line.split()) and cells[0].startswith("tests/")}
            # test_gone.py is no file of the checkout: its part leaves the record.
            self.assertEqual(rows, {"tests/test_acme.py": "3.0s",
                                    "tests/test_acme.py::fix_api": "12.0s"})


if __name__ == "__main__":
    unittest.main()
