"""The menu's past sessions screen, `p`: the seats the owner stopped, removed or reopened there.

A stopped seat keeps its record and its conversation, so it can come back where it stopped; it
leaves its project's rows on the main screen for this one, numbered from 1 there, and
`p past` is a key only while there is such a seat.  `x` there removes the seat for good, all but
the stop mark a hand-back of its runs still reads.  Enter asks its harness's adapter for the
command that reopens its own conversation and puts the owner in the seat; an adapter that gives
none leaves the seat stopped and says so.  Black-box: the program `AK_BIN` names runs in a
person's terminal (tests/fixtures/akterm.py) beside a live seat (tests/fixtures/akseat.py), and
a fake Claude adapter, named to ak by `AGENTKIT_ADAPTER_DIR`, keeps what it was asked.
"""

import json
import shlex
import sys
import time
import tomllib
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

ADAPTER = """#!/bin/sh
[ "$1" = interactive ] || exit 1
{python} -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@" >>{asked}
printf '%s' {command}
"""
HARNESS = "sh -c 'echo the harness is back; exec sleep 300'\n"
PAST_KEYS = "  ↑↓←→ move   ⏎ reopen   x remove   esc back"


class Stopped:
    """In `home`, a live seat, fix-api, and one the owner stopped 2.5 hours ago, beta, both of
    the project acme; and the menu open on a 100x30 terminal, the adapter printing `command`."""

    def __init__(self, home, command):
        self.home = home
        self.checkout = home.path / "code/acme"
        self.checkout.mkdir(parents=True)
        assert home.run("git", "init", "-q", str(self.checkout)).code == 0
        Seat(home, "fix-api", cwd=self.checkout, record={"repo": str(self.checkout)})
        home.write(".agentkit/state/session-beta.json", {
            "orchestrator": "fable", "workers": ["fable"], "cwd": str(self.checkout),
            "repo": str(self.checkout), "created": int(time.time()) - 90000,
            "conversation": "conv-beta", "id_source": "launcher", "resumable": True,
            "session_title": "beta"})
        self.mark = {"stopped_at": time.time() - 9000, "closed_by_owner": True}
        home.write(".agentkit/state/seat-beta.json", self.mark)
        home.write(".agentkit/state/rulebook-beta.md", "the rules beta was opened on\n")
        self.asked = home.root / "adapter-asked.log"
        adapters = home.root / "adapters"
        adapters.mkdir()
        adapters.joinpath("claude.sh").write_text(ADAPTER.format(
            python=shlex.quote(sys.executable), asked=shlex.quote(str(self.asked)),
            command=shlex.quote(command)))
        adapters.joinpath("claude.sh").chmod(0o755)
        self.menu = Terminal(home, size=(100, 30), env={"AGENTKIT_ADAPTER_DIR": str(adapters)})

    def state(self, name):
        return self.home.path / ".agentkit/state" / name

    def mark_now(self):
        return json.loads(self.state("seat-beta.json").read_text())

    def to_past(self):
        self.menu.wait(lambda screen: main_screen(screen) and "p past" in screen)
        self.menu.keys("p")
        # its rows can come a frame before its title
        return self.menu.wait(lambda screen: PAST_KEYS in screen
                              and screen.startswith("agentkit · past sessions"))


def main_screen(screen):
    return "esc leave" in screen and "fix-api" in screen


