"""A red target's first red first-parent commit gets the after-merge blame, not its tip.

Black-box through AK_BIN and akline: changes merged by acme-a, acme-b and acme-c pass
until a marker appears. Named failures repeat on the tip, starting its repair at once.
History keeps the culprit and each probe; old reds, flakes and a red that named no test blame
nobody.
"""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.akline import Line, RUNNER, rules
from test_key_history_db import ORIGINAL

RED = 'test ! -f "$(git rev-parse --git-common-dir)/red"\n'
FLAKY = ('[ -f c.txt ] && exit 1\n'
         'mark="$(git rev-parse --git-common-dir)/once-$(git rev-parse HEAD)"\n'
         '[ -f "$mark" ] || { touch "$mark"; exit 1; }\n')
UNSHARDED = ('[ -f "$(git rev-parse --git-common-dir)/red" ] || exit 0\n'
             '[ -n "$AK_SHARD" ] && [ ! -f c.txt ] && exit 0\nexit 1\n')


class RedMainBlamedOnFirstRedCommit(unittest.TestCase):
    def line(self, *, old=False, flaky=False, outside=False, blame="", dated=False, padding=0,
             unsharded=False, partial=False):
        home = Home()
        self.addCleanup(home.close)
        if dated:
            home.env["GIT_COMMITTER_DATE"] = "2000-01-01T00:00:00Z"
        files = ({"AGENTS.md": rules("sh suite.sh"), "suite.sh": UNSHARDED} if unsharded else
                 {"suite.sh": RUNNER.replace('[ $((i % n + 1)) = "$k" ]', '[ "$k" = "1" ]')}
                 if partial else {})
        line = Line({"t/ok.sh": "true\n", **({"t/bad.sh": RED} if old else {}), **files}, home=home)
        initial = line.base
        a = line.rig.commit({"a.txt": "a\n"}, "acme-a")
        home.env.pop("GIT_COMMITTER_DATE", None)
        script = ('test ! -f "$(git rev-parse --git-common-dir)/red" && exit 0\n' + FLAKY
                  if flaky or partial else RED)
        branch = line.rig.branch("ak/acme-b", {"t/bad.sh": script})
        line.rig.git("merge", "--no-ff", branch, "-m", "acme-b")
        line.rig.git("push", "origin", "main")
        b = line.rig.head()
        c = line.rig.commit({"c.txt": "c\n", **({"t/new.sh": RED} if partial else {})}, "acme-c")
        for n in range(padding):
            c = line.rig.commit({}, f"later merge {n}")
        line.base = c
        line.member({"work.txt": "work\n"})
        line.home.write(".agentkit/state/session-seat.json",
                        {"orchestrator": "opus", "workers": ["opus"]})
        path = line.members[0] / "run.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), "launched_session": "seat"}))
        with closing(sqlite3.connect(line.home.path / ".agentkit/history.db")) as db, db:
            db.execute("CREATE TABLE runs (%s, merge_sha TEXT, broke_after_merge TEXT)" %
                       ", ".join(map(" ".join, ORIGINAL)))
            for name, sha in (("acme-a", a), ("acme-b", b), ("acme-c", c), ("fix-1", None)):
                if outside and name == "acme-b":
                    continue
                db.execute("INSERT INTO runs (run_id, repo, final_state, merge_sha, "
                           "broke_after_merge) VALUES (?, 'acme', 'pass', ?, ?)",
                           (name, sha, blame if name == "acme-b" else ""))
        (line.rig.path / ".git/red").touch()
        self.output = ""
        for _ in range(7):
            done = line.land()
            self.assertEqual(done.code, 0, done.out + done.err)
            self.output += done.out + done.err
            repairs = list(line.members[0].parent.glob("*make-main-pass-*/task.md"))
            if repairs:
                break
            path = (line.members[0].parent / line.line).with_suffix(".green")
            data = json.loads(path.read_text())
            for red in data.get("red", {}).values():
                red["at"] = 0
            path.write_text(json.dumps(data))
        self.assertNotIn("fix", line.verdict(1))
        self.assertEqual(len(repairs), 1, done.out + done.err)
        return line, (initial, a, b, c)

    def blame(self, line):
        with closing(sqlite3.connect(line.home.path / ".agentkit/history.db")) as db:
            return dict(db.execute("SELECT run_id, broke_after_merge FROM runs "
                                   "WHERE broke_after_merge != ''"))

    def probes(self, line, sha):
        with closing(sqlite3.connect(line.home.path / ".agentkit/history.db")) as db:
            return [row[0] for row in db.execute(
                "SELECT exit FROM checks WHERE kind='tip' AND tree=? ORDER BY rowid", (sha,))]

    def test_the_first_red_merge_gets_the_blame_once(self):
        line, (_, _, b, _) = self.line()
        self.assertEqual(self.blame(line), {"acme-b": "tip"})
        self.assertEqual(self.probes(line, b), [1, 1])
        self.assertEqual(self.probes(line, line.rig.head("ak/acme-b")), [])
        before = (line.members[0] / "run.json").read_bytes()
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(self.blame(line), {"acme-b": "tip"})
        self.assertEqual(self.probes(line, b), [1, 1])
        self.assertEqual((line.members[0] / "run.json").read_bytes(), before)

    def test_red_before_the_range_blames_nobody(self):
        line, (oldest, _, _, _) = self.line(old=True)
        self.assertEqual(self.blame(line), {})
        self.assertEqual(self.probes(line, oldest), [1, 1])
        self.assertIn(f"red before {oldest[:12]}", self.output)

    def test_a_flaky_commit_ends_the_walk_without_blame(self):
        line, (_, _, b, _) = self.line(flaky=True)
        self.assertEqual(self.blame(line), {})
        self.assertEqual(self.probes(line, b), [1, 0])

    def test_a_red_that_named_no_test_blames_nobody(self):
        line, commits = self.line(unsharded=True)
        self.assertEqual(self.blame(line), {})
        # its repair starts, and no earlier commit is checked: only named tests walk
        self.assertEqual([self.probes(line, sha) for sha in commits[:-1]], [[], [], []])

    def test_missing_tests_do_not_hide_a_flake(self):
        line, (_, _, b, _) = self.line(partial=True)
        self.assertEqual(self.blame(line), {})
        self.assertEqual(self.probes(line, b), [1, 1])
        self.assertIn(f"{b[:12]} is flaky", self.output)

    def test_a_merge_outside_ak_leaves_no_blame_row(self):
        line, (_, _, b, _) = self.line(outside=True)
        self.assertEqual(self.blame(line), {})
        self.assertIn(f"{b[:12]} merged outside ak", self.output)

    def test_an_existing_after_merge_measure_is_kept(self):
        line, _ = self.line(blame="health")
        self.assertEqual(self.blame(line), {"acme-b": "health"})

    def test_the_walk_stays_within_the_green_records_day(self):
        line, (_, a, b, _) = self.line(dated=True)
        self.assertEqual(self.blame(line), {})
        self.assertEqual(self.probes(line, a), [])
        self.assertIn(f"red before {b[:12]}", self.output)

    def test_the_walk_stops_at_64_commits_in_six_steps(self):
        line, (_, a, b, _) = self.line(padding=62)
        self.assertEqual(self.blame(line), {})
        self.assertEqual(self.probes(line, a), [])
        self.assertIn(f"red before {b[:12]}", self.output)
        with closing(sqlite3.connect(line.home.path / ".agentkit/history.db")) as db:
            count = db.execute("SELECT COUNT(DISTINCT tree) FROM checks WHERE kind='tip'").fetchone()[0]
        self.assertEqual(count, 7)  # the red tip and six bisect steps


if __name__ == "__main__":
    unittest.main()
