"""The menu is live: it draws from the cache at once, probes behind the draw, and comes round
on its own clock.  And the usage row it draws is the provider's shared week, when that week
resets, a scoped cap only where it differs, and why a probe failed; offline, no adapter runs.
"""

from contextlib import redirect_stdout
import io
import json
import os
import select
import sys
import threading
import time
from unittest.mock import patch
import unittest

from test_v4n import REPO, Sandbox
from agentkit import config, menu, terminal, usage

NOW = 10000                 # the clock the Sandbox pins; 1970-01-01 02:46:40 UTC, a Thursday
RESETS_AT = 136800          # 1970-01-02 14:00:00 UTC -> `resets Fri 14:00`
LATER = 205200              # 1970-01-03 09:00:00 UTC -> `resets Sat 09:00`
WEEK = 604800


class LiveMenu(Sandbox):
    def setUp(self):
        super().setUp()
        # Local time is UTC here, so a pinned reset timestamp reads the same on every machine.
        self.stack.enter_context(patch.object(menu.time, "localtime", side_effect=time.gmtime))
        self.stack.enter_context(patch.object(menu.orch, "listing", return_value=[]))
        self.stack.enter_context(patch.object(menu.orch, "job_notices", return_value=[]))
        self.stack.enter_context(patch.object(terminal, "width", return_value=100))
        self.cache(self.providers())

    def meter(self, name, used, resets_at=RESETS_AT, window=WEEK, **extra):
        return {"name": name, "used": used, "resets_at": resets_at,
                "window_secs": window, **extra}

    def providers(self, **replace):
        found = {"anthropic": {"meters": [self.meter("weekly_all", 48),
                                          self.meter("weekly_scoped", 59)]},
                 "openai": {"meters": [self.meter("weekly", 31)], "resets": 2},
                 "meta": {"meters": [self.meter("weekly", 10)]}}
        found.update(replace)
        return found

    def cache(self, providers, fetched_at=NOW):
        (config.STATE / "usage.json").write_text(
            json.dumps({"fetched_at": fetched_at, "providers": providers}))

    def rows(self, width=100):
        return [terminal.plain(line) for line in menu.usage_lines(self.cfg, width)]

    def run_menu(self, answers, collect=None):
        """`menu.loop` driven by a scripted read; returns the screen drawn before each answer.

        Each entry of `answers` is called with the wake fd the loop is waiting on and returns
        what `wait_key` would: a key, or None for a wait that ended with nothing typed.
        """
        screens, out = [], io.StringIO()
        script = iter(answers)

        def wait_key(prompt, timeout=None, wake=None):
            self.assertEqual(timeout, menu.TICK)   # the main screen never waits longer
            screens.append(out.getvalue())
            out.seek(0)
            out.truncate()
            return next(script)(wake)

        with patch.object(menu, "wait_key", side_effect=wait_key), \
                patch.object(sys.stdin, "isatty", return_value=True), \
                patch.object(menu.usage, "collect",
                             side_effect=collect or (lambda cfg, **kw: {})), \
                redirect_stdout(out):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        return [terminal.plain(screen) for screen in screens]

    # --- live -------------------------------------------------------------

    def test_the_first_draw_is_the_cache_and_never_waits_for_the_probe(self):
        release, done = threading.Event(), threading.Event()
        waited = []

        def collect(cfg, **kwargs):
            release.wait(5)
            done.set()
            return {}

        def quit_now(wake):
            waited.append(done.is_set())
            release.set()
            return "q"

        screens = self.run_menu([quit_now], collect)
        self.assertTrue(done.wait(5))          # and the probe still ran, behind the draw
        self.assertEqual(waited, [False])      # the screen was up before the probe answered
        self.assertRegex(screens[0], r"Claude\s+[█░]+\s+52% left")

    def test_the_probe_landing_draws_again_with_the_meters_it_wrote(self):
        def collect(cfg, **kwargs):
            self.cache(self.providers(anthropic={"meters": [self.meter("weekly_all", 70),
                                                            self.meter("weekly_scoped", 70)]}))
            return {}

        def woken(wake):
            # The probe writes to this pipe when it lands, which is what ends the wait.
            self.assertEqual(select.select([wake], [], [], 5)[0], [wake])
            return None

        screens = self.run_menu([woken, lambda wake: "q"], collect)
        self.assertRegex(screens[0], r"Claude\s+[█░]+\s+52% left")
        self.assertRegex(screens[1], r"Claude\s+[█░]+\s+30% left")

    def test_a_wait_that_times_out_draws_again_and_the_clock_moves(self):
        clocks = iter(["14:02", "14:03"])
        real = time.strftime

        def strftime(fmt, *args):
            return next(clocks) if fmt == "%H:%M" and not args else real(fmt, *args)

        with patch.object(menu.time, "strftime", side_effect=strftime):
            screens = self.run_menu([lambda wake: None, lambda wake: "q"])
        self.assertIn("14:02", screens[0].splitlines()[0])
        self.assertIn("14:03", screens[1].splitlines()[0])
        for screen in screens:
            self.assertIn("usage left", screen)
            self.assertIn("no sessions; n starts one", screen)

    def test_a_key_typed_during_a_draw_is_read_by_the_next_wait(self):
        class Keyboard(io.TextIOWrapper):
            def isatty(self):
                return True

        reader, writer = os.pipe()
        self.addCleanup(os.close, writer)
        keyboard = Keyboard(open(reader, "rb", buffering=0))
        self.addCleanup(keyboard.close)
        live = menu.Live(self.cfg)
        self.addCleanup(live.close)
        os.write(writer, b"9\n")        # typed while the screen was being redrawn
        os.write(live.writer, b".")     # and a probe landed in the same moment
        with patch.object(sys, "stdin", keyboard), redirect_stdout(io.StringIO()):
            self.assertEqual(menu.wait_key("> ", menu.TICK, live.reader), "9")
            # Nothing typed and only the probe waiting: the wait ends for the draw's sake.
            self.assertIsNone(menu.wait_key("> ", 0.2, live.reader))

    def test_the_wait_is_bounded_on_a_pipe_as_well_as_a_keyboard(self):
        """Nothing typed must not stop the clock, and what stdin is makes no difference."""
        reader, writer = os.pipe()
        self.addCleanup(os.close, writer)
        pipe = os.fdopen(reader)
        self.addCleanup(pipe.close)
        self.addCleanup(setattr, terminal, "_HALF_TYPED", b"")
        self.assertFalse(pipe.isatty())     # a script, a smoke suite, a harness: not a keyboard
        began = time.monotonic()
        with patch.object(sys, "stdin", pipe), redirect_stdout(io.StringIO()):
            self.assertIsNone(menu.wait_key("> ", 0.3))
            self.assertLess(time.monotonic() - began, 5)   # the wait ended on its own clock
            os.write(writer, b"x\n")       # and a whole line waiting is answered at once
            self.assertEqual(menu.wait_key("> ", menu.TICK), "x")
        # A stdin with no descriptor at all -- a StringIO under a test -- still answers.
        with patch.object(sys, "stdin", io.StringIO("q\n")), redirect_stdout(io.StringIO()):
            self.assertEqual(menu.wait_key("> ", menu.TICK), "q")

    def test_half_a_line_on_a_pipe_stops_neither_the_clock_nor_the_key(self):
        """A writer that pauses mid-line must not outlast the wait, or lose what it wrote."""
        reader, writer = os.pipe()
        shut = []
        self.addCleanup(lambda: shut or os.close(writer))
        pipe = os.fdopen(reader)
        self.addCleanup(pipe.close)
        self.addCleanup(setattr, terminal, "_HALF_TYPED", b"")
        os.write(writer, b"1")              # a key typed but not yet entered
        began = time.monotonic()
        with patch.object(sys, "stdin", pipe), redirect_stdout(io.StringIO()):
            # the wait ends on its own clock, not when the writer gets round to the newline
            self.assertIsNone(menu.wait_key("> ", 0.3))
            self.assertLess(time.monotonic() - began, 5)
            self.assertEqual(terminal._HALF_TYPED, b"1")   # and what was typed is still typed
            os.write(writer, b"2\n")        # the rest of it, after however many redraws
            self.assertEqual(menu.wait_key("> ", menu.TICK), "12")
            self.assertEqual(terminal._HALF_TYPED, b"")
            # a writer that closes mid-line has said its piece; a closed one says `q`
            os.write(writer, b"n")
            os.close(writer)
            shut.append(True)
            self.assertEqual(menu.wait_key("> ", menu.TICK), "n")
            self.assertEqual(menu.wait_key("> ", menu.TICK), "q")

    def test_a_line_a_sub_screen_read_never_strands_the_key_behind_it(self):
        """One reader, or a buffered question swallows the next key and the screen spins."""
        reader, writer = os.pipe()
        self.addCleanup(os.close, writer)
        pipe = os.fdopen(reader)
        self.addCleanup(pipe.close)
        self.addCleanup(setattr, terminal, "_HALF_TYPED", b"")
        # a key, the answer to the question it opened, and the key after it, all at once
        os.write(writer, b"x\n1\nq\n")
        began = time.monotonic()
        with patch.object(sys, "stdin", pipe), redirect_stdout(io.StringIO()):
            self.assertEqual(menu.wait_key("> ", menu.TICK), "x")
            self.assertEqual(menu.read("which? ", ""), "1")        # the sub-screen's question
            self.assertEqual(terminal.ask("Stop", "a", ["a", "b"], read=menu.read), None)
            os.write(writer, b"q\n")
            self.assertEqual(menu.wait_key("> ", menu.TICK), "q")  # not stranded in a buffer
        self.assertLess(time.monotonic() - began, 5)
        # and `orch` asks its own questions through the same reader, for the same reason
        self.assertNotIn("input(", (REPO / "agentkit/orch.py").read_text())
        self.assertEqual((REPO / "agentkit/menu.py").read_text().count("input("), 0)

    def test_a_name_with_an_accent_in_it_survives_the_pipe_that_typed_it(self):
        """The gathering is in bytes: half of an `é` is not a character, and not a `?` either."""
        reader, writer = os.pipe()
        self.addCleanup(os.close, writer)
        pipe = os.fdopen(reader)
        self.addCleanup(pipe.close)
        self.addCleanup(setattr, terminal, "_HALF_TYPED", b"")
        name = "café · Größenänderung · 日本語"
        with patch.object(sys, "stdin", pipe), redirect_stdout(io.StringIO()):
            os.write(writer, name.encode() + b"\n")
            self.assertEqual(menu.read("Project: ", ""), name)      # a sub-screen's question
            os.write(writer, name.encode() + b"\n")
            self.assertEqual(menu.wait_key("> ", menu.TICK), name)  # and the main screen's
            # and a character the clock lands in the middle of is still that character
            raw = "café".encode()
            os.write(writer, raw[:4])          # `caf` and the first byte of the `é`
            self.assertIsNone(menu.wait_key("> ", 0.3))
            self.assertEqual(terminal._HALF_TYPED, raw[:4])
            os.write(writer, raw[4:] + b"\n")
            self.assertEqual(menu.wait_key("> ", menu.TICK), "café")

    def test_the_probe_runs_once_a_probe_window_and_never_twice_at_once(self):
        calls, release = [], threading.Event()

        def collect(cfg, **kwargs):
            calls.append(kwargs.get("refresh"))
            release.wait(5)
            return {}

        live = menu.Live(self.cfg)
        self.addCleanup(live.close)
        with patch.object(menu.usage, "collect", side_effect=collect), \
                patch.object(sys.stdin, "isatty", return_value=True):
            self.assertTrue(live.probe(NOW))
            self.assertFalse(live.probe(NOW))                      # one is already running
            release.set()
            live.thread.join(5)
            # The screen's clock is the host's cadence, once a minute: every open menu on the
            # box shares one probe with the tick and with `ak usage`.
            self.assertEqual(live.every, 60)
            self.assertFalse(live.probe(NOW + usage.PROBE_EVERY - 1))
            self.assertTrue(live.probe(NOW + usage.PROBE_EVERY))
            live.thread.join(5)
        self.assertEqual(calls, [True, True])   # always a refresh: the cache is the first draw
        # And a menu nobody is sitting at -- a script, a pipe, the smoke suite -- probes nothing.
        self.assertFalse(live.probe(NOW + 2 * usage.PROBE_EVERY))

    # --- the row ----------------------------------------------------------

    def test_the_row_is_the_shared_week_and_says_when_it_resets(self):
        # weekly_all is what every Claude model draws on; weekly_scoped is Fable's own cap,
        # and its 41% is never the provider's number.
        self.assertRegex(self.rows()[1], r"Claude\s+[█░]+\s+52% left · resets Fri 14:00")
        self.assertRegex(self.rows()[5], r"ChatGPT\s+[█░]+\s+69% left · resets Fri 14:00")
        # A meter that names no moment but says how long it has to run says that instead.
        self.cache(self.providers(openai={"meters": [{"name": "weekly", "used": 31,
                                                      "window_secs": WEEK,
                                                      "resets_in": 3 * 86400}]}))
        self.assertIn("69% left · resets in 3d", self.rows()[5])
        # `ak usage` keeps the columns that left the menu, and its `resets` is the row's:
        # the shared week's, even when the tightest meter it ranks on resets at another hour.
        meters = [self.meter("weekly_all", 48),
                  self.meter("weekly_scoped", 59, resets_at=LATER)]
        self.cache(self.providers(anthropic={"meters": meters}))
        table = {"anthropic": {"meters": [{**m, "elapsed": 50, "pace": 0} for m in meters],
                               "resets": 2}}
        row = dict(zip(usage.HEADERS, usage.rows(self.cfg, table)[0]))
        self.assertIn("52% left · resets Fri 14:00 · Fable 41%", self.rows()[1])
        self.assertEqual(row["resets"], "Fri 14:00")     # and never the scoped week's Sat 09:00
        self.assertEqual(row["left"], "41%")             # the picker still reads the tightest
        # Everything else the table knows stays in the table, the resets in hand among them.
        for kept in ("week elapsed", "session", "resets held", "headroom", "budget", "outlook"):
            self.assertIn(kept, usage.HEADERS)
        self.assertEqual(row["resets held"], "2")
        self.assertNotRegex("\n".join(self.rows()),
                            r"elapsed|headroom|budget|outlook|\+2 resets")

    def test_a_scoped_cap_that_differs_is_its_own_note(self):
        self.assertIn("52% left · resets Fri 14:00 · Fable 41%", self.rows()[1])
        # The same figure twice says nothing the row has not said: no note.
        self.cache(self.providers(anthropic={"meters": [self.meter("weekly_all", 48),
                                                        self.meter("weekly_scoped", 48)]}))
        self.assertIn("52% left · resets Fri 14:00", self.rows()[1])
        self.assertNotIn("Fable", self.rows()[1])
        # A provider whose only readable week is one model's own cap has no shared week to
        # show, and borrowing the cap would be the very number the owner's report called
        # wrong: the row says so instead, and carries no percentage at all.
        self.cache(self.providers(anthropic={"meters": [self.meter("weekly_scoped", 9)]}))
        self.assertEqual(self.rows()[1].split(), ["Claude", "—", "no", "shared", "week"])
        self.assertNotRegex(self.rows()[1], "91|Fable|[█░]")

    def test_a_failed_probe_keeps_its_bar_and_says_why(self):
        self.cache(self.providers(meta={"meters": [self.meter("weekly", 10)],
                                        "error": "unknown: muse usage timed out after 30s"}))
        self.assertIn("90% left · resets Fri 14:00 · ? muse usage timed out after 30s",
                      self.rows()[3])
        with patch.object(sys.stdout, "isatty", return_value=True), \
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True), \
                patch("curses.setupterm"), patch("curses.tigetnum", return_value=8):
            self.assertIn("\033[1;33m?\033[0m", menu.usage_lines(self.cfg, 100)[3])
        # With no meter to draw at all the row is still `—` and the words that say why -- and
        # `no login` comes from the `auth` verb the probe asked, never from the error's wording.
        self.cache(self.providers(meta={"meters": [], "error": "unknown: not logged in",
                                        "logged_in": False}))
        self.assertEqual(self.rows()[3].split(), ["Muse", "—", "no", "login"])
        self.cache(self.providers(meta={"meters": [], "error": "unknown: not logged in"}))
        self.assertEqual(self.rows()[3].split(), ["Muse", "—", "not", "reached"])
        # A probe the endpoint refused keeps the reading it could not replace, and says which of
        # the two ways it was refused rather than blaming the login.
        self.cache(self.providers(meta={"meters": [self.meter("weekly", 10)], "error": None,
                                        "probe_error": "unknown: HTTP 429 from api.example",
                                        "stale_since": NOW - 60}))
        self.assertIn("90% left · resets Fri 14:00 · rate limited", self.rows()[3])
        self.assertNotIn("no login", self.rows()[3])

    def test_no_reading_carries_an_age(self):
        # The readings are kept current instead: no row and no heading says how old one is,
        # however old the cache is.
        for late in (0, 599, 600, 2 * 3600):
            self.cache(self.providers(), fetched_at=NOW - late)
            self.assertNotIn("old", "\n".join(self.rows()))
            self.assertEqual(self.rows()[0], "usage left")


if __name__ == "__main__":
    unittest.main()
