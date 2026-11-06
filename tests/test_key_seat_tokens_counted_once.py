"""Each token a seat spends is counted into history once, from where its harness keeps it.

A tick reads each seat's conversations into history.db's `seat_usage`, a row for each usage
event, its seat's project, moment and tokens: the rows the weekly audit's `tokens` measure sums.
A Claude seat's conversation and its subagents' are where Claude Code keeps them, under
~/.claude/projects/; each message's usage counts once, its four counts summed, however many lines
Claude Code wrote for it.  A Codex seat's rollout is in the seat's own store under
~/.codex/agentkit-seats/, which its launch receipt names; each step of its running total counts
once.  A line still being written counts only once it ends; a conversation replaced at its
path, or one that shrank, is read again from its start; one whose seat went keeps being read.  A
home that never had a seat gets no tables for them.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each
tick in the box `home.tick()` builds, on seats of tests/fixtures/akseat.py whose conversations
are written as Claude Code and Codex write them, under invented ids.
"""

from contextlib import closing
from datetime import datetime, timezone
import json
import os
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

CONVERSATION = "5a1e7c3e-0b1d-4c2e-9f3a-7d6b2e1c0a01"
THREAD = "019a5e21-7c4b-7d10-8e2f-3b9a6c1d4e02"
LAUNCH, REMOTE = "3" * 32, "4" * 32
T0 = 1_793_955_600      # 2026-11-05 09:00 UTC
COUNTS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def stamp(at):
    """`at` seconds as Claude Code and Codex write a moment: UTC, to the millisecond."""
    return datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="milliseconds")[:-6] + "Z"


def moment(line):
    return round(datetime.fromisoformat(line["timestamp"]).timestamp(), 3)


def said(message, at, *counts):
    """A line Claude Code writes for a block of an assistant message, the message's usage on it."""
    return {"parentUuid": None, "isSidechain": False, "userType": "external",
            "sessionId": CONVERSATION, "version": "2.1.30", "type": "assistant",
            "uuid": str(uuid.uuid4()), "timestamp": stamp(at),
            "message": {"id": message, "type": "message", "role": "assistant",
                        "model": "claude-opus-5-5", "content": [{"type": "text", "text": "Done."}],
                        "usage": {**dict(zip(COUNTS, counts)), "service_tier": "standard"}}}


def counted(*lines):
    """The rows Claude lines come to, the Claude seat's: a message's four counts summed, at its
    moment."""
    return sorted(("acme", moment(line), sum(line["message"]["usage"][key] for key in COUNTS))
                  for line in lines)


def total(at, tokens):
    """A Codex rollout's token count: its running total, and the last turn's, which counts not."""
    info = tokens and {"total_token_usage": {"input_tokens": tokens - 100, "output_tokens": 100,
                                             "total_tokens": tokens},
                       "last_token_usage": {"total_tokens": 999_999},
                       "model_context_window": 272_000}
    return {"timestamp": stamp(at), "type": "event_msg",
            "payload": {"type": "token_count", "info": info}}


ASKED = {"type": "user", "uuid": str(uuid.uuid4()), "timestamp": stamp(T0),
         "sessionId": CONVERSATION,
         "message": {"role": "user", "content": "Add a retry to the api client"}}
FIRST = said("msg_01acme", T0 + 5.25, 3, 40, 1200, 5000)
# Claude Code writes a line for each block of a message, its usage on each.
FIRST_AGAIN = {**FIRST, "uuid": str(uuid.uuid4())}
SECOND = said("msg_02acme", T0 + 9.5, 2, 120, 300, 6200)
WRITING = said("msg_03acme", T0 + 14.125, 1, 75, 0, 6500)
CHILD = [said("msg_11acme", T0 + 7.75, 900, 60, 0, 0), said("msg_12acme", T0 + 8.5, 4, 30, 50, 900)]
BEFORE = said("msg_00acme", T0 + 2.5, 5, 10, 20, 30)
SHRUNK = said("msg_13acme", T0 + 20, 1, 2, 3, 4)
# Codex counts before its first turn with no usage yet, and may count one total twice.
STEPS = [total(T0 + 1, None), total(T0 + 6, 12_000), total(T0 + 7, 12_000),
         total(T0 + 11, 20_500)]
STEPPED = [("beta", moment(STEPS[1]), 12_000), ("beta", moment(STEPS[3]), 8_500)]
LATER = total(T0 + 30, 23_000)


