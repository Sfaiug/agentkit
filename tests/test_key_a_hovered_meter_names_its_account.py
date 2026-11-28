"""The line under the usage grid names the account of the meter the pointer is on.

The owner (24 Nov 2026), of the meters on the ak screen: "when I hover above a meter here, I
would like to see which account it is."  On the ak screen and `c` the line reads the label,
then the login's email as ak keeps it, dim as a note is, then the notes it gave before, bytes
kept as read with surrogateescape written back as they came; a login with no email kept, or one
kept as a number, only spaces or what the menu's stream cannot write, reads as before, and one
kept as a number opens on Subscriptions, its meter clicked, with no email to say.  A login
that ends soon reads as before, its own note naming the email once, or none where there is no
email to say, and only its meter is amber.  Too narrow for every note, the email is the last to give way.  The email and the ending
are one read's: the logins changed between the grid's read and the line's draw, the line tells
of the logins the grid was drawn from.
Black-box: `AK_BIN`'s menu in a terminal (tests/fixtures/akterm.py) over six Claude logins
holding the same reading in a temporary HOME (TZ=UTC), their harness faked
(tests/fixtures/fakeadapter.py), each cell judged by its look (tests/fixtures/aklooks.py); the
race in a child python3 of Python ak's own `c` meters, which no claim of Go's reaches.  This
test fails against `/bin/false`.
"""

import json
import re
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import ink, looks, plain
from fixtures.akterm import SERVER, Terminal

TESTS = Path(__file__).resolve().parent
DAY = 86400
LOGINS = ["default", "second", "third", "fourth", "fifth", "sixth"]   # Claude I to VI
EMAIL = "reef@acme.test"
METER = re.compile(r"[━╸─]+  \d+% left")
# `c`'s meters, the highlight on the first, the logins changed to sys.argv[2] by another
# process the moment after each read of them.
RACE = """import sys
sys.path[:0] = sys.argv[1:2]
from agentkit import config, logins, menu
read = logins.read

def changed():
    found = read()
    logins.path().write_text(sys.argv[2])
    return found
logins.read = changed
print(menu.config_meters(config.load(), 1)[0][-1])
"""


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def under_grid(screen):
    """The line under the usage grid: what the meter the pointer is on says."""
    shown = lines(screen)
    return shown[max(number for number, line in enumerate(shown) if METER.search(line)) + 1]


