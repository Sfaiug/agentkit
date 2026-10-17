"""The scoreboard shows each week's intents: those whose seat said done that week, the median
hours from the owner's first message to that done, and to live, when the last of the runs the
seat started in between went live.  The done records its intent from the seat's conversation
itself (`user_messages`, which leaves ak's own lines out): its first message since that
conversation's last done.  A rename keeps the conversation; a name opened anew is a
conversation of its own.  A done whose start ak cannot tell, in a conversation it cannot read
or one older than every done kept, leaves its week's count not recorded.  A new install, with
no database, shows `not recorded`.

Offline: a sandbox HOME with its own history database, a fake seat harness, git answering
nothing.
"""

from pathlib import Path
import unittest
from unittest.mock import patch

from fixtures.sandbox import Sandbox
from agentkit import config, history, menu, notify, orch, scoreboard, terminal

NOW = 1_800_000_000
WEEK = 7 * 86400
HOUR = 3600


class Harness:
    """A seat's harness, as notify sees it: its conversation and the owner's messages in each."""
    name, keeps_owner_messages = "claude", True

    def __init__(self):
        self.current, self.said = "c1", []

    def conversation(self, record, cwd):
        return self.current

    def user_messages(self, record, cwd, conversation, *, seat=None):
        return [{"at": at, "text": "words"} for at, where in self.said if where == conversation]


class IntentRow(Sandbox):
    def setUp(self):
        super().setUp()
        self.harness, self.seats, self.runs = Harness(), {"fix-api": {"cwd": "/acme"}}, []
        for target, name, value in ((orch, "seat_plugin", lambda record: self.harness),
                                    (config, "session_records", lambda: self.seats),
                                    (menu, "run_records", lambda: [
                                        (Path(run), {"launched_session": seat, "started_at": at})
                                        for run, seat, at in self.runs]),
                                    (scoreboard, "_git", lambda *args, **kw: None),
                                    (scoreboard.time, "time", lambda: NOW),
                                    (terminal, "content_width", lambda: 400)):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def done(self, seat, at):
        with notify.session_lock(seat) as name:
            notify._said(name, "done", "shipped", at=at)

    def intents(self):
        return [(each["began_at"], each["done_at"]) for each in history.intents_done(1, NOW)]

    def kept_from_0(self):
        """History holds a done from 0, before those `intents` reads: a conversation begun
        after it had no done before."""
        history.intent("claude:c0", None, 0, [])

    def test_a_done_ends_the_intent_from_the_owner_s_first_message_since_the_last_done(self):
        self.kept_from_0()
        self.harness.said = [(50.0, "c1"), (60.0, "c1")]
        self.runs = [("r-before", "fix-api", 40.0), ("r1", "fix-api", 70.0), ("r-other", "parser", 80.0)]
        self.done("fix-api", 300.0)
        self.done("fix-api", 350.0)             # no message since: ends nothing
        self.assertEqual(self.intents(), [(50.0, 300.0)])
        history.start_run("r1", repo="acme", session="fix-api", started_at=70.0, change="r1")
        history.update_run("r1", live_at=320.0)
        self.assertEqual(history.intents_done(1, NOW)[0]["live_at"], 320.0)
        # renamed, the seat keeps its conversation, and its next intent begins after 300
        self.seats = {"parser": self.seats.pop("fix-api")}
        self.harness.said += [(400.0, "c1")]
        self.done("parser", 500.0)
        self.assertEqual(self.intents(), [(50.0, 300.0), (400.0, 500.0)])
        # the name opened anew is a new conversation: its intent begins at its own first message
        self.harness.current = "c2"
        self.harness.said += [(520.0, "c1"), (550.0, "c2")]
        self.done("parser", 700.0)
        self.assertEqual(self.intents(), [(50.0, 300.0), (400.0, 500.0), (550.0, 700.0)])

    def test_a_conversation_older_than_every_done_kept_ends_its_next_done_with_no_start(self):
        # a done from before intents were kept, the notice since replaced, may have ended 50
        self.harness.said = [(50.0, "c1"), (150.0, "c1")]
        notify.record("fix-api", "done", "shipped", time=100.0)
        notify.record("fix-api", "needs", "Which format?", time=160.0, answered_at=180.0)
        self.done("fix-api", 200.0)
        self.harness.said += [(220.0, "c1")]
        self.done("fix-api", 300.0)
        self.assertEqual(self.intents(), [(None, 200.0), (220.0, 300.0)])

    def test_a_done_ak_cannot_read_leaves_its_week_s_count_not_recorded(self):
        history.intent("claude:c1", NOW - 3 * HOUR, NOW - 2 * HOUR, [])
        self.harness.keeps_owner_messages = False
        self.done("fix-api", NOW - HOUR)
        self.done("fix-api", NOW - HOUR + 60)      # none of the owner's input can be read between
        self.assertEqual(scoreboard.compute(NOW)["intent"][0], {"done": None, "hours": 1.0, "live_hours": None})
        self.assertIn("intent    count not recorded; median 1.0 hours from the first message to done",
                      "\n".join(scoreboard.render()))

    def test_live_is_when_the_last_run_to_start_went_live(self):
        history.start_run("first", repo="acme", started_at=20)
        history.start_run("last", repo="acme", started_at=40)
        history.intent("claude:c1", 10, 80, ["last", "first"])
        history.update_run("first", live_at=100)
        self.assertIsNone(history.intents_done(0, NOW)[0]["live_at"])
        history.update_run("last", live_at=60)
        self.assertEqual(history.intents_done(0, NOW)[0]["live_at"], 60)

    def test_the_week_s_intents_count_by_their_done_with_their_hours_to_done_and_to_live(self):
        history.start_run("r1", repo="acme", session="fix-api", started_at=NOW - 9 * HOUR, change="r1")
        history.update_run("r1", live_at=NOW - 2 * HOUR)
        history.intent("claude:c1", NOW - 10 * HOUR, NOW - 4 * HOUR, ["r1"])
        history.intent("claude:c2", NOW - 5 * HOUR, NOW - 3 * HOUR, [])
        history.intent("claude:c3", NOW - WEEK - 4 * HOUR, NOW - WEEK - 3 * HOUR, [])
        history.intent("claude:c4", NOW - WEEK - 4 * HOUR, NOW - WEEK, [])     # the boundary: this week's
        board = scoreboard.compute(NOW)
        self.assertEqual(board["intent"], [{"done": 3, "hours": 4.0, "live_hours": 8.0},
                                           {"done": 1, "hours": 1.0, "live_hours": None}])
        row = [line for line in scoreboard.render() if line.startswith("intent")][0]
        self.assertIn("3 intents done; median 4.0 hours from the first message to done, 8.0 to live", row)
        self.assertIn("1 intents done; median 1.0 hours from the first message to done", row)
        self.assertNotIn("1.0 hours from the first message to done,", row)

    def test_no_intent_done_and_a_new_install_read_differently(self):
        self.assertIsNone(history.intents_done(NOW - WEEK, NOW))
        self.assertEqual(scoreboard.compute(NOW)["intent"], [None, None])
        self.assertIn("intent    not recorded", "\n".join(scoreboard.render()))
        self.assertIsNone(history.last_done("claude:c1", 50.0))     # a database, but no done kept
        self.assertEqual(scoreboard.compute(NOW)["intent"],
                         [{"done": 0, "hours": None, "live_hours": None}] * 2)
        self.assertIn("intent    no intent done", "\n".join(scoreboard.render()))


if __name__ == "__main__":
    unittest.main()
