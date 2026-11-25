"""A seat's turn is kept as its harness timed it.

A tick files each turn a line of a seat's conversations ends in history.db's `seat_turns`: the
moment the turn ended and its seconds, under the seat's project, login, and the model and effort
it orchestrates with, as a usage row the tick read from that file holds them.  Claude Code writes
a turn's end as an entry of `type` `system` and `subtype` `turn_duration`, its `durationMs` the
turn's length: one whose length is no number of zero or more, or whose moment is none ak reads,
is no turn.  A turn filed stays as first filed: its conversation read again from its start, its
seat moved to another effort meanwhile, files it neither twice nor anew.  A harness whose plugin
reads no turn, as Codex's, files none, even of a line written as Claude Code ends a turn.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each
tick in the box `home.tick()` builds, on seats of tests/fixtures/akseat.py whose conversations
are written as Claude Code and Codex write them, under invented ids.
"""

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.hookdrive import conversation

CONVERSATION = "7c3a9e5a-2d3f-4e4a-9b5c-9f8d4a3e2c01"
ODD = "7c3a9e5a-2d3f-4e4a-9b5c-9f8d4a3e2c02"
THREAD = "019a6043-9e6d-7f32-a041-5dbc8e3f6a03"
LAUNCH, REMOTE = "7" * 32, "8" * 32
T0 = 1_793_955_600      # 2026-11-05 09:00 UTC


def stamp(at):
    """`at` seconds as Claude Code and Codex write a moment: UTC, to the millisecond."""
    return datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="milliseconds")[:-6] + "Z"


def line(session, at, **fields):
    """A line of Claude conversation `session` written at `at`, `fields` over its own."""
    return {"parentUuid": None, "isSidechain": False, "userType": "external",
            "sessionId": session, "version": "2.1.30", "uuid": str(uuid.uuid4()),
            "timestamp": stamp(at), **fields}


def asked(at, words, session=CONVERSATION):
    return line(session, at, type="user", message={"role": "user", "content": words})


def said(message, at, session=CONVERSATION):
    return line(session, at, type="assistant", message={
        "id": message, "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": "Done."}],
        "usage": {"input_tokens": 3, "cache_creation_input_tokens": 1200,
                  "cache_read_input_tokens": 5000, "output_tokens": 40}})


def ended(at, length, session=CONVERSATION, **fields):
    """The entry Claude Code writes as a turn ends at `at`, `length` its `durationMs`."""
    return line(session, at, type="system", subtype="turn_duration", durationMs=length,
                isMeta=False, **fields)


