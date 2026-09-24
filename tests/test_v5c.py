"""v5c: the menu's header and its usage rows, and the polarity `ak usage` prints; offline.

These used to live in test_v4r.py beside the runs drill-down.  They are the usage row's own
behaviours, so they are their own file now, and they read the row as it stands today: the
provider's shared week, when that week resets, a scoped cap only where it differs, and the
adapter's own reason when a probe failed.
"""

from contextlib import redirect_stdout
import io
import json
import os
import subprocess
import sys
import time
from unittest.mock import patch
import unittest

from test_v4n import REPO, Sandbox
from agentkit import config, menu, terminal, usage


class UsageRow(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(menu.time, "localtime", side_effect=time.gmtime))
        self.stack.enter_context(patch.object(usage, "collect", side_effect=AssertionError("probe")))
        self.stack.enter_context(patch.object(usage, "_probe", side_effect=AssertionError("probe")))
        self.stack.enter_context(patch.object(usage, "_maybe_reset", side_effect=AssertionError("reset")))
        self.providers = {
            "anthropic": {"meters": [self.meter("weekly_all", 79),
                                      self.meter("weekly_scoped", 53),
                                      self.meter("session", 100, window=18000)]},
            "openai": {"meters": [self.meter("weekly", 31)], "resets": 2},
            "meta": {"meters": [self.meter("weekly", 100, reset=22 * 3600)]}}
        self.cache()

    def meter(self, name, used, reset=3 * 86400, window=604800):
        return {"name": name, "used": used, "resets_at": reset, "window_secs": window}

    def cache(self):
        path = config.STATE / "usage.json"
        path.write_text(json.dumps({"fetched_at": 10000, "providers": self.providers}))
        return path

    def draw(self, seats, width, version="abc1234 · 12 Jan"):
        out = io.StringIO()
        with patch.object(terminal, "width", return_value=width), \
                patch.object(menu, "installed", return_value=version), \
                patch.object(menu.time, "strftime", wraps=time.strftime) as stamp, redirect_stdout(out):
            real = stamp._mock_wraps
            stamp.side_effect = lambda fmt, *args: "13:05" if not args else real(fmt, *args)
            menu.draw(self.cfg, seats)
        return out.getvalue()

    def test_v5c_header_shows_short_sha_and_date_never_the_hostname(self):
        calls = []

        def git(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "abc1234 950400\n", "")
        self.addCleanup(setattr, menu, "_INSTALLED", None)
        with patch.object(menu.subprocess, "run", side_effect=git):
            self.assertEqual(menu.installed(refresh=True), "abc1234 · 12 Jan")
            self.assertEqual(menu.installed(), "abc1234 · 12 Jan")   # read once (v5g): no second call
        self.assertEqual(calls, [["git", "-C", str(config.REPO), "log", "-1", "--format=%h %ct"]])
        # no git, no checkout, or git that will not answer: the title is `agentkit` alone
        failed = subprocess.CompletedProcess([], 128, "", "fatal: not a git repository")
        with patch.object(menu.subprocess, "run", return_value=failed):
            self.assertEqual(menu.installed(refresh=True), "")
        for exc in (OSError("no git"), subprocess.TimeoutExpired("git", 10)):
            with patch.object(menu.subprocess, "run", side_effect=exc):
                self.assertEqual(menu.installed(refresh=True), "")
        with patch.object(menu, "installed", return_value="v1234567890123456789"):
            for version in ("abc1234 · 12 Jan", ""):
                for width in (40, 100):
                    screen = self.draw([], width, version)
                    header = screen.splitlines()[0]
                    # The commit hash leaves the header; the frame is agentkit and the clock.
                    self.assertTrue(header.startswith("agentkit"))
                    self.assertIn("13:05", header)
                    self.assertNotIn("abc1234", header)
                    self.assertNotIn("12 Jan", header)
                    self.assertNotIn("v1234567890123456789", header)
                    self.assertEqual(screen.splitlines()[1],
                                     terminal.rule_line(width if width <= 120 else 120))
        self.assertNotIn("gethostname", (REPO / "agentkit/menu.py").read_text())

    def test_v5c_exhausted_provider_says_zero_left_and_when_it_is_back(self):
        week = self.providers["openai"]["meters"][0]
        week["used"], week["resets_at"] = 100, 24537600     # 12 Oct 1970, a Monday
        for resets in (2, 0):
            # the resets in hand are `ak usage`'s column now, whether there are any or not
            self.providers["openai"]["resets"] = resets
            self.cache()
            for width in (40, 100):
                line = menu.usage_lines(self.cfg, width)[5]
                self.assertRegex(line, r"ChatGPT\s+░+\s+0% left")
                self.assertNotIn("█", line)
                self.assertEqual("resets Mon 00:00" in line, width == 100)
                self.assertNotIn("+2 resets", line)
                self.assertLessEqual(terminal.cells(line), width)

    def test_v5c_read_meter_beside_an_error_keeps_its_bar_and_marks_it(self):
        reason = "unknown: Muse usage probe timed out"
        self.providers["meta"] = {"meters": [self.meter("weekly", 10)], "error": reason}
        self.cache()
        line = menu.usage_lines(self.cfg, 100)[3]
        # the bar stands, and the adapter's own line says why in one place rather than two
        self.assertRegex(line, r"Muse\s+█+░+\s+90% left · resets Sun 00:00 · "
                               r"\? Muse usage probe timed out$")
        # A whole sentence needs room a phone does not have, so it gives way -- but only it:
        # the reset beside it comes back as soon as there is room for it, and the bar, which
        # gives way first, is what makes that room.
        self.assertTrue(menu.usage_lines(self.cfg, 40)[3].endswith("90% left"))
        self.assertTrue(menu.usage_lines(self.cfg, 56)[3].endswith("90% left · resets Sun 00:00"))
        # `ak usage` keeps saying it too, under the table
        providers = {"meta": {"meters": [{**self.meter("weekly", 10), "elapsed": 50, "pace": -40}],
                              "resets": 0, "error": reason}}
        rendered = usage.render(self.cfg, providers, ["spark"])
        self.assertIn(f"note: meta {reason}", rendered)
        self.assertRegex(rendered, r"(?m)^meta +spark +90% ")
        with patch.object(sys.stdout, "isatty", return_value=True), \
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True), \
                patch("curses.setupterm"), patch("curses.tigetnum", return_value=8):
            self.assertIn("\033[1;33m?\033[0m", menu.usage_lines(self.cfg, 100)[3])   # the table's `?`

    def test_v5c_no_reading_is_a_dash_and_why(self):
        cases = ((None, "no reading yet"),
                 ({}, "no reading yet"),
                 ({"meters": [], "error": "unknown: adapter returned no meters"}, "no reading yet"),
                 ({"meters": [], "error": "unknown: muse usage timed out after 30s"}, "not reached"),
                 ({"meters": [], "error": "unknown: codex usage exited 1"}, "not reached"),
                 # `no login` is the `auth` verb's answer and nothing else: an error mentioning
                 # a token, a credential or a 401 is not itself evidence of a logout.
                 ({"meters": [], "error": "unknown: not logged in: Muse auth file is missing",
                   "logged_in": False}, "no login"),
                 ({"meters": [], "error": "unknown: not logged in: Muse auth file is missing"},
                  "not reached"),
                 ({"meters": [], "error": "unknown: could not obtain a Meta credential"},
                  "not reached"),
                 # ... and a probe the endpoint refused says so, with no reading to keep.
                 ({"meters": [], "probe_error": "unknown: HTTP 429 from api.meta.ai"},
                  "rate limited"),
                 ({"meters": [], "probe_error": "unknown: HTTP 502 from api.meta.ai"},
                  "unavailable"),
                 ({"meters": [self.meter("weekly", 40, reset=9000)]}, "window reset"),
                 # a week that rolled over beside one that cannot be read is not a window reset
                 ({"meters": [self.meter("weekly_all", 40, reset=9000),
                              self.meter("weekly_scoped", None)]}, "bad reading"),
                 ({"meters": [], "error": "unknown: every meter the cache reports has already reset"},
                  "window reset"),
                 ({"meters": [self.meter("session", 30, window=18000)]}, "no weekly meter"),
                 ({"meters": [self.meter("weekly", "lots")]}, "bad reading"),
                 ({"meters": [], "error": "unknown: muse reported a meter without a name and a "
                                          "numeric used%"}, "bad reading"))
        for prov, why in cases:
            if prov is None:
                self.providers.pop("meta", None)
            else:
                self.providers["meta"] = prov
            self.cache()
            for width in (40, 100):
                line = menu.usage_lines(self.cfg, width)[3]
                self.assertEqual(line.split(), ["Muse", "—", *why.split()], line)
                self.assertNotRegex(line, "[█░%]")
                self.assertNotIn("old", line)

    def test_v5c_no_row_says_how_old_its_reading_is(self):
        path = self.cache()
        # each row with a timestamp of its own, Muse's fresh beside the others' stale cache
        self.providers["meta"]["fetched_at"] = 10000 - 30
        for fetched in (10000, 10000 - 600, 10000 - 7200, None):
            path.write_text(json.dumps({"fetched_at": fetched, "providers": self.providers}))
            for width in (40, 100):
                lines = menu.usage_lines(self.cfg, width)
                self.assertRegex(lines[1], r"Claude\s+[█░]+\s+21% left")
                self.assertNotRegex("\n".join(lines), r"\bold\b|age unknown", lines)
                self.assertTrue(all(terminal.cells(line) <= width for line in lines), lines)

    def test_v5c_claude_row_is_the_shared_week_and_never_fables_own_cap(self):
        meters = self.providers["anthropic"]["meters"]
        # On 2026-09-20 the account page read 48% used for every model and 59% for Fable, and
        # the menu said `Claude 41% left`: a scoped cap shown as the provider's, which is wrong
        # on its face.  The row is weekly_all; Fable's cap is the note beside it.
        for all_used, scoped_used, left, note in ((48, 59, 52, "Fable 41%"),
                                                  (79, 53, 21, "Fable 47%"),
                                                  (18, 19, 82, "Fable 81%"),
                                                  (60, 100, 40, "Fable 0%")):
            meters[0]["used"], meters[1]["used"] = all_used, scoped_used
            self.cache()
            line = menu.usage_lines(self.cfg, 100)[1]
            self.assertRegex(line, rf"Claude\s+[█░]+\s+{left}% left · resets Sun 00:00 · {note}$")
            # the picker and the table keep ranking on the tightest meter, as they always did
            table = {"anthropic": {"meters": [{**m, "elapsed": 50, "pace": 0} for m in meters]}}
            self.assertEqual(usage.rows(self.cfg, table)[0][2],
                             f"{min(100 - all_used, 100 - scoped_used)}%")
        # a provider whose every readable week is one model's own cap has no shared week at
        # all, and borrowing the cap would be exactly the number the report called wrong
        self.providers["anthropic"]["meters"] = [self.meter("weekly_scoped", 9)]
        self.cache()
        self.assertEqual(menu.usage_lines(self.cfg, 100)[1].split(),
                         ["Claude", "—", "no", "shared", "week"])
        table = {"anthropic": {"meters": [{**self.meter("weekly_scoped", 9),
                                           "elapsed": 50, "pace": 0}]}}
        row = dict(zip(usage.HEADERS, usage.rows(self.cfg, table)[0]))
        self.assertEqual(row["resets"], "-")             # no shared week to name the reset of
        self.assertEqual(row["left"], "91%")             # the picker still ranks on the cap
        # a meter nothing can be drawn from never hides one that can: an expired scoped week
        # at 100% leaves the shared week the row, and a shared week without a number leaves
        # no row at all rather than Fable's cap wearing Claude's name
        for meters, tail, cell in (([self.meter("weekly_scoped", 100, reset=9000),
                                     self.meter("weekly_all", 20)], "80% left · resets Sun 00:00",
                                    "80%"),
                                   ([self.meter("weekly_all", None),
                                     self.meter("weekly_scoped", 53)],
                                    "—  no shared week", "47%"),
                                   ([self.meter("weekly_all", 100, reset=9000),
                                     self.meter("weekly_scoped", 100, reset=9500)],
                                    "—  window reset", "-")):
            self.providers["anthropic"]["meters"] = meters
            self.cache()
            line = menu.usage_lines(self.cfg, 100)[1]
            self.assertTrue(line.endswith(tail), line)
            readable = [{**m, "elapsed": 50, "pace": 0} for m in meters
                        if usage._number(m.get("used")) is not None]
            table = {"anthropic": usage._without_past({"meters": readable}, 10000, "the cache")}
            self.assertEqual(usage.rows(self.cfg, table)[0][2], cell)

    def test_v5c_ak_usage_prints_left_not_used(self):
        def meter(name, used, window=604800):
            return {**self.meter(name, used, window=window), "elapsed": 50, "pace": 0}
        providers = {"anthropic": {"meters": [meter("weekly_all", 79), meter("weekly_scoped", 53),
                                              meter("session", 40, window=18000)], "resets": 0},
                     "openai": {"meters": [meter("weekly", 31)], "resets": 2}}
        rows = [dict(zip(usage.HEADERS, row)) for row in usage.rows(self.cfg, providers)]
        self.assertEqual([(row["left"], row["week elapsed"], row["session"])
                          for row in rows], [("21%", "50%", "60%"), ("69%", "50%", "-")])
        # and the same `resets` the menu row says, off the same shared week
        self.assertEqual([row["resets"] for row in rows], ["Sun 00:00", "Sun 00:00"])
        self.assertEqual([row["resets held"] for row in rows], ["0", "2"])
        for width in (140, 100, 40):
            with patch.object(terminal, "width", return_value=width):
                rendered = usage.render(self.cfg, providers, ["astra", "opus"])
            if width == 40:      # the phone's label/value pairs carry the full heading
                self.assertIn("  left          21%", rendered)
            else:
                self.assertRegex(rendered, r"(?m)^provider +model\(s\) +left +resets ")
            # the split-week detail says what is left too (wrapped on a phone); the gap stays
            # in points of the week
            self.assertIn("weekly_all 21% left, weekly_scoped 47% left, gap 26", " ".join(rendered.split()))
            self.assertIn("fable behind by 26", rendered)
            self.assertNotIn("used", rendered)
            self.assertNotRegex(rendered, r"weekly_(all|scoped) (79|53)%")
            self.assertIn("21%", rendered)
            self.assertIn("69%", rendered)
            self.assertTrue(all(terminal.cells(line) <= width for line in rendered.splitlines()),
                            rendered)

    def test_v5c_notes_give_way_before_the_bar_does_on_a_phone(self):
        self.providers["anthropic"]["error"] = "unknown: claude usage exited 1"
        self.cache()
        # The bar gives way to the notes, down to four cells, and only then do the notes give
        # way -- each on its own, the least worth keeping first, so one note too long for the
        # room never takes a shorter one with it.
        for width, claude, chatgpt, muse in (
                (30, "░   21% left", "░   69% left", "░    0% left"),
                (40, "░   21% left · Fable 47%", "░   69% left", "░    0% left"),
                (56, "░   21% left · resets Sun 00:00", "░   69% left · resets Sun 00:00",
                 "░    0% left · resets Thu 22:00"),
                (100, "░   21% left · resets Sun 00:00 · Fable 47% · ? claude usage exited 1",
                 "░   69% left · resets Sun 00:00",
                 "░    0% left · resets Thu 22:00")):
            lines = menu.usage_lines(self.cfg, width)
            self.assertTrue(all(terminal.cells(line) <= width for line in lines), lines)
            self.assertTrue(lines[1].endswith(claude), lines)
            self.assertTrue(lines[5].endswith(chatgpt), lines)
            self.assertTrue(lines[3].endswith(muse), lines)
            self.assertRegex(lines[1], r"Claude\s+█+░+\s+21% left")


if __name__ == "__main__":
    unittest.main()
