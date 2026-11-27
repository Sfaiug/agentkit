"""No name is drawn in a colour of its own (the owner, 10 and 12 Nov 2026), though config.toml
still gives a provider a `colour`: `c` names each harness over its models and Subscriptions each
company over its subscriptions bold, in the colours a seat's name has on the ak screen, and Models
each harness on its row in them; the usage runs in the order config.toml names its providers; and
once nothing moves no cell is in a colour outside the theme's thirteen.

Nor does anything wash into a company's colour under the pointer: the subscription under it is
lit on the theme's selection over its whole cell, every colour in it kept, on the ak screen, on
`c` and on its Subscriptions page, a `c` too short for its usage to stay on top too, and nothing
else on the screen changes colour; on Subscriptions an act the keys are on is then at rest, one
thing lit at a time.

Black-box: the program AK_BIN names, in a 24-bit terminal on the black theme (akterm.py), its
harnesses fakes, the pointer typed as a terminal sends it, each cell judged once the screen rests
(aklooks.py); the pointer away on a blank cell puts out the keys' highlight as a subscription does.
"""

import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.aklooks import colours, plain, settled
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

# the black theme's thirteen roles (agentkit/themes.py)
BLACK = {"background": "000000", "selection": "08305d", "border": "3a3f46",
         "text": "e2e8ef", "muted": "acb4bd", "dim": "868d97", "accent": "4da3ff",
         "success": "33b65f", "warning": "d79200", "error": "fe756f", "info": "00b0bf",
         "special": "da7de0", "on-accent": "000000"}
OWNED = {f"{ground};2;" + ";".join(str(int(rgb[at:at + 2], 16)) for at in (0, 2, 4))
         for rgb in BLACK.values() for ground in ("38", "48")}
# each subscription as config.toml names them: its label, harness and the share of its week used
SUBSCRIPTIONS = {"google": ("Gemini", "antigravity", 30), "anthropic": ("Claude", "claude", 40),
                 "openai": ("ChatGPT", "codex", 50), "meta": ("Muse", "muse", 60)}
MODELS = ["gemini", "opus", "astra", "spark"]       # shipped, one on each
HARNESSES = ("Claude Code", "Codex", "Muse Code", "Antigravity")
COMPANIES = ("Anthropic", "OpenAI", "Meta", "Google")
SEATS = ("acme", "beta")
LIT = "48;2;8;48;93"                    # the black theme's selection
POINT = "\x1b[<35;{column};{row}M"      # the pointer moved, no button down, to a cell from 1
METER = "━╸─"                           # a meter's cells (terminal.share_parts)
SAID = ("  Gemini  resets ", "  ChatGPT  resets ")     # the line under the grid, of one pointed
SHORT = (120, 12)                       # too short for c to keep its usage over its page


def ink(shown):
    """A cell's look less its background: what it is drawn in."""
    return {part for part in shown if not part.startswith("48")}


def row(lines, test):
    """The first line, from 0, whose text passes `test`."""
    return next(number for number, line in enumerate(lines) if test(plain(line)))


