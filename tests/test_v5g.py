"""v5g: every seat row says what it has done -- the tally of the runs it launched; offline.

Fixed fake seats and run.json records, the real renderer.  The clock is pinned so that the
seven-day window has something on either side of it.
"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from unittest.mock import patch
import unittest

from test_v4n import REPO, Sandbox
from agentkit import config, menu, orch, run, terminal, watch

NOW = 1_800_000_000      # what every draw and tally reads as the time
INSTALLED = menu.installed   # the real title lookup, kept before the fixtures pin it
DAY = 86400
LONG_Q = ("Should the dashboard filter by workspace and show archived runs by default "
          "when there are more than twenty items, or keep the current filter behaviour for now?")


class Tallies(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        self.stack.enter_context(patch.object(menu.time, "time", return_value=NOW))
        self.stack.enter_context(patch("agentkit.watch.live_state", side_effect=lambda seat, *a, **kw:
                                      {"state": seat.get("live", "working"), "rule": "fixture",
                                       "since": seat.get("since"), "began": seat.get("since"),
                                       "evidence": seat.get("asked", "")}))
        self.stack.enter_context(patch.object(menu.time, "strftime", return_value="14:02"))
        self.stack.enter_context(patch.object(menu, "installed", return_value="3de8bef · 14 Sep"))
        # A project is a checkout: `checkouts()` asks for a .git, and nothing else
        # under ~/code is ever a heading.
        for name in ("agentkit", "atoll"):
            (config.CODE / name / ".git").mkdir(parents=True)
        self.seats = []
        # v5ay: a run under a live seat hands its ending back to that seat, so the one seat
        # whose row names a failure of its own is a seat nobody is in any more.
        for name, repo, live, since, gone in (
                ("atoll-fix", "atoll", "at_prompt", NOW - 4 * DAY, False),
                ("atoll-proxy", "atoll", "at_prompt", NOW - 3 * DAY, True),
                ("herdr", "agentkit", "asking", NOW - 120, False),
                ("scribe", None, "at_prompt", NOW - 3600, False)):
            path = str(config.CODE / repo) if repo else str(self.root)
            self.seats.append({"name": name, "repo": path if repo else None, "path": path,
                               "live": live, "since": since, "created": NOW - 5 * DAY,
                               **({"exited": True} if gone else {})})
            config.save_session(self.cfg, name, "fable", ["opus"], {"repo": path if repo else None, "cwd": path})
        # herdr: one run going, one merged this week
        self.ended("herdr-going", owner="herdr", repo=str(config.CODE / "agentkit"), title="Ship the tally",
                   state="running", finished_at=None, started_at=NOW - 900, rounds=3,
                   round_summaries=[{}], **run.process_owner())
        self.merged("herdr-merged", "herdr", NOW - 2 * DAY)
        # atoll-fix: three merges this week, one older than the week, one ending already acknowledged
        for n, ago in enumerate((3600, 2 * DAY, 6 * DAY)):
            self.merged(f"fix-merged-{n}", "atoll-fix", NOW - ago)
        self.merged("fix-merged-old", "atoll-fix", NOW - 8 * DAY)
        self.ended("fix-acknowledged", owner="atoll-fix", state="interrupted", verdict=None,
                   interrupted_at=NOW - DAY, recovery_pending=True, recovery_acknowledged_at=NOW - 3600)
        # atoll-proxy: two merges, and a failure nobody has acknowledged
        self.merged("proxy-merged-0", "atoll-proxy", NOW - DAY)
        self.merged("proxy-merged-1", "atoll-proxy", NOW - 4 * DAY)
        self.ended("proxy-failed", owner="atoll-proxy", state="fail", verdict="FAIL", finished_at=NOW - 3 * DAY)
        (config.STATE / "usage.json").write_text(json.dumps({"fetched_at": NOW, "providers": {
            "anthropic": {"meters": [{"name": "weekly_all", "used": 79}]},
            "openai": {"meters": [{"name": "weekly", "used": 31, "window_secs": 604800}], "resets": 2},
            "meta": {"meters": [{"name": "weekly", "used": 50, "window_secs": 604800}]}}}))
        # The clock is pinned to NOW, so the run directories are dated NOW too:
        # otherwise every running run would read silent with a false age.
        for path in list(config.RUNS.rglob("*")) + [config.RUNS]:
            try:
                if path.is_file() or path == config.RUNS:
                    os.utime(path, (NOW, NOW))
            except OSError:
                pass

    def merged(self, name, owner, finished_at):
        return self.ended(name, owner=owner, merged=True, finished_at=finished_at,
                          started_at=finished_at - 1800)

    def draw(self, width=100, height=30, page=0, keys=menu.KEYS):
        with patch.object(terminal, "width", return_value=width), \
                patch.object(terminal, "height", return_value=height), redirect_stdout(io.StringIO()) as out:
            pagination = menu.draw(self.cfg, self.seats, keys, page)
        return out.getvalue(), pagination

    def no_git(self, argv, *args, **kwargs):
        """A draw talks to tmux -- each seat's screen, then its bar -- and never to git."""
        self.assertNotIn("git", argv[0], argv)
        return subprocess.CompletedProcess(argv, 1, "", "")

    def tallies(self):
        return {row[1]: row[6] for project in menu.projects(self.cfg, self.seats) for row in project["rows"]}

    def test_v5g_a_running_and_merged_counts_per_seat(self):
        states = [{"launched_session": "a", "state": "running"},
                  {"launched_session": "a", "state": "queued"},
                  {"launched_session": "a", "state": "pass", "merged": True, "finished_at": NOW - DAY},
                  {"launched_session": "b", "state": "pass", "merged": True, "finished_at": NOW - 60},
                  {"launched_session": "b", "state": "pass", "merged": True, "finished_at": NOW - 6 * DAY},
                  {"launched_session": "b", "state": "pass", "merged": False, "finished_at": NOW - 60},
                  {"state": "running"},                            # launched from no seat: nobody's
                  {"launched_session": ["bad"], "state": "running"}]
        self.assertEqual(run.seat_tallies(states, now=NOW), {"a": (2, 0, 1), "b": (0, 0, 2)})
        self.assertEqual(menu.tally((2, 0, 1)), "2 running · 1 merged")
        self.assertEqual(menu.tally((0, 0, 2)), "0 running · 2 merged")
        found = self.tallies()
        self.assertEqual(found["herdr"], "1 running · 1 merged")
        self.assertEqual(found["atoll-fix"], "0 running · 3 merged")

    def test_v5g_b_an_ending_that_needs_him_takes_precedence_over_merged(self):
        self.assertEqual(self.tallies()["atoll-proxy"], "0 running · 1 needs you")
        for word in ("interrupted", "fail", "error"):
            with self.subTest(word=word):
                states = [{"launched_session": "s", "state": word, "finished_at": NOW - 2 * DAY},
                          {"launched_session": "s", "state": "pass", "merged": True, "finished_at": NOW - 60},
                          {"launched_session": "s", "state": "running"}]
                self.assertEqual(run.seat_tallies(states, now=NOW), {"s": (1, 1, 1)})
                self.assertEqual(menu.tally((1, 1, 1)), "1 running · 1 needs you")
                states[0]["recovery_acknowledged_at"] = NOW - 30    # acknowledged: it is not a look
                self.assertEqual(run.seat_tallies(states, now=NOW), {"s": (1, 0, 1)})
        # a run parked on a provider window or a stall resumes itself: it is nobody's look,
        # and it is still going -- the figure the seat's own reason counts, so `1 running`
        # on the row and `1 running` here can never be about different runs
        for word in ("exhausted", "stalled"):
            parked = {"launched_session": "s", "state": word, "finished_at": NOW - 2 * DAY,
                      "quota_dry": word == "exhausted"}
            self.assertEqual(run.seat_tallies([parked], now=NOW), {"s": (1, 0, 0)}, word)
        # an ending ages out with the week, acknowledged or not: after run.GC_AGE it
        # counts for nobody, and r is where it is still listed
        for word in ("interrupted", "fail", "error"):
            old = {"launched_session": "s", "state": word, "finished_at": NOW - 20 * DAY}
            self.assertEqual(run.seat_tallies([old], now=NOW), {"s": (0, 0, 0)}, word)
            fresh = {"launched_session": "s", "state": word, "finished_at": NOW - 6 * DAY}
            self.assertEqual(run.seat_tallies([fresh], now=NOW), {"s": (0, 1, 0)}, word)
        # the tally reads the same test the seat row's reason does
        self.assertTrue(menu.v5o_needs_look({"state": "fail", "finished_at": NOW - 6 * DAY},
                                            now=NOW))
        self.assertFalse(menu.v5o_needs_look({"state": "fail", "finished_at": NOW - 20 * DAY},
                                             now=NOW))
        self.assertEqual(self.tallies()["atoll-fix"], "0 running · 3 merged")    # its interruption was acknowledged

    def test_v5g_c_merged_counts_only_the_last_seven_days(self):
        states = [{"launched_session": "s", "state": "pass", "merged": True, "finished_at": NOW - 7 * DAY + 1},
                  {"launched_session": "s", "state": "pass", "merged": True, "finished_at": NOW - 7 * DAY - 1},
                  {"launched_session": "s", "state": "pass", "merged": True, "finished_at": NOW + 60},
                  {"launched_session": "s", "state": "pass", "merged": True, "finished_at": "yesterday"},
                  {"launched_session": "s", "state": "pass", "merged": True, "started_at": NOW - DAY}]
        self.assertEqual(run.seat_tallies(states, now=NOW), {"s": (0, 0, 2)})
        self.assertEqual(run.seat_tallies(states, now=NOW + 2), {"s": (0, 0, 1)})
        self.assertEqual(self.tallies()["atoll-fix"], "0 running · 3 merged")   # four merges, one is 8 days old

    def test_v5g_d_no_runs_gives_no_runs_yet(self):
        self.assertEqual(menu.tally(None), "no runs yet")
        self.assertEqual(self.tallies()["scribe"], "no runs yet")
        self.assertNotIn("scribe", run.seat_tallies(state for _, state in menu.run_records()))
        # a seat whose only run is older than the week has runs, and says so
        self.merged("scribe-old", "scribe", NOW - 30 * DAY)
        self.assertEqual(self.tallies()["scribe"], "0 running · 0 merged")
        # the smoke suite's own runs are nobody's tally, as they are off r
        self.ended("smoke-of-scribe", owner="scribe", merged=True, finished_at=NOW - 60,
                   task=str(config.TMP / "smoke-20260923-110800" / "task.md"))
        self.assertEqual(self.tallies()["scribe"], "0 running · 0 merged")

    def test_smoke_sandbox_runs_are_left_out(self):
        sandbox = config.TMP / "smoke-20260923-110800"
        for key, path in (("task", sandbox / "task.md"), ("repo", sandbox / "repo"),
                          ("repo", sandbox)):
            with self.subTest(key=key, path=path):
                directory = self.ended(f"suite-{key}-{path.name}", owner="scribe",
                                       state="running", finished_at=None, **{key: str(path)})
                self.assertNotIn(directory, [d for d, _ in menu.run_records()])
                self.assertEqual(self.tallies()["scribe"], "no runs yet")

    def test_smoke_in_run_id_counts_as_running(self):
        directory = self.ended("20260923-1057-agentkit-the-smoke-sandbox-borrows-login",
                               owner="scribe", state="running", finished_at=None,
                               started_at=NOW - 60, repo=str(config.CODE / "smoke-project"),
                               task=str(config.HOME / "tasks" / "smoke-task.md"))
        self.assertIn(directory, [d for d, _ in menu.run_records()])
        self.assertEqual(self.tallies()["scribe"], "1 running · 0 merged")
        seat = next(seat for seat in self.seats if seat["name"] == "scribe")
        answer = watch.session_state("scribe", NOW, session=seat, cfg=self.cfg,
                                     live={"state": "at_prompt"})
        self.assertEqual(answer["word"], "working")
        self.assertTrue(answer["reason"].startswith("1 running"))

    def test_v5g_e_the_100_column_fixture_renders_exactly(self):
        screen, pages = self.draw(100, 30)
        self.assertEqual(screen, (REPO / "tests/fixtures/v5g-100.txt").read_text())
        self.assertEqual(pages, (0, 1))
        # Seat rows carry number, name, orchestrator, state and one last column, and a
        # working seat's is never `N running`.
        for row in ("3  herdr", "fable",
                    "2  atoll-proxy", "session closed: press 2 to reopen",
                    "1  atoll-fix", "4  scribe"):
            self.assertIn(row, screen)
        self.assertNotIn("1 running", screen)
        self.assertNotIn("Ship the tally", screen)
        self.assertNotIn("run proxy-failed", screen)
        self.assertNotIn("press r", screen)
        self.assertNotIn("merged", screen)
        self.assertNotIn("fix-merged-0", screen)
        self.assertNotIn("no runs yet", screen)
        self.assertNotIn("↳", screen)
        self.assertNotIn("Finished proxy-failed", screen)
        self.assertNotIn("scratch", screen)
        self.assertTrue(all(terminal.cells(line) <= 100 for line in screen.splitlines()))
        # No age on any row: the last column, not a clock, says what the seat is doing.
        self.assertNotRegex(screen, r"(?m)\d+[smhd]\s*$")
        # The count is said once, on the top line.
        self.assertIn("your projects · 3 need you", screen)
        # ... and each needing row says the word too, in the state column
        self.assertEqual(screen.count("needs you"), 3)
        with patch.object(terminal, "colour_depth", return_value=24):
            coloured, _ = self.draw(100, 30)
        self.assertIn(terminal.styled("atoll", "accent"), coloured)
        self.assertNotIn("2 seats", coloured)
        self.assertTrue(all(terminal.cells(terminal.plain(line)) <= 100
                            for line in coloured.splitlines()))

    def test_v5g_f_at_40_columns_the_count_stays_and_every_row_fits(self):
        screen, pages = self.draw(40, 24)
        self.assertEqual(screen, (REPO / "tests/fixtures/v5g-40.txt").read_text())
        self.assertEqual(pages, (0, 1))
        # No count of running work, never merges, never a run reason.
        self.assertNotIn("1 running", screen)
        self.assertIn("session closed: press 2 to reopen", screen)
        self.assertNotIn("merged", screen)
        self.assertNotIn("no runs yet", screen)
        self.assertNotIn("press r", screen)
        # Narrow rows keep the head line and put the last column below it.
        self.assertIn("atoll-proxy", screen)
        self.assertIn("    session closed: press 2 to reopen\n", screen)
        self.assertTrue(all(terminal.cells(line) <= 40 for line in screen.splitlines()))
        # At every width the last column is drawn whole beside whole names, and every
        # line still fits; merges stay off the menu at every width.
        for width in range(40, 101):
            with self.subTest(width=width):
                screen, _ = self.draw(width, 40)
                self.assertTrue(all(terminal.cells(line) <= width for line in screen.splitlines()), screen)
                self.assertNotIn("1 running", screen)
                self.assertRegex(screen, r"session\s+closed:\s+press\s+2")
                self.assertNotIn("merged", screen)
        # A long note beside the new columns wraps onto one indented line, never past
        # the width.
        with patch.object(menu.notify, "last", return_value={"kind": "needs", "text": LONG_Q,
                                                             "time": NOW - 300}):
            screen, _ = self.draw(100, 30)
        self.assertIn("Should the dashboard filter by workspace", screen)
        self.assertIn("by default when there are more than twenty items", screen)
        self.assertNotIn("1 running", screen)
        self.assertTrue(all(terminal.cells(line) <= 100 for line in screen.splitlines()))

    def test_v5g_g_ak_orch_list_shows_the_tally(self):
        with patch.object(orch, "listing", return_value=self.seats), \
                patch.object(terminal, "width", return_value=100), \
                redirect_stdout(io.StringIO()) as out:
            orch.cmd_list([])
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 6)          # a header, four seats and the slice line
        self.assertRegex(lines[-1], r"^(slice \S+ ·|no slice )")
        self.assertRegex(lines[0], r"^name\s+project\s+state\s+tally\s+orchestrator\s+workers\s+age$")
        for name, expected in (("herdr", r"agentkit\s+● working\s+1 running · 1 merged\s+fable\s+opus\s+5d"),
                               ("atoll-fix", r"! needs you\s+0 running · 3 merged\s+fable\s+opus\s+5d"),
                               ("atoll-proxy", r"! needs you\s+0 running · 1 needs you\s+fable\s+opus\s+"),
                               ("scribe", r"no project\s+! needs you\s+no runs yet\s+fable\s+opus\s+")):
            line = next(line for line in lines if line.startswith(name + " "))
            self.assertRegex(line, expected)
        self.assertRegex(lines[1], r"^atoll-fix\s+atoll\s+! needs you\s+0 running")

    def test_v5g_h_three_hundred_records_draw_in_under_a_second_reading_each_once(self):
        for n in range(300):
            owner = self.seats[n % 4]["name"]
            if n % 3 == 0:
                self.merged(f"bulk-{n:03d}", owner, NOW - (n % 10) * DAY)
            elif n % 3 == 1:
                self.ended(f"bulk-{n:03d}", owner=owner, state="fail", verdict="FAIL", finished_at=NOW - 2 * DAY)
            else:
                self.ended(f"bulk-{n:03d}", owner=owner, state="pass", finished_at=NOW - 9 * DAY)
        self.ended("smoke-bulk", owner="herdr", merged=True, finished_at=NOW - 60,
                   repo=str(config.TMP / "smoke-20260923-110800" / "repo"))
        records = len(run.run_dirs())     # each record is read once, including the suite's
        # one draw settles each seat's word; the draws that follow write nothing at all
        self.draw(100, 30)
        before = {path: path.read_bytes() for directory in (config.RUNS, config.STATE)
                  for path in directory.rglob("*") if path.is_file()}
        # the real title lookup, as loop() reads it once before its first draw; every draw
        # after that, of any size, goes back to git for nothing and starts no process
        self.addCleanup(setattr, menu, "_INSTALLED", None)
        menu._INSTALLED = None
        with patch.object(menu, "installed", INSTALLED):
            self.assertEqual(INSTALLED(), "14:02")
            with patch.object(run, "read_state", wraps=run.read_state) as read, \
                    patch.object(run, "reap", side_effect=AssertionError("draw reconciled a run")), \
                    patch.object(run, "save_state", side_effect=AssertionError("draw wrote a record")), \
                    patch.object(subprocess, "run", side_effect=self.no_git), \
                    patch.object(subprocess, "Popen", side_effect=AssertionError("draw started a process")):
                started = time.perf_counter()
                screen, pages = self.draw(100, 30)
                elapsed = time.perf_counter() - started
                self.assertEqual(read.call_count, records)      # each record once for the draw
                self.draw(40, 24)
                self.assertEqual(read.call_count, 2 * records)  # and once again for the next
        self.assertLess(elapsed, 1.0, elapsed)
        self.assertTrue(screen.startswith("agentkit"), screen[:60])
        self.assertIn("14:02", screen.splitlines()[0])
        self.assertGreaterEqual(records, 300)
        # Endings never reach a row, nor does the going run's count; merged stays off.
        self.assertEqual(pages, (0, 1))
        self.assertNotIn("1 running", screen)
        self.assertNotIn("failed: press", screen)
        self.assertNotIn("press r", screen)
        self.assertNotIn("merged", screen)
        self.assertNotIn("↳", screen)
        after = {path: path.read_bytes() for directory in (config.RUNS, config.STATE)
                 for path in directory.rglob("*") if path.is_file()}
        self.assertEqual(after, before)


if __name__ == "__main__":
    if sys.argv[1:] == ["--fixtures"]:
        test = Tallies()
        test.setUp()
        try:
            for width, height in ((100, 30), (40, 24)):
                (REPO / f"tests/fixtures/v5g-{width}.txt").write_text(test.draw(width, height)[0])
        finally:
            test.doCleanups()
    else:
        unittest.main(verbosity=2)
