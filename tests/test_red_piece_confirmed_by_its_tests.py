"""A red piece of a sharded suite that names its failed tests retries just those first.

Offline: temporary HOME, injected host readings and short fixture commands; one real check
box shows the two files the contract passes.
"""

from collections import Counter
from contextlib import ExitStack
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home
from agentkit import config, gate, record, worker

ROOM = {"cpus": 4, "load": 0, "free_mb": 820,
        "slice_cpu_quota": 4, "slice_cpu_used": 0,
        "slice_memory_high_mb": 820, "slice_memory_used_mb": 0}
SUITE = 'printf "piece %s\\n" "${AK_SHARD:-all}"'
NAMED = ["tests/test_acme.py::test_total", "tests/test_acme.py::test_tax"]


class RedPieceConfirmedByItsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-red-named-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(account_home(self.root))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / name.lower()))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_HOST_READINGS": json.dumps(ROOM), "AK_CGROUP_FILE": str(self.root / "no-cgroup")}))
        config.ensure_dirs()
        self.run_dir = config.RUNS / "fixture"
        self.run_dir.mkdir()
        record.save_state(self.run_dir, {"run_id": "fixture", "state": "running"})

    def suite(self, piece, **kw):
        """The suite in two pieces, `piece(shard, only, failed)` giving each attempt's exit;
        an attempt that runs only named tests sees `AK_SHARD=1/1`."""
        calls = []

        def boxed(cmd, limit, env, output, only=None, failed=None, **_kw):
            calls.append((env["AK_SHARD"], only))
            output.write(b"named tests\n" if only else f"piece {env['AK_SHARD']}\n".encode())
            return piece(env["AK_SHARD"], only, failed), "", False

        with patch.object(worker, "boxed", side_effect=boxed):
            code, text, killed = gate.run_suite(
                SUITE, 10, cwd=self.root, activity=self.run_dir / "live.log",
                output=BytesIO(), run_dir=self.run_dir, **kw)
        self.assertEqual(sorted(calls[:2]), [("1/2", None), ("2/2", None)])
        return code, text, killed, calls[2:]

    def test_named_tests_failing_alone_make_the_piece_red_without_a_whole_retry(self):
        def piece(shard, only, failed):
            failed.extend(NAMED if shard != "2/2" else [])
            return int(shard != "2/2")

        code, text, killed, retries = self.suite(piece)
        self.assertEqual((code, killed), (1, False))
        self.assertEqual(retries, [("1/1", NAMED)])
        self.assertIn("--- AK_SHARD=1/2 ---\n[exit 1]\n"
                      "its failed tests failed again, run alone\nnamed tests", text)

    def test_named_tests_passing_alone_leave_the_whole_piece_to_decide(self):
        for second in (0, 1):
            with self.subTest(second=second):
                whole = Counter()

                def piece(shard, only, failed):
                    if only is not None or shard == "2/2":
                        return 0
                    whole[shard] += 1
                    if whole[shard] == 1:
                        failed.append(NAMED[0])
                        return 1
                    return second

                flaky = []
                code, text, killed, retries = self.suite(piece, flaky=flaky)
                self.assertEqual((code, killed), (second, False))
                self.assertEqual(retries, [("1/1", NAMED[:1]), ("1/2", None)])
                self.assertEqual(flaky, NAMED[:1])   # failed, then passed alone, whatever after
                self.assertEqual("its failed tests passed run alone: the failure needs the "
                                 "tests that ran before them" in text, bool(second))
                self.assertEqual("flaky: " in text, not second)

    def test_a_piece_naming_no_tests_retries_whole(self):
        code, text, killed, retries = self.suite(lambda shard, only, failed: int(shard == "1/2"))
        self.assertEqual((code, killed), (1, False))
        self.assertEqual(retries, [("1/2", None)])
        self.assertNotIn("its failed tests", text)

    def test_a_check_box_hands_over_the_tests_to_run_and_takes_back_those_that_failed(self):
        failed, activity = [], self.root / "check.log"
        with activity.open("w+b") as output:
            code, _, killed = worker.boxed(
                ["bash", "-c", 'sort -r "$AK_ONLY" > "$AK_FAILED"; '
                               'sed "s/.*/ & \\n/" "$AK_ONLY" >> "$AK_FAILED"; exit 3'],
                10, env=dict(os.environ), cwd=self.root, activity=activity, output=output,
                stderr=subprocess.STDOUT, only=NAMED, failed=failed)
        self.assertEqual((code, killed, failed), (3, False, sorted(NAMED, reverse=True)))

    def test_a_link_named_as_failed_is_not_followed_out_of_the_box(self):
        secret, failed, activity = self.root / "acme-token", [], self.root / "check.log"
        secret.write_text("acme-secret\n")
        with activity.open("w+b") as output:
            code, _, killed = worker.boxed(
                ["bash", "-c", f'ln -s {secret} "$AK_FAILED"; exit 1'], 10,
                env=dict(os.environ), cwd=self.root, activity=activity, output=output,
                stderr=subprocess.STDOUT, failed=failed)
        self.assertEqual((code, killed, failed), (1, False, []))

    def test_an_independent_suite_inherits_no_test_lists(self):
        with patch.dict(os.environ, {"AK_ONLY": "only-tests", "AK_FAILED": "failed-tests",
                                     "AK_RAN": "ran-tests"}):
            env = gate.suite_env()
        self.assertEqual({"AK_ONLY", "AK_FAILED", "AK_RAN"} & set(env), set())


if __name__ == "__main__":
    unittest.main()
