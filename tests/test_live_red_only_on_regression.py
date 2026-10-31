"""Only failures added over the running install hold its move; no live suite or model runs."""

import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox, REPO
from agentkit import config, update, watch, worker
import check_harness_contract as contract

HEAD, TIP = "a" * 40, "b" * 40
LABELS = ("3 acme", "3", "4")   # 3 acme printed first shares check 3's first token


class LiveRedOnlyOnRegression(Sandbox):
    def setUp(self):
        super().setUp()
        self.head, self.now, self.running, self.moves = HEAD, 10000, set(), []
        self.stack.enter_context(patch.object(config, "REPO", self.root))
        self.stack.enter_context(patch.object(update, "agentkit_dir", return_value=self.root))
        self.stack.enter_context(patch.object(update.versions, "finish"))
        self.stack.enter_context(patch.object(update.gitcall, "no_auto_gc"))
        self.stack.enter_context(patch.object(update, "_git", side_effect=self.git))
        self.stack.enter_context(patch.object(update, "update_once", side_effect=self.move))
        self.stack.enter_context(patch.object(worker, "marked_pids",
                                 side_effect=lambda mark: [123] if mark in self.running else []))
        self.kill = self.stack.enter_context(patch.object(worker, "kill_marked"))
        self.start = self.stack.enter_context(patch.object(update.orch, "start_in_slice",
                                                         side_effect=self.spawn))
        self.deliver = self.stack.enter_context(patch.object(watch, "after_merge_deliver",
                                                           return_value=True))

    def git(self, *args, **_kw):
        if args[0] == "rev-parse":
            return 0, self.head if args[-1] == "HEAD" else TIP
        if args[0] == "merge-base":
            return int(args[-2] != self.head), ""
        if args[0] == "rev-list":
            return 0, TIP
        return 0, "https://github.com/acme/agentkit.git"

    def move(self, _where, *, pull):
        self.moves.append(pull)
        self.head = pull
        return 0, []

    def spawn(self, argv, *_args, **_kw):
        self.running.add(argv[3])

    def check(self, commit, labels=LABELS, *, started=9900, ended=9950, code=1):
        check = config.STATE / update.LIVE / f"{commit}-{started}"
        check.mkdir(parents=True)
        if labels is not None:
            (check / "failed").write_text("".join(f"{label}\n" for label in labels))
        (check / "output").write_text("FAIL  \n" + "".join(f"FAIL  {label}: refused\n" for label in LABELS))
        self.finish(check, ended, code)
        return check

    def finish(self, check, ended, code=1):
        (check / "exit").write_text(f"{code}\n")
        os.utime(check / "exit", (ended, ended))
        self.running.discard(str(check))

    def tick(self):
        update.go_live(lambda _: None, self.now)

    def test_shared_failures_move_and_hand_back_each_label_and_first_line(self):
        self.check(TIP)
        self.check(HEAD, (*LABELS, "6"), started=9800)
        update.live_tick(lambda _: None, self.now, fetched=True)
        self.assertEqual(update.live_target(), TIP)
        self.assertEqual(update.owed_live(self.now), (TIP, 9950))
        self.tick()
        self.assertEqual(self.moves, [TIP])
        self.deliver.assert_called_once()
        line = self.deliver.call_args.args[3]
        self.assertIn("standing faults", line)
        for label in LABELS:
            self.assertIn(f"FAIL  {label}: refused", line)

    def test_any_regression_or_missing_failure_evidence_holds(self):
        for tip_labels, head_labels, head_code in (
                (LABELS, ("3 acme",), 1), (None, LABELS, 1), ((), LABELS, 1),
                (LABELS, None, 1), (LABELS, LABELS, 0)):
            with self.subTest(tip=tip_labels, baseline=head_labels, code=head_code):
                tip = self.check(TIP, tip_labels)
                head = self.check(HEAD, head_labels, code=head_code, started=9800)
                self.tick()
                self.assertEqual((self.moves, update.live_target(), update.owed_live(self.now)),
                                 ([], "", None))
                self.start.assert_not_called()
                shutil.rmtree(tip)
                shutil.rmtree(head)

    def test_one_head_check_after_red_and_none_while_either_check_runs(self):
        tip = self.check(TIP)
        self.running.add(str(tip))
        self.tick()
        self.start.assert_not_called()
        self.running.clear()
        self.tick()
        self.start.assert_called_once()
        argv = self.start.call_args.args[0]
        self.assertEqual(argv[5], HEAD)
        self.tick()
        self.start.assert_called_once()
        self.finish(config.STATE / update.LIVE / f"{HEAD}-{self.now}", self.now + 1, 0)
        self.now = 9950 + watch.RETRY_BACKOFF[0] - 1
        self.tick()
        self.start.assert_called_once()
        self.now += 1
        self.tick()
        self.assertEqual(self.start.call_args.args[0][5], TIP)

    def test_an_old_head_result_is_checked_again(self):
        self.check(TIP)
        self.check(HEAD, started=9700, ended=9899)
        self.tick()
        self.assertEqual((self.moves, self.start.call_args.args[0][5]), ([], HEAD))

    def test_a_harness_swap_between_checks_cannot_excuse_a_red(self):
        self.check(TIP)
        self.check(HEAD, started=9960, ended=9990)
        (config.STATE / update.SWAPS).write_text(json.dumps([["acme", 9955, 9956]]))
        self.tick()
        self.assertEqual(self.moves, [])

    def test_standing_fault_delivery_is_retried_after_the_move(self):
        self.check(TIP)
        self.check(HEAD, started=9800)
        self.deliver.return_value = False
        self.tick()
        self.assertEqual(self.moves, [TIP])
        self.deliver.return_value = True
        self.tick()
        self.assertEqual(self.deliver.call_count, 2)
        self.tick()
        self.assertEqual(self.deliver.call_count, 2)

    def test_shell_and_harness_failures_write_labels_without_reading_output(self):
        failed = self.root / "failed"
        env = {"WORK": str(self.root), "AK_LIVE_FAILED": str(failed) + ".tmp",
               "AK_LIVE_FAILED_FINAL": str(failed),
               "AGENTKIT_ACCEPTANCE_REQUIRED": "1"}
        with patch.dict(os.environ, env), patch.object(contract, "unavailable",
                                                     return_value=("refused", True)):
            contract.check({"models": {}, "providers": {}}, self.root, None, self.root,
                           harness="acme")
        self.assertFalse(failed.exists())
        script = ('. "$1"; no "4/4b ak run: refused"; skip "6: no coverage"; '
                  'skip_spent_checks 5/7 refused; finish')
        proc = subprocess.run(["bash", "-c", script, "fixture", str(REPO / "tests/acceptance.sh")],
                              env=env, capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(failed.read_text().splitlines(), ["3 acme", "3", "4", "4b", "6", "5", "7"])


if __name__ == "__main__":
    unittest.main()
