"""`n` makes the new seat's row in its place on the main screen, numbered as it will be, its name
typed there, else the free Clone Wars character's it shows (`orch.character_name`), last under
`not assigned yet` after every project, as its orchestrator has not filed it; Enter makes
the seat and opens it, Esc takes the row back.  The owner's pick of 18 Oct 2026.  The keyboard tests drive `menu.loop` on a pty (tests/test_close_and_info.py's `Menu`)
with the making of a seat faked too; nothing here starts a seat or a tmux server.
"""

import io
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
import test_close_and_info
from test_close_and_info import ENTER, ESC, Menu
from agentkit import menu, orch, terminal

MADE = """
orch.create = lambda cfg, name, cwd, **kw: print(
    f"<made {name} under {kw.get('repo')} by {kw['selection'][1][0]}>", flush=True) or ["true"]
"""
CHILD = test_close_and_info.CHILD.replace("sys.exit(menu.loop(", MADE + "sys.exit(menu.loop(")
# every harness logged out: the crew `n` starts with has no pair that can run
LOGGED_OUT = """
readings = menu.usage.Readings({})
readings.harnesses = {harness: f"{harness} is not logged in" for harness in ("claude", "codex")}
menu.usage.collect = lambda cfg, **kwargs: readings
"""

# /c/acme a project's checkout, which only a checkout under ~/code is otherwise
ACME = """
orch.checkout_of = lambda repo, stands=None: Path(repo) if repo else None
"""


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
        self.assertRegex(shown.highlighted(lines), r"^›\s+3  ▏[a-z]+\s+\S+\s+new$")
        self.assertIn(menu.BORN_KEYS, lines[-1])
        shown.send(b"Fix Apix\x7f")               # a space is a dash, and Backspace takes one back
        shown.frame(lambda lines: "fix-api▏" in shown.highlighted(lines), keys="esc back")
        mark = shown.mark()
        shown.send(ENTER)
        shown.saw("<made fix-api under None by ", "<opened fix-api>", after=mark)
        shown.leave()

    def test_n_starts_last_under_not_assigned_yet_whatever_the_highlight_is_on(self):
        filed = CHILD.replace('{"name": name, "repo": None,',
                              '{"name": name, "repo": "/c/acme" if name == "alpha" else None,'
                              ).replace("sys.exit(menu.loop(", ACME + "sys.exit(menu.loop(")
        with patch.object(test_close_and_info, "CHILD", filed):
            shown = Menu(self, {"alpha": "working", "beta": "working"})
        lines = shown.frame()
        self.assertIn("alpha", shown.highlighted(lines))           # a seat of acme's
        shown.send(b"n")
        lines = shown.frame(keys="esc back")
        row = lines.index(shown.highlighted(lines))
        self.assertIn("▏", lines[row])
        headings = [line.strip() for line in lines[:row] if line and line[0] not in " ›"]
        self.assertEqual(headings[-2:], ["acme", "not assigned yet"])   # after every project
        self.assertNotIn("as in", "\n".join(lines))                 # nor alpha's crew
        mark = shown.mark()
        shown.send(b"fix-api" + ENTER)
        shown.saw("<made fix-api under None by ", "<opened fix-api>", after=mark)
        shown.leave()

    def test_n_shows_a_free_character_s_name_and_enter_alone_makes_the_seat_by_it(self):
        shown = Menu(self, {"alpha": "working", "beta": "working"})
        shown.frame()
        shown.send(b"n")
        lines = shown.frame(keys="esc back")
        name = re.match(r"^›\s+3  ▏(\S+)\s", shown.highlighted(lines))[1]
        self.assertIn(name, orch.CHARACTERS)
        mark = shown.mark()
        shown.send(ENTER)
        shown.saw(f"<made {name} under None by ", f"<opened {name}>", after=mark)
        shown.leave()

    def test_esc_takes_the_row_back_and_a_taken_name_starts_nothing_on_a_phone(self):
        shown = Menu(self, {"fix-api-review": "working"}, cols=40)
        shown.frame()
        shown.send(b"n")
        shown.frame(keys="esc back")
        shown.send(b"fix-api-review")
        lines = shown.frame(lambda lines: any("a seat is called" in line for line in lines),
                            keys="esc back")
        self.assertTrue(all(terminal.cells(line) <= 40 for line in lines), lines)
        self.assertIn("a seat is called fix-api-review already",
                      " ".join(line.strip() for line in lines), lines)     # wrapped, not cut
        mark = shown.mark()
        shown.send(ENTER + ESC)
        lines = shown.frame(after=mark)
        self.assertEqual([line for line in lines if "fix-api-review" in line],
                         [shown.highlighted(lines)])
        self.assertNotIn("<made", shown.text())
        shown.leave()

    def test_a_crew_with_no_pair_that_can_run_starts_nothing(self):
        child = CHILD.replace("sys.exit(menu.loop(", LOGGED_OUT + "sys.exit(menu.loop(")
        with patch.object(test_close_and_info, "CHILD", child):
            shown = Menu(self, {"alpha": "working"})
        shown.frame()
        shown.send(b"nfix-api")
        shown.frame(lambda lines: any("no allowed executor/reviewer pair" in line
                                      for line in lines), keys="esc back")
        mark = shown.mark()
        shown.send(ENTER + ESC)
        shown.frame(after=mark)
        self.assertNotIn("<made", shown.text())
        shown.leave()


