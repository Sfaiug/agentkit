"""Every check a round runs leaves one row in history.db's `checks` table, written where it ran.

A row names the run and round, the check's kind (`done-when`, `rules`, `base-proof`, `replay`),
the command ak ran (a list the suite helper ran as one shell, a suite's piece with its share),
the commit checked (the base's for a base proof, none for a scratch run's one workspace), the
host or helper it ran on, its exit (none where it never returned: the row is written as the
check starts), when it was asked for, started and finished, and whether the same command already
ran on that commit in the run.  The columns an older ak made for a suite's measures and nothing
wrote are dropped from `runs`.  Black-box: the program `AK_BIN` names runs from outside
through tests/fixtures/akbin.py, on a project from gitrig.py, with scripted harnesses from
fakeadapter.py, and the test reads the Home's history.db.
"""

import contextlib
import json
import signal
import socket
import sqlite3
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import Home
from fixtures.gitrig import Rig
import test_key_round_checks_on_helper as on_helper

CHECKS = ("test -f retry.txt", "true")
OLD = ("suite_cpu_seconds", "suite_wall_seconds", "suite_peak_mb", "suite_repo")
# a finding proven on the first round's commit, which the fixer fixes in the second
FIX = "test -f fixed.txt"
FINDING = {"final": "Found one.", "hand_in": [
    ["finding", "retry.txt:1", "fixed.txt is missing", "it matters", "--run", FIX], ["done"]]}
FIXER = {"write": {"fixed.txt": "fixed\n"}, "commit": "add fixed.txt",
         "final": "## Summary\nwrote fixed.txt", "hand_in": [["done"]]}
# The Home's notify sink marks every run a test suite's, which ak never records: these runs go
# without it, as the owner's, and with no webhook configured nothing is posted anywhere.
OWNERS = {"AK_NOTIFY_SINK": None}


class Rows:
    """A Home of the class's own, the runs it launches and the rows they leave."""

    @classmethod
    def start(cls, **rig):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)
        cls.rig = Rig(cls.home, "widgets", **rig)
        cls.base = cls.rig.head()
        cls.db = cls.home.path / ".agentkit" / "history.db"

    @classmethod
    def launch(cls, title, checks=CHECKS, env=None, repo=None):
        """Run a task whose done-when lists `checks` in the rig, or `repo` (`none`: a scratch
        run); its record, with its branch's commits."""
        task = taskfile.write(cls.home, repo or cls.rig.path, title, done_when=checks)
        done = cls.home.ak("run", str(task), "--no-merge", env={**OWNERS, **(env or {})},
                           timeout=300)
        assert done.code == 0, done.out + done.err
        run_dir, = (path for path in taskfile.runs(cls.home)
                    if path.name.endswith(taskfile.slug(title)))
        state = json.loads((run_dir / "run.json").read_text())
        branch = state.get("branch")
        commits = branch and cls.rig.git("rev-list", "--reverse", f"{cls.base}..{branch}").split()
        return {**state, "id": run_dir.name, "commits": commits}

    def rows(self, run, kind):
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(
                "SELECT * FROM checks WHERE run_id=? AND kind=? ORDER BY rowid", (run["id"], kind))]


