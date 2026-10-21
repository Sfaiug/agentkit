"""Offline seat spending: invented harness records, a temporary HOME, no model calls."""

from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, history, scoreboard
from agentkit.harness import claude

NOW, WEEK = 1_800_000_000, 7 * 86400


def stamp(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def message(key, tokens, at=NOW - 1):
    return {"type": "assistant", "timestamp": stamp(at),
            "message": {"id": key, "usage": {"input_tokens": tokens}}}


def total(tokens, at=NOW - 1):
    return {"timestamp": stamp(at), "type": "event_msg", "payload": {"type": "token_count",
            "info": {"total_token_usage": {"total_tokens": tokens},
                     "last_token_usage": {"total_tokens": 999999}}}}


def muse_usage(key, tokens, family="provider"):
    return {"id": key, "recorded_at": (NOW - 1) * 1_000_000, "payload": {"kind": "run",
            "event": {"kind": "goal_usage_attribution", "record": {"usage_family": family,
            "quantity": {"input_tokens": tokens, "output_tokens": 0, "reported": True}}}}}


class SeatTokens(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-seat-tokens-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "XDG_DATA_HOME": str(self.root / "data"), "NO_COLOR": "1"}))
        self.stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        self.stack.enter_context(patch.object(config, "REPO", self.root / "toolkit"))
        self.stack.enter_context(patch.object(scoreboard, "_git", return_value=None))
        cfg = {"providers": {"p": {}}, "models": {name: {
            "harness": name, "model": "fixture", "effort": "high", "provider": "p"}
            for name in ("claude", "codex", "muse", "echo")}}
        self.stack.enter_context(patch.object(config, "load", return_value=cfg))

    def write(self, path, *events):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as output:
            output.writelines(json.dumps(event) + "\n" for event in events)
        return path

    def seat(self, name, adapter, **fields):
        record = {"orchestrator": adapter, "conversation": name, "cwd": str(self.root / "acme"),
                  "repo": str(self.root / "acme"), **fields}
        config.session_path(name).parent.mkdir(parents=True, exist_ok=True)
        config.session_path(name).write_text(json.dumps(record))
        return record

    def fixtures(self):
        seat = self.seat("larch", "claude", repo=str(config.REPO), account="second")
        own = message("m1", 10)
        own["message"]["usage"].update(output_tokens=20, cache_creation_input_tokens=30,
                                        cache_read_input_tokens=40)
        self.main = self.write(claude.transcript_path(seat, "larch"),
                               message("ancient", 9, NOW - 3 * WEEK),
                               message("old", 10, NOW - WEEK - 1), own, own)
        self.child = self.write(self.main.with_suffix("") / "subagents/agent-child.jsonl",
                                message("child", 25), {"type": "result", "usage": {"input_tokens": 999}})
        store = self.root / ".codex/agentkit-seats/fixture/sessions/2026/10/21"
        self.rollout = self.write(store / "rollout-seat.jsonl", total(100, NOW - WEEK - 1), total(160))
        self.write(store / "rollout-child.jsonl", total(40), total(40))
        self.seat("birch", "codex", codex_launch="1" * 32)
        (config.STATE / ("codex-launch-" + "1" * 32 + ".json")).write_text(json.dumps({
            "launch": "1" * 32, "remote": "fixture", "event": {"transcript_path": str(self.rollout)}}))
        self.seat("cedar", "muse")
        store = self.root / "data/muse/sessions/2026/10/21"
        def metadata(session, parent=None):
            return {"stream": {"id": session}, "payload": {"kind": "metadata",
                    "record": {"parent_session_id": parent}}}
        self.muse = self.write(store / "cedar/session.jsonl", muse_usage("u1", 70))
        self.write(store / "child/session.jsonl", metadata("child", "cedar"), muse_usage("u2", 30),
                   muse_usage("tool", 999, "tool"))
        self.write(store / "unrelated/session.jsonl", metadata("unrelated"), muse_usage("other", 999))
        for name, merged in (("merged", True), ("failed", False)):
            history.start_run(name, repo="acme", started_at=NOW - 10)
            history.finish_run(name, final_state="pass" if merged else "fail", finished_at=NOW - 1,
                               changed_lines=1 if merged else None, rounds_used=1)
            history.update_run(name, executor_tokens=80, reviewer_tokens=20)

    def test_backfill_counts_each_message_child_and_cumulative_delta_in_its_week(self):
        self.fixtures()
        board = scoreboard.compute(NOW)
        self.assertEqual(board["tokens"], [
            {"total_tokens": 525, "seat_tokens": 325, "not_counted": []},
            {"total_tokens": 110, "seat_tokens": 110, "not_counted": []}])
        self.assertEqual(board["ak"][0]["token_share"], 125 / 525)
        self.assertEqual(board["sunk"][0], {"share": 100 / 525, "tokens": 100})
        self.assertEqual(scoreboard.compute(NOW), board)
        self.assertEqual(scoreboard.compute(NOW - 2 * WEEK)["tokens"][0]["seat_tokens"], 9)
        self.write(self.main, message("seven", 7, NOW - WEEK), message("fourteen", 11, NOW - 2 * WEEK))
        self.assertEqual([cell["total_tokens"] for cell in scoreboard.compute(NOW)["tokens"]], [532, 121])

    def test_only_appended_complete_lines_are_read_and_replacements_do_not_recount(self):
        self.fixtures()
        scoreboard.compute(NOW)
        with patch.object(claude, "seat_token_usage", wraps=claude.seat_token_usage) as parsed:
            scoreboard.compute(NOW)
            parsed.assert_not_called()
            self.write(self.main, message("new", 50), message("m1", 100))
            self.write(self.child, message("new-child", 5))
            self.write(self.rollout, total(220))
            self.write(self.muse, muse_usage("u3", 10))
            self.assertEqual(scoreboard.compute(NOW)["tokens"][0]["seat_tokens"], 450)
            self.assertEqual(parsed.call_count, 3)
        line = json.dumps(message("partial", 7)) + "\n"
        with self.main.open("a") as output:
            output.write(line[:40])
        self.assertEqual(scoreboard.compute(NOW)["tokens"][0]["seat_tokens"], 450)
        with self.main.open("a") as output:
            output.write(line[40:])
        replacement = self.main.with_suffix(".tmp")
        replacement.write_bytes(self.main.read_bytes())
        replacement.replace(self.main)
        config.session_path("larch").rename(config.session_path("renamed"))
        self.assertEqual(scoreboard.compute(NOW)["tokens"][0]["seat_tokens"], 457)
        for path in config.STATE.glob("session-*.json"):
            path.unlink()
        self.assertEqual(scoreboard.compute(NOW)["tokens"][0]["seat_tokens"], 457)

    def test_harness_without_a_reader_and_missing_records_are_named(self):
        self.seat("ash", "echo")
        self.seat("elm", "claude")
        board = scoreboard.compute(NOW)
        self.assertEqual(board["tokens"][0]["not_counted"], ["ash (echo)", "elm (claude)"])
        text = " ".join(" ".join(scoreboard.render(board)).split())
        self.assertIn("not counted: ash (echo), elm (claude)", text)


if __name__ == "__main__":
    unittest.main()