class Row(unittest.TestCase):
    def test_it_goes_last_under_not_assigned_yet_numbered_as_it_will_be(self):
        acme, docs = Path("/c/acme"), Path("/c/docs")
        groups = ([{"name": "acme", "checkout": acme, "seats": [seat("fix-api", 1, acme)]},
                   {"name": "docs", "checkout": docs, "seats": [seat("blog", 2, docs)]}],
                  [], 0, {})
        born = {"typed": "", "taken": set(), "selected": {
            "orchestrator": "opus", "workers": ["astra"], "reviewers": ["fable"]}}
        ordered, *_ = menu.born_groups(groups, born)
        self.assertEqual([(project["name"], [(info["number"], info["name"])
                                             for info in project["seats"]])
                          for project in ordered],
                         [("acme", [("1", "fix-api")]), ("docs", [("2", "blog")]),
                          ("not assigned yet", [("3", menu.BORN)])])
        unfiled = {"name": "not assigned yet", "checkout": None, "seats": [seat("draft", 3)]}
        ordered, *_ = menu.born_groups(([*groups[0], unfiled], *groups[1:]), born)
        self.assertEqual([(project["name"], [info["number"] for info in project["seats"]])
                          for project in ordered],
                         [("acme", ["1"]), ("docs", ["2"]), ("not assigned yet", ["3", "4"])])

    def test_a_seat_filed_under_no_project_is_numbered_after_every_project(self):
        found = [{"name": "draft", "repo": None, "created": 1},
                 {"name": "zeta-fix", "repo": "/c/zeta", "created": 2},
                 {"name": "acme-fix", "repo": "/c/acme", "created": 3}]
        with patch.object(orch, "checkout_of", lambda repo, stands=None: Path(repo) if repo else None), \
                patch.object(orch, "listed", dict):
            self.assertEqual([seat["name"] for seat in orch.numbered(found, {})],
                             ["acme-fix", "zeta-fix", "draft"])

    def test_its_heading_is_dim_for_it_is_no_project(self):
        with patch.object(terminal, "colour_depth", lambda: 256):
            self.assertEqual(menu.v5o_header({"name": "acme", "checkout": Path("/c/acme")}, 100),
                             terminal.styled("acme", "bold"))
            self.assertEqual(menu.v5o_header({"name": menu.UNFILED, "checkout": None}, 100),
                             terminal.styled("not assigned yet", "dim"))

    def test_a_seat_left_unnamed_is_named_off_the_names_taken_now(self):
        born = {"cfg": {}, "typed": "", "taken": set(), "name": "new",
                "selected": {"orchestrator": "opus", "workers": ["astra"], "reviewers": ["fable"]}}
        printed = io.StringIO()
        # another menu made `new`, the name this row showed, after this one last read its seats
        with patch.object(orch, "listing", lambda **_kw: [{"name": "new"}]), \
                patch.object(orch, "CHARACTERS", ("new",)), \
                patch.object(orch, "alias_names", lambda names=None: set()), \
                patch.object(orch, "held_names", set), \
                patch.object(menu, "open_session", lambda *_args: None), \
                redirect_stdout(printed):
            self.assertEqual(menu.start_born(born, dry_run=True), "new-2")
        self.assertIn("would start new-2", printed.getvalue())


if __name__ == "__main__":
    unittest.main()