class EveryCheckLeavesARow(Rows, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start()
        akconfig.write(cls.home, ["opus", "astra"])
        fakes = fakeadapter.install(cls.home, claude="work", codex="pass")
        cls.one = cls.launch("Add retry file")
        # an older history's columns, which the next run's first write drops
        with contextlib.closing(sqlite3.connect(cls.db)) as connection:
            for name in OLD:
                connection.execute(f"ALTER TABLE runs ADD COLUMN {name} REAL")
        fakes["claude"].behave("work", FIXER)
        fakes["codex"].behave(FINDING, "pass")
        cls.two = cls.launch("Add fixed file")

    def test_each_done_when_command_leaves_a_row_with_its_exit_tree_and_place(self):
        head, = self.one["commits"]
        self.assertEqual([(row["round"], row["command"], row["exit"], row["tree"], row["place"],
                           row["rerun"]) for row in self.rows(self.one, "done-when")],
                         [(1, command, 0, head, socket.gethostname(), 0) for command in CHECKS])

    def test_the_rules_leave_one_row_a_round(self):
        head, = self.one["commits"]
        self.assertEqual([(row["round"], row["exit"], row["tree"])
                          for row in self.rows(self.one, "rules")], [(1, 0, head)])

    def test_the_base_proof_replays_on_the_base_where_one_check_fails(self):
        rows = self.rows(self.one, "base-proof")
        self.assertEqual(self.one["base_proof"], "proven")
        self.assertEqual({row["tree"] for row in rows}, {self.base})
        # the gate runs a failed command again at once: a row of its own, a re-run
        self.assertEqual([(row["command"], row["exit"], row["rerun"]) for row in rows
                          if row["exit"] != 0],
                         [("test -f retry.txt", 1, 0), ("test -f retry.txt", 1, 1)])

    def test_a_row_is_asked_for_then_started_then_finished(self):
        for kind in ("done-when", "rules", "base-proof"):
            for row in self.rows(self.one, kind):
                with self.subTest(kind=kind, command=row["command"]):
                    self.assertLessEqual(row["requested_at"], row["started_at"])
                    self.assertLessEqual(row["started_at"], row["finished_at"])

    def test_a_round_s_rows_carry_its_number_and_commit(self):
        first, second = self.two["commits"]
        self.assertEqual([(row["round"], row["command"], row["tree"])
                          for row in self.rows(self.two, "done-when")],
                         [(1, command, first) for command in CHECKS]
                         + [(2, command, second) for command in CHECKS])
        self.assertEqual([(row["round"], row["tree"]) for row in self.rows(self.two, "rules")],
                         [(1, first), (2, second)])

    def test_a_finding_s_proof_replayed_leaves_its_rows(self):
        self.assertEqual([(row["round"], row["command"], row["tree"], row["exit"] == 0)
                          for row in self.rows(self.two, "replay")],
                         [(1, FIX, self.two["commits"][0], False), (1, FIX, self.base, False),
                          (2, FIX, self.two["commits"][1], True)])

    def test_the_suite_columns_are_gone_from_runs(self):
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        self.assertIn("rounds_used", columns)
        self.assertEqual(columns & set(OLD), set())


class AScratchRun(Rows, unittest.TestCase):
    """A scratch run has no commit: its one workspace is the tree each of its checks runs on."""
    once = "test -f .once || { touch .once; false; }"     # red, then green when run again at once

    @classmethod
    def setUpClass(cls):
        cls.start()
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        cls.scratch = cls.launch("Add retry file", (cls.once,), repo="none")

    def test_the_command_run_again_is_a_rerun(self):
        self.assertEqual([(row["command"], row["tree"], row["exit"], row["rerun"])
                          for row in self.rows(self.scratch, "done-when")],
                         [(self.once, None, 1, 0), (self.once, None, 0, 1)])


class ACheckThatNeverReturns(Rows, unittest.TestCase):
    """A run stopped while its check runs keeps the check's row, written as it started."""
    hangs = 'echo started >"$(git rev-parse --git-common-dir)/started"; sleep 300'

    @classmethod
    def setUpClass(cls):
        cls.start()
        akconfig.write(cls.home, ["opus", "astra"])
        fakeadapter.install(cls.home, claude="work", codex="pass")
        task = taskfile.write(cls.home, cls.rig.path, "Add retry file", done_when=(cls.hangs,))
        proc = cls.home.spawn("run", str(task), "--no-merge", env=OWNERS)
        deadline = time.monotonic() + 240
        while not (cls.rig.path / ".git" / "started").exists():
            assert proc.poll() is None and time.monotonic() < deadline, "the check never started"
            time.sleep(0.1)
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=60)
        cls.stopped = {"id": taskfile.only_run(cls.home).name}

    def test_its_row_has_no_exit(self):
        self.assertEqual([(row["command"], row["exit"])
                          for row in self.rows(self.stopped, "done-when")], [(self.hangs, None)])


class OnTheSuiteHelper(Rows, unittest.TestCase):
    """A round's list goes to the suite helper as one shell, and a suite's pieces each go there,
    red there, then run here."""
    listed = (on_helper.HERE_ONLY, "true")
    sharded = f': "$AK_SHARD"; {on_helper.HERE_ONLY}'

    @classmethod
    def setUpClass(cls):
        cls.start(files={"tools/helper/Containerfile": "FROM docker.io/library/alpine:3.20\n"})
        akconfig.write(cls.home, ["opus", "astra"], settings={"suite_helper": "acme-mac"})
        helper = cls.home.root / "helper"
        helper.mkdir()
        (helper / "probe").write_text(on_helper.ROOM)
        cls.home.fake("ssh", on_helper.SSH.format(python=sys.executable, helper=str(helper)))
        fakeadapter.install(cls.home, claude="work", codex="pass")
        readings = {"AK_HOST_READINGS": on_helper.READINGS}
        cls.red = cls.launch("Add retry file", cls.listed, readings)
        cls.pieces = cls.launch("Add pieces", (cls.sharded,), readings)

    def test_the_list_is_one_row_there_and_each_command_a_rerun_here(self):
        head, = self.red["commits"]
        here = socket.gethostname()
        self.assertEqual([(row["command"], row["place"], row["exit"], row["tree"], row["rerun"])
                          for row in self.rows(self.red, "done-when")],
                         [("\n".join(self.listed), "acme-mac", 1, head, 0),
                          *((command, here, 0, head, 1) for command in self.listed)])

    def test_each_piece_is_a_row_where_it_ran_and_its_go_here_a_rerun(self):
        head, = self.pieces["commits"]
        shares = [f"AK_SHARD={share} {self.sharded}" for share in ("1/2", "2/2")]
        # the pieces run at once there: their rows start in either order
        self.assertEqual(sorted((row["rerun"], row["command"], row["place"], row["exit"],
                                 row["tree"]) for row in self.rows(self.pieces, "done-when")),
                         [*((0, piece, "acme-mac", 1, head) for piece in shares),
                          *((1, piece, socket.gethostname(), 0, head) for piece in shares)])


if __name__ == "__main__":
    unittest.main()
