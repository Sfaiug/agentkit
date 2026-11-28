"""A Codex seat's turn is kept as Codex timed it.

Codex writes a turn's end into a seat's rollout as a line of `type` `event_msg` whose `payload`
has `type` `task_complete`, its `turn_id` and its `duration_ms`, the turn's length.  A tick files
it in history.db's `seat_turns` at the line's moment with the length in seconds, under the
seat's project and login, as tests/test_key_a_seats_turn_is_kept.py files a Claude Code turn: a
length that is no number of zero or more is no turn.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its
tick in the box `home.tick()` builds, on seats of tests/fixtures/akseat.py whose rollouts are
written as Codex writes them, under invented ids.
"""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

T0 = 1_795_168_800      # 2026-11-20 10:00 UTC


def stamp(at):
    """`at` seconds as Codex writes a moment: UTC, to the millisecond."""
    return datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="milliseconds")[:-6] + "Z"


def ended(at, turn, length):
    """The line Codex writes as turn `turn` ends at `at`, `length` its `duration_ms`."""
    return {"timestamp": stamp(at), "type": "event_msg", "ordinal": 41, "payload": {
        "type": "task_complete", "turn_id": turn, "duration_ms": length,
        "started_at": T0, "completed_at": int(at), "last_agent_message": "Done."}}


def codex_seat(home, name, ids, *lines, **record):
    """Seat `name` on Codex, launched to the private store its launch receipt names, its rollout
    a thread's start, a step's usage and `lines`; `ids` its thread, launch and store."""
    thread, launch, remote = ids
    seat = Seat(home, name, model="astra", screen="codex-prompt-pane.txt", record={
        "conversation": thread, "codex_launch": launch,
        "repo": str(home.path / "code" / name), **record})
    rollout = (home.path / ".codex/agentkit-seats" / remote
               / f"sessions/2026/11/20/rollout-2026-11-20T10-00-00-{thread}.jsonl")
    rollout.parent.mkdir(parents=True)
    rollout.write_text("".join(json.dumps(line) + "\n" for line in (
        {"timestamp": stamp(T0), "type": "session_meta", "payload": {
            "id": thread, "timestamp": stamp(T0), "cwd": str(seat.cwd), "source": "cli",
            "originator": "codex_cli_rs", "cli_version": "0.163.0", "model_provider": "openai"}},
        {"timestamp": stamp(T0 + 60), "type": "event_msg", "payload": {
            "type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 9_000, "output_tokens": 300,
                                      "total_tokens": 9_300},
                "last_token_usage": {"total_tokens": 9_300}, "model_context_window": 272_000}}},
        *lines)))
    home.write(f".agentkit/state/codex-launch-{launch}.json", {
        "launch": launch, "cwd": str(seat.cwd), "expected": None, "remote": remote,
        "event": {"hook_event_name": "SessionStart", "source": "startup", "session_id": thread,
                  "cwd": str(seat.cwd), "transcript_path": str(rollout)}})


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ACodexSeatsTurnIsKept(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["astra"])  # no audit, which opens a seat of its own
        codex_seat(home, "acme", ("019a6043-9e6d-7f32-a041-5dbc8e3f6a01", "1" * 32, "2" * 32),
                   ended(T0 + 68.6, "t-acme-1", 68_600), account="second", home_account="second")
        codex_seat(home, "gamma", ("019a6043-9e6d-7f32-a041-5dbc8e3f6a02", "3" * 32, "4" * 32),
                   ended(T0 + 70, "t-gamma-1", "seventy"))
        done = home.tick()
        assert done.code == 0, done.out + done.err
        with closing(sqlite3.connect((home.path / ".agentkit/history.db").as_uri() + "?mode=ro",
                                     uri=True)) as db:
            cls.turns = [(repo, round(at - T0, 3), *kept) for repo, at, *kept in db.execute(
                "SELECT repo, at, seconds, account FROM seat_turns ORDER BY repo")]
            cls.used = {repo for repo, in db.execute("SELECT repo FROM seat_usage")}

    def test_a_codex_turn_is_kept_at_its_end_with_its_seconds_under_its_seats_project_and_login(
            self):
        self.assertIn(("acme", 68.6, 68.6, "second"), self.turns)

    def test_a_task_complete_whose_duration_ms_is_a_word_files_none(self):
        self.assertIn("gamma", self.used, "gamma's rollout was not read")
        self.assertEqual([turn for turn in self.turns if turn[0] == "gamma"], [])


if __name__ == "__main__":
    unittest.main()
