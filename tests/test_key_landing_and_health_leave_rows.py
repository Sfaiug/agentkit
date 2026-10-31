"""The lander's checks and the tick's live probe leave rows in history.db's `checks` table, as
a round's checks do, under the run they are about.

The lander's check of a member's tree leaves a `landing` row for each command and each piece of
the suite, its round none and its tree the commit checked; its probe of the target's tip, for a
member red on its piece, a `tip` row on the tip under that member; each probe of a merged run's
`health:` a `health` row on the merge commit with the probe's exit, none where it timed out.
Black-box: the program `AK_BIN` names checks a landing line from outside through
tests/fixtures/akline.py and runs the tick's health pass as tests/test_key_health_pass.py does,
in a Home whose history.db holds each run's row (a run with none keeps no checks), the rows read
back from there.
"""

import contextlib
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akline import SUITE, Line
from test_key_history_db import ORIGINAL
import test_key_health_pass as health

ONCE = "test -f api.txt"


def started(home, run):
    """The row `run`'s start left in the Home's history.db."""
    with contextlib.closing(sqlite3.connect(home.path / ".agentkit" / "history.db")) as db:
        db.execute("CREATE TABLE runs (%s)" % ", ".join(map(" ".join, ORIGINAL)))
        db.execute("INSERT INTO runs (run_id) VALUES (?)", (run,))
        db.commit()


def rows(home, run, kind):
    """`run`'s rows of `kind`, oldest first: (command, round, tree, exit)."""
    with contextlib.closing(sqlite3.connect(home.path / ".agentkit" / "history.db")) as db:
        return db.execute("SELECT command, round, tree, exit FROM checks WHERE run_id=? AND "
                          "kind=? ORDER BY rowid", (run, kind)).fetchall()


class Landed(unittest.TestCase):
    def land(self, tests, files, once=None):
        """The line with one member adding `files`, checked once, its task's `# once` command
        `once`, if any."""
        line = Line(tests)
        self.addCleanup(line.close)
        started(line.home, "fix-1")
        line.member(files)
        if once:
            (line.members[0] / "task.md").write_text(
                f"# fix-1\n\n## Done when\n```bash\n{once}  # once\n```\n")
        done = line.land()
        self.assertEqual(done.code, 0, done.out + done.err)
        return line

    def test_a_member_landing_leaves_a_landing_row_per_command_on_the_commit_checked(self):
        line = self.land({"t/ok.sh": "true\n"}, {"api.txt": "x\n"}, ONCE)
        found = rows(line.home, "fix-1", "landing")
        commands = [command for command, *_ in found]
        pieces = [command for command in commands if command != ONCE]
        self.assertEqual(sorted(pieces), [f"AK_SHARD={k}/{len(pieces)} {SUITE}"
                                          for k in range(1, len(pieces) + 1)], found)
        self.assertEqual(commands.count(ONCE), 1, found)
        commit = found[0][2]
        self.assertEqual({(round, tree, code) for _, round, tree, code in found},
                         {(None, commit, 0)})
        # the member's change on the tip, the tree it lands
        self.assertEqual(line.rig.git("rev-parse", f"{commit}^"), line.base)
        self.assertEqual(line.rig.git("rev-parse", f"{commit}^{{tree}}"), line.verdict(1)["land"])

    def test_a_member_red_on_its_piece_leaves_a_tip_row_on_the_tip(self):
        line = self.land({"t/ok.sh": "true\n", "t/bad.sh": "test ! -f bad.txt\n"},
                         {"bad.txt": "x\n"})
        self.assertIn("fix", line.verdict(1))
        self.assertEqual(rows(line.home, "fix-1", "tip"), [(SUITE, None, line.base, 0)])


class Probed(health.Merged):
    live = False

    @classmethod
    def stage(cls):
        started(cls.home, health.RUN)

    def probes(self):
        return rows(self.home, health.RUN, "health")


class FailsThenPasses(Probed):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.home.write("live-ok", "")
        cls.tick()

    def test_each_probe_leaves_a_health_row_with_its_exit_on_the_merge_commit(self):
        self.assertIsInstance(self.run_record().get("live_at"), (int, float))
        self.assertEqual(self.probes(), [(health.HEALTH, None, self.sha, 1),
                                         (health.HEALTH, None, self.sha, 0)])


class TimesOut(Probed):
    record = {"health": {"command": "sleep 60"}}

    def test_a_probe_that_times_out_leaves_a_row_with_no_exit(self):
        self.assertEqual(self.probes(), [("sleep 60", None, self.sha, None)])


if __name__ == "__main__":
    unittest.main()
