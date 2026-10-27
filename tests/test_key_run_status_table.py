"""`ak run status` opens with two host lines, then one table of runs that reads at any width.

The host lines say what the machine has and when ak admits a run.  ak reads them from
`AK_HOST_READINGS`, a JSON of the readings that stands in for /proc and the cgroups while
`AK_CGROUP_ROOT` is unset, so here the words are fixed and a Go build keeps that seam.  The
table is what a person reads to see which runs need them, so it is compared whole, spaces and
all, in a real terminal of each width; a model reads it through a pipe, at `COLUMNS` or 100.
From 100 columns up, each run is one row, a long title wrapped once under its column and cut
with `…` after that.  On a narrower terminal, each run's id and title sit over its state line,
which takes two lines where one is too short.  The order is fixed too: the run a loop holds first,
then runs still owed something, newest first whatever their word, then finished runs.  The
host counts each unfinished run's processes, so only that line's place and shape are pinned.

Black-box: the runs are records written by hand where ak keeps them, and the program `AK_BIN`
names runs from outside through tests/fixtures/akbin.py and akterm.py; this test fails against
`/bin/false`.
"""

import json
from pathlib import Path
import re
import subprocess
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home, owner
from fixtures.akterm import SERVER, Terminal

HOUR, DAY = 3600, 86400
READINGS = {"cpus": 8, "free_mb": 4096, "mem_total_mb": 16384, "slice_cpu_pressure": 12}
PROCESSES = re.compile(r"  \d+ process(es)? · \d+(\.\d+)? [KMG]B")
WORD = re.compile(r"[●!✓] (working|needs you|done)")
HIDDEN = "{} older run(s) hidden; ak run status --history [--json] shows full history"


def host(cpus, free, floor, heavy):
    return [f"host: {cpus} cpus · {free} G free · a run is admitted while ≥ {floor} G free",
            f"heavy suites: {heavy} at once (derived)"]


HOST = host(8, 4, 3.2, 9)

WIDE = """\
id                                 title                     state        worker      round      age
20260101-0900-ship-the-tally       Ship the tally so every   ● working    opus/astra  round 1/3  2h
                                   seat row says what the …
  <processes>
20260101-0830-fix-the-parser       Fix the parser            ! needs you  opus/astra  round 0/2  20m
20260101-0800-add-a-token          Add a token               ! needs you  opus/astra  round 0/2  25m
  ! blocked · no token
20260101-0700-write-release-notes  Write release notes       ✓ done       opus/astra  round 2/2  1h
"""

SIXTY = """\
id               title
20260101 0900 …  Ship the tally so every seat row says what
                 the run did
  ● working  opus/astra  round 1/3  2h
  <processes>
20260101 0830 …  Fix the parser
  ! needs you  opus/astra  round 0/2  20m
20260101 0800 …  Add a token
  ! needs you  opus/astra  round 0/2  25m
  ! blocked · no token
20260101 0700 …  Write release notes
  ✓ done  opus/astra  round 2/2  1h
"""

FORTY = """\
id               title
20260101 0900 …  Ship the tally so every
                 seat row says what …
  ● working  opus/astra  round 1/3  2h
  <processes>
20260101 0830 …  Fix the parser
  ! needs you  opus/astra
  round 0/2  20m
20260101 0800 …  Add a token
  ! needs you  opus/astra
  round 0/2  25m
  ! blocked · no token
20260101 0700 …  Write release notes
  ✓ done  opus/astra  round 2/2  1h
"""


def env(readings=READINGS):
    return {"AK_HOST_READINGS": json.dumps(readings)}


def placed(text):
    """Lines as printed, each process line read as its place alone."""
    return ["  <processes>" if PROCESSES.fullmatch(line) else line.rstrip()
            for line in text.rstrip("\n").splitlines()]


def record(home, run_id, **fields):
    home.write(f".agentkit/runs/{run_id}/run.json",
               {"run_id": run_id, "executor": "opus", "reviewer": "astra", **fields})


