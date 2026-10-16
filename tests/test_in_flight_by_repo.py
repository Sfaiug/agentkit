"""`ak orch project` shows what is in flight on the checkout, whatever each seat is filed under.

A seat filed under another project that has a going run on this checkout is listed with what
that run changes and its plan lines written on this checkout, never its other lines; a run of a
seat filed here that works on another checkout changes nothing here; a going run launched from
no seat is listed by its id.
Offline: invented checkouts, seat records, plans and runs under a temporary HOME.
"""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import Sandbox
from agentkit import config, orch, plan
from agentkit import record as run_record

TASK = "---\nfiles: {}\n---\n# t\n"


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
        # a line names its checkout by path and root commit; these checkouts have no commits
        self.stack.enter_context(patch.object(plan, "place", side_effect=lambda seat, project: (
            Path(project.replace("~", str(Path.home()))) if "/" in project else None)))

    def add_run(self, name, seat, repo, files):
        directory = config.RUNS / name
        directory.mkdir(parents=True)
        (directory / "task.md").write_text(TASK.format(files))
        run_record.save_state(directory, {"run_id": name, "launched_session": seat,
                                          "repo": str(repo), "state": "queued"})

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

    def test_a_run_launched_from_no_seat_is_listed_by_its_id(self):
        self.add_run("r1", None, self.acme, "app.py")
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.main(["project", "acme"]), 0)
        self.assertEqual(out.getvalue().splitlines(), [
            "filed fix-api under acme",
            "in flight on acme, plan around it:",
            "  run r1",
            "    changing: app.py",
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
