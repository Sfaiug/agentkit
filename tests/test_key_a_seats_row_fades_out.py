"""A past session removed from `past sessions` fades out where it stood before it goes.

`x` on `theta` over `beta`, `Remove` picked: while the motion clock stands before `motion.LEAVES`
and past the pick, `theta`'s row and the question under it stay on their rows in inks between
their own and the background, while `beta`'s row stays where and as it was; once `motion.LEAVES`
has passed, `theta` is gone and `beta` takes its row.  A key typed while they fade is read by the
page after; a resize ends the fade at once; at 8 colours the first screen after the pick has no
`theta`.

Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py) on the
injected motion clock (tests/fixtures/clock.py), its pane piped through tmux's `pipe-pane`.
"""

import os
from pathlib import Path
import re
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import clock
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import look, looks, plain
from fixtures.akterm import SERVER, Terminal

TZ = f"AKT{time.gmtime().tm_hour - 12:+d}"      # past noon, so both seats closed today
os.environ["TZ"] = TZ
time.tzset()

LEAVES = 0.2                    # motion.LEAVES
PAST_KEYS = "  ↑↓←→ move   ⏎ reopen   x remove   esc back"
UPDATE = re.compile(r"\x1b\[\?2026h(.*?)\x1b\[\?2026l", re.S)
CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def rgb(shown, ground=38):
    """(R, G, B) of `ground` (38 foreground, 48 background) in a cell's look, or None."""
    return next((tuple(int(ch) for ch in part.split(";")[2:])
                 for part in shown if part.startswith(f"{ground};2;")), None)


