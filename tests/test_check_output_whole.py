"""Check output a model is handed only part of names the file that keeps all of it.

A done-when command, a suite piece or a landing failure longer than the output cap reaches a
builder, fixer or reviewer as its end.  That end used to come with no word that anything was
left out, and the whole was overwritten once the check ended, so a cause printed early (an
import error ahead of pages of fallout) was out of every model's reach.  Now the part handed
on starts with a line naming a file in the run that holds everything the check printed.

Offline: a temporary HOME, injected host readings and short fixture commands.
"""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import tracemalloc
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home
from agentkit import config, gate, gitcall, prompts, roundloop, turns, worker
from agentkit import record

ROOM = {"cpus": 4, "load": 0, "free_mb": 820,
        "slice_cpu_quota": 4, "slice_cpu_used": 0,
        "slice_memory_high_mb": 820, "slice_memory_used_mb": 0}
LONG = turns.OUT_CAP + 4096
# a check that prints more than the cap between its first and last lines, and the same as a
# suite that names AK_SHARD, so it runs in pieces
CHATTY = f"printf 'first\\n'; head -c {LONG} /dev/zero | tr '\\0' x; printf '\\nlast\\n'"
PIECES = (f"printf 'first %s\\n' \"$AK_SHARD\"; head -c {LONG} /dev/zero | tr '\\0' x; "
          "printf '\\nlast %s\\n' \"$AK_SHARD\"")
SHORT = "printf 'all of it\\n'"
# more than a run's memory should hold of one check at once, and the same as a suite
LOUD = 8 * 1024 * 1024
FLOOD = f"yes acme | head -c {LOUD}"
FLOODS = f"{FLOOD}  # AK_SHARD"
NAMED = re.compile(r"^\[only part of this output is shown; all of it is in (.+)\]$", re.M)


class Handed(Exception):
    pass


class CheckOutputWhole(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-output-whole-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(account_home(self.root))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_HOST_READINGS": json.dumps(ROOM),
            "AK_CGROUP_FILE": str(self.root / "no-cgroup"), "AK_SHARD": "99/99",
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}))
        config.ensure_dirs()
        self.stack.enter_context(patch.object(gitcall, "dirty_paths", return_value=[]))
        self.stack.enter_context(patch.object(worker, "kill_marked"))
        self.stack.enter_context(patch.object(worker, "ACTIVITY_POLL", 0.01))
        self.run_dir = config.RUNS / "fixture"
        self.run_dir.mkdir()
        record.save_state(self.run_dir, {"run_id": "fixture", "state": "running",
                                        "repo": str(self.root), "round_summaries": []})

    def check(self, cmd):
        return gate.run_done_when([cmd], self.root, self.run_dir / "donewhen.log", set(),
                                  limit=30, log=lambda _line: None, run_dir=self.run_dir)

    def wholes(self, text):
        """Each file the text names as holding all of a check's output, with what it holds."""
        return [Path(path).read_text() for path in NAMED.findall(text)]

    def test_a_long_check_names_the_file_holding_all_it_printed(self):
        ok, text = self.check(CHATTY)
        self.assertTrue(ok, text[:300])
        self.assertNotIn("first\n", text)
        self.assertTrue(text.rstrip().endswith("last"))
        [whole] = self.wholes(text)
        self.assertTrue(whole.startswith("first\n"))
        self.assertTrue(whole.rstrip().endswith("last"))
        self.assertEqual(prompts.done_when_counts(text, [CHATTY]), (1, 1))
        self.assertEqual((self.run_dir / "donewhen.log").read_text(), text)

    def test_a_check_within_the_cap_is_handed_whole_and_saves_nothing(self):
        ok, text = self.check(SHORT)
        self.assertTrue(ok, text)
        self.assertEqual(text, f"$ {SHORT}\n[exit 0]\nall of it")
        self.assertEqual(list(self.run_dir.glob("*.log")), [self.run_dir / "donewhen.log"])

    def test_each_long_suite_piece_names_its_own_whole(self):
        ok, text = self.check(PIECES)
        self.assertTrue(ok, text[:300])
        shards = re.findall(r"^--- AK_SHARD=(\d+/\d+) ---$", text, re.M)
        self.assertGreater(len(shards), 1, text[:300])
        wholes = self.wholes(text)
        self.assertEqual(sorted(whole.splitlines()[0] for whole in wholes),
                         sorted(f"first {shard}" for shard in shards))
        for shard in shards:
            self.assertNotIn(f"first {shard}\n", text)
            self.assertIn(f"last {shard}", text)

    def test_a_check_printing_more_than_memory_holds_is_never_read_whole(self):
        for cmd in (FLOOD, FLOODS):
            with self.subTest(cmd=cmd):
                tracemalloc.start()
                try:
                    ok, text = self.check(cmd)
                    held = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                self.assertTrue(ok, text[:300])
                self.assertLess(held, LOUD // 2)
                self.assertTrue(all(len(whole) == LOUD for whole in self.wholes(text)))

    def test_a_landing_fixer_handed_part_of_a_failure_is_told_where_the_rest_is(self):
        failure = "FAIL  tests/test_acme.py: boom\n" + "PASS  tests/test_widget.py\n" * 2000
        log = self.run_dir / "final-check.log"
        log.write_text(failure)
        seen = []

        class Run:
            context, rnd, run_dir = "# Task", 1, self.run_dir
            state = {"waiting_on": {"line": ".merge-acme.lock", "fix": {"log": str(log)}}}

        def execute(_lp, _role, text, _name):
            seen.append(text)
            raise Handed
        with patch.object(roundloop, "execute", side_effect=execute), self.assertRaises(Handed):
            roundloop.landing_fixer(Run(), "## Resolve the rebase conflict.", "rebase-fixer")
        self.assertIn("FAIL  tests/test_acme.py: boom", seen[0])
        [whole] = self.wholes(seen[0])
        self.assertEqual(whole, failure)


if __name__ == "__main__":
    unittest.main()
