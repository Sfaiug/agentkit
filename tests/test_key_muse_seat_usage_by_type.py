"""A Muse seat's own model request is one usage row, under its model and its tokens by type.

Muse logs each request a log's own session asks twice: a `goal_usage_attribution` of its counts,
which names no model, then right after it a `model_completed` naming the model under the same
counts.  A tick files the completion alone: dated when Muse recorded it, its input less what it
says it cached, that under cache read, no cache write, and its output, the tokens their sum; a
tick read between the two lines files the request once all the same.  A parent's log attributes
its reminder children's requests and completes none: each such attribution is a row by itself, its
counts split as a completion's are, the tokens their sum, and no model, as it names none.  A child
keeping a log of its own, `subagent/<id>/session.jsonl` beside its parent's, completes its request
there too; a tick reads the seat's session logs alone, so that request is one row all the same,
its parent's line.

Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, each
tick in the box `home.tick()` builds, on a seat of tests/fixtures/akseat.py whose session logs
are written as Muse writes them, under invented ids and models.
"""

from contextlib import closing
import itertools
import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

SESSION = "01a1f0c2-6a10-7c31-9e41-acme00000001"
CHILD = "01a1f0c2-7b20-7d42-8f52-acme00000002"    # a reminder child keeping a log of its own
RUN = "01a1f0c2-6b11-7e53-a063-acme00000003"
LAUNCH = "7" * 32
T0 = 1_795_078_800      # 2026-11-19 09:00 UTC
IDS = (f"01a1f0c2-0000-7000-8000-{n:012d}" for n in itertools.count())


def line(session, at, event):
    """A line of that session's log: one event of its run, recorded `at` seconds past T0."""
    return {"schema_version": 1, "id": next(IDS), "stream": {"kind": "session", "id": session},
            "recorded_at": int((T0 + at) * 1_000_000), "record_type": "event",
            "durability": "durable", "payload_type": "runtime.session", "payload_schema_version": 1,
            "payload": {"kind": "run", "run_id": RUN, "event": event}}


def attributed(log, at, owner, asking, spent_in, spent_out, cached):
    """Muse's attribution of a request that `owner`'s session made asking as `asking`."""
    kind = {"main": "main_root"}.get(asking, f"{asking}_child")
    return line(log, at, {"kind": "goal_usage_attribution", "record": {
        "goal_attribution": {"mode": "none"}, "schema_version": 1, "usage_family": "provider",
        "usage_id": f"usage-{next(IDS)}",
        "owner": {"owner_id": "main-root" if asking == "main" else owner, "owner_type": kind,
                  "requester_kind": asking, "run_id": RUN, "session_id": owner},
        "quantity": {"cached_tokens": cached, "input_tokens": spent_in, "main_llm_steps": 1,
                     "output_tokens": spent_out, "reasoning_tokens": spent_out // 2,
                     "reported": True, "unit": "tokens"}}})


def completed(log, at, model, spent_in, spent_out, cached):
    """The completion Muse writes right after attributing a request of its log's own."""
    return line(log, at, {"kind": "model_completed", "model": model, "duration_ms": 2100,
                          "estimated_prompt_tokens": spent_in, "usage": {
        "cache_read_tokens": cached, "cache_write_tokens": 0, "cached_tokens": cached,
        "input_tokens": spent_in, "output_tokens": spent_out,
        "reasoning_tokens": spent_out // 2}})


def append(path, *lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        out.write("".join(json.dumps(each) + "\n" for each in lines))


def tick(home):
    done = home.tick()
    assert done.code == 0, done.out + done.err


def rows(home):
    """The seat's usage, as (seconds past T0, model, input, cache write, cache read, output,
    tokens) rows."""
    with closing(sqlite3.connect((home.path / ".agentkit/history.db").as_uri() + "?mode=ro",
                                 uri=True)) as db:
        return [(round(at - T0, 3), *kept) for at, *kept in sorted(db.execute(
            "SELECT at, model, input, cache_write, cache_read, output, tokens FROM seat_usage "
            "WHERE repo = 'acme'"))]


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class MuseSeatUsageByType(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        akconfig.write(home, {"orbit": "muse"})
        Seat(home, "acme", model="orbit", screen="muse-prompt-pane.txt",
             record={"muse_launch": LAUNCH, "repo": str(home.path / "code/acme")})
        home.write(f".agentkit/state/muse-launch-{LAUNCH}/session", SESSION)
        folder = home.path / f".local/share/muse/sessions/2026/11/19/{SESSION}"
        cls.log = folder / "session.jsonl"
        # The tick comes between the second request's attribution and its completion.
        append(cls.log, attributed(SESSION, 1, SESSION, "main", 33_260, 15, 33_140),
               completed(SESSION, 3, "orbit-2", 33_260, 15, 33_140),
               attributed(SESSION, 5, RUN, "reminder", 19, 4, 7),
               attributed(SESSION, 6, CHILD, "reminder", 4_313, 715, 0),
               attributed(SESSION, 7, SESSION, "main", 40_000, 500, 30_000))
        append(folder / f"subagent/{CHILD}/session.jsonl",
               attributed(CHILD, 6, CHILD, "reminder", 4_313, 715, 0),
               completed(CHILD, 6.5, "orbit-2-mini", 4_313, 715, 0))
        tick(home)
        cls.first = rows(home)
        append(cls.log, completed(SESSION, 9, "orbit-3", 40_000, 500, 30_000))
        tick(home)
        cls.second = rows(home)

    def test_its_own_request_is_one_row_under_its_completion_s_model_and_four_counts(self):
        self.assertIn((3.0, "orbit-2", 120, 0, 33_140, 15, 33_275), self.first)

    def test_a_tick_between_its_attribution_and_its_completion_files_it_once(self):
        self.assertEqual(self.second, sorted(self.first + [
            (9.0, "orbit-3", 10_000, 0, 30_000, 500, 40_500)]))

    def test_a_request_a_log_attributes_to_another_session_is_filed_with_its_four_counts(self):
        self.assertIn((5.0, None, 12, 0, 7, 4, 23), self.first)

    def test_a_request_of_a_child_that_keeps_a_log_is_one_row_its_parent_s_line(self):
        self.assertEqual(self.first, [(3.0, "orbit-2", 120, 0, 33_140, 15, 33_275),
                                      (5.0, None, 12, 0, 7, 4, 23),
                                      (6.0, None, 4_313, 0, 0, 715, 5_028)])


if __name__ == "__main__":
    unittest.main()