def between(colour, start, end):
    """Whether `colour` is strictly between `start` and `end`, every channel in range."""
    return (colour is not None and colour not in (start, end)
            and all(min(a, b) <= c <= max(a, b) for c, a, b in zip(colour, start, end)))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class PastRowFadesOut(unittest.TestCase):
    def open_past(self, env):
        """A Home with `theta` closed after `beta` on `acme`, `past sessions` open on a held
        clock, and its pane piped to `term.raw`."""
        home = Home()
        self.addCleanup(home.close)
        checkout = home.path / "code/acme"
        checkout.mkdir(parents=True)
        assert home.run("git", "init", "-q", str(checkout)).code == 0
        now = time.time()
        for name, closed in (("theta", now - 600), ("beta", now - 1200)):
            home.write(f".agentkit/state/session-{name}.json", {
                "orchestrator": "fable", "workers": ["fable"], "cwd": str(checkout),
                "repo": str(checkout), "created": int(closed) - 3600,
                "conversation": f"conv-{name}", "id_source": "launcher", "resumable": True,
                "session_title": name})
            home.write(f".agentkit/state/seat-{name}.json",
                       {"stopped_at": closed, "closed_by_owner": True})
        clock.standing(home, "AK_MOTION_CLOCK", 1000.0)
        term = Terminal(home, size=(100, 30), env={"TZ": TZ, **env})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("p past")
        term.keys("p")
        term.wait(lambda screen: PAST_KEYS in screen and "theta" in screen and "beta" in screen)
        self.at(home, 1010.0)
        term.wait(lambda screen: screen.startswith("agentkit · past sessions"))
        term.raw = home.root / f"raw{term.pane.strip('%')}"
        named = shlex.quote(str(term.raw)).replace("%", "%%").replace("#", "##")
        piped = home.tmux("pipe-pane", "-O", "-t", term.pane, f"cat >>{named}", server=SERVER)
        self.assertEqual(piped.code, 0, piped.err)
        return home, term

    def at(self, home, seconds):
        """Hold ak's motion clock at `seconds` via an atomic swap."""
        moment = Path(home.env["AK_MOTION_CLOCK"])
        moment.with_suffix(".new").write_text(repr(seconds))
        moment.with_suffix(".new").replace(moment)

    def updates(self, term, offset=0):
        """Every whole synchronized update written to the pane from `offset` bytes on."""
        data = term.raw.read_bytes()[offset:] if term.raw.exists() else b""
        return UPDATE.findall(data.decode("utf-8", "replace"))

    def ask_remove(self, home, term, settle=True):
        """Open `x` on `theta`, move to `× Remove`, and settle where `settle` is True."""
        term.keys("x")
        term.wait(lambda screen: "Remove theta from past sessions?" in screen
                  and "› ✓ Keep" in screen)
        if settle:
            self.at(home, 1020.0)
        term.keys("Down")
        term.wait("› × Remove")
        if settle:
            self.at(home, 1030.0)

            def rested(_):
                rows = looks(term.screen(colours=True))
                beta = look(rows, "beta")
                return (look(rows, "theta") == beta
                        and look(rows, "Remove theta") == beta
                        and rgb(look(rows, "✓ Keep"), 48) == rgb(beta, 48)
                        and rgb(look(rows, "× Remove"), 48) not in (None, rgb(beta, 48)))
            term.wait(rested)

    def row_of(self, lines, text, exclude=None):
        return next(n for n, line in enumerate(lines)
                    if text in plain(line) and (exclude is None or exclude not in plain(line)))

    def wait_mid_fade(self, term, theta_row, theta_ink):
        """The screen's looks once `theta`'s ink has moved off `theta_ink` while `theta` stays."""
        deadline = time.monotonic() + 10
        while True:
            shown = looks(term.screen(colours=True))
            line = plain(shown[theta_row])
            self.assertIn("theta", line, f"theta vanished before LEAVES:\n{term.screen()}")
            ink = rgb(look([shown[theta_row]], "theta"))
            if ink != theta_ink:
                return shown
            self.assertLess(time.monotonic(), deadline,
                            f"theta never faded from {theta_ink}:\n{term.screen()}")
            time.sleep(0.05)

    def test_removed_row_and_card_fade_out_before_beta_moves_up(self):
        home, term = self.open_past({"COLORTERM": "truecolor"})
        self.ask_remove(home, term)
        before = looks(term.screen(colours=True))
        theta_row = self.row_of(before, "theta", exclude="Remove theta")
        question_row = self.row_of(before, "Remove theta from past sessions?")
        remove_row = self.row_of(before, "× Remove")
        beta_row = self.row_of(before, "beta")
        bg = rgb(look([before[theta_row]], "theta"), 48)
        theta_ink = rgb(look([before[theta_row]], "theta"))
        question_ink = rgb(look([before[question_row]], "Remove theta"))
        remove_back = rgb(look([before[remove_row]], "× Remove"), 48)
        self.assertIsNotNone(bg)
        self.assertNotIn(bg, (theta_ink, question_ink, remove_back))

        since = term.raw.stat().st_size if term.raw.exists() else 0
        term.keys("Enter")
        term.wait(lambda _: self.updates(term, since), bound=10)

        self.at(home, 1030.0 + LEAVES / 2)
        mid = self.wait_mid_fade(term, theta_row, theta_ink)
        self.assertEqual(plain(mid[theta_row]), plain(before[theta_row]))
        self.assertEqual(plain(mid[question_row]), plain(before[question_row]))
        self.assertTrue(between(rgb(look([mid[theta_row]], "theta")), theta_ink, bg))
        self.assertTrue(between(rgb(look([mid[question_row]], "Remove theta")), question_ink, bg))
        self.assertTrue(between(rgb(look([mid[remove_row]], "× Remove"), 48), remove_back, bg))
        self.assertEqual(mid[beta_row], before[beta_row])

        self.at(home, 1030.0 + LEAVES + 0.05)
        after = term.wait(lambda screen: "theta" not in screen and "beta" in screen
                          and PAST_KEYS in screen)
        after_lines = after.split("\n")
        self.assertNotIn("theta", after)
        self.assertIn("beta", after_lines[theta_row])

    def test_key_typed_during_fade_is_read_after_and_resize_ends_fade_at_once(self):
        with self.subTest("key typed during fade is read by the page after"):
            home, term = self.open_past({"COLORTERM": "truecolor"})
            self.ask_remove(home, term)
            before = looks(term.screen(colours=True))
            theta_row = self.row_of(before, "theta", exclude="Remove theta")
            theta_ink = rgb(look([before[theta_row]], "theta"))
            since = term.raw.stat().st_size if term.raw.exists() else 0
            term.keys("Enter")
            term.wait(lambda _: self.updates(term, since), bound=10)
            self.at(home, 1030.0 + LEAVES / 2)
            mid = self.wait_mid_fade(term, theta_row, theta_ink)
            mid_ink = rgb(look([mid[theta_row]], "theta"))
            # Esc typed mid-fade does not cut it short; the fade continues, and the page after
            # reads Esc and goes back.
            term.keys("Escape")
            self.at(home, 1030.0 + LEAVES * 0.75)
            later = self.wait_mid_fade(term, theta_row, mid_ink)
            self.assertIn("theta", plain(later[theta_row]))
            self.at(home, 1030.0 + LEAVES + 0.05)
            main = term.wait(lambda screen: "esc leave" in screen and "past sessions" not in screen)
            self.assertIn("p past", main)
            self.assertFalse((home.path / ".agentkit/state/session-theta.json").exists())
            self.assertTrue((home.path / ".agentkit/state/session-beta.json").exists())

        with self.subTest("resize ends the fade at once"):
            home, term = self.open_past({"COLORTERM": "truecolor"})
            self.ask_remove(home, term)
            before = looks(term.screen(colours=True))
            theta_row = self.row_of(before, "theta", exclude="Remove theta")
            theta_ink = rgb(look([before[theta_row]], "theta"))
            since = term.raw.stat().st_size if term.raw.exists() else 0
            term.keys("Enter")
            term.wait(lambda _: self.updates(term, since), bound=10)
            self.at(home, 1030.0 + LEAVES / 2)
            self.wait_mid_fade(term, theta_row, theta_ink)
            # Clock never passes LEAVES; the resize ends the fade at once.
            term.resize(90, 28)
            after = term.wait(lambda screen: "theta" not in screen and "beta" in screen
                              and PAST_KEYS in screen)
            self.assertIn("beta", after.split("\n")[theta_row])

    def test_at_eight_colours_the_first_screen_after_the_pick_has_no_theta(self):
        home, term = self.open_past({"TERM": "xterm", "COLORTERM": ""})
        self.ask_remove(home, term, settle=False)
        before = term.screen().split("\n")
        theta_row = next(n for n, line in enumerate(before)
                         if "theta" in line and "Remove theta" not in line)
        since = term.raw.stat().st_size if term.raw.exists() else 0
        term.keys("Enter")
        after = term.wait(lambda screen: "theta" not in screen and "beta" in screen
                          and PAST_KEYS in screen)
        self.assertIn("beta", after.split("\n")[theta_row])
        updates = self.updates(term, since)
        self.assertTrue(updates, "expected a screen update after picking Remove")
        first = CSI.sub("", updates[0])
        self.assertNotIn("theta", first)
        self.assertIn("beta", first)


if __name__ == "__main__":
    unittest.main(verbosity=2)
