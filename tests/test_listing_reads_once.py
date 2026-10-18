"""Listing the seats asks git about a checkout once, and reads the config once.

The owner's report (18 Oct 2026): new sessions and the past screen were slow.  Every listing
asked git again about each worktree under ~/code, once per seat filed under a project, and read
the config once per seat record: a third of a second a listing on the host, paid by the menu
before its name question and on every read.  Git's answer is now kept while what it was read
from stands as it did, and a listing reads the config once.  Offline: a temporary HOME, git in
a temporary directory, no tmux.
"""

from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, orch, watch  # noqa: E402

GIT = ["git", "-c", "user.name=acme", "-c", "user.email=acme@example.com"]


class Asked(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(orch._ASKED, clear=True))
        self.asked = self.stack.enter_context(patch.object(orch, "git_in", wraps=orch.git_in))

    def repo(self, name):
        directory = self.root / name
        subprocess.run([*GIT, "init", "-q", "-b", "main", str(directory)], check=True)
        subprocess.run([*GIT, "-C", str(directory), "commit", "-q", "--allow-empty", "-m", "a"],
                       check=True)
        return directory

    def worktree(self, repo, name):
        directory = self.root / name
        subprocess.run([*GIT, "-C", str(repo), "worktree", "add", "-q", "-b", name,
                        str(directory)], check=True)
        return directory

    def test_a_worktree_is_asked_about_once_while_nothing_it_was_read_from_changes(self):
        acme = self.repo("acme")
        added = self.worktree(acme, "fix-api")
        answer = (acme.resolve() / ".git", True)
        self.assertEqual(orch.git_dirs(added), answer)
        self.assertEqual(orch.git_dirs(added), answer)
        self.assertEqual(self.asked.call_count, 1)

    def test_a_worktree_led_elsewhere_or_gone_is_asked_about_again(self):
        acme, docs = self.repo("acme"), self.repo("docs")
        added, other = self.worktree(acme, "fix-api"), self.worktree(docs, "fix-docs")
        self.assertEqual(orch.git_dirs(added), (acme.resolve() / ".git", True))
        (added / ".git").write_text((other / ".git").read_text())
        self.assertEqual(orch.git_dirs(added), (docs.resolve() / ".git", True))
        shutil.rmtree(docs / ".git" / "worktrees" / "fix-docs")
        self.assertIsNone(orch.git_dirs(added))
        self.assertEqual(self.asked.call_count, 3)


class Listing(Sandbox):
    def test_a_listing_reads_the_config_once_however_many_seats(self):
        for name in ("acme-api", "acme-web", "docs-site"):
            config.save_session(self.cfg, name, "fable", ["opus"], {"cwd": str(self.root)})
        # two that tmux holds, and one the owner stopped that only its record holds
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[
            {"name": name, "path": str(self.root), "created": 9000, "attached": False,
             "exited": False, "legacy": False} for name in ("acme-api", "acme-web")]))
        self.stack.enter_context(patch.object(watch, "seat_stopped_at",
                                              lambda name: 9500 if name == "docs-site" else None))
        loads = self.stack.enter_context(patch.object(config, "load", wraps=config.load))
        self.assertEqual([seat["name"] for seat in orch.listing()],
                         ["acme-api", "acme-web", "docs-site"])
        self.assertEqual(loads.call_count, 1)


if __name__ == "__main__":
    unittest.main()
