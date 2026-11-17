"""`+ add a subscription` reads as `Subscriptions`, the page it opens from: each company's name over
what it adds, drawn as Subscriptions draws one, each row named and drawn as Subscriptions draws a
row -- the config's companies first, then the shipped ones it has not, then OpenCode, which signs
in to any provider.  A heading is no stop for the keys, lights under no pointer and takes no
click, and Enter says `⏎ add` on every row.  On a terminal too short for them all the title stays
and the rows round the highlight are drawn, their headings over them.  A click on an item of the
key line does what its key does.  The owner (10 Nov 2026), of this page: "dependign on
the provider, it either says add or open. Fix this. And this screen does not look astheitcally
pleasing."

Black-box: `AK_BIN`'s menu in a terminal of 24-bit colour (tests/fixtures/akterm.py) over two
Claude subscriptions and a ChatGPT one, its harnesses faked (tests/fixtures/fakeadapter.py), the
pointer typed as the SGR sequence a terminal sends for it.  This test fails against `/bin/false`.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_c_chooses_the_theme import BLACK, SELECTION, sgr
from test_key_subscriptions_page import ADD, PAGE, lines, title

KEYS = "  ↑↓←→ move   ⏎ add   esc back"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AddASubscriptionPage(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")
        akconfig.write(self.home, {"fable": "claude", "astra": "codex"}, providers={
            "anthropic": {"mode": "subscription", "accounts": ["default", "two"]}})
        self.term = Terminal(self.home, size=(100, 40), env={"COLORTERM": "truecolor"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait("› Fable 5.1")
        self.term.keys("Down", "Down", "Down")        # past 6 Astra and `Models`
        self.term.wait("› Subscriptions")
        self.term.keys("Enter")
        self.term.wait(lambda screen: title(screen) == PAGE and "› Claude I " in screen)
        self.term.keys("Down", "Down", "Down")
        self.term.wait("› + add a subscription")
        # read once its highlight is at rest on the selection: it comes on from toward the accent
        # (tests/test_highlight_glows.py), as the page opened from it draws its own at rest
        self.term.wait(lambda _: sgr(SELECTION[BLACK], "48") in self.drawn("+ add a subscription"))
        self.theirs = {text: self.drawn(text)
                       for text in ("Anthropic", "OpenAI", "Claude II", "+ add a subscription")}
        self.term.keys("Enter")
        shown = lines(self.term.wait(lambda screen: title(screen) == ADD
                                     and "› Claude III" in screen and "another provider" in screen))
        self.page = shown[2:shown.index("", 2)]     # between the rule and the key line

    def drawn(self, text):
        """How the line up drawing `text`, flush left or two cells in, is drawn to the layout's
        edge, `text` itself `…` and its blanks one: captured alone, tmux writes it from no
        colour."""
        at = next(number for number, line in enumerate(lines(self.term.screen()))
                  if text in (line, line[2:2 + len(text)]))
        line = self.home.tmux("capture-pane", "-p", "-e", "-N", "-S", str(at), "-E", str(at),
                              "-t", self.term.pane, server=SERVER).out
        return re.sub(" +", " ", line.replace(text, "…"))

    def test_each_company_s_name_is_over_what_it_adds_drawn_as_on_subscriptions(self):
        listed = list(zip(self.page[::2], (row[2:] for row in self.page[1::2])))
        self.assertEqual([pair for pair in listed if pair[0] in ("Anthropic", "OpenAI", "xAI",
                                                                  "OpenCode")],
                         [("Anthropic", "Claude III"), ("OpenAI", "ChatGPT II"), ("xAI", "Grok"),
                          ("OpenCode", "another provider")])
        self.assertNotIn("xAI / Grok Build", self.page)
        self.assertIn("\x1b[1m", self.theirs["Anthropic"])        # bold
        for company in ("Anthropic", "OpenAI"):
            self.assertEqual(self.drawn(company), self.theirs[company])
        for company in ("xAI", "OpenCode"):
            self.assertEqual(self.drawn(company), self.theirs["Anthropic"])
        # a row at rest as Subscriptions draws a subscription's name, and lit as it lights the row
        # Enter acts on whole
        for row in ("ChatGPT II", "Grok", "another provider"):
            self.assertEqual(self.drawn(row).partition("…")[0],
                             self.theirs["Claude II"].partition("…")[0])
        self.assertEqual(self.drawn("Claude III"), self.theirs["+ add a subscription"])

    def test_the_keys_stop_on_each_row_saying_add_and_enter_logs_in(self):
        rows = [line[2:] for line in self.page if line[:2] in ("  ", "› ")]
        for row in rows:              # a heading the keys stopped on would light no row
            self.term.wait(lambda screen, row=row: f"› {row}" in lines(screen)
                           and KEYS in lines(screen))
            self.term.keys("Down")
        self.term.keys(*["Up"] * len(rows), "Enter")
        self.term.wait(lambda screen: title(screen) == PAGE and self.fakes["claude"].calls("login"))
        [call] = self.fakes["claude"].calls("login")
        self.assertEqual(call["argv"], [])
        self.assertNotIn(call["env"].get("AGENTKIT_ACCOUNT"), (None, "default", "two"))

    def test_a_heading_lights_under_no_pointer_and_takes_no_click(self):
        at = 3 + self.page.index("xAI")              # its screen row
        self.term.type(f"\x1b[<35;8;{at}M\x1b[<0;8;{at}M\x1b[<0;8;{at}m")    # on it, a click
        self.term.wait(lambda screen: not any(line[:1] == "›" for line in lines(screen)))
        self.term.keys("Down")                       # the highlight back, read after the click
        self.term.wait(lambda screen: title(screen) == ADD
                       and any(line[:1] == "›" for line in lines(screen)))
        self.assertEqual(self.fakes["claude"].calls("login"), [])

    def test_a_click_on_a_key_line_item_does_what_its_key_does(self):
        at = lines(self.term.screen()).index(KEYS) + 1          # the key line's screen row

        def pointer(item, reports):
            self.term.type(reports.format(f"{KEYS.index(item) + 1};{at}"))
        pointer("⏎ add", "\x1b[<35;{0}M")                       # off every row: none lit
        self.term.wait(lambda screen: not any(line[:1] == "›" for line in lines(screen)))
        pointer("⏎ add", "\x1b[<0;{0}M\x1b[<0;{0}m")  # as Enter there: the row the keys left lit
        self.term.wait(lambda screen: title(screen) == ADD and "› Claude III" in screen)
        pointer("esc back", "\x1b[<35;{0}M\x1b[<0;{0}M\x1b[<0;{0}m")
        self.term.wait(lambda screen: title(screen) == PAGE)
        self.assertEqual(self.fakes["claude"].calls("login"), [])

    def test_a_click_beside_the_layout_takes_no_row(self):
        asked = {name: fake.calls() for name, fake in self.fakes.items()}
        self.term.resize(160, 40)
        self.term.wait(lambda screen: lines(screen)[1] == "─" * 120)    # the layout's last column
        at = 3 + self.page.index("  ChatGPT II")
        self.term.type(f"\x1b[<35;150;{at}M\x1b[<0;150;{at}M\x1b[<0;150;{at}m")
        self.term.wait(lambda screen: not any(line[:1] == "›" for line in lines(screen)))
        self.term.keys("Down")
        self.term.wait(lambda screen: title(screen) == ADD
                       and any(line[:1] == "›" for line in lines(screen)))
        self.assertEqual({name: fake.calls() for name, fake in self.fakes.items()}, asked)

    def test_a_short_terminal_keeps_the_title_and_the_lit_row_on_it(self):
        rows = [line[2:] for line in self.page if line[:2] in ("  ", "› ")]
        asked = {name: fake.calls() for name, fake in self.fakes.items()}
        self.term.resize(100, 12)
        for row in rows:
            shown = lines(self.term.wait(lambda screen, row=row: title(screen) == ADD
                                         and f"› {row}" in lines(screen)))
            self.term.keys("Down")
        # a company's name on the last page, clicked on its third column, inked on any line
        at = next(number for number, line in enumerate(shown, 1)
                  if line in self.page[::2] and number > 2)
        self.term.type(f"\x1b[<35;3;{at}M\x1b[<0;3;{at}M\x1b[<0;3;{at}m")
        self.term.wait(lambda screen: not any(line[:1] == "›" for line in lines(screen)))
        self.term.keys("Down")
        self.term.wait(lambda screen: title(screen) == ADD
                       and any(line[:1] == "›" for line in lines(screen)))
        self.assertEqual({name: fake.calls() for name, fake in self.fakes.items()}, asked)

    def test_the_keys_page_through_a_row_taller_than_the_page_before_leaving_it(self):
        rows = [line[2:] for line in self.page if line[:2] in ("  ", "› ")]
        self.term.keys(*["Down"] * (len(rows) - 1))
        self.term.wait(f"› {rows[-1]}")
        self.term.resize(16, 7)          # a page one line high, `another provider` on two
        self.term.wait(lambda screen: "› another" in lines(screen))
        self.term.keys("Down")
        self.term.wait(lambda screen: "  provider" in lines(screen))
        self.term.keys("Up")
        self.term.wait(lambda screen: "› another" in lines(screen))
        self.term.keys("Up")
        self.term.wait(lambda screen: f"› {rows[-2]}" in lines(screen))


if __name__ == "__main__":
    unittest.main()
