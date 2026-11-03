"""Counting survives an interrupted commit and a stop's last worker flush. No real kills."""

from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import browser, config, history, record, stop, transitions


class KilledTurnTokensCount(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(config, "HOME", root / ".agentkit"))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(root), "AGENTKIT_SESSION": "", "AGENTKIT_RUN": "", "AK_PARENT_RUN": "",
            "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.run_dir = config.RUNS / "fix-api"
        self.out = self.run_dir / "round-1" / "executor"
        self.out.mkdir(parents=True)
        (self.out / "harness").write_text("claude")
        self.events = self.out / "events.jsonl"
        self.usage(350)
        history.start_run("fix-api", repo="acme", started_at=1)

    def usage(self, tokens):
        with self.events.open("a") as stream:
            stream.write(json.dumps({"type": "message", "usage": {"tokens": tokens}}) + "\n")

    def finally_tokens(self):
        transitions.history_role_tokens("fix-api", "executor", self.out)

    def finish(self):
        history.finish_run("fix-api", final_state="stopped")

    def test_a_failed_output_mark_cannot_double_a_committed_count(self):
        with patch.object(Path, "touch", side_effect=OSError(28, "No space left on device")):
            self.finally_tokens()
        self.assertEqual(history.get("fix-api")["executor_tokens"], 350)
        self.finish()
        self.finish()
        self.assertEqual(history.get("fix-api")["executor_tokens"], 350)

    def test_a_kill_before_commit_rolls_back_both_the_count_and_its_identity(self):
        write = history._write

        def interrupted(fn, log=None):
            def killed(connection):
                fn(connection)
                raise SystemExit("killed before commit")
            return write(killed, log)

        for count in (self.finally_tokens, self.finish):
            with patch.object(history, "_write", interrupted), self.assertRaises(SystemExit):
                count()
            self.assertIsNone(history.get("fix-api")["executor_tokens"])
        self.finish()
        self.finally_tokens()
        self.assertEqual(history.get("fix-api")["executor_tokens"], 350)

    def test_a_stop_and_a_concurrent_tick_wait_for_the_workers_last_usage(self):
        record.save_state(self.run_dir, {"run_id": "fix-api", "state": "running",
                                        "step": "executor", "started_at": 1})
        attempted = threading.Event()
        finish = history.finish_run

        def publishing(*args, **kwargs):
            attempted.set()
            return finish(*args, **kwargs)

        tick = None

        def completed_before_kill(*args):
            nonlocal tick
            tick = pool.submit(transitions.history_agree)
            self.assertTrue(attempted.wait(10), "the tick never tried to publish the stop")
            self.usage(50)
            self.finally_tokens()
            return True

        for target, name, value in (
                (stop.orch, "user_manager", lambda: False),
                (stop, "marker_pids", lambda run: [424242]),
                (stop.watch, "kill_tree", completed_before_kill),
                (stop.handback, "redress_seat", lambda *a: None),
                (stop.handback, "record_result", lambda *a: None),
                (browser, "close_owned", lambda **kw: None),
                (history, "finish_run", publishing)):
            self.stack.enter_context(patch.object(target, name, value))
        with ThreadPoolExecutor(max_workers=1) as pool:
            stop.end(self.run_dir, keep=True, why="stopped by the user", log=lambda message: None)
            tick.result(timeout=10)
        self.assertEqual(history.get("fix-api")["executor_tokens"], 400)


if __name__ == "__main__":
    unittest.main()
