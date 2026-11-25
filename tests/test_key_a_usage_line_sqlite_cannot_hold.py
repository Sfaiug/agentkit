"""A usage line SQLite cannot hold files nothing, and the lines after it count as without it.

A tick files each usage line of a seat's conversations in history.db's `seat_usage`
(tests/test_key_seat_tokens_by_type.py).  A line whose moment is past SQLite's integers or a
float, whose tokens are past SQLite's integers, or whose message id or model holds a lone
surrogate, files nothing: a later line of its Claude message is filed at its own moment, and a
later Codex step counts its growth from the step filed before it.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, its tick
in the box `home.tick()` builds, on seats of tests/fixtures/akseat.py whose conversations are
written as Claude Code and Codex write them, under invented ids.
"""

from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.hookdrive import conversation
from test_key_seat_tokens_by_type import (CONVERSATION, LAUNCH, REMOTE, T0, THREAD, append, meta,
                                          rows, said, step, tick, turn)


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class AUsageLineSQLiteCannotHold(unittest.TestCase):
    def test_files_nothing_and_the_lines_after_it_count_as_without_it(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])     # no audit, which opens a seat of its own
        acme = Seat(home, "acme", record={"conversation": CONVERSATION,
                                          "repo": str(home.path / "code/acme")})
        append(conversation(home, acme),
               {**said("msg_01far", T0, 1, 0, 0, 0), "timestamp": 2 ** 64 - 1},
               {**said("msg_01past", T0, 1, 0, 0, 0), "timestamp": 10 ** 400},
               said("msg_01\ud800", T0 + 1, 1, 0, 0, 0),
               said("msg_01many", T0 + 2, 2 ** 63, 0, 0, 0),
               said("msg_01odd", T0 + 3, 1, 0, 0, 0, model="claude-\ud800"),
               said("msg_01far", T0 + 4, 3, 1200, 5000, 40))     # its message's next block
        codex = Seat(home, "beta", model="astra", screen="codex-prompt-pane.txt",
                     record={"conversation": THREAD, "codex_launch": LAUNCH,
                             "repo": str(home.path / "code/beta")})
        rollout = (home.path / ".codex/agentkit-seats" / REMOTE
                   / f"sessions/2026/11/05/rollout-2026-11-05T09-00-00-{THREAD}.jsonl")
        append(rollout, meta(T0, THREAD, str(codex.cwd), "cli"), turn(T0 + 1, "gpt-6-astra"),
               step(T0 + 2, 10_000, 6_000, 400), step(T0 + 3, 2 ** 64, 0, 0),
               step(T0 + 4, 14_000, 9_000, 650))
        home.write(f".agentkit/state/codex-launch-{LAUNCH}.json", {
            "launch": LAUNCH, "cwd": str(codex.cwd), "expected": None, "remote": REMOTE,
            "event": {"hook_event_name": "SessionStart", "source": "startup",
                      "session_id": THREAD, "cwd": str(codex.cwd),
                      "transcript_path": str(rollout)}})
        tick(home)
        self.assertEqual(rows(home), {
            "acme": [(4.0, "default", "claude-opus-5-5", 3, 1200, 5000, 40, 6243)],
            "beta": [(2.0, "default", "gpt-6-astra", 4_000, 0, 6_000, 400, 10_400),
                     (4.0, "default", "gpt-6-astra", 1_000, 0, 3_000, 250, 4_250)]})
        # and nothing else, rows() leaving out rows of no tokens
        with closing(sqlite3.connect((home.path / ".agentkit/history.db").as_uri() + "?mode=ro",
                                     uri=True)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM seat_usage").fetchone(), (3,))


if __name__ == "__main__":
    unittest.main()