def append(path, *lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        out.write("".join(json.dumps(line) + "\n" for line in lines))


def tick(home):
    done = home.tick()
    assert done.code == 0, done.out + done.err


def filed(home):
    """Each project's turns, as (seconds past T0, seconds, account, orchestrator, effort) rows,
    and the projects any usage was filed under: what shows a conversation was read."""
    turns = {}
    with closing(sqlite3.connect((home.path / ".agentkit/history.db").as_uri() + "?mode=ro",
                                 uri=True)) as db:
        for repo, at, *kept in sorted(db.execute(
                "SELECT repo, at, seconds, account, orchestrator, effort FROM seat_turns")):
            turns.setdefault(repo, []).append((round(at - T0, 3), *kept))
        used = {repo for repo, in db.execute("SELECT repo FROM seat_usage")}
    return turns, used


# acme's two turns, as it orchestrates with opus at its own effort on its own login
TURNS = [(90.0, 90.0, "second", "opus", "low"), (150.5, 30.5, "second", "opus", "low")]


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ASeatsTurnIsKept(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, ["opus", "astra"])     # no audit, which opens a seat of its own
        acme = Seat(home, "acme", record={
            "conversation": CONVERSATION, "repo": str(home.path / "code/acme"),
            "account": "second", "home_account": "second", "efforts": {"opus": {"effort": "low"}}})
        kept = conversation(home, acme)
        append(kept, asked(T0, "Add a retry to the api client"),
               said("msg_01acme", T0 + 85), ended(T0 + 90, 90_000),
               asked(T0 + 120, "And log each retry"))
        odd = Seat(home, "gamma", record={"conversation": ODD,
                                          "repo": str(home.path / "code/gamma")})
        append(conversation(home, odd), asked(T0, "Tidy the readme", ODD),
               said("msg_01gamma", T0 + 5, ODD), ended(T0 + 10, "ninety", ODD),
               ended(T0 + 20, -1, ODD), ended(T0 + 30, True, ODD),
               # a moment with no zone
               ended(T0 + 40, 40_000, ODD, timestamp="2026-11-05T09:00:40.000"))
        codex = Seat(home, "beta", model="astra", screen="codex-prompt-pane.txt",
                     record={"conversation": THREAD, "codex_launch": LAUNCH,
                             "repo": str(home.path / "code/beta")})
        rollout = (home.path / ".codex/agentkit-seats" / REMOTE
                   / f"sessions/2026/11/05/rollout-2026-11-05T09-00-00-{THREAD}.jsonl")
        append(rollout, {"timestamp": stamp(T0), "type": "session_meta", "payload": {
            "id": THREAD, "timestamp": stamp(T0), "cwd": str(codex.cwd), "source": "cli",
            "originator": "codex_cli_rs", "cli_version": "0.163.0", "model_provider": "openai"}},
               {"timestamp": stamp(T0 + 6), "type": "event_msg", "payload": {
                   "type": "token_count", "info": {
                       "total_token_usage": {"input_tokens": 9_000, "output_tokens": 300,
                                             "total_tokens": 9_300},
                       "last_token_usage": {"total_tokens": 9_300},
                       "model_context_window": 272_000}}},
               {"timestamp": stamp(T0 + 8), "type": "event_msg",
                "payload": {"type": "task_complete", "last_agent_message": "Done."}},
               ended(T0 + 8, 8_000, THREAD))
        home.write(f".agentkit/state/codex-launch-{LAUNCH}.json", {
            "launch": LAUNCH, "cwd": str(codex.cwd), "expected": None, "remote": REMOTE,
            "event": {"hook_event_name": "SessionStart", "source": "startup",
                      "session_id": THREAD, "cwd": str(codex.cwd),
                      "transcript_path": str(rollout)}})
        tick(home)
        cls.seen = [filed(home)]
        append(kept, said("msg_02acme", T0 + 148), ended(T0 + 150.5, 30_500))
        tick(home)
        cls.seen.append(filed(home))
        # A new file at the path, a copy of the old, read again from its start; the seat on
        # another effort meanwhile.
        copy = kept.with_suffix(".tmp")
        copy.write_text(kept.read_text())
        os.replace(copy, kept)
        record = home.path / ".agentkit/state/session-acme.json"
        record.write_text(json.dumps({**json.loads(record.read_text()),
                                      "efforts": {"opus": {"effort": "high"}}}))
        tick(home)
        cls.seen.append(filed(home))

    def test_each_turn_claude_code_timed_is_kept_at_its_end_under_its_seat(self):
        self.assertEqual([turns.get("acme") for turns, _ in self.seen[:2]], [TURNS[:1], TURNS])

    def test_a_conversation_read_again_from_its_start_files_nothing_twice_and_changes_nothing(self):
        self.assertEqual(self.seen[2][0], self.seen[1][0])

    def test_a_length_no_number_of_zero_or_more_or_a_moment_ak_cannot_read_is_no_turn(self):
        for turns, used in self.seen:
            self.assertIn("gamma", used, "gamma's conversation was not read")
            self.assertNotIn("gamma", turns)

    def test_a_codex_conversation_files_none(self):
        for turns, used in self.seen:
            self.assertIn("beta", used, "beta's rollout was not read")
            self.assertNotIn("beta", turns)


if __name__ == "__main__":
    unittest.main()
