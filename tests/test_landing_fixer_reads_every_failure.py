"""A landing fixer is handed every failure the final check printed, not only its end.

A suite run in pieces prints each piece's failures where that piece ends: one red file 32 KB
before the end of a landing log never reached the fixer handed the last 20 KB, which spent a
round on the others (7 Oct).  Offline: a fake run record and fixer; nothing runs.
"""

from contextlib import ExitStack, nullcontext
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, gate, run
from agentkit import record as run_record

EARLY = ("FAIL  tests/test_acme_limits.py: exit 1 after 177s, its last lines:\n"
         "      FileNotFoundError: [Errno 2] No such file or directory: 'taken'\n")
LATE = ("FAIL  12b acme smoke: the widget never answered\n"
        "      [12:00:00] WARN acme exited 1\n")
PASSES = "".join(f"PASS  tests/test_widget_{n}.py ({n % 7}s)\n" for n in range(1500))


class Handed(Exception):
    pass


class FakeRun:
    context, rnd, state = "# Task", 1, {}

    def save(self):
        pass


class LandingFixer(unittest.TestCase):
    def fixer_reads(self, text):
        seen = []

        def fixer(_lp, fix, _label):
            seen.append(fix)
            raise Handed

        with patch.object(run, "landing_fixer", side_effect=fixer), \
                patch.object(run, "released_gate_turn", nullcontext), \
                self.assertRaises(Handed):
            run.fix_final_check(FakeRun(), "main", text)
        return seen[0]

    def test_a_failure_far_from_the_end_reaches_the_fixer(self):
        text = "--- AK_SHARD=2/5 ---\n" + EARLY + PASSES + "--- AK_SHARD=5/5 ---\n" + LATE
        self.assertGreater(len(text) - text.index(EARLY), 2 * run.OUT_CAP)
        fix = self.fixer_reads(text)
        self.assertIn(EARLY.rstrip(), fix)
        self.assertIn(LATE.rstrip(), fix)
        self.assertLess(fix.index(EARLY.splitlines()[0]), fix.index(LATE.splitlines()[0]))

    def test_every_other_landing_fixer_gets_the_lines_failure_the_same_way(self):
        log = Path(self.enterContext(__import__("tempfile").TemporaryDirectory())) / "red.log"
        log.write_text("--- AK_SHARD=2/5 ---\n" + EARLY + PASSES + LATE)
        lp = FakeRun()
        lp.state = {"waiting_on": {"line": ".merge-acme.lock", "fix": {"log": str(log)}}}
        seen = []

        def execute(_lp, _role, text, _name):
            seen.append(text)
            raise Handed

        with patch.object(run, "execute", side_effect=execute), self.assertRaises(Handed):
            run.landing_fixer(lp, "## Resolve the rebase conflict.", "rebase-fixer")
        self.assertIn(EARLY.rstrip(), seen[0])
        self.assertIn(LATE.rstrip(), seen[0])

    def test_a_red_targets_repair_is_told_every_failure(self):
        text = run.red_target_text("python3 tests/landing.py", "main", "c0ffee",
                                   "--- AK_SHARD=2/5 ---\n" + EARLY + PASSES + LATE)
        self.assertTrue(text.startswith("`python3 tests/landing.py` fails on main at c0ffee"))
        for block in (EARLY, LATE):
            for line in block.splitlines():
                self.assertIn("    " + line, text)

    def test_short_output_and_output_naming_no_failure_read_as_before(self):
        short = "PASS  tests/test_widget.py\n" + LATE
        self.assertIn(short, self.fixer_reads(short))
        unnamed = PASSES + "Traceback (most recent call last):\n  boom\n"
        self.assertIn(unnamed[-run.OUT_CAP:], self.fixer_reads(unnamed))


class CheckOutput(unittest.TestCase):
    """The gate keeps a failure far from the end of a command's output, and of a piece's."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-every-failure-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        stack.enter_context(patch.object(run, "dirty_paths", return_value=[]))
        config.RUNS.mkdir(parents=True)
        self.run_dir = config.RUNS / "20261007-0000-acme"
        self.run_dir.mkdir()
        run_record.save_state(self.run_dir, {
            "run_id": self.run_dir.name, "title": "acme", "state": "running", "verdict": None,
            **run_record.process_owner(), "started_at": time.time(), "round_summaries": []})
        self.printed = self.root / "printed.txt"
        self.printed.write_text("--- AK_SHARD=2/5 ---\n" + EARLY + PASSES + LATE)

    def gate(self, cmd):
        ok, text = gate.run_done_when([cmd], self.root, self.run_dir / "donewhen.log", set(),
                                      limit=120, log=lambda _: None, run_dir=self.run_dir)
        self.assertFalse(ok)
        return text

    def test_a_commands_early_failure_is_in_what_the_gate_returns(self):
        text = self.gate(f"cat {shlex.quote(str(self.printed))}; exit 1")
        self.assertIn(EARLY.rstrip(), text)
        self.assertIn(LATE.rstrip(), text)

    def test_a_pieces_early_failure_is_in_what_the_gate_returns(self):
        text = self.gate(f"export AK_SHARD; cat {shlex.quote(str(self.printed))}; exit 1")
        self.assertIn(EARLY.rstrip(), text)
        self.assertIn(LATE.rstrip(), text)


if __name__ == "__main__":
    unittest.main()
