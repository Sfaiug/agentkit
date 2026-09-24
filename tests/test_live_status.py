"""A seat's tmux bar and its menu row say the same thing, within two seconds.

A hook event has the seat looked at again at once, off the harness's path, and the word goes to
the seat's record and its bar through the one writer; an open menu draws again within two
seconds of a record's word moving, off an mtime and never a pane capture.  The bar names the
workers after the orchestrator and is cut to its own length, and an estimate reads in minutes,
hours or days.  Offline: a fake tmux (a callable in-process, a script on PATH for the hook's own
process), fake captures and a throwaway HOME; no tmux server is ever started.
"""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agentkit import config, menu, orch, terminal, watch  # noqa: E402

# The hook's own process asks tmux through PATH, so this stands in for the server: one marked
# seat on the suite's socket, which lives at /fake/agentkit-test, whose pane is %7, a capture as
# slow as $FAKE_TMUX_SLOW, and every option it is told to set written down, `option<TAB>value`.
FAKE_TMUX = r"""#!/bin/bash
socket=
if [[ $1 = -L ]]; then socket=$2; shift 2; fi
case $1 in
  list-sessions) [[ $socket = agentkit-test ]] || exit 1
                 printf 'herdr\t%s\t1\t0\t1\n' "$HOME" ;;
  list-panes) printf 'herdr\t0\n' ;;
  display-message) [[ $4 = %7 ]] && printf '/fake/agentkit-test\therdr\n' ;;
  capture-pane) sleep "${FAKE_TMUX_SLOW:-0}"; printf '$ \n' ;;
  set-option) [[ $2 = -u ]] || printf '%s\t%s\n' "$4" "$5" >>"$FAKE_TMUX_LOG" ;;
esac
exit 0
"""


