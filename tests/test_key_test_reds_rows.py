"""Named reds and flakes outlive a suite check in history.db.

Black-box: AK_BIN runs a round in a Home, with Rig, GitHub and fakeadapter.py;
the project's runner names its failed, flaky and executed tests through their files.
"""

import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig
from test_key_history_db import OWNERS, read

SUITE = 'export AK_SHARD; python3 suite.py'
RUNNER = """\
import os, subprocess, sys
from pathlib import Path
only = os.environ.get('AK_ONLY')
tests = Path(only).read_text().splitlines() if only else sorted(map(str, Path('tests').glob('*.py')))
k, n = map(int, os.environ.get('AK_SHARD', '1/1').split('/'))
ran, failed, flaky = [], [], []
for index, test in enumerate(tests):
    if not only and index % n != k - 1:
        continue
    ran.append(test)
    if subprocess.call([sys.executable, test]):
        (failed if subprocess.call([sys.executable, test]) else flaky).append(test)
for key, names in [('AK_RAN', ran), ('AK_FAILED', failed), ('AK_FLAKY', flaky)]:
    if os.environ.get(key):
        Path(os.environ[key]).write_text(''.join(name + '\\n' for name in names))
raise SystemExit(bool(failed))
"""
WEB = """\
from pathlib import Path
seen = Path('.web-seen')
failed = not seen.exists()
seen.touch()
raise SystemExit(failed)
"""


class SuiteRun:
    repo = "widgets"
    broken_history = False

    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, cls.repo, files={
            "AGENTS.md": f"---\ntests: {SUITE}\n---\n# widgets\n", "suite.py": RUNNER,
            ".gitignore": ".web-seen\n", "tests/test_api.py": "raise SystemExit(1)\n",
            "tests/test_web.py": WEB, "tests/test_ok.py": "raise SystemExit(0)\n"})
        GitHub(cls.home).grant(cls.rig.slug, "WRITE")
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        if cls.broken_history:
            (cls.home.path / ".agentkit/history.db").mkdir()
        task = taskfile.write(cls.home, cls.rig.path, "Record failing tests",
                              done_when=(SUITE,), front={"rounds": 1})
        cls.done = cls.home.ak("run", str(task), "--no-merge", env=OWNERS, timeout=300)
        cls.run_dir = taskfile.only_run(cls.home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())


class TestReds(SuiteRun, unittest.TestCase):
    def test_a_failed_round_keeps_both_named_outcomes_and_no_passing_tests(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(self.state["state"], "fail")
        rows = read(self.home, "SELECT * FROM test_reds")
        self.assertEqual({(row["test"], row["flaky"]) for row in rows},
                         {("tests/test_api.py", 0), ("tests/test_web.py", 1)})

    def test_each_row_names_its_round_s_check_and_tree_after_the_piece_ends(self):
        rows = read(self.home, "SELECT * FROM test_reds")
        self.assertTrue(rows)
        checks = read(self.home, "SELECT * FROM checks WHERE kind='done-when'")
        for row in rows:
            self.assertEqual((row["run_id"], row["round"], row["kind"]),
                             (self.run_dir.name, 1, "done-when"))
            matching = [check for check in checks if all(check[key] == row[key]
                        for key in ("run_id", "round", "kind", "tree"))]
            self.assertTrue(matching, row)
            self.assertTrue(row["tree"], row)
            self.assertGreaterEqual(row["at"], min(check["finished_at"] for check in matching))
            self.assertLessEqual(row["at"], self.state["finished_at"])


class Sandbox(SuiteRun, unittest.TestCase):
    repo = "agentkit-smoke"

    def test_a_sandbox_keeps_no_test_rows(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(read(self.home, "SELECT * FROM test_reds"), [])


class UnwritableHistory(SuiteRun, unittest.TestCase):
    broken_history = True

    def test_history_cannot_change_the_round_s_result(self):
        self.assertEqual(self.done.code, 1, self.done.out + self.done.err)
        self.assertEqual(self.state["state"], "fail")
        self.assertTrue((self.home.path / ".agentkit/history.db").is_dir())


if __name__ == "__main__":
    unittest.main()
