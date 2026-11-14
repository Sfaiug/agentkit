"""A model its harness's `[catalog]` gives no label is named by its name and number, read off what
its harness calls it; a label the table gives wins.

The owner (10 Nov 2026), where a seat's row read `claude-fable-5-2 max`: "I always want it just to
be the model name, number and effort. [...] Just like Opus 5.5 xhigh", and "Every single time we
add a new model, it should be added and named correctly."  A provider's prefix, a trailing date
and the maker's family word its manifest names are no part of the name, unless only numbers
follow that word; a hyphen is a space, between two numbers a point (config.model_label).

Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py), over
the shipped manifests, its harnesses the fakes of tests/fixtures/fakeadapter.py beside seats of
tests/fixtures/akseat.py, judged by what the terminal shows; this test fails against `/bin/false`.
The terminal has no colour (NO_COLOR).
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

OPENS = 60      # the first draw looks at every seat, which a loaded host makes slow
# each configured model, by harness in the `c` screen's order, beside the name it reads as
NAMED = {"Claude Code": [("nova", "claude-nova-7-1", "Nova 7.1"), ("opus", None, "Opus 5.5"),
                         ("fable", "claude-fable-5-2", "Fable 5.2"),
                         ("dated", "claude-opus-4-5-20251101", "Opus 4.5")],
         "Codex": [("vega", "gpt-7.2-vega", "7.2 Vega"), ("seven", "gpt-7", "GPT 7")],
         "Antigravity": [("neon", "gemini-5-neon", "5 Neon"),
                         ("agy-opus", "claude-opus-5-5", "Claude Opus 5.5")],
         "Muse Code": [("wonder", "muse-wonder-full-1.0", "Wonder Full 1.0")],
         "Grok Build": [("grok", "grok-4.7", "Grok 4.7")],
         "OpenCode": [("flash", "acme/acme-flash-free", "Acme Flash Free")]}
HARNESS = {"Claude Code": "claude", "Codex": "codex", "Antigravity": "antigravity",
           "Muse Code": "muse", "Grok Build": "grokbuild", "OpenCode": "opencode"}


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def row(screen, seat):
    """The menu row of `seat`, highlighted or not, or None."""
    return next((line for line in lines(screen) if re.match(rf"[› ] \d+  {seat} ", line)), None)


def c_names(screen):
    """The `c` screen's harnesses and models, each by the name it shows, from its headings to
    `Models`."""
    shown = lines(screen)
    block = shown[next(n for n, line in enumerate(shown) if "orch" in line.split()) + 1:]
    return [re.split(r" {2,}", line.lstrip("› ").strip())[0]
            for line in block[:block.index("  Models")] if line]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NamedFromItsId(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass")

    def test_each_model_on_its_harness_is_named_off_its_id_and_a_seat_s_row_adds_its_effort(self):
        models = {name: {"harness": HARNESS[harness], **({"model": model} if model else {})}
                  for harness, listed in NAMED.items() for name, model, _ in listed}
        models["nova"]["effort"], models["opus"]["effort"] = "max", "xhigh"
        models["flash"]["provider"] = "acme"
        akconfig.write(self.home, models, workers=["nova"])
        Seat(self.home, "fix-api", model="nova")
        Seat(self.home, "acme-ask", model="opus")
        term = Terminal(self.home, size=(110, 40), env={"NO_COLOR": "1"})
        screen = term.wait(lambda screen: row(screen, "fix-api") and row(screen, "acme-ask"),
                           bound=OPENS)
        self.assertRegex(row(screen, "fix-api"), r"^[› ] \d+  fix-api +Nova 7\.1 max  ")
        self.assertRegex(row(screen, "acme-ask"), r"^[› ] \d+  acme-ask +Opus 5\.5 xhigh  ")
        term.keys("c")
        screen = term.wait(lambda screen: "  Models" in lines(screen))
        self.assertEqual(c_names(screen), [name for harness, models in NAMED.items()
                                           for name in [harness, *(said for *_, said in models)]])

    def test_a_listed_model_reads_off_its_label_on_the_models_screen_and_once_added_on_a_row(self):
        akconfig.write(self.home, ["opus", "astra"])
        # Codex lists a model the table holds no label for under its maker's label, and its own
        # model by its id alone: the table's label for that wins
        self.fakes["codex"].answer("models", "gpt-7.2-vega\tGPT-7.2-Vega\tlow medium high\n"
                                             "default\tdefault\tlow medium high\n")
        term = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1"})
        term.wait("esc leave", bound=OPENS)
        term.keys("c")
        term.wait("› Opus 5.5")
        term.keys("j", "j")
        term.wait("› Models")
        term.keys("Enter")
        term.wait("› Claude Code  Opus 5.5")
        term.keys("j", "Enter")
        # after them Astra, which it does not list, the highlight on the one marked
        term.wait(lambda screen: ["    □ 7.2 Vega", "    □ Codex's own model",
                                  "›   ■ 6 Astra"]
                  == [line for line in lines(screen) if "□" in line or "■" in line])
        term.keys("Up", "Up", "Space")
        term.wait(lambda screen: "  Codex        6 Astra, 7.2 Vega" in lines(screen)
                  and "›   ■ 7.2 Vega" in lines(screen))
        name, entry = next(item for item in akconfig.read(self.home)["models"].items()
                           if item[1]["model"] == "gpt-7.2-vega")
        for back in ("› Codex        6 Astra, 7.2 Vega", "› Models", "esc leave"):
            term.keys("Escape")
            term.wait(back)
        term.keys("Escape")
        term.exit_code()
        Seat(self.home, "acme-vega", model=name)
        term = Terminal(self.home, size=(100, 30), env={"NO_COLOR": "1"})
        screen = term.wait(lambda screen: row(screen, "acme-vega"), bound=OPENS)
        self.assertRegex(row(screen, "acme-vega"),
                         rf"^[› ] \d+  acme-vega +7\.2 Vega {entry['effort']}  ")


if __name__ == "__main__":
    unittest.main()
