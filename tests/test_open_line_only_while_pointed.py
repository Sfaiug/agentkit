"""A row opens its line only while the owner points at it, with the pointer or ↑/↓.

The owner's report (18 Oct 2026): one row always showed its line, the one highlighted by default
or the last the pointer had been on, though the pointer was on none.  The line opens under the
row the pointer is on, or the one ↑/↓ moved to, and closes once the pointer is on no row.  The
menu runs in a child on a pty of its own (`test_menu_keys.Menu`), its seats and their words
faked; nothing here starts a session, a tmux server or a probe.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_hover import move  # noqa: E402
from test_menu_keys import DOWN, Menu  # noqa: E402

ASKED = "Which schema should acme use, the old one or the new one?"
UP = b"\x1b[A"


def row(lines, name):
    """The screen row `name`'s row is on, counted from 1."""
    return next(number for number, line in enumerate(lines, 1) if f" {name} " in f"{line} ")


class OpensOnlyWhilePointed(unittest.TestCase):
    def test_the_line_opens_under_the_pointer_or_the_arrows_and_closes_off_every_row(self):
        menu = Menu(self, ["acme-plan", "acme-api", "acme-web"], asks={"acme-plan": ASKED})
        lines = menu.frame()
        self.assertIn("acme-plan", menu.highlighted(lines))     # the first, so lit
        self.assertNotIn(ASKED, "\n".join(lines), "a line open that nothing points at")
        menu.send(move(20, row(lines, "acme-plan")))
        lines = menu.frame(lambda lines: ASKED in "\n".join(lines))
        self.assertEqual(lines[row(lines, "acme-plan")].strip(), ASKED)     # under its row
        menu.send(move(1, 2))                                   # the rule: on no row
        menu.frame(lambda lines: ASKED not in "\n".join(lines)
                   and not any(line.startswith("›") for line in lines))
        menu.send(DOWN)                                         # the arrows point too
        lines = menu.frame(lambda lines: any(line.startswith("›") for line in lines))
        self.assertIn("acme-api", menu.highlighted(lines))
        self.assertNotIn(ASKED, "\n".join(lines))               # which says nothing more
        menu.send(UP)
        lines = menu.frame(lambda lines: "acme-plan" in menu.highlighted(lines)
                           and ASKED in "\n".join(lines))
        menu.send(move(*keyline(lines)))
        menu.frame(lambda lines: ASKED not in "\n".join(lines))
        menu.leave()

    def test_a_key_that_opens_nothing_keeps_the_line_the_arrows_opened(self):
        menu = Menu(self, ["acme-plan", "acme-api"], asks={"acme-plan": ASKED})
        menu.frame()
        menu.send(DOWN)
        menu.frame(lambda lines: "acme-api" in menu.highlighted(lines))
        menu.send(UP)
        menu.frame(lambda lines: ASKED in "\n".join(lines))
        mark = len(menu.text())
        menu.send(b"i")
        lines = menu.frame(after=mark)
        menu.leave()
        self.assertIn(ASKED, "\n".join(lines))

    def test_back_from_a_seat_no_line_is_open_though_the_pointer_moved_while_its_number_was_typed(
            self):
        menu = Menu(self, [f"acme-{n:02}" for n in range(1, 13)], asks={"acme-01": ASKED})
        lines = menu.frame()
        menu.send(b"1" + move(20, row(lines, "acme-01")))   # while 1 waits for a second digit
        menu.saw("<opened acme-01>")
        lines = menu.frame(after=menu.text().index("<opened acme-01>"))
        menu.leave()
        self.assertNotIn(ASKED, "\n".join(lines))

    def test_a_row_moved_from_under_the_pointer_opens_no_line(self):
        long = "Choose a schema. " + "The importer still reads the old fields and the new. " * 5
        menu = Menu(self, ["acme-api", "acme-web"], asks={"acme-api": long, "acme-web": ASKED})
        lines = menu.frame()
        menu.send(move(20, row(lines, "acme-api")))
        lines = menu.frame(lambda lines: "Choose a schema." in "\n".join(lines))
        below = row(lines, "acme-web")
        mark = len(menu.text())
        menu.send(move(20, below))                  # its question closes, and acme-web moves up
        lines = menu.frame(after=mark)
        self.assertEqual(lines[below - 1].strip(), "")
        self.assertNotIn(ASKED, "\n".join(lines))
        mark = len(menu.text())
        menu.send(b"i")                             # nor does a key that opens nothing
        lines = menu.frame(after=mark)
        menu.leave()
        self.assertNotIn(ASKED, "\n".join(lines))

    def test_the_pointer_on_the_name_of_a_seat_with_a_plan_opens_its_line(self):
        # at 50 columns its progress line is under its name, and the line opens under both
        menu = Menu(self, ["acme-plan", "acme-web"], cols=50, asks={"acme-plan": "Deploy?"},
                    plans={"acme-plan": "- [x] done\n- [ ] todo\n"})
        lines = menu.frame()
        self.assertIn("1 of 2", lines[row(lines, "acme-plan")])
        menu.send(move(20, row(lines, "acme-plan")))
        menu.frame(lambda lines: "Deploy?" in "\n".join(lines))
        menu.leave()


def keyline(lines):
    """(column, row) of `n new` on the key line."""
    return lines[-1].index("n new") + 1, len(lines)


if __name__ == "__main__":
    unittest.main()
