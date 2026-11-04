"""The scoreboard shows each week's intents: the median hours from the owner's first message
to the done that ends it, over the dones of that week whose start ak knows.  A done reads the
start from the seat's conversation itself (`user_messages`, which leaves ak's own lines out):
the owner's first message since that conversation's previous done.  A rename keeps the
conversation; a name opened anew is a conversation of its own.  The start is unknown with no
message of theirs since, in a harness that reads no messages or cannot read them at that
done, and for the first done of a conversation begun before an older history first kept
dones. The owner's answered waits in each measured intent's conversation and time window,
over those intents' total hours, are their share of that week's intent time. No database: `not recorded`.

Offline: a sandbox HOME with its own history database, a fake seat harness, git answering
nothing.
"""

from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, history, menu, notify, orch, plan, scoreboard, terminal

NOW = 1_800_000_000
WEEK = 7 * 86400
HOUR = 3600


class Harness:
    """A seat's harness, as notify sees it: its conversation and the owner's messages in each."""
    name = "claude"

    def __init__(self):
        self.current, self.said = "c1", []

    def conversation(self, record, cwd):
        return self.current

    def seat_token_sources(self, record):
        return None

    def user_messages(self, record, cwd, conversation, *, seat=None):
        return [{"at": at, "text": "words"} for at, where in self.said if where == conversation]


