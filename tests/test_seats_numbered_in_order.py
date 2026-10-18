"""Seats are numbered 1, 2, 3 down the screen, and each keeps its place whatever its word.

The owner's report (18 Oct 2026): the numbers looked random.  Each seat's number was its place
by name among every seat, the stopped ones included, while the rows sorted needing projects
first and seats by their word.  Projects now come in the order of their oldest seat and seats in
the order they were made, so a seat's number is its place on the screen, and one made or
stopped moves only the ones after it.  Offline: a temporary HOME, fake tmux seats, no tmux.
"""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, orch, terminal, watch  # noqa: E402


class Numbered(Sandbox):
    def setUp(self):
        super().setUp()
        for project in ("acme", "docs"):
            directory = config.CODE / project
            directory.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", "-b", "main", str(directory)], check=True)
        # what tmux holds: every instance started at once, as a restart of its server leaves them
        self.tmux, self.stopped, self.words = [], {}, {}
        self.stack.enter_context(patch.object(orch, "sessions",
                                              lambda: [dict(seat) for seat in self.tmux]))
        self.stack.enter_context(patch.object(watch, "seat_stopped_at", self.stopped.get))
        self.stack.enter_context(patch.object(menu, "seat_row_state", lambda cfg, session, **_kw: {
            "word": self.words.get(session["name"], "working"), "reason": "", "since": None}))
        for name, project, made in (("acme-api", "acme", 100), ("docs-site", "docs", 200),
                                    ("acme-web", "acme", 300), ("docs-blog", "docs", 400)):
            self.made(name, project, made)

    def made(self, name, project, at):
        directory = str(config.CODE / project)
        config.save_session(self.cfg, name, "fable", ["opus"],
                            {"repo": directory, "cwd": directory, "created": at})
        self.tmux.append({"name": name, "path": directory, "created": 9000, "attached": False,
                          "exited": False, "legacy": False})

    def stop(self, name):
        self.tmux = [seat for seat in self.tmux if seat["name"] != name]
        self.stopped[name] = 9500

    def screen(self):
        """Each row's number and name, top to bottom, and the seats as the menu has them."""
        found = orch.listing(reconcile=False)
        groups, *_ = menu.v5o_groups(self.cfg, found, records=[], now=10_000, look=False)
        rows = [(info["number"], info["name"]) for project in groups for info in project["seats"]]
        for number, name in rows:       # what Enter on a row opens is that row's number
            self.assertEqual(menu.pressed(terminal.Key("enter"), {"cursor": name}, found), number)
        return rows, found

    def test_rows_are_numbered_down_the_screen_in_the_order_they_were_made(self):
        rows, _ = self.screen()
        self.assertEqual(rows, [("1", "acme-api"), ("2", "acme-web"),
                                ("3", "docs-site"), ("4", "docs-blog")])

    def test_a_seat_keeps_its_place_whatever_its_word(self):
        before, _ = self.screen()
        self.words.update({"docs-blog": "needs you", "acme-api": "idle"})
        self.assertEqual(self.screen()[0], before)

    def test_one_made_or_stopped_moves_only_the_ones_after_it(self):
        self.stop("acme-web")
        rows, found = self.screen()
        self.assertEqual(rows, [("1", "acme-api"), ("2", "docs-site"), ("3", "docs-blog")])
        self.assertEqual([session["name"] for session in found][3:], ["acme-web"])   # past: 4
        self.made("acme-ops", "acme", 500)
        rows, _ = self.screen()
        self.assertEqual(rows, [("1", "acme-api"), ("2", "acme-ops"),
                                ("3", "docs-site"), ("4", "docs-blog")])


if __name__ == "__main__":
    unittest.main()
