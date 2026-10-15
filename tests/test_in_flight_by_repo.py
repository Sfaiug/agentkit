"""`ak orch project` shows what is in flight on the checkout, whatever each seat is filed under.

A seat filed under another project that has a going run on this checkout is listed with
what that run changes and its plan lines naming this checkout, never its other lines; a run of a
seat filed here that works on another checkout changes nothing here; and the checkout's open
pull requests that no going run reviews or delivers are listed with their files.
Offline: invented checkouts, seat records, plans and runs under a temporary HOME, gh faked.
"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import config, gitcall, orch, plan
from agentkit import record as run_record

TASK = "---\nfiles: {}\n---\n# t\n"
URL = "https://github.com/acme/acme/pull/{}"


class InFlightByRepo(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {config.SESSION_ENV: "fix-api"}))
        self.acme, self.bramble = config.CODE / "acme", config.CODE / "bramble"
        for checkout in (self.acme, self.bramble):
            (checkout / ".git").mkdir(parents=True)
        for seat, repo in (("fix-api", None), ("design", self.acme), ("growth", self.bramble)):
            config.save_session(self.cfg, seat, "fable", ["opus"],
                                {"cwd": str(config.CODE), "repo": str(repo) if repo else None})
        self.prs = []
        self.stack.enter_context(patch.object(gitcall, "gh", side_effect=lambda cwd, *args, **kw: (
            0, json.dumps(self.prs))))
        # a line names its checkout by path and root commit; these checkouts have no commits
        self.stack.enter_context(patch.object(plan, "place", side_effect=lambda seat, project: (
            Path(project.replace("~", str(Path.home()))) if "/" in project else None)))

    def add_run(self, name, seat, repo, files, **state):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        (directory / "task.md").write_text(TASK.format(files))
        run_record.save_state(directory, {"run_id": name, "launched_session": seat,
                                          "repo": str(repo), "state": "queued", **state})

    def line(self, what, checkout):
        return f"- [ ] {what} · check: `true` · {checkout} · written 2026-10-15 12:00\n"

    def test_a_seat_filed_elsewhere_with_a_run_here_is_listed(self):
        config.plan_path("growth").write_text(self.line("removed model loads", self.acme)
                                              + self.line("growth page", self.bramble))
        self.add_run("r1", "growth", self.acme, "config.py")
        self.assertEqual(orch.in_flight("fix-api", self.acme),
                         [("growth", [self.line("removed model loads", self.acme)[6:].strip()],
                           {"config.py"})])

    def test_a_run_on_another_checkout_changes_nothing_here(self):
        self.add_run("r1", "design", self.bramble, "landing.py")
        self.assertEqual(orch.in_flight("fix-api", self.acme), [])

    def test_open_pull_requests_in_no_run_are_listed(self):
        self.add_run("r1", "design", self.acme, "menu.py", review_pr=URL.format(7))
        self.prs = [{"number": 7, "title": "Reviewed now", "url": URL.format(7),
                     "files": [{"path": "menu.py"}]},
                    {"number": 9, "title": "Waiting between runs", "url": URL.format(9),
                     "files": [{"path": "docs/guide.md"}, {"path": "README.md"}]}]
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.main(["project", "acme"]), 0)
        self.assertEqual(out.getvalue().splitlines(), [
            "filed fix-api under acme",
            "in flight on acme, plan around it:",
            "  design",
            "    changing: menu.py",
            "  pull request #9, in no run: Waiting between runs",
            "    changing: README.md, docs/guide.md",
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