def last_line(screen):
    return screen.rstrip().split("\n")[-1]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class PastSessions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = Home()
        cls.addClassCleanup(home.close)
        cls.seats = seats = Stopped(home, HARNESS)
        cls.main = seats.menu.wait(lambda screen: main_screen(screen) and "p past" in screen)
        cls.past = seats.to_past()
        seats.menu.keys("Escape")
        cls.back = seats.menu.wait(main_screen)
        seats.to_past()
        seats.menu.keys("x")
        seats.menu.wait("Remove beta from past sessions?")
        seats.menu.keys("Down", "Enter")
        cls.removed = seats.menu.wait(lambda screen: main_screen(screen)
                                      and "p past" not in screen)

    def test_a_stopped_seat_has_no_row_on_the_main_screen_and_p_past_is_offered(self):
        self.assertNotIn("beta", self.main)
        self.assertIn("1  fix-api  Opus 5.5", self.main)
        self.assertIn("p past", last_line(self.main))

    def test_p_lists_it_under_the_day_it_closed_numbered_from_1(self):
        lines = [line.rstrip() for line in self.past.split("\n")]
        self.assertTrue(lines[0].startswith("agentkit · past sessions"), lines[0])
        row = next(n for n, line in enumerate(lines) if line.startswith("› 1  beta  acme  no plan"))
        self.assertIn(lines[row - 1], ("today", "yesterday"))
        self.assertNotIn("fix-api", self.past)
        # the usage is the main screen's: no subscription's cell is drawn here
        self.assertNotIn("Claude", self.past)
        self.assertEqual(last_line(self.past), PAST_KEYS)

    def test_esc_goes_back_to_the_main_screen(self):
        self.assertTrue(self.back.startswith("agentkit "), self.back)
        self.assertNotIn("past sessions", self.back)
        self.assertIn("p past", last_line(self.back))

    def test_x_removes_the_seat_all_but_its_stop_mark(self):
        self.assertFalse(self.seats.state("session-beta.json").exists())
        self.assertFalse(self.seats.state("rulebook-beta.md").exists())
        mark = self.seats.mark_now()
        self.assertEqual({key: mark.get(key) for key in self.seats.mark}, self.seats.mark)
        self.assertTrue(self.seats.state("session-fix-api.json").exists())

    def test_with_the_last_one_removed_the_menu_is_back_without_p_past(self):
        self.assertNotIn("beta", self.removed)
        self.assertNotIn("past sessions", self.removed)
        self.assertNotIn("p past", last_line(self.removed))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EnterReopens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = Home()
        cls.addClassCleanup(home.close)
        cls.seats = seats = Stopped(home, HARNESS)
        seats.to_past()
        seats.menu.keys("Enter")
        seats.menu.wait("the harness is back")      # the owner is in the seat

    def tmux_says(self, form):
        return self.seats.home.tmux("display-message", "-p", "-t", "=beta:", form).out.strip()

    def test_the_adapter_is_asked_for_the_seat_s_own_conversation(self):
        config = self.seats.home.path / ".agentkit/config.toml"
        fable = tomllib.loads(config.read_text())["models"]["fable"]
        asked = [json.loads(line) for line in self.seats.asked.read_text().splitlines()]
        # Claude never wrote conv-beta in this Home, so it is handed over as one to open
        self.assertEqual(asked, [["interactive", fable["model"], fable["effort"], "conv-beta",
                                  "new"]])

    def test_the_seat_is_back_in_tmux_where_it_ran_and_the_owner_is_in_it(self):
        self.assertEqual(self.tmux_says("#{@ak_orch}"), "1")
        self.assertEqual(self.tmux_says("#{session_path}"), str(self.seats.checkout))
        clients = self.seats.home.tmux("list-clients", "-F", "#{client_session}").out.split()
        self.assertEqual(clients, ["beta"])

    def test_it_is_no_longer_stopped(self):
        mark = self.seats.mark_now()
        self.assertFalse(mark.get("stopped_at"), mark)
        self.assertFalse(mark.get("closed_by_owner"), mark)
        self.assertTrue(self.seats.state("session-beta.json").exists())


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AnAdapterWithNoCommand(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = Home()
        cls.addClassCleanup(home.close)
        cls.seats = seats = Stopped(home, "")
        seats.to_past()
        seats.menu.keys("Enter")
        cls.note = seats.menu.wait(lambda screen: last_line(screen) == "esc back")
        seats.menu.keys("Escape")
        cls.back = seats.menu.wait(main_screen)

    def test_a_note_says_the_resume_failed_for_that_model_and_esc_goes_back(self):
        asked = [json.loads(line) for line in self.seats.asked.read_text().splitlines()]
        self.assertEqual([call[0] for call in asked], ["interactive"])
        self.assertTrue(self.note.startswith("resume: "), self.note)
        self.assertIn("fable", self.note.split("\n")[0])
        self.assertEqual(last_line(self.note), "esc back")

    def test_the_seat_is_not_started_and_stays_stopped(self):
        self.assertNotEqual(self.seats.home.tmux("has-session", "-t", "=beta").code, 0)
        self.assertEqual(self.seats.mark_now()["stopped_at"], self.seats.mark["stopped_at"])

    def test_esc_goes_back_to_the_main_screen_still_offering_p_past(self):
        self.assertNotIn("beta", self.back)
        self.assertIn("p past", last_line(self.back))


if __name__ == "__main__":
    unittest.main()
