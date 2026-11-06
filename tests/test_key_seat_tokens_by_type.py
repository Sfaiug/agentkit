"""Each usage row of a seat's tokens keeps them by type, with the model and login they were
spent on.

A tick files each usage line of a seat's conversations in history.db's `seat_usage`, its tokens
summed, and beside them its counts of input, cache-written, cache-read and output tokens, its
model, and the login of the seat that owns the conversation as the tick reads the line
(`default` for a record naming none).  A Claude line's counts and model are its message's; of
the lines Claude Code writes for one message, the one counting the most is kept.  A Codex step's
counts are the growth of each running count in its rollout's `total_token_usage` since the step
before, its input less the cached and cache-written input it holds, a count the rollout leaves
out being 0; its model is the latest turn's before it in its rollout.  A seat moved to another
login has the lines read after the move filed under that one.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each
tick in the box `home.tick()` builds, on seats of tests/fixtures/akseat.py whose conversations
are written as Claude Code and Codex write them, under invented ids.
"""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

CONVERSATION = "6b2f8d4f-1c2e-4d3f-8a4b-8e7c3f2d1b01"
THREAD = "019a5f32-8d5c-7e21-9f30-4cab7d2e5f01"
CHILD = "019a5f32-9e6d-7f32-a041-5dbc8e3f6a02"
LAUNCH, REMOTE = "5" * 32, "6" * 32
T0 = 1_793_955_600      # 2026-11-05 09:00 UTC


def stamp(at):
    """`at` seconds as Claude Code and Codex write a moment: UTC, to the millisecond."""
    return datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="milliseconds")[:-6] + "Z"


def said(message, at, fresh, written, read, output):
    """A line Claude Code writes for a block of an assistant message, the message's usage on it."""
    return {"parentUuid": None, "isSidechain": False, "userType": "external",
            "sessionId": CONVERSATION, "version": "2.1.30", "type": "assistant",
            "uuid": str(uuid.uuid4()), "timestamp": stamp(at),
            "message": {"id": message, "type": "message", "role": "assistant",
                        "model": "claude-opus-5-5", "content": [{"type": "text", "text": "Done."}],
                        "usage": {"input_tokens": fresh, "cache_creation_input_tokens": written,
                                  "cache_read_input_tokens": read, "output_tokens": output,
                                  "service_tier": "standard"}}}


def turn(at, model):
    """The turn context Codex writes as each turn starts."""
    return {"timestamp": stamp(at), "type": "turn_context", "payload": {
        "cwd": "/tmp", "approval_policy": "never", "model": model, "effort": "high",
        "summary": "auto"}}


def step(at, fresh, cached, output, written=None):
    """A Codex rollout's token count: its running totals, its input holding the cached and
    cache-written input; the last turn's counts, which count not."""
    usage = {"input_tokens": fresh, "cached_input_tokens": cached, "output_tokens": output,
             "reasoning_output_tokens": output // 2, "total_tokens": fresh + output,
             **({} if written is None else {"cache_write_input_tokens": written})}
    return {"timestamp": stamp(at), "type": "event_msg", "payload": {
        "type": "token_count", "info": {"total_token_usage": usage,
                                        "last_token_usage": {"total_tokens": 999_999},
                                        "model_context_window": 272_000}}}


def meta(at, thread, cwd, source):
    return {"timestamp": stamp(at), "type": "session_meta", "payload": {
        "id": thread, "timestamp": stamp(at), "cwd": cwd, "source": source,
        "originator": "codex_cli_rs", "cli_version": "0.163.0", "model_provider": "openai"}}


