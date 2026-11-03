"""`ak run gc --dry-run` names each leftover outside runs and jobs it would take, and why.

Past its age, nobody holding it and its seat gone, the collector plans to take each family: an
ephemeral file in ~/.agentkit/tmp, a checkout no run owns, a passed one never merged, a gone
seat's file, a harness's entries naming a gone checkout, a /tmp entry, one in a repository's
TMPDIR, an entry of ak's home and an ended conversation.  Younger, held open or its seat alive,
each stays off the plan, and a dry run changes nothing.  Black-box: the program `AK_BIN` names
runs from outside through tests/fixtures/akbin.py, and this test fails against `/bin/false`.
Each dry run is boxed with a /tmp, a /var/tmp and processes of its own, which are all it judges.
"""

import json
import os
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, boxable, Home

DAY = 86400
# Each held path is opened by a process of the box before the program starts; the shell is
# the box's first process, so the box and its holders end with it.
HOLD = ('for path do exec 3<"$path"; sleep 600 & done; exec 3<&-; '
        '"$0" run gc --dry-run')


def plant(path, days, data=None):
    """A file holding `data`, or a folder when there is none, last changed `days` back."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if data is None:
        path.mkdir()
    else:
        path.write_text(data if isinstance(data, str) else json.dumps(data))
    stamp = time.time() - days * DAY
    os.utime(path, (stamp, stamp))
    return path


class Leftovers:
    """One of each family planted in a Home, past all that keeps it off the plan or, `kept`,
    short of it: kepter than its age, held open, or its seat alive."""

    def __init__(self, home, kept=False):
        self.home, ak = home, home.path / ".agentkit"
        # the box's /tmp and /var/tmp, bound whole: a path bwrap is handed is one it holds
        self.tmp, self.var = plant(home.root / "box-tmp", 0), plant(home.root / "box-var", 0)
        now = time.time()
        view = plant(ak / "tmp" / "view.html", 2, "<html></html>")
        plant(ak / "tmp" / "view.html.agentkit-ephemeral.json", 0, {
            "version": 1, "kind": "viewer", "path": str(view), "pid": None,
            "created_at": now - 2 * DAY, "finished_at": now - 2 * DAY})
        orphan = plant(ak / "wt" / ("new-fix" if kept else "old-fix"), 0 if kept else 2)
        passed = plant(ak / "wt" / "passed-fix", 0)
        plant(ak / "runs" / "passed-fix" / "run.json", 0, {
            "run_id": "passed-fix", "worktree": str(passed), "state": "pass", "merged": False,
            "no_merge": True, "finished_at": now - (6.5 if kept else 8.5) * DAY})
        seat = plant(ak / "state" / "notify-acme-seat.json", 2, {})
        if kept:
            plant(ak / "state" / "session-acme-seat.json", 0, {})
        # kept, the entry names a checkout still there
        trusted = orphan if kept else ak / "wt" / "gone-fix"
        claude = plant(home.path / ".claude.json", 0, {"projects": {str(trusted): {}}})
        plant(self.tmp / "acme-notes", 3.5)
        plant(self.var / "acme" / "build", 0.5 if kept else 3.5)
        plant(ak / "env" / "acme.env", 0, "TMPDIR=/var/tmp/acme\n")
        old = plant(ak / "old-notes", 8.5)
        talk = plant(home.path / ".gemini" / "antigravity-cli" / "conversations" / "talk.db",
                     29.5 if kept else 31.5, "")
        self.expected = [
            f"gc: would remove viewer {view}",
            f"gc: would remove orphan-worktree {orphan}: no run record",
            f"gc: would remove unmerged-worktree {passed}: passed, never merged, ended 8 days ago",
            f"gc: would remove seat-file {seat}: seat acme-seat is gone",
            f"gc: would prune harness-entries {claude}: 1 trust entries and 0 MCP servers name a "
            "gone smoke sandbox or checkout",
            "gc: would remove tmp-entry /tmp/acme-notes: untouched for 3 days",
            "gc: would remove tmp-entry /var/tmp/acme/build: untouched for 3 days",
            f"gc: would remove home-entry {old}: untouched for 8 days",
            f"gc: would remove conversation {talk}: untouched for 31 days",
        ]
        # kept, these are as old as when taken, and held open
        self.held = [str(view), "/tmp/acme-notes", str(old)] if kept else []

    def dry_run(self):
        box = ("bwrap", "--dev-bind", "/", "/", "--bind", str(self.tmp), "/tmp",
               "--bind", str(self.var), "/var/tmp", "--unshare-pid", "--as-pid-1",
               "--proc", "/proc")
        return self.home.run(*self.home.box(box), "sh", "-c", HOLD, AK, *self.held)

    def seen(self):
        """Every file and folder planted, its bytes and when it last changed."""
        return {str(path): (path.read_bytes() if path.is_file() else None,
                            path.lstat().st_mtime_ns)
                for root in (self.home.path, self.tmp / "acme-notes", self.var / "acme")
                for path in (root, *sorted(root.rglob("*")))}


@unittest.skipUnless(boxable(), "no bwrap able to box a dry run here")
class Taken(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.leftovers = Leftovers(cls.home)
        cls.done = cls.leftovers.dry_run()

    def test_it_names_each_family_in_order_and_why(self):
        self.assertEqual(self.done.code, 0, self.done.err)
        self.assertEqual(self.done.out.splitlines(), self.leftovers.expected)


@unittest.skipUnless(boxable(), "no bwrap able to box a dry run here")
class Kept(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.done = Leftovers(cls.home, kept=True).dry_run()

    def test_kepter_held_open_or_its_seat_alive_each_stays_off_the_plan(self):
        self.assertEqual(self.done.code, 0, self.done.err)
        self.assertEqual(self.done.out.splitlines(), ["gc: no eligible artifacts"])


@unittest.skipUnless(boxable(), "no bwrap able to box a dry run here")
class Still(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.leftovers = Leftovers(cls.home)
        cls.before = cls.leftovers.seen()
        cls.done = cls.leftovers.dry_run()

    def test_a_dry_run_changes_nothing_it_saw(self):
        self.assertEqual(self.done.code, 0, self.done.err)
        self.assertEqual(self.leftovers.seen(), self.before)


if __name__ == "__main__":
    unittest.main()