def login(email, ends=60 * DAY):
    return {"email": email, "ends": int(time.time() + ends), "plan": None,
            "checked_at": time.time()}


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AHoveredMeterNamesItsAccount(unittest.TestCase):
    def open(self, ends=60 * DAY, size=(120, 40), others=60 * DAY):
        """The menu over Claude I to VI, each holding a reset and a week resetting in two days:
        Claude I's login `EMAIL`'s, ending `ends` seconds from now; Claude II's email kept as a
        number, Claude III's as spaces, nothing kept of Claude IV's, Claude V's holding a lone
        surrogate, which JSON keeps and UTF-8 cannot write, and Claude VI's kept as an adapter's
        UTF-8 bytes read with surrogateescape, which the menu's stream writes back, those of
        Claude II, III, V and VI ending `others` seconds from now."""
        self.home = Home()
        self.addCleanup(self.home.close)
        akconfig.write(self.home, {"fable": "claude"}, providers={
            "anthropic": {"mode": "subscription", "accounts": LOGINS}})
        now = time.time()
        answer = {"meters": [{"name": "weekly", "used": 40, "window_secs": 604800,
                              "resets_at": now + 2 * DAY}], "resets": 1, "error": None}
        # what a probe of any of them reads, the reading already kept
        fakeadapter.install(self.home, claude="pass")["claude"].answer("usage", json.dumps(answer))
        reading = {**answer, "fetched_at": now}
        self.home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {
            "anthropic": {**reading, "accounts": {name: reading for name in LOGINS}}}})
        self.home.write(".agentkit/state/logins.json", {"anthropic": {
            "default": login(EMAIL, ends), "second": login(5, others),
            "third": login(" \t ", others), "fifth": login("ops\ud800@acme.test", others),
            "sixth": login("zoë@acme.test".encode().decode("ascii", "surrogateescape"), others)}})
        self.term = Terminal(self.home, size=size, env={"TZ": "UTC", "COLORTERM": "truecolor"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait(lambda screen: "Claude VI" in screen and METER.search(screen))

    def at(self, label):
        """Where `label`'s meter is: a column inside its label, then its row, each from 1."""
        shown = lines(self.term.screen())
        row = next(number for number, line in enumerate(shown)
                   if f"{label}  " in line and METER.search(line))
        return shown[row].index(label + "  ") + 3, row + 1

    def hovered(self, label):
        """The line under the grid once the pointer is on `label`'s meter."""
        self.term.type("\x1b[<35;{};{}M".format(*self.at(label)))
        return under_grid(self.term.wait(
            lambda screen: under_grid(screen).startswith(f"  {label}  ")))

    def settled(self, holds):
        """Once `holds` holds of the screen's looks: what the pointer lights fades in."""
        self.term.wait(lambda _: holds(looks(self.term.screen(colours=True))))

    def said(self):
        """Each meter's line under the grid, the pointer on it, as {label: what follows it}."""
        return {label: self.hovered(label).removeprefix(f"  {label}  ")
                for label in ("Claude I", "Claude II", "Claude III", "Claude IV", "Claude V",
                              "Claude VI")}

    def assert_names_its_account(self):
        said = self.said()
        # nothing kept of Claude IV's login: it reads as before, its reset and the one in hand
        self.assertRegex(said["Claude IV"], r"\Aresets \w{3} \d\d:\d\d · 1 reset in hand\Z")
        self.assertEqual(said["Claude I"], f"{EMAIL} · {said['Claude IV']}")
        # its bytes as kept, which the terminal shows as the address they spell
        self.assertEqual(said["Claude VI"], f"zoë@acme.test · {said['Claude IV']}")
        # kept as a number, only spaces or what UTF-8 cannot write, there is no email to say
        for label in ("Claude II", "Claude III", "Claude V"):
            self.assertEqual(said[label], said["Claude IV"], label)
        self.hovered("Claude I")

        def dim(rows):           # the email in the look of the notes after it
            line = next((line for line in rows
                         if plain(line).startswith(f"  Claude I  {EMAIL} · resets ")), None)
            if line is None:
                return False
            text = plain(line)
            email = {frozenset(ink(shown)) for _, shown in line[text.index(EMAIL):][:len(EMAIL)]}
            note = {frozenset(ink(shown)) for _, shown in line[text.index("resets "):][:6]}
            return len(email) == 1 and email == note
        self.settled(dim)

    def test_the_line_under_the_grid_names_the_hovered_meters_account(self):
        self.open()
        self.assert_names_its_account()
        # its acts' line under the line of its limits
        self.term.type("\x1b[<0;{0};{1}M\x1b[<0;{0};{1}m".format(*self.at("Claude II")))
        self.term.wait(lambda screen: any(
            row.startswith("› Claude II ") and limits.startswith("    resets ")
            and below == "    → spend a reset   − remove"
            for row, limits, below in zip(lines(screen), lines(screen)[1:], lines(screen)[2:])))

    def test_on_c_the_line_under_its_meters_names_the_account_too(self):
        self.open()
        self.term.keys("c")
        self.term.wait(lambda screen: "› Fable 5.1" in screen and "esc back" in screen)
        self.assert_names_its_account()

    def test_a_login_that_ends_soon_names_its_email_once_and_only_its_meter_is_amber(self):
        self.open(ends=2 * DAY)
        line = self.hovered("Claude I")
        self.assertTrue(line.startswith(f"  Claude I  login {EMAIL} ends "), line)
        self.assertEqual(line.count(EMAIL), 1, line)

        def only_its_own(rows):
            """Claude I's meter in the ink of its login's note under the grid, and no other."""
            drawn = {}
            for line in rows:
                text = plain(line)
                for found in re.finditer(r"(Claude [IV]+) +(━)[━╸─]*  \d+% left", text):
                    drawn[found[1]] = ink(line[found.start(2)][1])
            note = next((line for line in rows if plain(line).startswith("  Claude I  login")),
                        None)
            amber = note and ink(note[plain(note).index(EMAIL)][1])
            return len(drawn) == 6 and drawn["Claude I"] == amber and all(
                shown != amber for label, shown in drawn.items() if label != "Claude I")
        self.settled(only_its_own)

    def test_a_login_ending_soon_with_no_email_to_say_says_when_it_ends(self):
        self.open(others=2 * DAY)
        for label in ("Claude II", "Claude III", "Claude V"):
            self.assertTrue(self.hovered(label).startswith(f"  {label}  login ends "), label)
        self.assertTrue(self.hovered("Claude VI").startswith("  Claude VI  login zoë@acme.test "
                                                             "ends "))
        # Subscriptions, which drops from its lines what no terminal can write, names it still,
        # under the line of its limits
        self.term.type("\x1b[<0;{0};{1}M\x1b[<0;{0};{1}m".format(*self.at("Claude V")))
        self.term.wait(lambda screen: any(
            row.startswith("› Claude V ") and limits.startswith("    resets ")
            and below.startswith("    login ops@acme.test ends ")
            for row, limits, below in zip(lines(screen), lines(screen)[1:], lines(screen)[2:])))

    def test_too_narrow_for_every_note_the_email_is_the_last_to_go(self):
        self.open(size=(40, 40))
        # Claude IV has room for its reset still, Claude I for its email alone
        self.assertRegex(self.hovered("Claude IV"), r"\A  Claude IV  resets \w{3} \d\d:\d\d\Z")
        self.assertEqual(self.hovered("Claude I"), f"  Claude I  {EMAIL}")

    def test_the_logins_changed_after_the_grids_read_leave_the_line_one_logins(self):
        for ends, later in ((60 * DAY, 2 * DAY), (2 * DAY, 60 * DAY)):
            with self.subTest(ends=ends), Home() as home:
                akconfig.write(home, {"fable": "claude"})
                now = time.time()
                home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {
                    "anthropic": {"meters": [{"name": "weekly", "used": 40,
                                              "window_secs": 604800}], "fetched_at": now}}})
                home.write(".agentkit/state/logins.json",
                           {"anthropic": {"default": login(EMAIL, ends)}})
                changed = json.dumps({"anthropic": {"default": login("tide@acme.test", later)}})
                done = home.run(sys.executable, "-c", RACE, str(TESTS.parent), changed,
                                env={"TZ": "UTC", "COLUMNS": "120"})
                self.assertEqual(done.code, 0, done.err)
                line = done.out.rstrip("\n")
                self.assertTrue(line.startswith(
                    f"  Claude  login {EMAIL} ends " if ends < DAY * 7 else f"  Claude  {EMAIL}"),
                    line)
                self.assertNotIn("tide", line)
                self.assertEqual(line.count(EMAIL), 1, line)


if __name__ == "__main__":
    unittest.main()