class LiveStatus(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="live-status-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # laid out the way a process whose HOME this is lays it out, so the hook's own
        # process and this one read and write the same files
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "NO_COLOR": "1", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "TMUX": "/fake/agentkit-test,1,0", "TMUX_PANE": "%7"}))   # the seat's own pane
        for key in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(key, None)    # the tick and the hook's look are no run of the caller's
        home = self.root / ".agentkit"
        self.stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, home / name.lower()))
        self.stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        self.stack.enter_context(patch.object(terminal, "width", return_value=100))
        self.stack.enter_context(patch.object(terminal, "height", return_value=24))
        self.cfg = config.load()
        config.ensure_dirs()
        (config.CODE / "atoll" / ".git").mkdir(parents=True)
        self.repo = str(config.CODE / "atoll")
        self.seat = {"name": "herdr", "path": self.repo, "created": time.time() - 600,
                     "attached": False, "exited": False, "legacy": False, "resumable": False}
        config.save_session(self.cfg, "herdr", "opus", ["opus", "astra"],
                            {"repo": self.repo, "cwd": self.repo})
        self.options = {}
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(orch, "sessions",
                                              side_effect=lambda: [dict(self.seat)]))
        self.pane = self.stack.enter_context(patch.object(watch, "pane_text",
                                                          return_value="$ "))

    def tmux(self, *args, **kwargs):
        if args[0] == "display-message":
            return ((0, f"/fake/agentkit-test\t{self.seat['name']}")
                    if args[args.index("-t") + 1] == "%7" else (1, "no such pane"))
        if args[0] == "set-option" and "-u" not in args:
            self.options[args[args.index("-t") + 2]] = args[-1]
        return 0, ""

    def hook(self, event, kind=""):
        """What hooks/seat-state.sh writes down for that event."""
        config.hook_facts_path("herdr").write_text(json.dumps(
            {"session": "herdr", "event": event, "kind": kind, "text": "", "at": time.time()}))

    def plan(self, done, total):
        config.plan_path("herdr").write_text(
            "".join(["- [x] done\n"] * done + ["- [ ] todo\n"] * (total - done)))

    def row(self):
        """The seat's row as the menu's next draw would put it, and its values."""
        info = menu.v5o_seat_info(self.cfg, 1, dict(self.seat, repo=self.repo),
                                  menu.run_records(), {}, {}, time.time())
        return info, terminal.plain(menu.v5o_format_seats([info], 100)[0])

    # --- one answer, fast --------------------------------------------------------

    def test_a_hook_event_rewrites_the_bar_with_no_menu_open(self):
        if not shutil.which("jq"):
            self.skipTest("the hook needs jq")
        fake = self.root / "bin" / "tmux"
        fake.parent.mkdir()
        fake.write_text(FAKE_TMUX)
        fake.chmod(0o755)
        log = self.root / "tmux.log"
        env = {key: value for key, value in os.environ.items()
               if key not in ("AK_RUN_ROLE", "NO_COLOR")}
        env.update({"PATH": f"{fake.parent}:{os.environ['PATH']}", "AGENTKIT_SESSION": "herdr",
                    "FAKE_TMUX_LOG": str(log), "FAKE_TMUX_SLOW": "3"})

        def hook(payload):
            began = time.monotonic()
            subprocess.run(["bash", str(REPO / "hooks/seat-state.sh")], input=json.dumps(payload),
                           env=env, text=True, capture_output=True, timeout=30, check=True)
            return time.monotonic() - began

        def sets():
            # whole lines only: the look may be in the middle of writing the last one
            text = log.read_text(encoding="utf-8") if log.exists() else ""
            return [line.split("\t", 1) for line in text.split("\n")[:-1]]

        def published(word):
            """The bar, once the look has published that word on it."""
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                options = dict(sets())
                if options.get("set-titles-string") == f"herdr · {word}":
                    return options
                time.sleep(0.05)
            self.fail(f"the bar never said {word!r}: {sets()}")

        # a turn begins: the look takes three seconds of capture, and the hook waits on none
        self.assertLess(hook({"hook_event_name": "UserPromptSubmit", "prompt": "go"}), 2.0)
        options = published("working")
        self.assertEqual(options["status-left"], " herdr · opus → opus astra · ● working ")
        self.assertEqual(options[orch.STATE_OPTION], "working")
        self.assertEqual(watch.seat_read("herdr")["word"], "working")
        # Claude's Stop is written down by hooks/orchestrator-stop.sh, beside this hook, in
        # whichever order the two finish: that one first, and the look publishes it at once
        env["FAKE_TMUX_SLOW"] = "0"
        self.hook("Stop")
        began = time.monotonic()
        hook({"hook_event_name": "Stop", "background_tasks": []})
        published("needs you")
        self.assertLess(time.monotonic() - began, 3.0)      # and never waits HOOK_LOOK_WAIT
        hook({"hook_event_name": "UserPromptSubmit", "prompt": "go"})
        published("working")
        # ... or this one first: the seat is as it was until that one's word lands, then it moves
        hook({"hook_event_name": "Stop", "background_tasks": []})
        time.sleep(1)
        self.assertEqual(dict(sets())["set-titles-string"], "herdr · working")
        self.hook("Stop")
        options = published("needs you")
        self.assertTrue(options["status-left"].startswith(
            " herdr · opus → opus astra · ! needs you"), options["status-left"])
        self.assertEqual(watch.seat_read("herdr")["word"], "needs you")

    def test_a_hook_outside_the_seat_s_own_pane_moves_no_bar(self):
        # a harness under some other tmux, or a sandbox that borrowed a seat's name, is not
        # that seat, and its facts are not the seat's either -- a pane with the seat's own id on
        # another server included
        self.hook("UserPromptSubmit")
        for outside in ({"TMUX_PANE": ""}, {"TMUX_PANE": "%8"}, {"TMUX": ""},
                        {"TMUX": "/tmp/tmux-1000/default,4242,0"}):
            with self.subTest(outside=outside), patch.dict(os.environ, outside):
                self.assertIsNone(watch.hook_look("herdr"))
        self.assertEqual(self.options, {})
        self.assertEqual(watch.seat_read("herdr"), {})
        self.assertEqual(watch.hook_look("herdr")["word"], "working")   # ... and from its own
        self.assertIn("● working", self.options["status-left"])

    def test_an_open_menu_draws_again_within_two_seconds_of_a_record_changing(self):
        self.hook("Stop")
        watch.hook_look("herdr")                       # at its prompt, and recorded so
        screens, out, woke, captures = [], io.StringIO(), [], []

        def flip():
            # another process's look: the seat's record and its bar move under the open menu
            self.hook("UserPromptSubmit")
            watch.hook_look("herdr")

        def touch():
            # ... or its record changes where no row looks
            watch.seat_write("herdr", evidence="something new on its screen")

        def news(change):
            def answer(wake):
                time.sleep(menu.STIR + 0.2)             # whatever the last draw stirred has landed
                try:
                    os.read(wake, 4096)
                except BlockingIOError:
                    pass
                change()
                began = time.monotonic()
                woke.append((bool(select.select([wake], [], [], 2)[0]), time.monotonic() - began))
                return None
            return answer

        answers = iter([news(flip), news(touch), lambda wake: "q"])

        def wait_key(prompt, timeout=None, wake=None):
            self.assertEqual(timeout, menu.TICK)
            screens.append(terminal.plain(out.getvalue()))
            captures.append(self.pane.call_count)
            out.seek(0)
            out.truncate()
            return next(answers)(wake)

        with patch.object(orch, "listing",
                          side_effect=lambda *a, **k: [dict(self.seat, repo=self.repo)]), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu.Live, "probe", return_value=False), \
                patch.object(menu, "wait_key", side_effect=wait_key), \
                redirect_stdout(out):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        for ready, waited in woke:
            self.assertTrue(ready, "the menu was never woken")
            self.assertLess(waited, 2.0)
        # the flip's own look captured the one pane; the draws the news asked for, none
        self.assertEqual(captures, [captures[0], captures[0] + 1, captures[0] + 1])
        rows = [[line for line in screen.splitlines() if " herdr " in line] for screen in screens]
        self.assertIn("! needs you", rows[0][0])
        self.assertIn("● working", rows[1][0])          # the recorded word
        self.assertIn("● working", rows[2][0])

    def test_an_older_look_never_lands_on_the_bar_after_a_newer_one(self):
        # a menu's look decides on what it read; the turn ends and the seat's own hook publishes
        # that; the menu's older answer must not reach the bar after it
        self.hook("UserPromptSubmit")
        decided, release, real = threading.Event(), threading.Event(), menu.redress

        def redress(session, answer, **kwargs):
            if not decided.is_set():
                decided.set()
                release.wait(5)
            return real(session, answer, **kwargs)

        with patch.object(menu, "redress", side_effect=redress):
            older = threading.Thread(target=menu.seat_row_state,
                                     args=(self.cfg, dict(self.seat, repo=self.repo)))
            older.start()
            self.assertTrue(decided.wait(5))            # `working`, not on the bar yet
            self.hook("Stop")
            newer = threading.Thread(target=watch.hook_look, args=("herdr",))
            newer.start()
            newer.join(0.5)
            self.assertTrue(newer.is_alive())           # it waits for the older one to finish
            release.set()
            older.join(5)
            newer.join(5)
        self.assertEqual(watch.seat_read("herdr")["word"], "needs you")
        self.assertIn("! needs you", self.options["status-left"])
        self.assertEqual(self.options[orch.STATE_OPTION], "needs you")

    def test_the_tick_s_older_look_never_lands_after_the_hook_s(self):
        # the tick reads the seat mid-turn; the turn ends and the seat's own hook publishes that
        # before the tick has written down what it read
        self.hook("UserPromptSubmit")
        decided, release, real = threading.Event(), threading.Event(), watch.classify

        def classify(*args, **kwargs):
            found = real(*args, **kwargs)
            if threading.current_thread().name == "tick" and not decided.is_set():
                decided.set()
                release.wait(5)
            return found

        with patch.object(watch, "classify", side_effect=classify), \
                patch.object(watch, "seat_model", return_value=("claude", "anthropic")), \
                patch.object(watch, "type_into", return_value=True), \
                patch.object(watch.notify, "shaped", return_value=0), \
                patch.object(watch, "spend_reset"), \
                patch.object(watch, "window_ends", return_value=None):
            tick = threading.Thread(target=watch.health, name="tick", daemon=True,
                                    args=({}, watch.load_state(), False, lambda _line: None))
            tick.start()
            self.assertTrue(decided.wait(5))            # `working`, not written down yet
            self.hook("Stop")
            hook = threading.Thread(target=watch.hook_look, args=("herdr",), daemon=True)
            hook.start()
            hook.join(0.5)
            self.assertTrue(hook.is_alive())            # it waits for the tick's look to land
            release.set()
            tick.join(10)
            hook.join(10)
        self.assertEqual(watch.seat_read("herdr")["word"], "needs you")
        self.assertEqual(self.options[orch.STATE_OPTION], "needs you")

    def test_a_capture_that_hangs_holds_up_no_draw(self):
        # a second seat whose screen takes its time: the menu still draws at once, and draws
        # again within two seconds of the first seat's word moving, with the look at it going on
        config.save_session(self.cfg, "tern", "opus", ["astra"],
                            {"repo": self.repo, "cwd": self.repo})
        seats = [dict(self.seat, repo=self.repo), dict(self.seat, name="tern", repo=self.repo)]
        release = threading.Event()

        def capture(session):
            if session["name"] == "tern":
                release.wait(10)
            return "$ "

        self.pane.side_effect = capture
        self.hook("Stop")
        began, drawn, woke, screens, out = time.monotonic(), [], [], [], io.StringIO()

        def flip(wake):
            self.hook("UserPromptSubmit")
            watch.hook_look("herdr")
            at = time.monotonic()
            woke.append((bool(select.select([wake], [], [], 2)[0]), time.monotonic() - at))
            return None

        def leave(wake):
            release.set()
            return "q"

        answers = iter([flip, leave])

        def wait_key(prompt, timeout=None, wake=None):
            drawn.append(time.monotonic() - began)
            screens.append(terminal.plain(out.getvalue()))
            out.seek(0)
            out.truncate()
            return next(answers)(wake)

        with patch.object(orch, "listing", side_effect=lambda *a, **k: [dict(s) for s in seats]), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu.Live, "probe", return_value=False), \
                patch.object(menu, "wait_key", side_effect=wait_key), \
                redirect_stdout(out):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        self.assertLess(drawn[0], 2.0)                  # the first draw waited LOOK_WAIT at most
        self.assertEqual([ready for ready, _ in woke], [True])
        self.assertLess(woke[0][1], 2.0)
        rows = [[line for line in screen.splitlines() if " herdr " in line] for screen in screens]
        self.assertIn("! needs you", rows[0][0])
        self.assertIn("● working", rows[1][0])

    def test_the_menu_s_looks_use_the_config_the_c_screen_saved(self):
        # a model added on `c` and a seat started with it: the next background look resolves
        # that model, and keeps the seat's word and its workers on the record and the bar
        captures = []

        def add(wake):
            cfg = config.load()
            cfg["models"]["sonnet"] = dict(cfg["models"]["opus"])
            config.save(cfg)
            return "c"

        def start(wake):
            config.save_session(config.load(), "herdr", "sonnet", ["sonnet", "astra"],
                                {"repo": self.repo, "cwd": self.repo})
            self.hook("UserPromptSubmit")
            self.assertEqual(watch.hook_look("herdr")["word"], "working")
            time.sleep(menu.STIR + 0.2)                 # the record's news has landed ...
            try:
                os.read(wake, 4096)                     # ... and is taken, so the clock looks
            except BlockingIOError:
                pass
            captures.append(self.pane.call_count)
            return None

        def leave(wake):
            captures.append(self.pane.call_count)
            return "q"

        answers = iter([add, start, leave])
        with patch.object(orch, "listing",
                          side_effect=lambda *a, **k: [dict(self.seat, repo=self.repo)]), \
                patch.object(orch, "job_notices", return_value=[]), \
                patch.object(menu.Live, "probe", return_value=False), \
                patch.object(menu, "LOOK_WAIT", 10), \
                patch.object(menu, "wait_key",
                             side_effect=lambda prompt, timeout=None, wake=None:
                             next(answers)(wake)), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(menu.loop(self.cfg, dry_run=True), 0)
        self.assertEqual(watch.seat_read("herdr")["word"], "working")
        self.assertEqual(self.options["status-left"], " herdr · sonnet → sonnet astra · ● working ")
        self.assertEqual(self.options[orch.STATE_OPTION], "working")
        self.assertEqual(captures[1], captures[0] + 1)  # the background look came round

    def test_a_renamed_seat_s_own_hooks_still_move_its_row_and_bar(self):
        # the harness keeps the name it was launched with; the seat's records moved with it
        if not shutil.which("jq"):
            self.skipTest("the hook needs jq")
        config.rename_session("herdr", "tern")
        self.seat["name"] = "tern"
        env = {"PATH": os.environ["PATH"], "HOME": str(self.root), "AGENTKIT_SESSION": "herdr",
               "AK_RUN_ROLE": "orchestrator"}

        def hook(script, payload):
            subprocess.run(["bash", str(REPO / "hooks" / script)], input=json.dumps(payload),
                           env=env, text=True, capture_output=True, timeout=30, check=True)

        hook("seat-state.sh", {"hook_event_name": "UserPromptSubmit", "prompt": "go"})
        self.assertEqual(watch.hook_facts("tern")["event"], "UserPromptSubmit")
        self.assertEqual(watch.hook_look("herdr")["word"], "working")
        hook("orchestrator-stop.sh", {"hook_event_name": "Stop", "background_tasks": []})
        self.assertEqual(watch.hook_facts("tern")["event"], "Stop")
        self.assertEqual(watch.hook_look("herdr")["word"], "needs you")
        self.assertIn(" tern · opus → opus astra · ! needs you", self.options["status-left"])

    def test_the_row_and_the_bar_say_the_same_after_a_flip(self):
        self.plan(4, 8)
        for event, word in (("UserPromptSubmit", "working"), ("Stop", "needs you"),
                            ("UserPromptSubmit", "working")):
            with self.subTest(event=event):
                self.hook(event)
                watch.hook_look("herdr")                # the flip, from the seat's own hook
                bar = self.options["status-left"]
                info, row = self.row()                  # ... and the menu's next draw
                self.assertEqual(info["word"], word)
                self.assertEqual(watch.seat_read("herdr")["word"], word)
                self.assertIn(terminal.state_text(word), row)
                # the bar is the row's own values, word and last column alike
                self.assertEqual(bar, orch.bar("herdr", "opus", info["word"], menu._last_text(info),
                                               ["opus", "astra"])[0])
                self.assertEqual(self.options[orch.STATE_OPTION], word)
                self.assertEqual(self.options["set-titles-string"], f"herdr · {word}")

    # --- the bar names the workers ------------------------------------------------

    def test_the_bar_names_the_workers(self):
        self.assertEqual(
            orch.bar("ak-verification", "opus", "working", "tasks ████░░░░ 4/8",
                     ["opus", "astra"])[0],
            " ak-verification · opus → opus astra · ● working · tasks ████░░░░ 4/8 ")
        # through the one writer, from the session record's workers
        self.plan(4, 8)
        menu.redress(dict(self.seat, repo=self.repo), {"word": "working", "reason": "", "since": None},
                     cfg=self.cfg, records=[])
        self.assertEqual(self.options["status-left"],
                         f" herdr · opus → opus astra · ● working · tasks {terminal.progress_bar(4, 8)} ")
        # before its first word a seat's bar is who is in it, as it always was
        self.assertEqual(orch.bar("herdr", "opus")[0], " herdr · opus ")
        with patch.dict(os.environ, {"LANG": "C"}):
            os.environ.pop("LC_ALL")
            self.assertEqual(orch.bar("herdr", "opus", None, "", ["astra"])[0],
                             " herdr · opus -> astra ")

    def test_the_bar_is_cut_to_its_length_and_never_mid_glyph(self):
        # two cells a glyph, so a cut at an odd column would halve one, and `#`s that tmux
        # reads doubled and shows once
        reason = "#1 漢字" * 40
        left, _, _ = orch.bar("herdr", "opus", "needs you", reason, ["opus", "astra"])
        shown = left.replace("##", "#")
        self.assertLessEqual(terminal.cells(shown), orch.BAR_LEFT)
        # cut at the length, or at a word boundary at most four columns before it
        self.assertGreaterEqual(terminal.cells(shown), orch.BAR_LEFT - 6)
        self.assertTrue(shown.startswith(" herdr · opus → opus astra · ! needs you · #1 漢字"))
        self.assertTrue(shown.endswith("… "), shown)
        # and tmux is told that same length, so it never cuts one of its own
        orch.dress("herdr", "opus")
        self.assertEqual(self.options["status-left-length"], str(orch.BAR_LEFT))
        # a bar that fits is left whole
        self.assertEqual(orch.bar("herdr", "opus", "done", "shipped", ["astra"])[0],
                         f" herdr · opus → astra · {terminal.state_text('done')} · shipped ")

    # --- estimates read in human units --------------------------------------------

    def test_an_estimate_reads_in_minutes_hours_or_days(self):
        session = {"repo": self.repo}
        # seconds a task, tasks done of all -- and what is left of the plan reads
        for seconds, done, total, text in ((900, 5, 8, "~45m left"),
                                           (3600, 3, 8, "~5h left"),
                                           (34500, 3, 8, "~48h left"),    # under two days
                                           (34560, 3, 8, "~2d left"),     # two days
                                           (775800, 4, 8, "~36d left")):  # was ~51720m left
            with self.subTest(text=text), \
                    patch.object(menu.history, "estimate_seconds", return_value=seconds):
                self.assertEqual(menu.seat_estimate("herdr", session=session,
                                                    job=(done, total, "")), text)
        # in the row and on the bar alike
        self.plan(3, 8)
        self.hook("UserPromptSubmit")
        with patch.object(menu.history, "estimate_seconds", return_value=3600):
            _, row = self.row()
        self.assertIn(f"tasks {terminal.progress_bar(3, 8)} · ~5h left", row)
        self.assertIn(f"tasks {terminal.progress_bar(3, 8)} · ~5h left", self.options["status-left"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
