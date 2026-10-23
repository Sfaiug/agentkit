"""The menu lists projects by name and seats by when they were made; a number is a place.

A seat's number is its place on the screen, so the owner opens a seat by the number they saw
last time.  That holds only if the order never hangs on a seat's word: projects by name in byte
order, the seats no project holds yet last, under each heading its seats in the order they were
made, the numbers running on across headings, and a checkout with no seat no heading at all.
Past nine seats a number is two wide and two digits typed together open one seat, while a first
digit no number on the screen starts with opens its seat at once, the keys after it the seat's.
A seat whose record names no repository is filed under the checkout its runs went to, and its
record says so from then on.  Black-box: the program `AK_BIN` names, in a person's terminal
(tests/fixtures/akterm.py) over seats as ak leaves them (tests/fixtures/akseat.py), judged by
what the terminal shows, which seat tmux attaches it to, what each seat's pane received and the
seat records; this test fails against `/bin/false`.
"""

import json
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

KEYS = "esc leave"     # on the key line, the menu's last


def checkout(home, name):
    path = home.path / "code" / name
    done = home.run("git", "init", "-q", str(path))
    assert done.code == 0, done.err
    return path


def listed(screen, heading):
    """The screen's lines from that heading down to the key line, blank lines at the end left
    out; None while it shows neither."""
    lines = [line.rstrip() for line in screen.split("\n")]
    keys = next((at for at, line in enumerate(lines) if KEYS in line), None)
    if heading not in lines or keys is None:
        return None
    block = lines[lines.index(heading):keys]
    while block and not block[-1]:
        block.pop()
    return block


def until(test, bound=30, what="it"):
    deadline = time.monotonic() + bound
    while not (got := test()):
        if time.monotonic() > deadline:
            raise AssertionError(f"{what} never came")
        time.sleep(0.05)
    return got


class Listing(unittest.TestCase):
    def shows(self, term, rows, cursor=True):
        """The menu's rows once it shows them: the first frame is drawn before the seats' looks
        land.  Without `cursor` the highlight's mark is left out, wherever it is."""
        def read(screen):
            block = listed(screen, rows[0])
            return block if cursor or block is None else [row.replace("›", " ") for row in block]
        try:
            term.wait(lambda screen: read(screen) == rows)
        except AssertionError:
            self.assertEqual(read(term.screen()), rows)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ProjectsBySeatsMade(Listing):
    def test_projects_come_by_name_and_under_each_its_seats_in_the_order_made(self):
        with Home() as home:
            now = int(time.time())
            atoll, acme, big = (checkout(home, name) for name in ("atoll", "acme", "ATOLL2"))
            checkout(home, "emptyproj")
            # made the other way round from their names, so only when they were made orders them
            Seat(home, "atoll-a", cwd=atoll, alive=False,
                 record={"repo": str(atoll), "created": now - 3500})
            Seat(home, "atoll-b", cwd=atoll, alive=False,
                 record={"repo": str(atoll), "created": now - 3600})
            Seat(home, "fix-api", cwd=acme, alive=False, record={"repo": str(acme)})
            Seat(home, "big", cwd=big, alive=False, record={"repo": str(big)})
            Seat(home, "scribe", cwd=home.path / "code", alive=False)
            self.shows(Terminal(home, size=(100, 40)), [
                "ATOLL2",
                "› 1  big      Opus 5.5  ○ idle",
                "",
                "acme",
                "  2  fix-api  Opus 5.5  ○ idle",
                "",
                "atoll",
                "  3  atoll-b  Opus 5.5  ○ idle",
                "  4  atoll-a  Opus 5.5  ○ idle",
                "",
                "not assigned yet",
                "  5  scribe   Opus 5.5  ○ idle"])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TwoDigitNumbers(Listing):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        acme, now = checkout(cls.home, "acme"), int(time.time())
        cls.seats = {f"seat{n:02d}": Seat(cls.home, f"seat{n:02d}", cwd=acme,
                                          record={"repo": str(acme), "created": now - 100 + n})
                     for n in range(1, 14)}
        cls.term = Terminal(cls.home, size=(100, 40))

    def attached(self):
        done = self.home.tmux("list-clients", "-F", "#{session_name}")
        return done.out.split() if done.code == 0 else []

    def opens(self, typed, seat, then=""):
        """Type into the menu, and that seat is the one tmux hands the terminal to; `then` is
        what reaches its pane.  The person comes back to the menu after."""
        self.term.wait(KEYS)
        self.term.type(typed)
        try:
            self.assertEqual(until(self.attached, what=f"a seat for {typed!r}"), [seat])
            if then:
                until(self.seats[seat].typed, bound=10, what=f"keys in {seat}")
            self.assertEqual(self.seats[seat].typed(), then)
        finally:
            for name in self.attached():
                self.home.tmux("detach-client", "-s", f"={name}")
            self.term.wait(lambda screen: KEYS in screen and not self.attached())

    def test_past_nine_seats_every_number_is_two_wide(self):
        # the other cases move the highlight to the seat each opened
        self.shows(self.term, ["acme", *(f"  {n:>2}  seat{n:02d}  Opus 5.5  ○ idle"
                                         for n in range(1, 14))], cursor=False)

    def test_two_digits_typed_together_open_one_seat(self):
        self.opens("12", "seat12")

    def test_a_digit_that_could_start_a_number_alone_opens_its_own_seat(self):
        self.opens("1", "seat01")

    def test_a_digit_no_number_starts_with_opens_its_seat_and_the_next_key_is_the_seats(self):
        self.opens("7", "seat07")
        self.opens("99", "seat09", then="9")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class FiledByItsRuns(Listing):
    def test_a_seat_naming_no_repository_is_filed_where_its_runs_went(self):
        with Home() as home:
            atoll2, now = checkout(home, "atoll2"), int(time.time())
            # no repo at all, and the one the menu writes while no run of the seat has voted
            for name, record, run in (("loose", {"created": now - 700}, "20260101-0900-a"),
                                      ("stray", {"repo": None, "created": now - 600},
                                       "20260101-0910-b")):
                Seat(home, name, model="fable", cwd=home.path / "code" / "x", record=record)
                home.write(f".agentkit/runs/{run}/run.json",
                           {"state": "pass", "merged": True, "launched_session": name,
                            "repo": str(atoll2)})
            term = Terminal(home, size=(100, 40))
            self.shows(term, ["atoll2",
                              "› 1  loose  Fable 5.1  ○ idle",
                              "  2  stray  Fable 5.1  ○ idle"])
            term.keys("Escape")
            term.exit_code()      # read once the menu has ended, no write of its on the way
            for name in ("loose", "stray"):
                record = json.loads(
                    (home.path / f".agentkit/state/session-{name}.json").read_text())
                self.assertEqual(record.get("repo"), str(atoll2), name)


if __name__ == "__main__":
    unittest.main()
