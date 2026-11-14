"""No model is named by its maker's family word: `6.1 Sol max`, never `GPT-6.1-Sol max`.

The owner (10 Nov 2026): "I always want it just to be the model name, number and effort. Even for
sol, I want it to be 6.1 Sol max from now on, no more GPT. Just like Opus 5.5 xhigh."  A
manifest's `[catalog]` labels a model only where its name off its id cannot say it
(config.model_label), so a seat's row, and the models screen whether its harness lists the
models itself or its table answers for it, read the name without the family word, and a model
taken in there is filed under that name's words (`sol`).

Black-box: the program `AK_BIN` names, in a person's terminal (tests/fixtures/akterm.py), over
the shipped manifests, its harnesses the fakes of tests/fixtures/fakeadapter.py beside seats of
tests/fixtures/akseat.py, judged by what the terminal shows and the config it saves; this test
fails against `/bin/false`.  The terminal has no colour (NO_COLOR).
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
LISTS = 60      # a harness's listing is asked while the models screen waits
# what Codex and Antigravity list, each under its maker's label, and Codex's own model by its id
LISTED = {"codex": "default\tdefault\tlow medium high\n"
                   "gpt-6.1-sol\tGPT-6.1-Sol\tlow medium high xhigh max ultra\n"
                   "gpt-6-astra\tGPT-6-Astra\tlow medium high xhigh max ultra\n",
          "antigravity": "gemini-4-argon\tGemini 4 Argon\tlow medium high\n"
                         "gpt-oss-120b\tGPT-OSS 120B\tmedium\n"}


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def row(screen, seat):
    """The menu row of `seat`, highlighted or not, or None."""
    return next((line for line in lines(screen) if re.match(rf"[› ] \d+  {seat} ", line)), None)


def offered(screen):
    """The models the open harness offers on the models screen, by the names they show."""
    return [found[1] for line in lines(screen) if (found := re.match(r"[› ]   [■□] (.+)", line))]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class NoFamilyWord(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.fakes = fakeadapter.install(self.home, claude="pass", codex="pass",
                                         antigravity="pass")

    def test_a_seat_s_row_names_its_model_without_its_maker_s_word(self):
        akconfig.write(self.home, {"sol": {"harness": "codex", "model": "gpt-6.1-sol",
                                           "effort": "max"},
                                   "argon": {"harness": "antigravity", "model": "gemini-4-argon"},
                                   "opus": {}})
        for seat, model in (("fix-api", "sol"), ("acme-ask", "argon"), ("acme-web", "opus")):
            Seat(self.home, seat, model=model)
        term = Terminal(self.home, size=(110, 40), env={"NO_COLOR": "1"})
        screen = term.wait(lambda screen: all(row(screen, seat) for seat in
                                              ("fix-api", "acme-ask", "acme-web")), bound=OPENS)
        self.assertRegex(row(screen, "fix-api"), r"^[› ] \d+  fix-api +6\.1 Sol max  ")
        self.assertRegex(row(screen, "acme-ask"), r"^[› ] \d+  acme-ask +4 Argon high  ")
        self.assertRegex(row(screen, "acme-web"), r"^[› ] \d+  acme-web +Opus 5\.5 xhigh  ")

    def models_screen(self):
        """Codex's and Antigravity's models as the models screen offers them, after taking in
        6.1 Sol; and the name the config files it under."""
        akconfig.write(self.home, ["opus", "astra", "gemini"])
        term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        term.wait("esc leave", bound=OPENS)
        term.keys("c")
        term.wait("› Opus 5.5")
        term.keys("j", "j", "j")
        term.wait("› Models")
        term.keys("Enter")
        term.wait("› Claude Code  Opus 5.5")
        term.keys("j", "Enter")
        codex = offered(term.wait(lambda screen: "›   ■ 6 Astra" in lines(screen), bound=LISTS))
        term.keys("Up" if codex.index("6.1 Sol") < codex.index("6 Astra") else "Down")
        term.wait("›   □ 6.1 Sol")
        term.keys("Space")
        term.wait("›   ■ 6.1 Sol")
        term.keys("Escape")
        term.wait("› Codex        6 Astra, 6.1 Sol")
        term.keys("j", "Enter")
        agy = offered(term.wait(lambda screen: "    □ GPT-OSS 120B" in lines(screen), bound=LISTS))
        filed = [name for name, entry in akconfig.read(self.home)["models"].items()
                 if entry["model"] == "gpt-6.1-sol"]
        return codex, agy, filed

    def test_the_models_screen_names_what_a_harness_lists_without_its_maker_s_word(self):
        for harness, listing in LISTED.items():
            self.fakes[harness].answer("models", listing)
        # after Antigravity's listed ones the config's 3.8 Flash, which it does not list
        self.assertEqual(self.models_screen(),
                         (["Codex's own model", "6.1 Sol", "6 Astra"],
                          ["4 Argon", "GPT-OSS 120B", "3.8 Flash"], ["sol"]))

    def test_the_models_screen_names_what_a_table_answers_without_its_maker_s_word(self):
        codex, agy, filed = self.models_screen()      # the fakes list nothing: the tables answer
        self.assertLessEqual({"6.1 Sol", "6 Astra", "Codex's own model"}, set(codex))
        self.assertLessEqual({"4 Argon", "GPT-OSS 120B"}, set(agy))
        self.assertEqual(filed, ["sol"])


if __name__ == "__main__":
    unittest.main()
