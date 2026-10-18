"""`n` makes the new seat's row in its place on the main screen, numbered as it will be, its name
typed there; Enter makes the seat and opens it, Esc takes the row back.  The owner's pick of 18
Oct 2026.  The keyboard tests drive `menu.loop` on a pty (tests/test_close_and_info.py's `Menu`)
with the making of a seat faked too; nothing here starts a seat or a tmux server.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
import test_close_and_info
from test_close_and_info import ENTER, ESC, Menu
from agentkit import menu, terminal

MADE = """
orch.create = lambda cfg, name, cwd, **kw: print(
    f"<made {name} under {kw['repo']} by {kw['selection'][1][0]}>", flush=True) or ["true"]
"""
CHILD = test_close_and_info.CHILD.replace("sys.exit(menu.loop(", MADE + "sys.exit(menu.loop(")


def seat(name, number, repo=None):
    return {"number": str(number), "name": name, "orchestrator": "opus", "count": "working",
            "word": "working", "crew": ([], []), "tasks": [], "sentence": "", "repo": repo}


@patch.object(test_close_and_info, "CHILD", CHILD)
class Keys(unittest.TestCase):
    def test_n_types_the_name_in_place_and_enter_makes_the_seat_and_opens_it(self):
        shown = Menu(self, {"alpha": "working", "beta": "working"})
        shown.frame()
        shown.send(b"n")
        lines = shown.frame(keys="esc back")
        self.assertRegex(shown.highlighted(lines), r"^›\s+3  ▏a name, or ⏎\s+\S+\s+new$")
        self.assertIn(menu.BORN_KEYS, lines[-1])
        shown.send(b"Fix Apix\x7f")               # a space is a dash, and Backspace takes one back
        shown.frame(lambda lines: "fix-api▏" in shown.highlighted(lines), keys="esc back")
        mark = shown.mark()
        shown.send(ENTER)
        shown.saw("<made fix-api under None by ", "<opened fix-api>", after=mark)
        shown.leave()

    def test_esc_takes_the_row_back_and_a_taken_name_starts_nothing_on_a_phone(self):
        shown = Menu(self, {"alpha": "working"}, cols=40)
        shown.frame()
        shown.send(b"n")
        shown.frame(keys="esc back")
        shown.send(b"alpha")
        lines = shown.frame(lambda lines: any("a seat is called alpha already" in line
                                              for line in lines), keys="esc back")
        self.assertTrue(all(terminal.cells(line) <= 40 for line in lines), lines)
        mark = shown.mark()
        shown.send(ENTER + ESC)
        lines = shown.frame(after=mark)
        self.assertEqual([line for line in lines if "alpha" in line], [shown.highlighted(lines)])
        self.assertNotIn("<made", shown.text())
        shown.leave()


class Row(unittest.TestCase):
    def test_it_goes_last_under_its_project_and_the_rows_after_it_are_numbered_on(self):
        acme, docs = Path("/c/acme"), Path("/c/docs")
        groups = ([{"name": "acme", "checkout": acme, "seats": [seat("fix-api", 1, acme)]},
                   {"name": "docs", "checkout": docs, "seats": [seat("blog", 2, docs)]}],
                  [], 0, {})
        born = {"typed": "", "like": "fix-api", "repo": acme, "taken": set(), "selected": {
            "orchestrator": "opus", "workers": ["astra"], "reviewers": ["fable"]}}
        ordered, *_ = menu.born_groups(groups, born)
        self.assertEqual([[(info["number"], info["name"]) for info in project["seats"]]
                          for project in ordered],
                         [[("1", "fix-api"), ("2", menu.BORN)], [("3", "blog")]])
        self.assertEqual([info["number"] for info in groups[0][1]["seats"]], ["2"])  # as it was
        ordered, *_ = menu.born_groups(groups, {**born, "repo": Path("/c/beta")})
        self.assertEqual([project["name"] for project in ordered], ["acme", "beta", "docs"])


if __name__ == "__main__":
    unittest.main()