def append(path, *lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        out.write("".join(json.dumps(line) + "\n" for line in lines))


def tick(home):
    done = home.tick()
    assert done.code == 0, done.out + done.err


def rows(home):
    """Each project's seat usage, as (seconds past T0, account, model, input, cache write, cache
    read, output, tokens) rows; a row of no tokens, a step of no growth, adds nothing."""
    found = {}
    with closing(sqlite3.connect((home.path / ".agentkit/history.db").as_uri() + "?mode=ro",
                                 uri=True)) as db:
        for repo, at, *kept in sorted(db.execute(
                "SELECT repo, at, account, model, input, cache_write, cache_read, output, tokens "
                "FROM seat_usage WHERE tokens != 0")):
            found.setdefault(repo, []).append((round(at - T0, 3), *kept))
    return found


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class SeatTokensByType(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])     # no audit, which opens a seat of its own
        claude = Seat(home, "acme", record={"conversation": CONVERSATION,
                                            "repo": str(home.path / "code/acme")})
        folder = home.path / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(claude.cwd))
        # Claude Code writes a line for each block of a message, a later one counting more.
        append(folder / f"{CONVERSATION}.jsonl", said("msg_01acme", T0 + 5.25, 3, 1200, 5000, 12),
               said("msg_01acme", T0 + 5.25, 3, 1200, 5000, 40))
        codex = Seat(home, "beta", model="astra", screen="codex-prompt-pane.txt",
                     record={"conversation": THREAD, "codex_launch": LAUNCH,
                             "repo": str(home.path / "code/beta")})
        store = home.path / ".codex/agentkit-seats" / REMOTE / "sessions/2026/11/05"
        rollout = store / f"rollout-2026-11-05T09-00-00-{THREAD}.jsonl"
        # Codex counts before its first turn with no usage yet, may count one total twice, and
        # may leave a count out: its growth to the step after it is then all of that count.
        append(rollout, meta(T0, THREAD, str(codex.cwd), "cli"),
               {"timestamp": stamp(T0 + 1), "type": "event_msg",
                "payload": {"type": "token_count", "info": None}},
               turn(T0 + 2, "gpt-6-astra"),
               step(T0 + 6, 10_000, 6_000, 400, written=1_500),
               step(T0 + 7, 10_000, 6_000, 400, written=1_500),
               step(T0 + 9, 14_000, 9_000, 650),
               turn(T0 + 10, "gpt-6.1-sol"),
               step(T0 + 12, 21_000, 14_000, 900, written=1_800))
        # A subagent's thread in the seat's store, on a model and counts of its own, its rollout
        # leaving the cache writes out.
        append(store / f"rollout-2026-11-05T09-00-08-{CHILD}.jsonl",
               meta(T0 + 8, CHILD, str(codex.cwd),
                    {"subagent": {"thread_spawn": {"parent_thread_id": THREAD, "depth": 1}}}),
               turn(T0 + 8, "gpt-6-astra-mini"),
               step(T0 + 11, 3_000, 1_000, 200))
        home.write(f".agentkit/state/codex-launch-{LAUNCH}.json", {
            "launch": LAUNCH, "cwd": str(codex.cwd), "expected": None, "remote": REMOTE,
            "event": {"hook_event_name": "SessionStart", "source": "startup",
                      "session_id": THREAD, "cwd": str(codex.cwd),
                      "transcript_path": str(rollout)}})
        tick(home)
        cls.first = rows(home)
        # The seat moves to another login, its home with it, as ak moves a seat between them.
        record = home.path / ".agentkit/state/session-beta.json"
        record.write_text(json.dumps({**json.loads(record.read_text()),
                                      "account": "second", "home_account": "second"}))
        append(rollout, step(T0 + 30, 25_000, 17_000, 1_000, written=2_400))
        tick(home)
        cls.moved = rows(home)

    def test_a_claude_line_keeps_its_four_counts_its_model_and_its_seats_login(self):
        self.assertEqual(self.first["acme"],
                         [(5.25, "default", "claude-opus-5-5", 3, 1200, 5000, 40, 6243)])

    def test_a_codex_step_is_split_by_type_under_the_model_of_the_turn_before_it(self):
        self.assertEqual(self.first["beta"], [
            (6.0, "default", "gpt-6-astra", 2_500, 1_500, 6_000, 400, 10_400),
            (9.0, "default", "gpt-6-astra", 1_000, 0, 3_000, 250, 4_250),
            (11.0, "default", "gpt-6-astra-mini", 2_000, 0, 1_000, 200, 3_200),
            (12.0, "default", "gpt-6.1-sol", 200, 1_800, 5_000, 250, 7_250)])

    def test_after_a_seat_moves_to_another_login_the_lines_read_next_are_filed_under_it(self):
        self.assertEqual(self.moved["beta"], self.first["beta"] + [
            (30.0, "second", "gpt-6.1-sol", 400, 600, 3_000, 100, 4_100)])
        self.assertEqual(self.moved["acme"], self.first["acme"])


if __name__ == "__main__":
    unittest.main()
