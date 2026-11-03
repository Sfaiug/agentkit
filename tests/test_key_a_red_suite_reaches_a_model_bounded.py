"""A suite red in every piece reaches the next model bounded, and a lone red piece keeps its 20 KB.

A suite's pieces share 256 KB, each at most 20 KB, the red ones taking theirs first: on 3 Nov 128
pieces red on one test made a landing log the harnesses refused as too long.  Black-box: the
program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on a host with room for
40 pieces and a project from gitrig.py with scripted harnesses from fakeadapter.py; the suite is
the task's done-when.
"""

import json
import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig

KB = 1024
PIECES = 40
READINGS = {"cpus": 64, "free_mb": PIECES * 410, "mem_total_mb": 65536, "slice_cpu_pressure": 0}
# 30 KB of numbered lines, the same in every piece, then the piece's own: upper case, so it cannot
# be read off the command, which every prompt names.
LINES = "".join(f"line {n:05}\n" for n in range(1, 2731))
LOUD = 'seq -f "line %05g" 2730; printf "end of %s\\n" "$AK_SHARD" | tr a-z A-Z'
WHOLE = re.compile(r"^\[only part of this output is shown; all of it is in (.+)\]$", re.M)
# what a piece hands on, its header lines aside
HANDED = re.compile(r"^--- AK_SHARD=\d+/\d+ ---\n\[[^\]\n]*\]\n(?:\[only part of [^\n]*\]\n)?"
                    r"(.*?)(?=\n\n|\Z)", re.M | re.S)


def prompts_of(case, check):
    """Every prompt a one-round task whose done-when is `check` handed a model."""
    home = Home()
    case.addCleanup(home.close)
    home.env["AK_HOST_READINGS"] = json.dumps(READINGS)
    rig = Rig(home, "widgets")
    akconfig.write(home, ["opus", "astra"])
    fakeadapter.install(home, claude="work", codex="pass")
    task = taskfile.write(home, rig.path, "Add retry file", front={"rounds": 1},
                          done_when=(f"{check} # AK_SHARD",))
    home.ak("run", str(task), "--no-merge", timeout=600)
    return [path.read_text() for path in taskfile.only_run(home).glob("**/prompt.md")]


class ARedSuiteReachesAModelBounded(unittest.TestCase):
    def test_a_check_red_and_loud_in_every_piece_stays_under_the_bound(self):
        prompts = prompts_of(self, f"{LOUD}; exit 1")
        fixer = max(prompts, key=len)
        self.assertLess(max(len(text.encode()) for text in prompts), 300 * KB)
        self.assertEqual(len(re.findall(r"^--- AK_SHARD=\d+/\d+ ---$", fixer, re.M)), PIECES)
        for index in range(1, PIECES + 1):
            self.assertIn(f"END OF {index}/{PIECES}\n", fixer)
        self.assertTrue(Path(WHOLE.findall(fixer)[0]).read_text().startswith(LINES))

    def test_one_piece_red_and_the_rest_quiet_hands_on_that_piece_s_last_20_kb(self):
        said = f"{LINES}END OF 7/{PIECES}\n"
        prompts = prompts_of(self, f'test "$AK_SHARD" != 7/{PIECES} || {{ {LOUD}; exit 1; }}')
        fixer = max(prompts, key=len)
        self.assertIn(said[-20 * KB:], fixer)
        self.assertNotIn(said[-20 * KB - 1:], fixer)
        self.assertEqual(Path(WHOLE.findall(fixer)[0]).read_text(), said)

    def test_one_piece_red_and_the_rest_loud_share_256_kb_the_red_piece_s_20_kb_first(self):
        said = f"{LINES}END OF 7/{PIECES}\n"
        prompts = prompts_of(self, f'{LOUD}; test "$AK_SHARD" != 7/{PIECES} || exit 1')
        fixer = max(prompts, key=len)
        handed = HANDED.findall(fixer)
        self.assertEqual(len(handed), PIECES)
        self.assertLessEqual(sum(len(text.encode()) for text in handed), 256 * KB)
        self.assertIn(said[-20 * KB:], fixer)
        self.assertNotIn(said[-20 * KB - 1:], fixer)


if __name__ == "__main__":
    unittest.main()
