"""Offline: Codex's running thread totals buy each token once, including old history."""

import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history, transitions
from agentkit.harness import codex

TOTALS = ((760051, 4370), (1557752, 7161), (2115892, 8723))
CFG = {"models": {"acme": {"harness": "codex", "model": "acme", "effort": "high",
                            "provider": "openai"}}, "providers": {"openai": {}}}


class CodexTokens(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-codex-tokens-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.addCleanup(patch.stopall)
        patch.object(config, "HOME", self.home).start()
        patch.dict(os.environ, {"HOME": str(self.home)}).start()

    def turn(self, number, counts, *, thread="acme-thread", run="fix-api", role="reviewer",
             stamp=None):
        out = config.RUNS / run / f"round-{number}" / role
        out.mkdir(parents=True)
        events = out / "events.jsonl"
        events.write_text("\n".join(json.dumps(event) for event in (
            {"type": "thread.started", "thread_id": thread},
            {"type": "turn.completed", "usage": {"input_tokens": counts[0],
                "cached_input_tokens": counts[0] // 2, "output_tokens": counts[1]}})) + "\n")
        # Reporting order is injected; tests never depend on how fast the host writes files.
        at = number if stamp is None else stamp
        os.utime(events, ns=(at, at))
        return out

    def record(self, out, role="reviewer", run="fix-api"):
        transitions.history_role_tokens(run, role, out, cfg=CFG, model="acme")

    def test_three_resumed_turns_add_only_their_own_input_and_output(self):
        history.start_run("fix-api")
        previous, outs, spent = (0, 0), [], []
        # Round 10 must follow round 2, regardless of filename sorting or file times.
        for number, counts in zip((1, 2, 10), TOTALS):
            out = self.turn(number, counts, stamp=20 - number)
            delta = tuple(now - before for now, before in zip(counts, previous))
            self.assertEqual(codex.tokens(out), sum(delta))
            self.record(out)
            self.assertEqual(history.get("fix-api")["reviewer_tokens"], sum(counts))
            previous = counts
            outs.append(out)
            spent.append(sum(delta))
        self.assertEqual([codex.tokens(out) for out in outs], spent)
        self.assertEqual(sum(spent), 2115892 + 8723)

    def test_three_fresh_threads_count_in_full_and_other_runs_are_separate(self):
        self.turn(1, (9000000, 9000), thread="acme-thread-1", run="other-run")
        history.start_run("fix-api")
        for number, counts in enumerate(TOTALS, 1):
            out = self.turn(number, counts, thread=f"acme-thread-{number}")
            self.assertEqual(codex.tokens(out), sum(counts))
            self.record(out)
        self.assertEqual(history.get("fix-api")["reviewer_tokens"],
                         sum(sum(counts) for counts in TOTALS))

    def test_same_round_retries_and_fixer_share_the_threads_previous_total(self):
        history.start_run("fix-api")
        first = self.turn(1, TOTALS[0], role="executor")
        retry = self.turn(1, TOTALS[1], role="executor-retry1", stamp=2)
        self.record(first, "executor")
        self.assertEqual(history.get("fix-api")["executor_tokens"], sum(TOTALS[1]))
        # An unfinished retry reports no new total and must not hide the last known one.
        silent = self.turn(1, (0, 0), role="executor-retry2", stamp=3)
        (silent / "events.jsonl").write_text(json.dumps(
            {"type": "thread.started", "thread_id": "acme-thread"}) + "\n")
        os.utime(silent / "events.jsonl", ns=(3, 3))
        self.assertIsNone(codex.tokens(silent))
        fixer = self.turn(1, TOTALS[2], role="fixer", stamp=4)
        self.record(fixer, "executor")
        self.assertEqual(codex.tokens(retry), sum(TOTALS[1]) - sum(TOTALS[0]))
        self.assertEqual(history.get("fix-api")["executor_tokens"], 2115892 + 8723)

    def test_claudes_per_turn_counts_and_logs_without_thread_ids_stay_unchanged(self):
        history.start_run("fix-api")
        for number, counts in enumerate(TOTALS, 1):
            out = self.turn(number, counts)
            (out / "events.jsonl").write_text(json.dumps(
                {"type": "result", "usage": {"input_tokens": counts[0],
                                                "output_tokens": counts[1]}}))
            transitions.history_role_tokens("fix-api", "executor", out)
            self.assertEqual(codex.tokens(out), sum(counts))
        self.assertEqual(history.get("fix-api")["executor_tokens"],
                         sum(sum(counts) for counts in TOTALS))

    def test_old_rows_are_corrected_once_before_the_board_reads_them(self):
        for number, counts in enumerate(TOTALS, 1):
            self.turn(number, counts)
        # Mixed harnesses in one role: only the proven duplication may be removed.
        old = sum(sum(counts) for counts in TOTALS) + 123
        with sqlite3.connect(history.path()) as db:
            db.execute(history.SCHEMA)
            db.execute("PRAGMA user_version=1")
            for name in ("fix-api", "logs-gone"):
                db.execute("INSERT INTO runs (run_id, reviewer_tokens, executor_tokens, "
                           "final_state, started_at, finished_at) VALUES (?,?,?,'pass',1,2)",
                           (name, old, 456))
        rows = {row["run_id"]: row for row in history.ended_runs(0, 3)}
        corrected = 2115892 + 8723 + 123
        self.assertEqual(rows["fix-api"]["reviewer_tokens"], corrected)
        self.assertEqual(rows["fix-api"]["executor_tokens"], 456)
        self.assertEqual(rows["logs-gone"]["reviewer_tokens"], old)

        out = self.turn(4, (2200000, 9000))
        with patch.object(codex, "token_counts", side_effect=AssertionError("recounted twice")):
            self.assertEqual(history.get("fix-api")["reviewer_tokens"], corrected)
            history.update_run("fix-api", verdict="PASS")
            rows = {row["run_id"]: row for row in history.ended_runs(0, 3)}
            self.assertEqual(rows["fix-api"]["reviewer_tokens"], corrected)
        self.record(out)
        self.assertEqual(history.get("fix-api")["reviewer_tokens"], 2200000 + 9000 + 123)


if __name__ == "__main__":
    unittest.main()