def cells(lines, label):
    """The line, from 0, of `label`'s subscription on the grid, and the columns, from 0, of its
    label and meter."""
    at = row(lines, lambda line: f"{label} " in line and "% left" in line)
    text = plain(lines[at])
    first = text.index(f"{label} ")
    meter = next(column for column in range(first, len(text)) if text[column] in METER)
    return at, range(first, next(column for column in range(meter, len(text) + 1)
                                 if column == len(text) or text[column] not in METER))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NoNameHasAColour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        fakes = fakeadapter.install(home, **{harness: "pass"
                                             for _, harness, _ in SUBSCRIPTIONS.values()})
        akconfig.write(home, MODELS, providers={"google": {"mode": "subscription",
                                                           "colour": "#123456"}})
        assert list(akconfig.read(home)["providers"]) == list(SUBSCRIPTIONS)
        reset = int(time.time()) + 3 * 86400

        def week(used):
            return {"meters": [{"name": "weekly", "used": used, "resets_at": reset,
                                "window_secs": 604800}]}
        # read now, and read the same again by every probe
        for _, harness, used in SUBSCRIPTIONS.values():
            fakes[harness].answer("usage", json.dumps({**week(used), "error": None}))
        home.write(".agentkit/state/usage.json", {"fetched_at": time.time(), "providers": {
            provider: week(used) for provider, (_, _, used) in SUBSCRIPTIONS.items()}})
        # idle, so nothing breathes: one on the Gemini subscription
        Seat(home, SEATS[0], model="gemini", screen="antigravity-prompt-pane.txt")
        Seat(home, SEATS[1], model="opus")
        cls.term = term = Terminal(home, size=(120, 40), env={"COLORTERM": "truecolor"})
        # each screen's looks once it rests, the pointer away and on the Gemini subscription
        cls.screens = screens = {}
        term.wait(lambda text: "esc leave" in text and all(seat in text for seat in SEATS)
                  and all(f"{label} " in text for label, _, _ in SUBSCRIPTIONS.values()), 60)
        screens["ak away"] = cls.away("esc leave", cls.rest(lambda text: "% left" in text))
        screens["ak on"] = cls.point(screens["ak away"], "Gemini")
        term.keys("c")
        ready = cls.rest(lambda text: "agentkit · config" in text and "% left" in text)
        screens["c away"] = cls.away("esc back", ready)
        screens["c on"] = cls.point(screens["c away"], "Gemini")
        term.keys("Escape")
        cls.rest(lambda text: "esc leave" in text)
        term.keys("c", *["Down"] * len(MODELS))             # past the models
        cls.rest(lambda text: "› Models" in text)
        term.keys("Enter")
        ready = cls.rest(lambda text: "config · models" in text
                         and all(name in text for name in HARNESSES))
        screens["models away"] = cls.away("esc back", ready)
        for back in ("r your runs", "esc leave"):        # onto `c`, then the ak screen
            term.keys("Escape")
            cls.rest(lambda text: back in text)
        term.keys("c", *["Down"] * (len(MODELS) + 1))       # past the models and `Models`
        cls.rest(lambda text: "› Subscriptions" in text)
        term.keys("Enter")
        ready = cls.rest(lambda text: "config · subscriptions" in text and "% left" in text)
        screens["page away"] = cls.away("esc back", ready)
        screens["page on"] = cls.point(screens["page away"], "Gemini", "› Gemini ")
        # the keys onto Gemini's act, then the pointer away, which keeps it, and onto its meter
        term.keys("Right")
        screens["page keyed"] = keyed = cls.rest(lambda text: "⏎ remove" in text)
        screens["page act"] = cls.point(cls.away("esc back", keyed), "Gemini", "⏎ remove")
        for back in ("r your runs", "esc leave"):        # onto `c`, then the ak screen
            term.keys("Escape")
            cls.rest(lambda text: back in text)

    @classmethod
    def rest(cls, ready):
        return settled(cls.term, ready, bound=60)

    @classmethod
    def away(cls, keys, lines):
        """The screen with the pointer on the blank line over its key line."""
        at = row(lines, lambda line: keys in line)
        assert plain(lines[at - 1]).strip() == "", plain(lines[at - 1])
        cls.term.type(POINT.format(column=1, row=at))
        return cls.rest(lambda text: "›" not in text)

    @classmethod
    def point(cls, lines, label, said=None):
        """The screen with the pointer on `label`'s meter, once it says `said`, by default the
        line under the grid saying the rest of it."""
        at, columns = cells(lines, label)
        meter = next(column for column in columns if plain(lines[at])[column] in METER)
        cls.term.type(POINT.format(column=meter + 1, row=at + 1))
        return cls.rest(lambda text: (said or f"  {label}  resets ") in text)

    def assert_lit_alone(self, before, on):
        """Gemini's label and meter lit on `on`, each cell in what it is drawn in `before`, and
        every other cell too: only the line under the grid says the rest of it, and the keys what
        they do there.  A cell lit is lit to its end, blanks too."""
        at, columns = cells(before, "Gemini")
        self.assertEqual(plain(on[at]).rstrip(), plain(before[at]).rstrip())
        for column in columns:
            self.assertEqual(ink(on[at][column][1]), ink(before[at][column][1]), column)
            self.assertIn(LIT, on[at][column][1], column)
        for was, now in zip(before, on):
            if not plain(now).startswith((*SAID, "  ↑↓←→ move ")):
                self.assertEqual([ink(shown) for (_, shown), _ in zip(now, was)],
                                 [ink(shown) for _, (_, shown) in zip(now, was)], plain(now))

    def named(self):
        """The look of each cell of a seat's name on the ak screen: a name's."""
        lines = self.screens["ak away"]
        at = row(lines, lambda line: f"  {SEATS[0]}  " in line)
        first = plain(lines[at]).index(f"  {SEATS[0]}  ") + 2
        [shown] = {shown for _, shown in lines[at][first:first + len(SEATS[0])]}
        return shown

    def assert_named(self, screen, name, bold):
        """`name` leads a line of `screen` -- a heading flush left, or two in a row's label -- each
        of its cells in a seat's name's look, bold too where `bold`."""
        lines, lead = self.screens[screen], "" if bold else "  "
        at = row(lines, lambda line: line.rstrip() == name if bold
                 else f"{line.rstrip()}  ".startswith(f"  {name}  "))
        for column in range(len(lead), len(lead) + len(name)):
            self.assertEqual(lines[at][column][1], self.named() | ({"1"} if bold else set()),
                             (screen, name, column))

    def test_c_and_subscriptions_name_each_harness_and_company_bold_in_no_colour(self):
        for screen, names in (("c away", HARNESSES), ("page away", COMPANIES)):
            for name in names:
                with self.subTest(screen=screen, name=name):
                    self.assert_named(screen, name, bold=True)

    def test_models_names_each_harness_on_its_row_as_the_ak_screen_names_a_seat(self):
        for name in HARNESSES:
            with self.subTest(name):
                self.assert_named("models away", name, bold=False)

    def test_the_usage_names_the_subscriptions_in_the_order_config_toml_does(self):
        grid = " ".join(plain(line) for line in self.screens["ak away"] if "% left" in plain(line))
        found = [grid.index(f"{label} ") for label, _, _ in SUBSCRIPTIONS.values()]
        self.assertEqual(found, sorted(found), grid)

    def test_at_rest_no_cell_is_in_a_colour_outside_the_theme(self):
        for name, lines in self.screens.items():
            with self.subTest(name):
                self.assertEqual(colours(lines) - OWNED, set())

    def test_on_the_ak_screen_and_c_the_pointer_lights_it_and_changes_no_colour(self):
        for screen in ("ak", "c"):
            with self.subTest(screen):
                self.assert_lit_alone(self.screens[f"{screen} away"], self.screens[f"{screen} on"])

    def test_on_subscriptions_the_pointer_lights_it_and_changes_no_colour(self):
        before, on = self.screens["page away"], self.screens["page on"]
        at, columns = cells(before, "Gemini")
        lit = row(on, lambda line: "Gemini " in line and "% left" in line)
        for column in columns:
            # bright too, as the row the keys are on
            self.assertEqual(ink(on[lit][column][1]) - {"1"}, ink(before[at][column][1]), column)
            self.assertIn(LIT, on[lit][column][1], column)
        # every other line as it was, wherever the line the pointed row opens moves it
        was = {plain(line).rstrip(): line for line in before}
        for number, line in enumerate(on):
            if number != lit and plain(line).rstrip() in was:
                self.assertEqual([ink(shown) for _, shown in line],
                                 [ink(shown) for _, shown in was[plain(line).rstrip()]],
                                 plain(line))

    def test_on_subscriptions_the_pointer_on_its_meter_puts_its_act_at_rest(self):
        """One thing lit at a time (docs/cli-design.md, Keys): the keys on `− remove`, the
        pointer onto its subscription's meter lights the meter and leaves the act at rest."""
        keyed, on = self.screens["page keyed"], self.screens["page act"]

        def lit(lines):
            """The act's line's cells lit: on the selection, or reversed where a build lights
            an act so."""
            act = row(lines, lambda line: "− remove" in line)
            return [column for column, (_, shown) in enumerate(lines[act]) if shown & {LIT, "7"}]
        self.assertTrue(lit(keyed))         # lit while the keys are on it
        at, columns = cells(on, "Gemini")
        for column in columns:
            self.assertIn(LIT, on[at][column][1], column)
        self.assertEqual(lit(on), [])

    def test_on_a_c_too_short_for_its_usage_to_stay_on_top_it_lights_alike(self):
        term = self.term
        term.resize(*SHORT)
        # ↑ past the first model onto the meters, as far as the first, which brings the grid in
        term.keys("c", *["Up"] * 8)
        shown = self.rest(lambda text: "esc back" in text and "Gemini " in text
                          and "ChatGPT " in text)
        # with no row shown the pointer cannot be away: on another meter it is off this one
        before = self.point(shown, "ChatGPT")
        self.assert_lit_alone(before, self.point(before, "Gemini"))
        # its usage pages with the rest: gone once the highlight is on the last row
        term.keys(*["Down"] * 30)
        end = self.rest(lambda text: "› Money" in text)
        self.assertFalse(any("% left" in plain(line) for line in end))


if __name__ == "__main__":
    unittest.main()