def append(path, *lines, end="\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        out.write("".join(json.dumps(line) + end for line in lines))


def tick(home):
    done = home.tick()
    assert done.code == 0, done.out + done.err


def rows(home, project):
    """What history.db holds of a project's seat usage, as (project, moment, tokens) rows; a
    row of no tokens, a step of no growth, adds nothing to the measure."""
    with closing(sqlite3.connect((home.path / ".agentkit/history.db").as_uri() + "?mode=ro",
                                 uri=True)) as db:
        return sorted((repo, round(at, 3), tokens) for repo, at, tokens in db.execute(
            "SELECT repo, at, tokens FROM seat_usage WHERE repo = ? AND tokens > 0", (project,)))


def tables(home):
    """The tables of history.db, if it stands."""
    path = home.path / ".agentkit/history.db"
    if not path.exists():
        return set()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        return {name for name, in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class SeatTokensCountedOnce(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home, cls.bare = home, bare = Home(), Home()
        for each in (home, bare):
            cls.addClassCleanup(each.close)
            akconfig.write(each, ["opus", "astra"])     # no audit, which opens a seat of its own
        claude = Seat(home, "acme", record={"conversation": CONVERSATION,
                                            "repo": str(home.path / "code/acme")})
        # Claude Code's folder for a working directory: each character not an ASCII letter or
        # digit a hyphen, for a path as short as a Home's.
        folder = home.path / ".claude/projects" / re.sub(r"[^A-Za-z0-9]", "-", str(claude.cwd))
        cls.main = folder / f"{CONVERSATION}.jsonl"
        cls.child = folder / CONVERSATION / "subagents/agent-a1b2c3d4e5f6a7b8c.jsonl"
        append(cls.main, ASKED, FIRST, FIRST_AGAIN, SECOND)
        append(cls.main, WRITING, end="")
        append(cls.child, *CHILD)
        codex = Seat(home, "beta", model="astra", screen="codex-prompt-pane.txt",
                     record={"conversation": THREAD, "codex_launch": LAUNCH,
                             "repo": str(home.path / "code/beta")})
        cls.rollout = (home.path / ".codex/agentkit-seats" / REMOTE
                       / f"sessions/2026/11/05/rollout-2026-11-05T09-00-00-{THREAD}.jsonl")
        append(cls.rollout, {"timestamp": stamp(T0), "type": "session_meta", "payload": {
            "id": THREAD, "timestamp": stamp(T0), "cwd": str(codex.cwd), "source": "cli",
            "originator": "codex_cli_rs", "cli_version": "0.163.0", "model_provider": "openai"}},
               *STEPS)
        cls.receipt = home.write(f".agentkit/state/codex-launch-{LAUNCH}.json", {
            "launch": LAUNCH, "cwd": str(codex.cwd), "expected": None, "remote": REMOTE,
            "event": {"hook_event_name": "SessionStart", "source": "startup",
                      "session_id": THREAD, "cwd": str(codex.cwd),
                      "transcript_path": str(cls.rollout)}})
        cls.seen = [cls.ticked()]
        cls.seen.append(cls.ticked())
        with cls.main.open("a") as out:
            out.write("\n")
        cls.seen.append(cls.ticked())
        # A new file at the path, a message ahead of where the last tick stopped reading.
        replacement = cls.main.with_suffix(".tmp")
        replacement.write_text(json.dumps(BEFORE) + "\n" + cls.main.read_text())
        os.replace(replacement, cls.main)
        cls.child.write_text(json.dumps(SHRUNK) + "\n")       # in place, shorter
        # The seat goes as ak takes one away: its record and its launch receipt; its store stays.
        (home.path / ".agentkit/state/session-beta.json").unlink()
        cls.receipt.unlink()
        append(cls.rollout, LATER)
        cls.seen.append(cls.ticked())
        tick(bare)
        cls.bare_tables = tables(bare)

    @classmethod
    def ticked(cls):
        """Each project's rows after a tick."""
        tick(cls.home)
        return {project: rows(cls.home, project) for project in ("acme", "beta")}

    def test_a_claude_seat_counts_each_message_of_its_own_and_subagents_conversations_once(self):
        self.assertEqual(self.seen[0]["acme"], counted(FIRST, SECOND, *CHILD))
        self.assertEqual(self.seen[1], self.seen[0], "a second tick counted more")

    def test_a_line_still_being_written_counts_once_it_ends(self):
        self.assertNotIn(counted(WRITING)[0], self.seen[1]["acme"])
        self.assertEqual(self.seen[2]["acme"], counted(FIRST, SECOND, *CHILD, WRITING))

    def test_a_codex_seat_counts_each_step_of_its_running_total_once(self):
        self.assertEqual(self.seen[0]["beta"], STEPPED)

    def test_a_conversation_replaced_at_its_path_or_shrunk_is_read_from_its_start(self):
        self.assertEqual(self.seen[3]["acme"],
                         counted(BEFORE, FIRST, SECOND, *CHILD, WRITING, SHRUNK))

    def test_a_removed_seats_conversation_is_still_counted(self):
        self.assertEqual(self.seen[3]["beta"], STEPPED + [("beta", moment(LATER), 2_500)])

    def test_a_home_with_no_seats_gets_no_seat_tables(self):
        self.assertFalse(self.bare_tables & {"seat_sources", "seat_usage"}, self.bare_tables)


if __name__ == "__main__":
    unittest.main()
