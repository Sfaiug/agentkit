"""A seat's models page holds each effort stepped on it, with where it began, and applies what it
holds once, as it closes or before a model is picked on it: the owner (17 Nov 2026), "see the
closing of the hover menu as kind of like 'apply'".  It holds no mark: one made is in the seat's
record before the page closes, and the close applies nothing of it.  Black-box: `AK_BIN`, as the
popup over a seat on Opus 5.5 at `xhigh` in every role (tests/fixtures/akseat.py); fails against
`/bin/false`.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal

SEAT = "acme-fix"
KEYS = "  ↑↓←→ move   ␣ mark   r your runs   esc back"
LEVELS = ("low", "medium", "high", "xhigh", "max")      # Claude's, Space going up and round
# each role's effort key, as Opus's row orders them, and the keys from its first mark onto its own
ROLES = {"effort": (), "exec_effort": ("Right", "Right"), "review_effort": ("Right",) * 4}
OFFLINE = {name: "http://127.0.0.1:9"
           for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}


def drawn(screen):
    row = next(line for line in screen.split("\n") if line.lstrip("› ").startswith("Opus 5.5"))
    return dict(zip(ROLES, (word for word in row.split() if word in LEVELS)))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EffortsApplyWhenThePageCloses(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        fakeadapter.install(home, claude="pass", codex="pass")
        akconfig.write(home, ["opus", "fable"], workers=["opus"])
        self.seat = Seat(home, SEAT, model="opus", record={
            "reviewers": ["opus"], "efforts": {"opus": {"effort": "xhigh"}}})
        self.path = home.path / ".agentkit" / "state" / f"session-{SEAT}.json"
        self.term = Terminal(home, "attach", "--overlay", size=(100, 30),
                             env={"NO_COLOR": "1", "AGENTKIT_SESSION": SEAT, **OFFLINE})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", self.term.pane, "sleep 86400",
                        server=SERVER)
        self.term.wait("esc leave")
        self.opened()

    def opened(self, *when):
        self.term.keys("c")
        self.term.wait(lambda screen: KEYS in screen and "› Opus 5.5" in screen
                       and all(drawn(screen)[role] == word for role, word in when))

    def record(self):
        return json.loads(self.path.read_text())

    def says(self, role):
        efforts = self.record()["efforts"]["opus"]
        return efforts.get(role, efforts["effort"])

    def saved(self, role, effort, **fields):
        """Another writer saves Opus's `role` at `effort`, and `fields`, in one swap."""
        record = {**self.record(), **fields}
        record["efforts"]["opus"][role] = effort
        swap = self.path.with_suffix(".swap")
        swap.write_text(json.dumps(record))
        swap.replace(self.path)

    def until(self, holds, what):
        deadline = time.monotonic() + 300   # as long as `Seat.wait_lines` waits
        while not holds():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.1)

    def typed(self):
        live = self.home.path / ".agentkit" / "state" / f"seat-{SEAT}.json"
        self.until(lambda: not live.exists() or not json.loads(live.read_text()).get(
            "owed_lines"), "a line is still owed to the seat")
        return self.seat.lines()

    def step(self, role, *words):
        """Space on Opus's `role` effort, the keys on it, `words` drawn there in turn."""
        for word in words:
            self.term.keys("Space")
            self.term.wait(lambda screen: drawn(screen)[role] == word)

    def picked_and_back(self, role):
        """Fable 5.1 picked for `role` and back, the keys from Opus's `role` effort and onto it."""
        group = {"effort": "orchestrator", "exec_effort": "workers", "review_effort": "reviewers"}
        self.term.keys("Left", "Down", "Space")     # Fable 5.1's mark
        self.until(lambda: "fable" in self.record()[group[role]], "Fable was never picked")
        # Opus's mark takes the orchestrator back; Fable's own lets it go from a group
        self.term.keys(*(("Up", "Space") if role == "effort" else ("Space", "Up")))
        self.until(lambda: "fable" not in self.record()[group[role]], "Fable never left")
        self.term.keys("Right")

    def closed(self):
        self.term.keys("Escape")
        self.term.wait("esc leave")

    def test_three_steps_and_esc_put_one_effort_line_in_the_seat_the_last_one(self):
        record = self.path.read_bytes()
        self.term.keys("Right")
        self.step("effort", "max", "low", "medium")
        self.assertEqual(self.path.read_bytes(), record)     # held: the record as it was
        self.closed()
        self.assertEqual(self.says("effort"), "medium")
        self.assertEqual(self.seat.wait_lines(1), ["/effort medium"])
        self.assertEqual(self.typed(), ["/effort medium"])

    def test_an_effort_held_for_the_orchestrator_another_window_left_is_saved_alone(self):
        self.term.keys("Right")
        self.step("effort", "max")
        self.saved("effort", "xhigh", orchestrator="fable")
        self.closed()
        self.assertEqual(self.record()["orchestrator"], "fable")
        self.assertEqual({role: self.says(role) for role in ROLES},
                         {"effort": "max", "exec_effort": "xhigh", "review_effort": "xhigh"})
        self.assertEqual(self.typed(), [])

    def test_a_step_back_to_where_it_began_leaves_what_another_writer_saved(self):
        for role, keys in ROLES.items():
            with self.subTest(role=role):
                self.term.keys(*keys, "Right")
                self.step(role, "max")
                self.saved(role, "medium")
                # up and round to xhigh, where it began: the record's own, medium, again
                self.step(role, "low", "medium", "high", "medium")
                self.closed()
                self.assertEqual(self.says(role), "medium")
                self.assertEqual(self.typed(), [])
                self.saved(role, "xhigh")
                self.opened((role, "xhigh"))

    def test_a_model_picked_applies_what_is_held_and_the_page_then_holds_nothing(self):
        for role, keys in ROLES.items():
            with self.subTest(role=role):
                self.term.keys(*keys, "Right")
                self.step(role, "max")
                self.picked_and_back(role)
                self.assertEqual(self.says(role), "max")
                self.step(role, "low", "medium", "high", "xhigh")
                self.closed()
                self.assertEqual(self.says(role), "xhigh")
                self.opened()

    def test_a_mark_is_saved_before_the_page_closes_and_the_close_applies_nothing(self):
        self.term.keys("Down", "Right", "Space")     # Fable 5.1's build mark
        self.until(lambda: self.record()["workers"] == ["opus", "fable"], "the mark was not saved")
        self.closed()
        self.assertEqual(self.record()["workers"], ["opus", "fable"])


if __name__ == "__main__":
    unittest.main()
