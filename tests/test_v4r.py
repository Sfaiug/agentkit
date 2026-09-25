"""Provider usage-left menus and the runs drill-down; offline, with no harness calls."""

from contextlib import redirect_stdout
import io
import json
import os
import subprocess
import sys
import threading
import time
from unittest.mock import patch
import unittest

from test_v4n import REPO, Sandbox
from agentkit import config, macbridge, menu, orch, run, terminal, usage


class UsageLeft(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(menu.time, "localtime", side_effect=time.gmtime))
        self.stack.enter_context(patch.object(usage, "collect", side_effect=AssertionError("probe")))
        self.stack.enter_context(patch.object(usage, "_probe", side_effect=AssertionError("probe")))
        self.stack.enter_context(patch.object(usage, "_maybe_reset", side_effect=AssertionError("reset")))
        # A tty -- a real one, or the startup test pretending stdin is a keyboard --
        # starts Live.probe's thread. This mock is gone when the test is, and the
        # thread then either raises this AssertionError into whatever runs next or
        # calls the real collector, which starts adapter processes. The file is
        # offline: the probe never starts, and one that already did is finished
        # before the mock comes down.
        self.stack.enter_context(patch.object(menu.Live, "probe", return_value=False))
        self.addCleanup(self._join_probe_threads)
        self.providers = {
            "anthropic": {"meters": [self.meter("weekly_all", 79),
                                      self.meter("weekly_scoped", 53),
                                      self.meter("session", 100, window=18000)]},
            "openai": {"meters": [self.meter("weekly", 31)], "resets": 2},
            "meta": {"meters": [self.meter("weekly", 100, reset=22 * 3600)]}}
        self.cache()

    @staticmethod
    def _join_probe_threads():
        """Finish a usage refresh before this test's collector mock comes down."""
        for thread in threading.enumerate():
            if thread is threading.current_thread() or not thread.name.endswith("(_work)"):
                continue
            thread.join(5)
            if thread.is_alive():
                raise AssertionError("usage refresh still running after the test")

    def meter(self, name, used, reset=3 * 86400, window=604800):
        return {"name": name, "used": used, "resets_at": reset, "window_secs": window}

    def cache(self):
        path = config.STATE / "usage.json"
        path.write_text(json.dumps({"fetched_at": 10000, "providers": self.providers}))
        return path

    def fixtures(self):
        seats = [{"name": "atoll-fix", "created": 9100},
                 {"name": "web-portal", "created": 8800}]
        for seat in seats:
            config.save_session(self.cfg, seat["name"], "fable", ["opus"])
        self.ended("active", owner="atoll-fix", title="Hidden active work-run",
                   state="running", **run.process_owner(), started_at=9100, finished_at=None,
                   rounds=3, round_summaries=[{}])
        for n in range(9):
            self.ended(f"ended-{n}", owner=None, title=f"Hidden completed work-run {n}")
        self.ended("interrupted", owner=None, title="Hidden unfinished work-run",
                   state="interrupted", started_at=1000, interrupted_at=9900)
        self.ended("smoke-secret", title="Hidden smoke run", state="running",
                   task=str(config.TMP / "smoke-20260923-110800" / "task.md"),
                   **run.process_owner(), started_at=9900, finished_at=None)
        return seats

    def draw(self, seats, width, version="abc1234 · 12 Jan"):
        out = io.StringIO()
        with patch.object(terminal, "width", return_value=width), \
                patch.object(menu, "installed", return_value=version), \
                patch.object(menu.time, "strftime", wraps=time.strftime) as stamp, redirect_stdout(out):
            real = stamp._mock_wraps
            stamp.side_effect = lambda fmt, *args: "13:05" if not args else real(fmt, *args)
            menu.draw(self.cfg, seats)
        return out.getvalue()

    def test_usage_rows_at_40_and_100_columns_above_project_groups(self):
        seats = self.fixtures()
        before = self.cache().read_bytes()
        for width in (40, 100):
            with self.subTest(width=width):
                text = self.draw(seats, width)
                self.assertTrue(all(terminal.cells(line) <= width for line in text.splitlines()))
                self.assertNotIn("\033", text)
                block, sessions = text.split("\nyour projects · ")
                self.assertIn("usage left", block)
                for name, left, filled in (("Claude", 21, 3), ("ChatGPT", 69, 8), ("Muse", 0, 0)):
                    row = next(line for line in block.splitlines() if line.strip().startswith(name))
                    self.assertRegex(row, rf"{name}\s+[█░]+\s+{left}% left")
                    # one column: every bar is the width the row with the
                    # least room can afford, and the bar is what gives way to a
                    # note, so a phone's is narrower than a laptop's
                    bar = 6 if width == 40 else 12
                    self.assertEqual(row.count("█"), round(bar * left / 100))
                    self.assertEqual(row.count("░"), bar - round(bar * left / 100))
                self.assertEqual("resets Thu 22:00" in block, width == 100)
                self.assertIn("Fable 47%", block)   # the short note fits on a phone too
                self.assertNotIn("+2 resets", block)
                self.assertEqual(sum("░" in line for line in block.splitlines()), 3)
                # Seats only: an orphan run is no row and makes no project, and
                # merged runs were never rows either.
                self.assertNotIn("Hidden unfinished work-run", sessions)
                self.assertNotIn("↳", sessions)
                for name in ("atoll-fix", "web-portal"):
                    self.assertEqual(text.count(name), 1)
                self.assertIn("no project", sessions)
                self.assertNotIn("scratch", sessions)
                self.assertNotIn("11 runs", sessions)
                self.assertIn("\n  n new" if width == 100 else "n new", sessions)
                # A working seat without a plan or a job reads empty, never `N running`;
                # titles fold away.
                self.assertNotIn("1 running", text)
                self.assertNotIn("Hidden active work-run", text)
                self.assertNotRegex(text, "smoke|more · r|no runs going")
                self.assertNotIn("opus/astra", text)
                self.assertNotIn("merged", text)
        self.assertEqual((config.STATE / "usage.json").read_bytes(), before)

    def test_redraw_only_lists_owner_seats_and_refreshes_cached_usage(self):
        seats = self.fixtures()
        def answer(*args):
            if self.providers["openai"]["resets"] == 2:
                self.providers["openai"]["resets"] = 0
                self.providers["openai"]["meters"][0]["used"] = 40
                self.cache()
                return ""
            return "q"
        # The wait is mocked beside the read: the real one selects on stdin, and a
        # stdin that never delivers EOF -- a backgrounded run's open pipe -- would redraw
        # into `out` every TICK forever, growing without bound instead of finishing.
        with patch.object(menu.orch, "listing", return_value=seats), \
                patch.object(menu.orch, "job_notices", return_value=[]), \
                patch.object(menu, "read", side_effect=answer), \
                patch.object(menu, "wait_key", side_effect=lambda prompt, timeout=None,
                             wake=None: menu.read(prompt, "q")), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        self.assertIn("69%", out.getvalue())
        self.assertIn("60%", out.getvalue())
        # the resets in hand are `ak usage`'s column; the menu says when the week is back
        self.assertNotIn("+2 resets", out.getvalue())
        self.assertEqual(out.getvalue().count("resets Sun 00:00"), 4)

    def test_colours_and_terminal_fallbacks(self):
        with patch.object(sys.stdout, "isatty", return_value=True), \
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True), \
                patch("curses.setupterm"), patch("curses.tigetnum", return_value=8):
            lines = menu.usage_lines(self.cfg, 100)
            # each company's own colour, the nearest of eight here, and the empty cells dim
            self.assertIn("\033[31m███\033[0m\033[2m░░░░░░░░░\033[0m", lines[1])
            self.assertIn("\033[37m████████\033[0m\033[2m░░░░\033[0m", lines[5])
            self.assertIn("  \033[2m░░░░░░░░░░░░\033[0m  ", lines[3])
            plain = [terminal.plain(line) for line in lines]
            for env in ({"TERM": "dumb"}, {"TERM": "xterm-256color", "NO_COLOR": ""}, {}):
                with patch.dict(os.environ, env, clear=True):
                    rendered = menu.usage_lines(self.cfg, 100)
                    self.assertNotIn("\033", "\n".join(rendered))
                    self.assertEqual([terminal.plain(line) for line in rendered], plain)
            with patch.object(sys.stdout, "isatty", return_value=False):
                self.assertNotIn("\033", "\n".join(menu.usage_lines(self.cfg, 100)))
            with patch("curses.tigetnum", return_value=0):
                self.assertNotIn("\033", "\n".join(menu.usage_lines(self.cfg, 100)))

    def test_missing_corrupt_or_unreadable_usage_keeps_every_provider_row(self):
        path = self.cache()
        path.unlink()
        for raw in (None, "not json", "[]", '{"providers": []}', '{"providers": {}}'):
            if raw is not None:
                path.write_text(raw)
            for width in (40, 100):
                text = self.draw([], width)
                self.assertIn("no sessions; n starts one", text)
                self.assertEqual(text.count("—"), 6)
                self.assertNotRegex(text, "[█░]")
        with patch.object(type(path), "read_text", side_effect=PermissionError):
            self.assertEqual("\n".join(menu.usage_lines(self.cfg, 40)).count("—"), 6)

    def test_unknown_or_expired_provider_does_not_hide_the_others(self):
        for prov, tail in (({"error": "offline", "meters": [self.meter("weekly", 10)]},
                            "90% left · resets Sun 00:00 · ? offline"),
                           ({"meters": [self.meter("weekly", 100, reset=9999)]}, "—  window reset"),
                           ({"meters": [self.meter("session", 100, window=18000)]}, "—  no weekly meter"),
                           ({"meters": [self.meter("weekly", None)]}, "—  bad reading"),
                           ({"meters": [None]}, "—  bad reading"), ("bad", "—  no reading yet")):
            self.providers["meta"] = prov
            self.cache()
            lines = menu.usage_lines(self.cfg, 100)
            self.assertIn("69%", lines[5])
            self.assertTrue(lines[3].endswith(tail), lines)

    def test_provider_names_come_from_config_and_bar_uses_tightest_week(self):
        self.cfg["providers"] = {"openai": {}, "界" * 80: {}}
        self.providers["openai"]["meters"].append(self.meter("other-week", 80))
        self.providers["界" * 80] = {"meters": [self.meter("weekly", -10)]}
        self.cache()
        for width in (40, 100):
            lines = menu.usage_lines(self.cfg, width)
            self.assertEqual(len(lines), 3)
            # the unknown provider is drawn in the accent, a blue, and ChatGPT's white comes after
            self.assertIn("100%", lines[1])
            self.assertIn("20%", lines[2])
            self.assertTrue(all(terminal.cells(line) <= width for line in lines))
        self.providers["openai"]["resets"] = 0
        self.providers["openai"]["meters"] = [self.meter("weekly", 120)]
        self.cache()
        self.assertIn("0% left · resets Sun 00:00", menu.usage_lines(self.cfg, 100)[2])

    def test_spent_windows_keep_scoped_allowance_and_unspent_resets(self):
        self.providers["anthropic"]["meters"][0]["used"] = 100
        self.providers["openai"]["meters"][0]["used"] = 100
        self.cache()
        lines = menu.usage_lines(self.cfg, 100)
        self.assertIn("0% left · resets Sun 00:00 · Fable 47%", lines[1])
        self.assertIn("0% left · resets Sun 00:00", lines[5])
        self.assertNotIn("+2 resets", "\n".join(lines))
        self.assertNotIn("█", "\n".join(lines))

    def test_rounded_zero_gets_spent_style_and_reset_note(self):
        for used, shown in ((99.49, 1), (99.5, 0), (99.9, 0), (100, 0)):
            self.providers["meta"]["meters"][0]["used"] = used
            self.cache()
            with patch.object(sys.stdout, "isatty", return_value=True), \
                    patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True), \
                    patch("curses.setupterm"), patch("curses.tigetnum", return_value=8):
                line = menu.usage_lines(self.cfg, 100)[3]
                self.assertIn(f"{shown}%", line)
                self.assertIn("resets Thu 22:00", line)
                if shown == 0:
                    self.assertIn("\033[2m  0% left\033[0m", line)
                    self.assertNotIn("\033[33m", line)

    def test_cache_age_is_never_shown_and_drawing_changes_no_allowance(self):
        path = self.cache()
        for fetched in (10000, 10000 - usage.CACHE_TTL, 6400, None):
            path.write_text(json.dumps({"fetched_at": fetched, "providers": self.providers}))
            before = path.read_bytes()
            for width in (40, 100):
                lines = menu.usage_lines(self.cfg, width)
                self.assertEqual(lines[0], "  usage left")
                self.assertIn("21%", lines[1])
                self.assertTrue(all(terminal.cells(line) <= width for line in lines))
            self.assertEqual(path.read_bytes(), before)
        with patch.object(sys.stdout, "isatty", return_value=True), \
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True), \
                patch("curses.setupterm"), patch("curses.tigetnum", return_value=8):
            self.assertTrue(menu.usage_lines(self.cfg, 40)[0].startswith("\033[2m"))

    def test_startup_pauses_for_warnings_and_never_for_receipts_before_drawing_once(self):
        # A live seat's ending is that seat's to report, so the menu opens on the seats
        directory = self.ended("old-owned", owner="atoll-fix", finished_at=10000 - 8 * 3600)
        self.assertIn(directory, [path for path, _ in menu.run_records()])
        warning = "WARN could not check the runs: the run directory is unreadable"
        updates = [["agentkit: reaped a loop whose process was gone", warning], []]
        real_maintenance = orch.maintenance
        def maintenance(log):
            for message in updates.pop(0):
                log(message)
            real_maintenance(log)
        with patch.object(macbridge, "start_background"), \
                patch.object(config, "server_alias", return_value=None), \
                patch.object(orch, "maintenance", side_effect=maintenance), \
                patch.object(orch, "sessions", return_value=[{"name": "atoll-fix", "created": 9100}]), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu, "wait_key", side_effect=lambda prompt, timeout=None,
                             wake=None: menu.read(prompt, "q")), \
                patch.object(sys.stdin, "isatty", return_value=True):
            for first in (True, False):
                out = io.StringIO()
                with redirect_stdout(out), patch.object(out, "isatty", return_value=True), \
                        patch.object(menu, "read", side_effect=lambda prompt, default:
                                     "" if prompt.startswith("Enter") else "q") as read:
                    self.assertEqual(menu.main([]), 0)
                # The header carries no hash; split on it, not on the update notice.
                before, screen = out.getvalue().split("agentkit ", 1)
                if first:
                    self.assertIn("agentkit: reaped a loop whose process was gone", before)
                    self.assertIn(warning, before)
                    self.assertEqual(before.count("Finished old-owned"), 0)
                    self.assertEqual([call.args[0] for call in read.call_args_list],
                                     ["q back ", "> "])
                else:
                    self.assertEqual(before, "")
                    self.assertEqual([call.args[0] for call in read.call_args_list], ["> "])
                self.assertNotIn("Finished old-owned", screen)
                self.assertNotIn(warning, screen)
                self.assertFalse(run.read_state(directory)["reported"])

    def test_notice_pause_wraps_complete_messages_on_a_phone(self):
        message = "WARN could not check the runs: the repository is temporarily unavailable"
        with patch.object(terminal, "width", return_value=40), \
                redirect_stdout(io.StringIO()) as out:
            menu.show_notices([message])
        self.assertEqual(" ".join(out.getvalue().split()), message)
        self.assertTrue(all(terminal.cells(line) <= 40 for line in out.getvalue().splitlines()))

    def test_records_retain_rounds_recovery_and_hide_smoke_runs(self):
        self.fixtures()
        listing = list(menu.run_records())
        self.assertFalse(any("smoke" in directory.name for directory, _ in listing))
        for directory, record in listing:
            if directory.name == "active":
                row = menu.run_row(1, directory, record)
                self.assertEqual((row[3], row[5]), ("working", "15m"))
                self.assertIn("2/3", row[4])
            elif directory.name == "interrupted":
                self.assertEqual(menu.run_progress(record)[2:], ("interrupted", "1m"))
        self.assertFalse(hasattr(menu, "runs"))
        # `ak run status` is where runs are listed now.
        with redirect_stdout(io.StringIO()) as out:
            run.cmd_status([])
        self.assertIn("Hidden active work-run", out.getvalue())
        self.assertIn("Hidden unfinished work-run", out.getvalue())


if __name__ == "__main__":
    unittest.main()
