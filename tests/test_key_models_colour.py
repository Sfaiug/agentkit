"""The models screen draws no maker's colour when it opens, though the highlight is on the first
role's pick; once ↓ moves it onto a row, every row of that row's maker, in every role, has the
company's colour, its provider's `colour`: its line in it, its name in it lifted a quarter of the
way toward the foreground, a dark background's white.  No row of another maker has it.

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

# each maker's company and colour, every channel a multiple of 4, so a quarter of the way to
# white is never half way between two
MAKERS = {"Acme": ("acme", (224, 64, 64)), "Bolt": ("bolt", (64, 160, 224))}
ROW = re.compile(r"[ ›] .{7}  (\S.*?) +([━╸─]{8,}) +\d+\.\d +\$\d+\.\d\d")


def sgr(rgb):
    return "38;2;" + ";".join(map(str, rgb))


def lifted(rgb):
    return tuple(round(channel * 0.75 + 255 * 0.25) for channel in rgb)


def boards():
    """test_key_models_answer's but for Crux 2, whose build line is empty: Bolt 3 made by
    Bolt, the rest by Acme."""
    held = answer.boards()
    for board in held.values():
        board["rows"] = [row for row in board["rows"] if row["model"] != "Crux 2"]
    for row in held["artificialanalysis.ai"]["rows"]:
        row["maker"] = "Bolt" if row["model"] == "Bolt 3" else "Acme"
    return held


def rows(lines):
    """(its role, its maker, the look of each cell of its name, the look of its line's last
    full cell, its line) of each row drawn on one line."""
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
        akconfig.write(self.home, {"mid": {"harness": "claude", "model": "acme-mid-5"}},
                       providers={company: {"mode": "subscription",
                                            "colour": "#%02X%02X%02X" % rgb}
                                  for company, rgb in MAKERS.values()})
        self.home.write(".agentkit/state/boards.json", boards())
        env = {key: value for key, value in answer.ENV.items() if key != "NO_COLOR"}
        self.term = Terminal(self.home, size=(100, 60), env={**env, "COLORTERM": "truecolor"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait("esc leave")
        self.term.keys("c")
        self.term.wait("r recommended")
        self.term.keys("r")

    def test_no_maker_lights_at_rest_and_down_lights_the_pointed_rows_maker(self):
        shown = settled(self.term, "comparing all 3 models")
        self.assertTrue(rows(shown))
        self.assertFalse({sgr(paint(rgb)) for _, rgb in MAKERS.values()
                          for paint in (tuple, lifted)} & colours(shown))
        self.term.keys("Down")
        shown = settled(self.term, lambda screen: "› ★ pick" not in screen)
        found = rows(shown)
        _, rgb = MAKERS["Acme"]
        self.assertEqual([maker for _, maker, *_, line in found if plain(line)[0] == "›"],
                         ["Acme"])
        self.assertEqual({role for role, maker, *_ in found if maker == "Acme"},
                         {"orch", "builds", "reviews"})
        self.assertIn("Bolt", {maker for _, maker, *_ in found})
        for role, maker, name, tip, line in found:
            if maker == "Acme":
                self.assertTrue(all(sgr(lifted(rgb)) in look for look in name), (role, name))
                self.assertIn(sgr(rgb), tip, role)
            else:
                self.assertFalse({sgr(rgb), sgr(lifted(rgb))} & colours([line]), role)


if __name__ == "__main__":
    unittest.main()
