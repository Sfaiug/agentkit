"""`ak orch project` shows what is in flight on the checkout, whatever each seat is filed under.

A seat filed under another project that has a going run on this checkout is listed with
what that run changes and its plan lines naming this checkout, never its other lines; a run of a
seat filed here that works on another checkout changes nothing here; a going run launched from
no seat is listed by its id; and the checkout's open pull requests that no going run reviews or
delivers are listed with their files, every page of both, and how many GitHub does not list.
Offline: invented checkouts, seat records, plans and runs under a temporary HOME, gh faked.
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
from agentkit import config, orch, plan, watch
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
        self.stack.enter_context(patch.object(watch, "gh_json", side_effect=self.github))
        # a line names its checkout by path and root commit; these checkouts have no commits
        self.stack.enter_context(patch.object(plan, "place", side_effect=lambda seat, project: (
            Path(project.replace("~", str(Path.home()))) if "/" in project else None)))

    def github(self, cwd, *args, **_kw):
        """gh api --paginate's pages: the open pull requests 100 at a time, each naming its first
        100 files, and a pull request's own files endpoint 100 at a time, 3,000 at most."""
        def pages(items):
            return [items[at:at + 100] for at in range(0, max(len(items), 1), 100)]
        if "graphql" in args:
            return [{"data": {"repository": {"pullRequests": {"nodes": [
                {**pr, "changedFiles": len(pr["files"]),
                 "files": {"nodes": [{"path": path} for path in pr["files"][:100]]}}
                for pr in page]}}}} for page in pages(self.prs)], ""
        number = int(args[-1].split("/pulls/")[1].split("/")[0])
        files = next(pr["files"] for pr in self.prs if pr["number"] == number)
        return [[{"filename": path} for path in page] for page in pages(files[:3000])], ""

    def pr(self, number, title, *files):
        return {"number": number, "title": title, "url": URL.format(number), "files": list(files)}

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
        self.prs = [self.pr(7, "Reviewed now", "menu.py"),
                    self.pr(9, "Waiting between runs", "docs/guide.md", "README.md")]
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

    def test_a_run_launched_from_no_seat_is_listed_with_its_pull_request(self):
        self.add_run("r1", None, self.acme, "app.py", review_pr=URL.format(7))
        self.prs = [self.pr(7, "Standalone review", "app.py")]
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.main(["project", "acme"]), 0)
        self.assertEqual(out.getvalue().splitlines(), [
            "filed fix-api under acme",
            "in flight on acme, plan around it:",
            "  run r1",
            "    changing: app.py",
        ])

    def test_every_open_pull_request_and_every_file_is_read(self):
        files = [f"f{n:03}.py" for n in range(101)]
        self.prs = [self.pr(1, "Wide", *files),
                    *(self.pr(n, f"pr {n}", "a.py") for n in range(2, 102))]
        found = orch.open_prs(self.acme)
        self.assertEqual([number for number, *_ in found], list(range(1, 102)))
        self.assertEqual(found[0][2:], (files, 0))

    def test_files_github_does_not_list_are_counted(self):
        files = [f"f{n:04}.py" for n in range(3001)]
        self.prs = [self.pr(1, "Large move", *files)]
        self.assertEqual(orch.open_prs(self.acme), [(1, "Large move", files[:3000], 1)])
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.main(["project", "acme"]), 0)
        self.assertTrue(" ".join(line.strip() for line in out.getvalue().splitlines()).endswith(
            "f2999.py, 1 more GitHub does not list"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
