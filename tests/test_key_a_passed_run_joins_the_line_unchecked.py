"""A run that passes review joins its landing line at once, rebased onto its target, unchecked:
the line's check is the one check of its tree before it merges.

A run passing review waits in the line with no `landing` row of its own before the line's check
of its tree, which leaves that tree's one row, written as it starts; a red the line finds still
hands the run a fixer, and the run rejoins and merges; a target missing on origin ends the run as
a delivery failure, never a run waiting in the line.  Black-box: the program `AK_BIN` names runs tasks from outside
through tests/fixtures/akbin.py on the project and suite of tests/fixtures/akline.py, unsplit,
whose line the run starts itself, with harnesses from fakeadapter.py and the GitHub of
fakegh.py; the ledger is read back from the Home's history.db.
"""

import contextlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akline import READINGS, Line, rules
from fixtures.fakegh import GitHub

SUITE = "sh suite.sh"
# The line's first check waits here until the test lets it go.
HELD = 'own="$(git rev-parse --git-common-dir)"\n: >"$own/held"\n' \
       'until [ -f "$own/go" ]; do sleep 0.1; done\n'


def staged(case, tests, claude="work"):
    """A Line's project, its suite unsplit with `tests`, a writer scripted by `claude`."""
    line = Line({"AGENTS.md": rules(SUITE), **tests})
    case.addCleanup(line.close)
    # the Home's notify sink marks a run a suite's, which history never records: the owner's
    line.home.env.update(AK_HOST_READINGS=READINGS, AK_NOTIFY_SINK=None)
    GitHub(line.home).grant(line.rig.slug, "WRITE")
    akconfig.write(line.home, ["opus", "astra"])
    case.fakes = fakeadapter.install(line.home, claude=claude, codex="pass")
    return line


def landing(line, run):
    """`run`'s `landing` rows in the ledger, oldest first: (tree, exit)."""
    with contextlib.closing(sqlite3.connect(line.home.path / ".agentkit" / "history.db")) as db:
        return db.execute("SELECT tree, exit FROM checks WHERE run_id=? AND kind='landing' "
                          "ORDER BY rowid", (run.name,)).fetchall()


def record(run):
    return json.loads((run / "run.json").read_text())


class PassedRunJoinsUnchecked(unittest.TestCase):
    def test_it_waits_in_line_unchecked_and_the_lines_check_leaves_the_trees_one_row(self):
        line = staged(self, {"t/held.sh": HELD, "t/ok.sh": "true\n"})
        own = line.rig.path / ".git"
        ran = line.home.spawn("run", str(taskfile.write(line.home, line.rig.path)))
        deadline = time.monotonic() + 300
        while not (own / "held").exists():
            self.assertLess(time.monotonic(), deadline, "the line never checked the run")
            self.assertIsNone(ran.poll(), line.home.log("spawn-1.err").read_text())
            time.sleep(0.1)
        run = taskfile.only_run(line.home)
        state = record(run)
        self.assertEqual((state["state"], state["review"]["verdict"]), ("waiting", "PASS"))
        self.assertEqual(set(state["waiting_on"]), {"line", "joined"})
        # the line's check, under way, is the only one: a row is written as a check starts
        (tree, code), = landing(line, run)
        self.assertIsNone(code)
        (own / "go").touch()
        self.assertEqual(ran.wait(timeout=300), 0, line.home.log("spawn-1.err").read_text())
        self.assertTrue(record(run).get("merged"))
        self.assertEqual((line.whole(), landing(line, run)), (1, [(tree, 0)]))
        self.assertEqual(line.rig.git("rev-parse", f"{tree}^"), line.base)

    def test_a_red_in_the_line_hands_the_run_a_fixer_and_it_merges_after(self):
        work = {**fakeadapter.WORK, "write": {"retry.txt": "hello\n", "bad.txt": "x\n"}}
        fix = {"sh": "git rm -q bad.txt", "commit": "remove bad.txt",
               "final": "## Summary\nremoved bad.txt", "hand_in": [["done"]]}
        line = staged(self, {"t/ok.sh": "true\n", "t/bad.sh": "test ! -f bad.txt\n"},
                      claude=[work, fix])
        done = line.home.ak("run", str(taskfile.write(line.home, line.rig.path)), timeout=600)
        self.assertEqual(done.code, 0, done.out + done.err)
        run = taskfile.only_run(line.home)
        self.assertTrue(record(run).get("merged"))
        self.assertEqual([turn["role"] for turn in self.fakes["claude"].runs()],
                         ["executor", "fixer"])
        rows = landing(line, run)
        trees = list(dict.fromkeys(tree for tree, _ in rows))
        self.assertEqual(len(trees), 2, rows)
        self.assertNotIn(0, {code for tree, code in rows if tree == trees[0]}, rows)
        self.assertEqual([code for tree, code in rows if tree == trees[1]], [0], rows)

    def test_a_target_missing_on_origin_ends_the_run_as_a_delivery_failure(self):
        line = staged(self, {"t/ok.sh": "true\n"})
        task = taskfile.write(line.home, line.rig.path, front={"target": "missing"})
        done = line.home.ak("run", str(task), timeout=300)
        self.assertEqual(done.code, 1, done.out + done.err)
        state = record(taskfile.only_run(line.home))
        self.assertTrue(state["merge_failed"])
        self.assertIn("origin/missing does not exist on origin; nothing to merge into",
                      state["merge_note"])
        self.assertNotEqual(state["state"], "waiting")
        self.assertIsNone(state.get("waiting_on"))


if __name__ == "__main__":
    unittest.main()
