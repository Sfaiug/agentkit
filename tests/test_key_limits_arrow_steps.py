"""On `config · limits`, ← and → move the limit the pointer is on one step down or up, saved to
config.toml at once: `Review rounds` 0 to 5, `Max lines per executor task` 0 to 1000 in
hundreds then `no limit`, `Max lines per orchestrator task` 0 to 200 in 25s then `no limit`.  A
value between steps, as written by hand, moves to the next step in the arrow's direction, and
neither arrow moves past an end.  The pointed row shows its value as `◂ value ▸`, a side's arrow
left out at that end, a click on one moving it as its key does, and the key line reads
`↑↓ limit   ←→ value   esc back`.  With the pointer off every row, the first ← or → only
brings the highlight back, as Enter and Space do.

The owner's design of 5 Nov 2026.  Black-box: the program `AK_BIN` names, in a person's
terminal (tests/fixtures/akterm.py), its harnesses the fakes of tests/fixtures/fakeadapter.py,
judged by the screen and config.toml.  The terminal has no colour (NO_COLOR).  This test fails
against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal

MODELS = {"fable": {"harness": "claude", "effort": "xhigh"},
          "astra": {"harness": "codex", "effort": "high"}}
# each row's name: its key in config.toml, its steps and ak's default
LIMITS = {"Review rounds": ("review_rounds", list(range(6)), 3),
          "Max lines per executor task": ("executor_lines", [*range(0, 1001, 100), "no limit"], 300),
          "Max lines per orchestrator task": ("orchestrator_lines", [*range(0, 201, 25), "no limit"],
                                              50)}
NAMES = list(LIMITS)
WIDE = max(map(len, NAMES))
KEY_LINE = "  ↑↓ limit   ←→ value   esc back"


def lines(screen):
    return [line.rstrip() for line in screen.split("\n")]


def row(name, value, on=False, down=True, up=True):
    """`name`'s row as drawn: its value, `off` for 0, between the arrows it moves by where `on`,
    and `default N` after where that is not ak's default."""
    default = LIMITS[name][2]
    shown = " ".join([*["◂"] * (on and down), "off" if value == 0 else str(value),
                      *["▸"] * (on and up), *[f"default {default}"] * (value != default)])
    return f"{'›' if on else ' '} {name:<{WIDE}}  {shown}"


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ArrowSteps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        fakeadapter.install(cls.home, claude="pass", codex="pass")

    def limits(self, settings=None):
        """`config · limits` from `c`, in a window of its own, over a config.toml setting
        `settings`."""
        akconfig.write(self.home, MODELS, settings=settings)
        term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        term.keys("c")
        term.wait("r recommended")
        term.keys(*["j"] * 30)       # Limits is the last config row.
        term.wait("› Limits")
        term.keys("Enter")
        term.wait("config · limits")
        return term

    def pointed(self, term, name, value, **ends):
        """Once `name`'s row is pointed and shows `value`: the screen's lines, and `value` is
        what config.toml holds."""
        shown = lines(term.wait(lambda screen: row(name, value, True, **ends) in lines(screen)))
        self.assertEqual(akconfig.read(self.home).get(LIMITS[name][0], LIMITS[name][2]), value)
        return shown

    def point(self, term, name, value, **ends):
        term.keys(*["j"] * NAMES.index(name))
        return self.pointed(term, name, value, **ends)

    def test_the_pointed_row_shows_its_value_between_arrows_and_the_key_line_names_them(self):
        term = self.limits()
        shown = self.pointed(term, NAMES[0], 3)
        self.assertEqual([line for line in shown if any(name in line for name in NAMES)],
                         [row(NAMES[0], 3, on=True), row(NAMES[1], 300), row(NAMES[2], 50)])
        self.assertIn(KEY_LINE, shown)
        term.keys("j")
        shown = self.pointed(term, NAMES[1], 300)
        self.assertEqual([line for line in shown if any(name in line for name in NAMES)],
                         [row(NAMES[0], 3), row(NAMES[1], 300, on=True), row(NAMES[2], 50)])
        self.assertIn(KEY_LINE, shown)

    def test_each_limit_walks_its_steps_from_0_up_and_back_each_saved_at_once(self):
        for name, (key, steps, _) in LIMITS.items():
            with self.subTest(name=name):
                term = self.limits({key: 0})
                self.point(term, name, 0, down=False)
                path = [*range(1, len(steps)), *range(len(steps) - 2, -1, -1)]
                for at, before in zip(path, [0, *path]):
                    term.keys("Right" if at > before else "Left")
                    self.pointed(term, name, steps[at], down=at > 0, up=at < len(steps) - 1)

    def test_a_value_between_steps_moves_to_the_next_step_each_way(self):
        for name, held, arrow, value in ((NAMES[1], 250, "Right", 300), (NAMES[1], 250, "Left", 200),
                                         (NAMES[1], 2000, "Right", "no limit"),
                                         (NAMES[1], 2000, "Left", 1000),
                                         (NAMES[2], 60, "Right", 75), (NAMES[2], 60, "Left", 50)):
            with self.subTest(name=name, held=held, arrow=arrow):
                term = self.limits({LIMITS[name][0]: held})
                self.point(term, name, held)
                term.keys(arrow)
                self.pointed(term, name, value, up=value != "no limit")

    def test_neither_end_moves_further(self):
        for name, (key, steps, _) in LIMITS.items():
            with self.subTest(name=name):
                term = self.limits({key: 0})
                self.point(term, name, 0, down=False)
                term.keys("Left", "Right")      # ← at the bottom moves nothing: → takes the next
                self.pointed(term, name, steps[1])
                # → past the top moves nothing: ← takes the one under it
                term.keys(*["Right"] * len(steps), "Left")
                self.pointed(term, name, steps[-2])

    def test_a_click_on_an_arrow_moves_the_value_as_its_key_does(self):
        term = self.limits()
        for name, (_, steps, default) in LIMITS.items():
            with self.subTest(name=name):
                at = steps.index(default)
                for arrow, value in (("▸", steps[at + 1]), ("◂", default), ("◂", steps[at - 1])):
                    shown = lines(term.wait(f"› {name}"))
                    row_at = next(number for number, line in enumerate(shown, 1)
                                  if line.startswith(f"› {name}"))
                    column = shown[row_at - 1].index(arrow) + 1
                    term.type(f"\x1b[<0;{column};{row_at}M\x1b[<0;{column};{row_at}m")
                    self.pointed(term, name, value)
                term.keys("j")

    def test_with_the_highlight_hidden_the_first_arrow_only_brings_it_back(self):
        for arrow, value in (("Left", 2), ("Right", 4)):
            with self.subTest(arrow=arrow):
                term = self.limits()
                self.pointed(term, NAMES[0], 3)
                term.type("\x1b[<35;8;1M")      # the pointer onto the header: no row lit
                term.wait(lambda screen: not any(line.startswith("›") for line in lines(screen)))
                term.keys(arrow)
                self.pointed(term, NAMES[0], 3)
                term.keys(arrow)                # the keys go on from there
                self.pointed(term, NAMES[0], value)


if __name__ == "__main__":
    unittest.main()