class HostLines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Home()
        cls.addClassCleanup(cls.home.close)

    def status(self, readings):
        done = self.home.ak("run", "status", env=env(readings))
        self.assertEqual(done.code, 0, done.err)
        return done.out.splitlines()

    def test_with_no_runs_it_says_where_it_looked_and_that_none_are_hidden(self):
        self.assertEqual(self.status(READINGS),
                         [*HOST, f"no current runs in {self.home.path}/.agentkit/runs",
                          HIDDEN.format(0)])

    def test_the_host_lines_follow_the_readings(self):
        no_total = {key: value for key, value in READINGS.items() if key != "mem_total_mb"}
        small = {"cpus": 2, "free_mb": 8192, "mem_total_mb": 65536, "slice_cpu_pressure": 55}
        # a run needs a fifth of the memory free, and never under 3 G; a heavy suite takes
        # 0.7 of a core and 410 MB, and the fewer that fit is the count
        for readings, lines in ((no_total, host(8, 4, 3, 9)),
                                (small, host(2, 8, 12.8, 2))):
            with self.subTest(readings=readings):
                self.assertEqual(self.status(readings)[:2], lines)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Table(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        now = time.time()
        record(home, "20260101-0900-ship-the-tally", state="stalled", rounds=3,
               title="Ship the tally so every seat row says what the run did",
               round_summaries=[{}], started_at=now - 2.5 * HOUR)
        record(home, "20260101-0830-fix-the-parser", title="Fix the parser", state="fail",
               rounds=2, started_at=now - 3 * HOUR - 1200, finished_at=now - 3 * HOUR)
        record(home, "20260101-0800-add-a-token", title="Add a token", state="blocked",
               error="no token", rounds=2, started_at=now - 4 * HOUR - 1500,
               finished_at=now - 4 * HOUR)
        record(home, "20260101-0700-write-release-notes", title="Write release notes",
               state="pass", merged=True, rounds=2, round_summaries=[{}, {}],
               started_at=now - 2 * HOUR, finished_at=now - HOUR)
        # finished past the seven days the listing keeps
        record(home, "20251001-0700-retire-the-old-api", title="Retire the old API",
               state="pass", merged=True, rounds=2, round_summaries=[{}, {}],
               started_at=now - 30 * DAY - HOUR, finished_at=now - 30 * DAY)

    def shown(self, width):
        """What a terminal `width` columns wide shows once the listing has ended, with each line
        the terminal wrapped joined back as it was printed."""
        term = Terminal(self.home, "run", "status", size=(width, 40), env=env())
        self.assertEqual(term.exit_code(), 0, term.screen())
        term.wait("full history")
        return placed(self.home.tmux("capture-pane", "-p", "-J", "-t", term.pane,
                                     server=SERVER).out)

    def assertTable(self, width, table):
        self.assertEqual(self.shown(width), [*HOST, *table.splitlines(), HIDDEN.format(1)])

    def test_at_100_columns_each_run_is_one_row_with_its_word_worker_round_and_age(self):
        self.assertTable(100, WIDE)

    def test_a_wider_terminal_shows_the_same_100_column_table(self):
        self.assertEqual(self.shown(120), self.shown(100))

    def test_through_a_pipe_the_width_is_columns_or_else_100(self):
        for columns, width in ((None, 100), ("40", 40)):
            with self.subTest(columns=columns):
                done = self.home.ak("run", "status", env={**env(), "COLUMNS": columns})
                self.assertEqual(done.code, 0, done.err)
                self.assertEqual(placed(done.out), self.shown(width))

    def test_at_60_columns_each_run_stacks_its_id_and_title_over_its_state(self):
        self.assertTable(60, SIXTY)

    def test_at_40_columns_a_state_line_too_long_for_one_line_takes_two(self):
        self.assertTable(40, FORTY)


class Order(unittest.TestCase):
    def test_the_run_its_loop_holds_comes_first_then_newest_owed_then_finished(self):
        with Home() as home:
            # a running run is owned by a live process, as `ak run` owns its run, or the
            # listing would rightly call it interrupted
            keeper = subprocess.Popen(["sleep", "3600"], start_new_session=True)
            self.addCleanup(lambda: (keeper.kill(), keeper.wait()))
            now = time.time()
            record(home, "20260101-0600-start-early", title="Start early", state="running",
                   rounds=2, started_at=now - 6 * HOUR, **owner(keeper.pid))
            record(home, "20260101-0700-stall-midway", title="Stall midway", state="stalled",
                   rounds=2, started_at=now - 3 * HOUR)
            record(home, "20260101-0800-fail-late", title="Fail late", state="fail", rounds=2,
                   started_at=now - 2 * HOUR, finished_at=now - HOUR)
            record(home, "20260101-0900-merge-last", title="Merge last", state="pass",
                   merged=True, rounds=2, round_summaries=[{}, {}],
                   started_at=now - 1200, finished_at=now - 600)
            done = home.ak("run", "status", env=env())
            self.assertEqual(done.code, 0, done.err)
            rows = [(line.split()[0], WORD.search(line).group())
                    for line in done.out.splitlines() if line.startswith("2026")]
            # the stalled run is `working` too, yet the newer failure sits above it
            self.assertEqual(rows, [("20260101-0600-start-early", "● working"),
                                    ("20260101-0800-fail-late", "! needs you"),
                                    ("20260101-0700-stall-midway", "● working"),
                                    ("20260101-0900-merge-last", "✓ done")])


if __name__ == "__main__":
    unittest.main()
