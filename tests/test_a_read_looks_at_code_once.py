"""A read of the seats looks at ~/code once, and a listing reads the config once, however many
seats it files.

The owner's report (18 Oct 2026): ak took over two seconds to its first frame.  Filing each seat
under its project looked at ~/code again, a seat at a time, and each look asks git about every
worktree there: on the host, a dozen seats cost a dozen asks of 50 ms each, and a listing read
the config once for each seat record.  The look is now one per read, handed to each filing, so
nothing is kept from one read to the next.  Offline: a temporary HOME, git in it, no tmux.
"""

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import Sandbox  # noqa: E402
from agentkit import config, menu, orch, watch  # noqa: E402

GIT = ["git", "-c", "user.name=acme", "-c", "user.email=acme@example.com"]
SEATS = ["acme-api", "acme-docs", "acme-web", "acme-ops"]


class LooksOnce(Sandbox):
    def setUp(self):
        super().setUp()
        self.acme = config.CODE / "acme"
        subprocess.run([*GIT, "init", "-q", "-b", "main", str(self.acme)], check=True)
        subprocess.run([*GIT, "-C", str(self.acme), "commit", "-q", "--allow-empty", "-m", "a"],
                       check=True)
        # a worktree under ~/code: every look at ~/code asks git about it
        subprocess.run([*GIT, "-C", str(self.acme), "worktree", "add", "-q", "-b", "fix-api",
                        str(config.CODE / "fix-api")], check=True)
        for name in SEATS:
            config.save_session(self.cfg, name, "fable", ["opus"],
                                {"repo": str(self.acme), "cwd": str(self.acme)})
        self.asked = self.stack.enter_context(patch.object(orch, "git_in", wraps=orch.git_in))

    def test_a_main_screen_read_looks_at_code_once_however_many_seats(self):
        groups, *_ = menu.v5o_groups(self.cfg, [{"name": name, "repo": str(self.acme)}
                                                for name in SEATS], [], look=False)
        self.assertEqual([(project["name"], [info["name"] for info in project["seats"]])
                          for project in groups], [("acme", SEATS)])
        self.assertEqual(self.asked.call_count, 1)

    def test_a_listing_looks_at_code_once_and_reads_the_config_once(self):
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[
            {"name": name, "path": str(self.acme), "created": 9000, "attached": False,
             "exited": False, "legacy": False, "repo": str(self.acme)} for name in SEATS[:3]]))
        # and one the owner stopped, that only its record holds
        self.stack.enter_context(patch.object(watch, "seat_stopped_at",
                                              lambda name: 9500 if name == "acme-ops" else None))
        loads = self.stack.enter_context(patch.object(config, "load", wraps=config.load))
        self.assertEqual([seat["name"] for seat in orch.listing(reconcile=False)], SEATS)
        self.assertEqual((loads.call_count, self.asked.call_count), (1, 1))


if __name__ == "__main__":
    unittest.main()
