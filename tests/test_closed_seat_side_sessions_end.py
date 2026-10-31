"""Once ak forgets a seat, the tick saves and closes its side sessions, live panes and all.

A seat's own sessions for a dev server, a build or a long test are tagged with its name, which
a rename leaves as it was.  While ak holds the seat, by a record (closed, renamed) or a session
in tmux, they stay, as does a session no seat tagged and one whose seat ak cannot tell.
Offline: the tick sees a fake tmux and a temporary HOME (tests/fixtures/sidesessions.py).
"""

import json
import unittest
from unittest.mock import patch

from fixtures.sidesessions import SideSessions
from agentkit import config, orch

LIVE = (None,)


class ForgottenSeat(SideSessions):
    def record(self, name, data):
        config.session_path(name).write_text(json.dumps(data))

    def test_a_forgotten_seat_s_sessions_close_with_their_screens_saved(self):
        self.record("gone", {})
        self.record("old", {"renamed": "new"})
        self.record("new", {})
        self.add("$1", "dev", LIVE, owner="gone")
        self.add("$2", "build", (None, 3600), owner="old")
        self.tick()
        self.assertEqual(self.closed, [])
        for name in ("gone", "new"):
            orch.forget_seat(name, {})
        self.add("$3", "orphan", LIVE, owner="$1")     # a seat named as tmux names an id
        self.tick()
        self.assertEqual(self.closed, ["$1", "$2", "$3"])
        screens = "".join(path.read_text() for path in config.TMP.glob("tmux-*.txt"))
        for pane in ("%0", "%10", "%11", "%20"):
            self.assertIn(f"  last screen {pane}  \n\n", screens)
        closes = [line for line in self.messages if line.startswith("closed ")]
        self.assertEqual(len(closes), 3, self.messages)
        self.assertIn("closed dev, a side session gone started", closes[0])
        self.assertIn("closed build, a side session old started", closes[1])

    def test_a_seat_ak_still_holds_or_cannot_tell_keeps_them(self):
        self.add("$1", "live", LIVE, mark="1", owner="")
        self.add("$2", "live-dev", LIVE, owner="live")
        self.record("shut", {})
        (config.STATE / "seat-shut.json").write_text(json.dumps({"closed_by_owner": True}))
        self.add("$3", "shut-dev", LIVE, owner="shut")
        self.record("was", {"renamed": "now"})
        self.record("now", {})
        self.add("$4", "was-dev", LIVE, owner="was")
        self.add("$5", "by-hand", LIVE, owner="")
        config.session_path("blurred").write_text("{")
        self.add("$6", "blurred-dev", LIVE, owner="blurred")
        self.record("loop-a", {"renamed": "loop-b"})
        self.record("loop-b", {"renamed": "loop-a"})
        self.add("$7", "loop-dev", LIVE, owner="loop-a")
        # a pointer stands for the seat until ak removes it, though it leads to no record
        self.record("left", {"renamed": "nowhere"})
        self.add("$8", "left-dev", LIVE, owner="left")
        config.session_path("linked").symlink_to(self.root / "no-such-record")
        self.add("$9", "linked-dev", LIVE, owner="linked")
        # a seat of the owner's own tmux server, which this one's listing does not hold
        self.enterContext(patch.object(orch, "sessions", return_value=[{"name": "legacy"}]))
        self.add("$10", "legacy-dev", LIVE, owner="legacy")
        self.add("$11", "$99", LIVE, owner="")
        self.add("$12", "dollar-dev", LIVE, owner="$99")
        self.tick()
        self.assertEqual(self.closed, [])
        self.assertEqual(list(config.TMP.glob("tmux-*.txt")), [])

    def test_a_record_no_parser_can_hold_stops_no_other_close(self):
        config.session_path("huge").write_text('{"seen":' + "1" * 5000 + "}")
        self.add("$1", "huge-dev", LIVE, owner="huge")
        config.session_path("deep").write_text("[" * 200000)
        self.add("$2", "deep-dev", LIVE, owner="deep")
        self.add("$3", "finished")
        self.tick()
        self.assertEqual(self.closed, ["$3"])

    def test_a_seat_appearing_while_screens_are_saved_keeps_them(self):
        for appears in (lambda: self.add("$2", "gone", LIVE, owner="", mark="1"),
                        lambda: self.record("gone", {})):
            self.add("$1", "dev", LIVE, owner="gone")
            self.after_capture = appears
            self.tick()
            self.assertEqual(self.closed, [])
            self.sessions.pop("$2", None)
            config.session_path("gone").unlink(missing_ok=True)

    def test_a_tmux_that_cannot_be_asked_proves_no_seat_gone(self):
        self.add("$1", "dev", LIVE, owner="gone")
        refused = (1, "error connecting to /tmp/tmux-1000/agentkit-test (Permission denied)")
        with patch.object(orch, "tmux_out", side_effect=lambda *args, **kw: refused
                          if args[0] == "list-sessions" else self.tmux(*args, **kw)):
            self.tick()
        self.assertEqual(self.closed, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
