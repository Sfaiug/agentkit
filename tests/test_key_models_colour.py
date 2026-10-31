"""The models screen draws no maker's colour when it opens, though the highlight is on the first
role's pick; once ↓ moves it onto a row, every row of that row's maker, in every role, has its
company's colour, its provider's `colour`: its line in it, its name in it lifted a quarter of the
way toward the foreground, a dark background's white.  No row of another maker has it.  ↑ on the
first row, where the highlight cannot move, lights its maker too.  A provider whose `maker`
names the boards' maker is its company, as `mimo`'s names Xiaomi.

The owner's ask of 30 Oct 2026, colour only under the pointer.  Black-box, as
tests/test_key_models_answer.py: the program `AK_BIN` names in a terminal with its colours
(tests/fixtures/akterm.py), its harness a fake listing an invented model, the boards held as
just asked with invented rows of two invented makers; judged by how each cell looks
(tests/fixtures/aklooks.py).  Fails against /bin/false.
"""

import re
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from fixtures.aklooks import colours, plain, settled
import test_key_models_answer as answer

# each maker's colour by its models' first word, every channel a multiple of 4, so a quarter of
# the way to white is never half way between two; Bolt's provider is named apart from its maker
COLOURS = {"Acme": (224, 64, 64), "Bolt": (64, 160, 224)}
PROVIDERS = {"acme": {"mode": "subscription", "colour": "#E04040"},
             "bolt": {"mode": "subscription", "colour": "#40A0E0", "maker": "Bolt Labs"}}
ROW = re.compile(r"[ ›] .{7}  (\S.*?) +([━╸─]{8,}) +\d+\.\d +\$\d+\.\d\d")


def sgr(rgb):
    return "38;2;" + ";".join(map(str, rgb))


def lifted(rgb):
    return tuple(round(channel * 0.75 + 255 * 0.25) for channel in rgb)


def boards():
    """test_key_models_answer's but for Crux 2, whose build line is empty: Bolt 3 made by Bolt
    Labs, the rest by Acme."""
    held = answer.boards()
    for board in held.values():
        board["rows"] = [row for row in board["rows"] if row["model"] != "Crux 2"]
    for row in held["artificialanalysis.ai"]["rows"]:
        row["maker"] = "Bolt Labs" if row["model"] == "Bolt 3" else "Acme"
    return held


def rows(lines):
    """(its role, its name's first word, the look of each cell of its name, the look of its
    line's last full cell, its line) of each row drawn on one line."""
    found, role = [], None
    for line in lines:
        text = plain(line)
        drawn = ROW.match(text)
        if drawn:
            name = drawn[1].split("  ")[0]
            tip = drawn.start(2) + len(drawn[2].rstrip("─")) - 1
            found.append((role, name.split()[0], [line[at][1] for at in range(
                drawn.start(1), drawn.start(1) + len(name)) if line[at][0] != " "],
                          line[tip][1], line))
        elif re.match(r"  [a-z]", text):
            role = text.split()[0]
    return found


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsColour(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        fakes = fakeadapter.install(self.home, claude="pass")
        fakes["claude"].answer("models", "acme-mid-5\tAcme Mid 5\tlow medium high xhigh max\n")
        self.home.write(".agentkit/state/boards.json", boards())

    def models(self, **settings):
        """`r` on `c` in a window of its own, once its answer rests: no maker's colour on it."""
        akconfig.write(self.home, {"mid": {"harness": "claude", "model": "acme-mid-5"}},
                       providers=PROVIDERS, settings=settings)
        env = {key: value for key, value in answer.ENV.items() if key != "NO_COLOR"}
        self.term = Terminal(self.home, size=(100, 60), env={**env, "COLORTERM": "truecolor"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait("r recommended")
        self.term.keys("r")
        shown = settled(self.term, "comparing all 3 models")
        self.assertEqual({made for _, made, *_ in rows(shown)}, set(COLOURS))
        self.assertFalse({sgr(paint(rgb)) for rgb in COLOURS.values()
                          for paint in (tuple, lifted)} & colours(shown))
        return shown

    def pointed(self, maker):
        """The screen once the highlight rests on a row of `maker`'s, each of its rows lit."""
        rgb = COLOURS[maker]
        self.term.wait(lambda _: sgr(lifted(rgb)) in self.term.screen(colours=True))
        shown = settled(self.term, lambda screen: any(
            line.startswith("› ") and f"  {maker} " in line for line in screen.split("\n")))
        found = rows(shown)
        self.assertEqual({role for role, made, *_ in found if made == maker},
                         {"orch", "builds", "reviews"})
        for role, made, name, tip, line in found:
            if made == maker:
                self.assertTrue(all(sgr(lifted(rgb)) in look for look in name), (role, name))
                self.assertIn(sgr(rgb), tip, role)
            else:
                self.assertFalse({sgr(rgb), sgr(lifted(rgb))} & colours([line]), (role, made))

    def test_no_maker_lights_at_rest_and_the_pointed_rows_maker_lights(self):
        self.models()
        self.term.keys("Down")
        self.pointed("Acme")
        self.term.keys("Down", "Down", "Down")
        self.pointed("Bolt")

    def test_up_where_the_highlight_cannot_move_lights_its_maker(self):
        # within no points of the best the first role's pick is its best, the first row
        shown = self.models(within=0)
        self.assertTrue(next(plain(line) for line in shown if plain(line).startswith("› "))
                        .startswith("› ★ pick   Acme"))
        self.term.keys("Up")
        self.pointed("Acme")

if __name__ == "__main__":
    unittest.main()
