"""On 40 cells `r recommended` on `c` names every model in full, its version included, and cuts
no word (docs/cli-design.md): each role's lines hold the model it uses at its effort, and each
bar's label its model's name, a word wider than its six-cell column broken only after a hyphen
or a dot in it, and one with neither whole in a wider column; `ak models` on 40 cells the same,
a control sequence in a board's name never reaching the terminal.

Black-box: `AK_BIN` in a terminal 40 cells wide (tests/fixtures/akterm.py) and as `ak models`, a
fake harness running three invented models, each for a role of [defaults], among five choices on
the boards as tests/test_key_role_choices.py writes them; judged by the screen and the output.
Fails against /bin/false.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_answer import ENV
from test_key_models_bars import bars
from test_key_models_role_lines import said
from test_key_role_choices import hold

# Release, name, effort, quality and cost a task: five choices, cheapest first, so five bars in
# six-cell columns.  Anvil is long with its version, Bolt has a hyphen and a dot in a word wider
# than six cells, Crux a word of eight letters with neither.
ROWS = [("acme-gale-2", "Acme Gale 2", "high", 91, 1),
        ("bolt-7-1-sol", "Bolt-7.1 Sol", "high", 93, 2),
        ("crux-monolith-2", "Crux Monolith 2", "high", 95, 3),
        ("acme-dune-3", "Acme Dune 3", "high", 97, 4),
        ("acme-anvil-5-5", "Acme Anvil 5.5", "xhigh", 100, 8)]
# [defaults]: the three, Anvil orchestrating, Bolt building, Crux reviewing, and what each role's
# lines name
CONFIGURED = {"anvil": ("acme-anvil-5-5", "xhigh"), "bolt": ("bolt-7-1-sol", "high"),
              "crux": ("crux-monolith-2", "high")}
USES = {"orchestrator": "Acme Anvil 5.5 xhigh", "executor": "Bolt-7.1 Sol high",
        "reviewer": "Crux Monolith 2 high"}


def whole(name, text):
    """Whether `text` holds `name` with each word whole or broken only after a hyphen or a dot
    in it, its words and their parts on one line or several."""
    words = ["".join(re.escape(c) + r"\s*" * (c in "-.") for c in word) for word in name.split()]
    return re.search(r"(?<!\S)" + r"\s+".join(words) + r"(?!\S)", text) is not None


def role_lines(screen):
    """Each role's lines under the column heads, from its word's to the next role's, on one."""
    shown = said(screen)
    at = [n for n, line in enumerate(shown) if set(line.split()) & set(USES)]
    return {next(word for word in USES if word in shown[n].split()): " ".join(shown[n:end])
            for n, end in zip(at, [*at[1:], None])}


def in_full(screen):
    """Whether every role's lines and every one of the orchestrator's bars' labels name its
    model in full; False before they are drawn."""
    try:
        roles, labels = role_lines(screen), [bar["name"] for bar in bars(screen, "orchestrator")]
    except (StopIteration, ValueError, IndexError):
        return False
    return (roles.keys() == USES.keys() and all(whole(USES[role], roles[role]) for role in USES)
            and len(labels) == len(ROWS)
            and all(whole(name, label) for (_, name, *_), label in zip(ROWS, labels)))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsNamesInFull(unittest.TestCase):
    def home(self, mark=""):
        """A home over ROWS and CONFIGURED, `mark` after each name's first word."""
        home = Home()
        self.addCleanup(home.close)
        rows = [(release, name.replace(" ", " " + mark, 1), *rest)
                for release, name, *rest in ROWS]
        fakeadapter.install(home, claude="pass")["claude"].answer("models", "".join(
            f"{release}\t{name}\thigh xhigh\n" for release, name, *_ in rows))
        akconfig.write(home, {short: {"harness": "claude", "model": release, "effort": effort}
                              for short, (release, effort) in CONFIGURED.items()},
                       orchestrator="anvil", workers=["bolt"], reviewers=["crux"])
        hold(home, [(release, name, effort, quality / 100 - 0.1, cost)
                    for release, name, effort, quality, cost in rows])
        return home

    def test_on_40_cells_each_role_line_and_bar_label_names_its_model_in_full(self):
        home = self.home()
        term = Terminal(home, size=(40, 40), env=ENV)
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys("r")
        term.wait(in_full)

    def test_ak_models_on_40_cells_names_them_in_full_and_no_boards_control_sequence(self):
        done = self.home("\x1b[2J").ak("models", env={**ENV, "COLUMNS": "40"})
        self.assertEqual(done.code, 0, done.err)
        self.assertNotIn("\x1b", done.out)
        self.assertTrue(in_full(done.out), done.out)


if __name__ == "__main__":
    unittest.main()