class IntentRow(Sandbox):
    def setUp(self):
        super().setUp()
        self.harness, self.seats = Harness(), {"fix-api": {"cwd": "/acme"}}
        for target, name, value in ((orch, "seat_plugin", lambda record, **_kw: self.harness),
                                    (config, "session_records", lambda: self.seats),
                                    (menu, "run_records", lambda **_kw: []),
                                    (scoreboard, "_git", lambda *args, **kw: None),
                                    (terminal, "content_width", lambda: 400)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def done(self, seat, at):
        with notify.session_lock(seat) as name:
            plan.write(name, [*plan.lines(name), f"- [x] step {at}"])   # each finishes something
            notify._intent(name, at)

    def test_a_done_starts_at_the_owner_s_first_message_since_the_conversation_s_last_done(self):
        self.harness.said = [(50.0, "c1"), (60.0, "c1"), (900.0, "c1")]   # 900: after the done
        self.done("fix-api", 300.0)
        self.done("fix-api", 350.0)             # no message since: its start is unknown
        self.harness.said += [(400.0, "c1")]
        self.done("fix-api", 500.0)
        # renamed, the seat keeps its conversation, and its next intent begins after 500
        self.seats = {"parser": self.seats.pop("fix-api")}
        self.harness.said += [(600.0, "c1")]
        self.done("parser", 700.0)
        # the name opened anew is a new conversation: its intent begins at its own first message
        self.harness.current = "c2"
        self.harness.said += [(650.0, "c2")]
        self.done("parser", 800.0)
        self.assertEqual([done[:2] for done in history.dones(0, NOW)],
                         [(300.0, 50.0), (350.0, None), (500.0, 400.0), (700.0, 600.0), (800.0, 650.0)])

    def test_a_conversation_begun_before_dones_were_kept_has_no_start_for_its_first(self):
        # a history from before dones were kept: its runs table only, as its first schema made it
        config.HOME.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, final_state TEXT, finished_at REAL)")
        with patch.object(history.time, "time", return_value=1000.0):
            self.assertEqual(history.last_done("claude:c1"), (None, 1000.0, None))
        self.harness.said = [(50.0, "c1"), (1100.0, "c1")]
        self.done("fix-api", 1200.0)            # its done at 100 went unrecorded: no start
        self.harness.said += [(1300.0, "c1")]
        self.done("fix-api", 1400.0)
        # a conversation begun since is known from its first message
        self.harness.current = "c2"
        self.harness.said += [(1500.0, "c2")]
        self.done("fix-api", 1600.0)
        self.assertEqual([done[:2] for done in history.dones(0, NOW)],
                         [(1200.0, None), (1400.0, 1300.0), (1600.0, 1500.0)])

    def test_a_harness_that_reads_no_messages_measures_no_intent(self):
        self.harness.user_messages = lambda *args, **kw: []
        self.done("fix-api", NOW - 2 * HOUR)
        self.done("fix-api", NOW - HOUR)
        with patch.object(scoreboard.time, "time", return_value=NOW):
            self.assertEqual(scoreboard.compute(NOW)["intent"],
                             [{"measured": 0, "hours": None, "live": 0, "live_hours": None,
                               "answer_share": None}] * 2)
            row = [line for line in scoreboard.render() if line.startswith("intent")][0]
        self.assertIn("no intent measured", row)

    def test_a_done_whose_messages_cannot_be_read_has_no_start_and_still_bounds_the_next(self):
        self.harness.said = [(50.0, "c1")]
        with patch.object(self.harness, "user_messages", side_effect=OSError("unreadable")):
            self.done("fix-api", 300.0)
        self.harness.said += [(400.0, "c1")]
        self.done("fix-api", 500.0)
        self.assertEqual([done[:2] for done in history.dones(0, NOW)], [(300.0, None), (500.0, 400.0)])

    def test_each_intent_counts_in_the_week_its_done_fell_in(self):
        self.assertEqual(scoreboard.compute(NOW)["intent"], [None, None])   # no database
        for at, began in ((NOW - HOUR, NOW - 3 * HOUR), (NOW - 2 * HOUR, NOW - 6 * HOUR),
                          (NOW - WEEK, NOW - WEEK - HOUR),        # the boundary: this week's
                          (NOW - 3 * HOUR, None),                  # no start: not measured
                          (NOW - WEEK - HOUR, NOW - WEEK - 4 * HOUR)):
            history.done("claude:c1", at, began)
        with patch.object(scoreboard.time, "time", return_value=NOW):
            self.assertEqual(scoreboard.compute(NOW)["intent"],
                             [{"measured": 3, "hours": 2.0, "live": 0, "live_hours": None, "answer_share": 0},
                              {"measured": 1, "hours": 3.0, "live": 0, "live_hours": None, "answer_share": 0}])
            row = [line for line in scoreboard.render() if line.startswith("intent")][0]
        self.assertIn("3 intents measured, median 2.0 hours from the owner's first message to done", row)
        self.assertIn("0.0% of intent time waiting for the owner's answers", row)

    def test_answer_share_uses_the_measured_intents_total_hours_and_their_own_answers(self):
        for conversation, at, began in (("c1", NOW - HOUR, NOW - 11 * HOUR),
                                        ("c2", NOW - WEEK, NOW - WEEK - 90 * HOUR),
                                        ("c1", NOW - WEEK - HOUR, NOW - 3 * WEEK),
                                        ("c3", NOW - HOUR, None)):
            history.done(f"claude:{conversation}", at, began)
        for conversation, at, kind, hours in (
                ("c1", NOW - 11 * HOUR, "answered", .4),  # both ends of the intent count
                ("c1", NOW - HOUR, "answered", .6),
                ("c2", NOW - WEEK - 3 * HOUR, "answered", 11.8),
                ("c1", NOW - 2 * WEEK - HOUR, "answered", 10),  # before the board's window
                ("c1", NOW - 12 * HOUR, "answered", 100),       # before began
                ("c1", NOW, "answered", 100),                 # after done
                ("c3", NOW - 5 * HOUR, "answered", 100),       # no measured intent
                (None, NOW - 5 * HOUR, "answered", 100),       # an older, unnamed answer
                ("c1", NOW - 5 * HOUR, "asked", 100),
                ("c1", NOW - 5 * HOUR, "paged", 100)):
            self.harness.current = conversation
            history.owner_time(kind, at, hours * HOUR, session="fix-api")
        self.harness.current = "c1"
        with patch.object(self.harness, "name", "muse"):
            history.owner_time("answered", NOW - 5 * HOUR, 100 * HOUR, session="fix-api")
        board = scoreboard.compute(NOW)
        self.assertAlmostEqual(board["intent"][0]["answer_share"], .128)
        self.assertAlmostEqual(board["intent"][1]["answer_share"], 10 / (2 * WEEK / HOUR - 1))
        self.assertEqual(board["intent"][0]["hours"], 50)
        self.assertIn("12.8% of intent time waiting for the owner's answers", "\n".join(scoreboard.render(board)))

    def test_zero_intent_hours_or_an_older_owner_schema_has_no_answer_share(self):
        history.done("claude:c1", NOW, NOW)
        self.assertIsNone(scoreboard.compute(NOW)["intent"][0]["answer_share"])
        with closing(sqlite3.connect(history.path())) as db, db:
            db.execute("UPDATE dones SET began = ?", (NOW - HOUR,))
            db.execute("DROP TABLE owner")
            db.execute(history.OWNER_SCHEMA)
        board = scoreboard.compute(NOW)
        self.assertEqual(board["intent"][0]["hours"], 1)
        self.assertIsNone(board["intent"][0]["answer_share"])
        self.assertNotIn("waiting for the owner's answers", "\n".join(scoreboard.render(board)))


if __name__ == "__main__":
    unittest.main()
