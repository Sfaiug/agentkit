"""Each file handed to a conflict fixer leaves its git classification and final outcome.

Black-box: AK_BIN runs against Home, Rig, GitHub and fakeadapter. Both branches append
notes.md and change app.py; the target moves while the executor holds its first turn.
"""

import json
import shlex
import sqlite3
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.fakegh import GitHub
from fixtures.gitrig import Rig


class ConflictRows(unittest.TestCase):
    how = "rebase"
    outcome = "resolved"
    notes = "notes.md"
    split = False

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.rig = rig = Rig(home, "widgets", files={
            "AGENTS.md": "---\ncontent: notes.md\n---\n# widgets\n",
            cls.notes: "shared notes\n", "app.py": "value = 1\n",
            ".gitattributes": "notes.md merge\n"})
        gh = GitHub(home)
        gh.grant(rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        ready, release = (home.root / "adapters" / name for name in ("ready", "release"))
        work = {**fakeadapter.PASS, "write": {
            cls.notes: "shared notes\nbranch note\n", "app.py": "value = 2\n"},
            "commit": "update notes and app",
            "sh": f"touch {shlex.quote(str(ready))}; "
                  f"while test ! -f {shlex.quote(str(release))}; do sleep 0.1; done"
                  + ("; git add app.py && git commit -qm 'update app'" if cls.split else "")}
        finish = ("git -c core.editor=true rebase --continue" if cls.how == "rebase"
                  else "git commit -qm 'resolve conflicts'")
        contents = {cls.notes: "shared notes\nbranch note\ntarget note\n", "app.py": "value = 3\n"}
        resolve = ("import subprocess; from pathlib import Path\n"
                   "paths = subprocess.check_output(['git', 'diff', '--name-only', "
                   "'--diff-filter=U', '-z']).decode().split('\\0')\n"
                   f"for path in filter(None, paths): Path(path).write_text({contents!r}[path])\n")
        fix = {**fakeadapter.PASS,
               "sh": f"python3 -c {shlex.quote(resolve)} && git add -A && {finish}"}
        cls.fakes = fakeadapter.install(home, claude=[
            work, fix if cls.outcome == "resolved" else "pass"], codex="pass")
        task = taskfile.write(home, rig.path, "Combine notes and app", done_when=(
            f"test -f {shlex.quote(cls.notes)} && test -f app.py",),
            front={"merge": "merge" if cls.how == "merge" else "squash"})
        cls.before = time.time()
        proc = home.spawn("run", str(task), env={"AK_NOTIFY_SINK": None})
        deadline = time.monotonic() + 120
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert ready.exists(), home.log("spawn-1.err").read_text()
        cls.tip = rig.commit({cls.notes: "shared notes\ntarget note\n",
                              "app.py": "value = 4\n"}, "target moves")
        release.touch()
        cls.code = proc.wait(timeout=300)
        cls.after = time.time()
        cls.run_dir = taskfile.only_run(home)
        cls.state = json.loads((cls.run_dir / "run.json").read_text())

    def rows(self):
        db = sqlite3.connect(self.home.path / ".agentkit/history.db")
        db.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in db.execute(
                "SELECT * FROM conflicts WHERE run_id=? ORDER BY path", (self.run_dir.name,))]
        finally:
            db.close()

    def test_each_file_keeps_the_pinned_target_and_its_own_classification(self):
        rows = self.rows()
        self.assertEqual(len(rows), 2, rows)
        self.assertEqual({row["path"] for row in rows}, {"app.py", self.notes})
        for row in rows:
            path, added = row["path"], int(row["path"] == self.notes)
            with self.subTest(path=path):
                self.assertEqual({key: row[key] for key in (
                    "run_id", "how", "target", "tip", "path", "added_only", "outcome")}, {
                    "run_id": self.run_dir.name, "how": self.how, "target": "origin/main",
                    "tip": self.tip, "path": path, "added_only": added, "outcome": self.outcome})
                self.assertLessEqual(self.before, row["at"])
                self.assertLessEqual(row["at"], self.after)
        if not self.split:
            self.assertEqual(rows[0]["at"], rows[1]["at"])

    def test_the_fixer_still_resolves_or_parks_the_same_work(self):
        diagnostic = self.home.log("spawn-1.out").read_text() + self.home.log("spawn-1.err").read_text()
        diagnostic += (self.run_dir / "round-1/donewhen.log").read_text()
        self.assertEqual(self.code, 0 if self.outcome == "resolved" else 1, diagnostic)
        if self.outcome == "resolved":
            self.assertEqual((self.state["state"], self.state["merged"]), ("pass", True))
            self.assertEqual(self.rig.origin("show", f"main:{self.notes}"),
                             "shared notes\nbranch note\ntarget note")
        else:
            self.assertEqual(self.state["state"], "waiting")
            self.assertEqual(self.rig.head(), self.tip)
        self.assertEqual([call["role"] for call in self.fakes["claude"].runs()],
                         ["executor"] + ["fixer"] * (
                             (2 if self.split else 1) if self.outcome == "resolved" else 3))


class MergeConflictRows(ConflictRows):
    how = "merge"


class AbortedConflictRows(ConflictRows):
    outcome = "aborted"


class QuotedConflictRows(ConflictRows):
    notes = ' notes-é\t".txt '


class LaterRebaseConflictRows(ConflictRows):
    split = True


if __name__ == "__main__":
    unittest.main()
