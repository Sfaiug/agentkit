"""Exact babysitter, attach coordination, and phone runs regressions; stdlib and offline."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, watch


class Babysitter(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v4l-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {"AGENTKIT_TMUX_SOCKET": "agentkit-test"}))
        self.now = 10000
        self.stack.enter_context(patch.object(watch.time, "time", lambda: self.now))
        self.seats = [{"name": "seat"}]
        self.stack.enter_context(patch.object(orch, "sessions", lambda: self.seats))
        self.harness, self.provider = "claude", "anthropic"
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              lambda *_: (self.harness, self.provider)))
        self.tail = "API Error: 500"
        self.stack.enter_context(patch.object(watch, "pane_text", lambda _: self.tail))
        self.typed = self.stack.enter_context(patch.object(watch, "type_into", return_value=True))
        self.notified = self.stack.enter_context(patch.object(watch.notify, "shaped", return_value=0))
        self.reset = self.stack.enter_context(patch.object(watch, "spend_reset"))
        self.window = self.stack.enter_context(patch.object(watch, "window_ends", return_value=None))
        self.data = watch.load_state()
        self.logs = []

    def tick(self, seconds=0, dry=False):
        self.now += seconds
        watch.health({}, self.data, dry, self.logs.append)

    def test_stable_error_waits_three_minutes_and_throttles(self):
        self.tick()
        self.tick(179)
        self.typed.assert_not_called()
        self.tick(1)
        self.assertEqual(self.typed.call_args.args[1], "continue")
        self.tick(179)
        self.assertEqual(self.typed.call_count, 1)
        self.tick(1)
        self.assertEqual(self.typed.call_count, 2)

    def test_each_seats_clock_starts_when_its_pane_is_captured(self):
        self.seats = [{"name": "first"}, {"name": "second"}]
        def capture(session):
            if session["name"] == "second":
                self.now += 300
            return self.tail
        with patch.object(watch, "pane_text", side_effect=capture):
            self.tick()
        self.assertEqual(self.data["stalls"]["second"]["stall_at"], self.now)
        self.seats = [{"name": "second"}]
        self.tick(179)
        self.typed.assert_not_called()
        self.tick(1)
        self.typed.assert_called_once()

    def test_slow_meter_reads_do_not_shorten_the_nudge_interval(self):
        self.harness, self.provider = "codex", "openai"
        self.tail = "usage limit reached"
        self.tick()
        self.reset.side_effect = lambda *_: setattr(self, "now", self.now + 120)
        self.tick(180)
        self.assertEqual(self.data["stalls"]["seat"]["nudged_at"], self.now)
        self.reset.side_effect = None
        self.tick(179)
        self.assertEqual(self.typed.call_count, 1)
        self.assertEqual(self.reset.call_count, 1)
        self.assertEqual(self.window.call_count, 1)
        self.tick(1)
        self.assertEqual(self.typed.call_count, 2)

    def test_new_error_and_pane_changes_restart_the_clock(self):
        self.tick()
        self.tick(179)
        self.tail = "API Error: 503"
        self.tick(1)
        self.assertEqual(self.data["stalls"]["seat"]["stall_at"], self.now)
        self.tick(179)
        self.typed.assert_not_called()
        self.tick(1)
        self.assertEqual(self.typed.call_count, 1)
        self.tail += "\nAPI Error: 503"  # a fresh occurrence of the same error
        self.tick(3600)
        self.typed.reset_mock()
        self.notified.assert_not_called()
        self.tick(179)
        self.typed.assert_not_called()
        self.tick(1)
        self.typed.assert_called_once()
        self.tail += "\n›"  # even a prompt repaint gets a new quiet period
        self.tick(180)
        self.assertEqual(self.typed.call_count, 1)
        self.assertEqual(self.data["stalls"]["seat"]["changed_at"], self.now)
        self.tail = "API Error: 500\nOverloaded"
        self.tick(180)
        self.assertEqual(self.data["stalls"]["seat"]["signature"], "Overloaded")
        self.assertEqual(self.typed.call_count, 1)

    def test_old_error_followed_by_progress_never_gets_typed_into(self):
        self.tick()
        self.tail += "\nReading the next file"
        self.tick(3600)
        self.tick(3600)
        self.typed.assert_not_called()
        self.notified.assert_not_called()
        self.assertNotIn("seat", self.data["stalls"])
        self.tail += "\nAPI Error: connection lost"
        self.tick()
        self.tick(179)
        self.typed.assert_not_called()

    def test_progress_above_the_tail_restarts_the_quiet_clock(self):
        self.tail = "Top of screen\n" + "\n" * 20 + "API Error: 500"
        self.tick()
        self.tail = self.tail.replace("Top of screen", "New progress above the error")
        self.tick(3600)
        self.tick(179)
        self.typed.assert_not_called()
        self.notified.assert_not_called()
        self.tick(1)
        self.typed.assert_called_once()

    def test_harness_prompt_and_footer_do_not_hide_the_latest_error(self):
        self.tail += "\n────────────────\n❯\n────────────────\n⏵⏵ bypass permissions on (shift+tab to cycle)"
        self.tick()
        self.tick(180)
        self.typed.assert_called_once()
        self.tail = "API Error: 500\nReading the tests\n❯\n? for shortcuts"
        self.tick(3600)
        self.assertEqual(self.typed.call_count, 1)
        self.notified.assert_not_called()
        self.assertNotIn("seat", self.data["stalls"])

    def test_real_tui_panes_keep_the_error_visible_but_reject_later_progress(self):
        panes = [(harness, (REPO / f"tests/fixtures/{harness}-stall-pane.txt").read_text())
                 for harness in ("claude", "codex", "muse")]
        # Earlier harness versions from the review: boxed Claude composer and Codex key hints.
        panes += [
            ("claude", '⎿ API Error: 500 upstream connect error\n╭──────────────────╮\n'
                       '│ > Try "fix tests" │\n╰──────────────────╯\n'
                       '⏵⏵ bypass permissions on (shift+tab to cycle)   ◯ 92% context left'),
            ("codex", '• stream error: rate limit reached\n▌ Ask Codex to do something\n'
                      '⏎ send  ⌃T transcript'),
        ]
        for harness, pane in panes:
            with self.subTest(harness=harness, pane=pane):
                self.data = watch.load_state()
                self.harness, self.tail = harness, pane
                self.typed.reset_mock()
                self.tick()
                self.tick(179)
                self.typed.assert_not_called()
                self.tick(1)
                self.typed.assert_called_once()
                # Insert actual progress between the latest error and its untouched footer.
                lines = pane.splitlines()
                at = max(i for i, line in enumerate(lines)
                         if any(mark.lower() in line.lower() for mark in watch.stalls(harness)))
                lines.insert(at + 1, "Reading the next file")
                self.tail = "\n".join(lines)
                self.tick(3600)
                self.tick(3600)
                # The error is answered and nothing is typed at it again.  A harness with no
                # blocking end-of-turn hook then has the three-way rule typed at its prompt
                # instead -- watch.stop_nudge -- which is one keystroke, not a resume.
                self.assertEqual(self.typed.call_count,
                                 2 if watch.stop_enforced(harness) else 1)
                self.notified.assert_not_called()
                self.assertNotIn("seat", self.data["stalls"])

    def test_attach_discards_stale_state_before_both_watcher_saves(self):
        self.tick()
        self.tick(3600)
        watch.save_state(self.data)
        stale = copy.deepcopy(self.data)
        orch.seen_by_user("seat")
        stamp = watch.load_state()["seen_at"]["seat"]
        watch.save_state(stale)
        self.assertNotIn("seat", watch.load_state()["stalls"])
        self.assertNotIn("seat", stale["stalls"])
        stale["stalls"]["seat"] = {"told": self.now, "since": 1}
        orch.seen_by_user("seat")  # same wall-clock time still advances the generation
        watch.save_state(stale)
        self.assertGreater(stale["seen_at"]["seat"], stamp)
        self.assertNotIn("seat", watch.load_state()["stalls"])

    def test_unknown_footer_logs_the_ignored_signature_and_winning_line(self):
        footer = "New harness footer: ready for input"
        for harness in ("claude", "codex", "muse"):
            with self.subTest(harness=harness):
                self.harness = harness
                self.tail = (REPO / f"tests/fixtures/{harness}-stall-pane.txt").read_text() + footer
                self.logs.clear()
                self.tick()
                mark = {"claude": "API Error", "codex": "429 Too Many Requests", "muse": "429"}[harness]
                self.assertEqual(self.logs, [
                    f"seat: ignored {mark!r}; newer line {footer!r} is not known chrome"])
                self.tick(3600)
                self.typed.assert_not_called()
                self.notified.assert_not_called()
                self.reset.assert_not_called()
                self.window.assert_not_called()
                self.assertNotIn("seat", self.data["stalls"])
        self.logs.clear()
        self.tail = footer
        self.tick()
        self.assertEqual(self.logs, [])

    def test_attach_generations_increase_even_with_a_backwards_clock(self):
        orch.seen_by_user("seat")  # no stall has ever existed
        stamp = watch.load_state()["seen_at"]["seat"]
        self.now -= 1000
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(orch.seen_by_user, ["seat"] * 12))
        self.assertGreater(watch.load_state()["seen_at"]["seat"], stamp)

    def test_a_stale_watcher_cannot_clear_another_ticks_stop_record(self):
        self.tick()
        stale = copy.deepcopy(self.data)
        self.tick(3600)
        watch.save_state(self.data)
        stale["stalls"].clear()
        watch.save_state(stale)
        self.assertTrue(watch.load_state()["stalls"]["seat"]["told"])

    def test_attach_during_meter_read_prevents_nudge_and_restored_stall(self):
        self.harness, self.provider = "codex", "openai"
        self.tail = "usage limit reached\nGoal stalled"
        self.tick()
        watch.save_state(self.data)
        self.reset.side_effect = lambda *_: orch.seen_by_user("seat")
        self.tick(180)
        self.typed.assert_not_called()
        watch.save_state(self.data)
        self.assertNotIn("seat", watch.load_state()["stalls"])

    def test_progress_during_meter_read_prevents_nudge(self):
        self.harness, self.provider = "codex", "openai"
        self.tail = "usage limit reached"
        self.tick()
        self.reset.side_effect = lambda *_: setattr(self, "tail", "Reading tests now")
        self.tick(180)
        self.typed.assert_not_called()

    # The seat is mid-turn when the error lands: the stall words below are the
    # new classifier's `idle` for a bare pane, and an idle seat is never asked.
    @patch.object(watch, "live_state", return_value={"word": "working"})
    def test_stop_until_attach_survives_blank_failure_and_progress(self, _live):
        self.tick()
        self.tick(3600)
        self.notified.assert_called_once()
        for tail in ("", "working", "API Error: 503"):
            self.tail = tail
            self.tick(3600)
            self.assertTrue(self.data["stalls"]["seat"]["told"])
        self.typed.assert_not_called()
        self.notified.assert_called_once()
        watch.save_state(self.data)
        orch.seen_by_user("seat")
        self.tick()
        self.assertNotIn("seat", self.data["stalls"])
        self.tick()
        self.tick(180)
        self.typed.assert_called_once()

    def test_stopped_seat_does_not_pass_its_latch_to_a_reused_name(self):
        self.tick()
        self.tick(3600)
        watch.save_state(self.data)
        stale = copy.deepcopy(self.data)
        with patch.object(orch, "tmux_out", return_value=(0, "")), redirect_stdout(io.StringIO()):
            self.assertEqual(orch.cmd_stop(["seat"]), 0)
        # A replacement can appear before the watcher observes any absence at all.
        watch.save_state(stale)
        self.assertNotIn("seat", watch.load_state()["stalls"])
        self.tick()
        self.tick()
        self.tick(179)
        self.typed.assert_not_called()
        self.tick(1)
        self.typed.assert_called_once()

    def test_pruned_orphan_latch_cannot_be_restored_by_a_stale_save(self):
        self.tick()
        self.tick(3600)
        watch.save_state(self.data)
        stale = copy.deepcopy(self.data)
        self.seats.clear()
        # A resumable record still owns the latch, even without its tmux session.
        with patch.object(orch, "records", return_value={"seat": {}}):
            self.tick()
        self.assertTrue(self.data["stalls"]["seat"]["told"])
        self.tick()
        watch.save_state(self.data)
        watch.save_state(stale)
        self.assertNotIn("seat", watch.load_state()["stalls"])
        self.seats.append({"name": "seat"})
        self.tick()
        self.tick(180)
        self.typed.assert_called_once()

    def test_fresh_create_and_inbox_ensure_clear_an_absent_seats_old_latch(self):
        cfg = config.load()
        for creator in ("create", "ensure"):
            with self.subTest(creator=creator):
                self.data = watch.load_state()
                self.data["stalls"]["seat"] = {"since": 1, "told": self.now}
                watch.save_state(self.data)
                stale = copy.deepcopy(self.data)
                config.save_session(cfg, "seat", "opus", ["astra"], {"created": 1})
                self.seats.clear()
                with patch.object(orch.usage, "collect", return_value={}), \
                     patch.object(orch, "select", return_value=("opus", "fixture", ["astra"])), \
                     patch.object(orch, "fresh_command", return_value=(["false"], "fresh-id")), \
                     patch.object(orch, "seat_cwd", return_value=self.root), \
                     patch.object(orch, "launch"), redirect_stdout(io.StringIO()):
                    if creator == "create":
                        orch.create(cfg, "seat", self.root, prompting=False)
                    else:
                        self.assertTrue(orch.ensure(cfg, "seat"))
                watch.save_state(stale)
                self.assertNotIn("seat", watch.load_state()["stalls"])
                self.seats.append({"name": "seat"})
                self.data = watch.load_state()
                self.typed.reset_mock()
                self.tick()
                self.tick(180)
                self.typed.assert_called_once()

    def test_pruning_an_alias_preserves_the_live_seats_notice_and_latch(self):
        cfg = config.load()
        config.save_session(cfg, "old", "opus", ["astra"])
        notice = '{"kind": "needs", "text": "waiting for you"}\n'
        config.notify_path("old").write_text(notice)
        config.rename_session("old", "seat")
        self.data["stalls"] = {"old": {"since": 1, "told": 10},
                               "seat": {"since": 2, "told": 20}}
        self.data["seen_at"]["seat"] = 5
        watch.save_state(self.data)
        stale = copy.deepcopy(self.data)
        self.tick(dry=True)
        self.assertIn("old", watch.load_state()["stalls"])
        self.data = watch.load_state()
        self.tick()
        watch.save_state(self.data)
        watch.save_state(stale)
        saved = watch.load_state()
        self.assertNotIn("old", saved["stalls"])
        self.assertEqual(saved["stalls"]["seat"], {"since": 2, "told": 20})
        self.assertEqual(saved["seen_at"]["seat"], 5)
        self.assertEqual(config.notify_path("seat").read_text(), notice)
        self.assertEqual(config.resolve_session("old"), "seat")
        self.typed.assert_not_called()
        self.notified.assert_not_called()
        # v4x: opening via the alias records a baseline; reading an owner question
        # does not answer it. Only fresh output after the open clears the live latch.
        orch.seen_by_user("old")
        self.data = watch.load_state()
        self.assertGreater(self.data["seen_at"]["seat"], saved["seen_at"]["seat"])
        opened = watch.notify.last("seat")
        self.assertEqual(opened["text"], "waiting for you")
        self.assertEqual(opened["opened_at"], self.now)
        self.tick(1)
        watch.save_state(self.data)
        self.assertEqual(watch.load_state()["stalls"]["seat"], {"since": 2, "told": 20})
        self.assertEqual(watch.notify.last("seat"), opened)
        self.tail = "Reading the next file"
        self.tick(1)
        watch.save_state(self.data)
        watch.save_state(stale)
        self.assertNotIn("seat", watch.load_state()["stalls"])
        self.assertIsNone(watch.notify.last("seat"))
        resolved = watch.notify.last("seat", include_seen=True)
        self.assertEqual(resolved["opened_at"], opened["opened_at"])
        self.assertGreater(resolved["last_progress_at"], resolved["opened_at"])
        self.typed.assert_not_called()
        self.notified.assert_not_called()

    def test_long_quota_window_bypasses_hour_cutoff_and_resumes_once(self):
        for harness, provider, tail in (("muse", "meta", "429 quota exhausted"),
                                        ("claude", "anthropic", "rate limit reached"),
                                        ("codex", "openai", "usage limit\nGoal stalled")):
            with self.subTest(harness=harness):
                self.data = watch.load_state()
                self.harness, self.provider, self.tail = harness, provider, tail
                self.typed.reset_mock()
                self.reset.reset_mock()
                self.window.reset_mock()
                ends = self.now + 7200
                self.window.side_effect = lambda *_: ends if self.now < ends else None
                self.tick()
                self.tick(180)
                self.tick(3600)
                self.assertEqual(self.window.call_count, 1)
                self.assertEqual(self.reset.call_count, int(harness == "codex"))
                self.typed.assert_not_called()
                self.notified.assert_not_called()
                entry = self.data["stalls"]["seat"]
                self.assertEqual(entry["resets_at"], ends)
                self.assertTrue(entry["status"].startswith("waiting until "))
                self.tick(ends - self.now)
                self.typed.assert_called_once()
                if harness == "codex":
                    self.reset.assert_called()
                    self.assertEqual(self.typed.call_args.args[1], "/goal resume")
                self.tick(300)
                self.assertEqual(self.typed.call_count, 1)
                self.assertEqual(self.window.call_count, 1)
                self.assertEqual(self.reset.call_count, int(harness == "codex"))
                self.assertNotIn("status", entry)

    def test_a_new_nonquota_error_clears_the_waiting_status(self):
        self.tail = "rate limit reached"
        self.window.return_value = self.now + 7200
        self.tick()
        self.tick(180)
        self.assertIn("status", self.data["stalls"]["seat"])
        self.tail = "API Error: connection lost"
        self.tick()
        self.assertNotIn("status", self.data["stalls"]["seat"])
        self.assertNotIn("resets_at", self.data["stalls"]["seat"])

    def test_a_restarted_watcher_uses_the_saved_window_without_polling(self):
        self.harness, self.provider = "codex", "openai"
        self.tail = "usage limit reached"
        ends = self.now + 7200
        self.window.return_value = ends
        self.tick()
        self.tick(180)
        watch.save_state(self.data)
        self.data = watch.load_state()
        self.window.side_effect = AssertionError("polled a known window")
        self.reset.side_effect = AssertionError("invalidated usage during a known window")
        self.tick(3600)
        self.typed.assert_not_called()
        self.notified.assert_not_called()
        self.tick(ends - self.now)
        self.typed.assert_called_once()
        watch.save_state(self.data)
        self.data = watch.load_state()
        self.tick(180)
        self.typed.assert_called_once()

    def test_quota_policy_precedes_goal_resume_in_either_order(self):
        self.harness, self.provider = "codex", "openai"
        for tail in ("usage limit reached\nGoal stalled", "Goal stalled\nrate limit reached"):
            self.data = watch.load_state()
            self.tail = tail
            order = []
            self.reset.side_effect = lambda *_: order.append("reset")
            self.typed.side_effect = lambda _, keys, __: order.append(keys) or True
            self.tick()
            self.tick(180)
            self.assertEqual(order, ["reset", "/goal resume"])

    def test_unknown_legacy_and_exited_seats_never_receive_keys(self):
        for extra in ({"legacy": True}, {"exited": True}):
            self.seats = [{"name": "seat", **extra}]
            self.tick()
            self.tick(3600)
        self.seats = [{"name": "seat"}]
        self.harness = None
        self.tick()
        self.tick(3600)
        self.typed.assert_not_called()
        self.assertEqual(self.data["stalls"], {})

    def test_dry_run_never_writes_or_calls_policy(self):
        self.harness, self.provider = "codex", "openai"
        self.tail = "usage limit reached\nGoal stalled"
        self.tick(dry=True)
        self.tick(180, dry=True)
        self.assertTrue(any("would resume seat" in line for line in self.logs))
        self.reset.assert_not_called()
        self.typed.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])


class RunsAndSmoke(unittest.TestCase):
    def test_smoke_codex_startup_continues_without_trusting_hooks(self):
        source = (REPO / "tests/smoke.sh").read_text()
        block = source[source.index("# --- 6d:"):source.index("# --- 7:")]
        poll = block[block.index('PANE=""'):block.index('\ncp "$HOME/')]
        with tempfile.TemporaryDirectory(prefix=".v4l-", dir=REPO) as directory:
            script = '''set -uo pipefail
tm() {
  case "$1" in
    capture-pane)
      if [ -f "$WORK/continued" ]; then
        echo 'OpenAI Codex'
      elif [ -f "$WORK/first-frame" ]; then
        touch "$WORK/options-visible"
        cat "$REPO/tests/fixtures/codex-hooks-review-pane.txt"
      else
        touch "$WORK/first-frame"
        echo 'Hooks need review'  # a partial frame must not get any answer yet
      fi ;;
    send-keys)
      printf '%s\\n' "$*" >>"$WORK/keys"
      [ "$*" = 'send-keys -t smoke-astra 3 Enter' ] || return 1
      [ -f "$WORK/options-visible" ] || return 1
      touch "$WORK/continued" ;;
    *) return 1 ;;
  esac
}
sleep() { :; }
'''
            env = {**os.environ, "WORK": directory, "REPO": str(REPO)}
            result = subprocess.run(["bash", "-c", script + poll + '\nprintf "%s" "$PANE"'],
                                    env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "OpenAI Codex")
            self.assertEqual((Path(directory) / "keys").read_text(),
                             "send-keys -t smoke-astra 3 Enter\n")

    def test_smoke_notification_number_ignores_the_callers_resumable_seats(self):
        source = (REPO / "tests/smoke.sh").read_text()
        block = source[source.index("# --- 21:"):source.index("# --- 22:")]
        number = next(line for line in block.splitlines() if line.startswith("NUM="))
        with tempfile.TemporaryDirectory(prefix=".v4l-", dir=REPO) as directory:
            root = Path(directory)
            caller, notify_home = root / "caller", root / "notify"
            for home in (caller, notify_home):
                (home / ".agentkit/state").mkdir(parents=True)
            for name in ("a-resumable", "b-resumable"):
                record = {"session": name, "orchestrator": "fable", "workers": ["opus"],
                          "cwd": directory, "created": time.time(), "seen": time.time(),
                          "conversation": name, "id_source": "launcher", "resumable": True}
                (caller / ".agentkit/state" / f"session-{name}.json").write_text(json.dumps(record))
            fake = root / "tmux"
            fake.write_text('''#!/bin/sh
case "$*" in
  *list-sessions*) printf 'smoke-shape\\t/tmp\\t10000\\t0\\t1\\n' ;;
  *list-panes*) printf 'smoke-shape\\t0\\n' ;;
  *) exit 1 ;;
esac
''')
            fake.chmod(0o755)
            env = {**os.environ, "HOME": str(caller), "NSH": str(notify_home),
                   "AGENTKIT_SESSION": "", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                   "PATH": f"{root}:{REPO / 'bin'}:{os.environ['PATH']}"}
            listing = subprocess.run(["ak", "orch", "list"], env=env, text=True,
                                     capture_output=True, check=True)
            rows = [line for line in listing.stdout.splitlines()
                    if not line.startswith("name ") and line.split()]
            self.assertRegex(rows[-1], r"^(slice \S+ ·|no slice )")   # the listing's last line
            self.assertEqual([line.split()[0] for line in rows[:-1]],
                             ["a-resumable", "b-resumable", "smoke-shape"])
            result = subprocess.run(["bash", "-c", 'set -uo pipefail\n' + number + '\necho "$NUM"'],
                                    env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "1")

    def test_smoke_empty_pick_order_requires_exhausted_providers(self):
        source = (REPO / "tests/smoke.sh").read_text()
        block = source[source.index("# --- 1: usage"):source.index("# --- 2:")]
        with tempfile.TemporaryDirectory(prefix=".v4l-", dir=REPO) as directory:
            root = Path(directory)
            # Claude and Codex installed and logged in here, whatever the caller's HOME holds:
            # the check asks for their logins before it judges the pick order.
            for harness in ("claude", "codex"):
                for path, body in ((root / harness, "exit 97"),
                                   (root / f"{harness}.sh", "echo 'fixture: logged in'")):
                    path.write_text(f"#!/bin/sh\n{body}\n")
                    path.chmod(0o755)
            env = {**os.environ, "WORK": directory, "HOME": directory, "REPO": str(REPO),
                   "AGENTKIT_ADAPTER_DIR": directory, "PATH": f"{root}:{os.environ['PATH']}"}
            for exhausted, order, expected in ((True, [], 0), (False, [], 1), (False, ["astra"], 0)):
                with self.subTest(exhausted=exhausted, order=order):
                    data = {"pick_order": order, "providers": {
                        provider: {"exhausted": exhausted, "meters": [{"used": 100 if exhausted else 10}]}
                        for provider in ("anthropic", "openai", "meta")}}
                    (root / "fixture.json").write_text(json.dumps(data))
                    script = (f'. {REPO}/tests/acceptance.sh\n'
                              'ak() { cat "$WORK/fixture.json"; }; ok() { :; }; '
                              'no() { exit 1; };\n' + block)
                    result = subprocess.run(["bash", "-c", script], env=env,
                                            text=True, capture_output=True)
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_smoke_checks_forced_harnesses_when_the_default_is_not_claude(self):
        source = (REPO / "tests/smoke.sh").read_text()
        block = source[source.index("# --- 6: orch"):source.index("# --- 6c:")]
        with tempfile.TemporaryDirectory(prefix=".v4l-", dir=REPO) as directory:
            root = Path(directory)
            fake = root / "tmux"
            fake.write_text("#!/bin/sh\nexit 1\n")
            fake.chmod(0o755)
            env = {**os.environ, "HOME": directory, "WORK": directory, "REPO": str(REPO),
                   "U": str(root / "usage.json"), "AGENTKIT_SESSION": "",
                   "AGENTKIT_ADAPTER_DIR": str(REPO / "adapters"),
                   "PATH": f"{root}:{REPO / 'bin'}:{os.environ['PATH']}"}
            for anthropic, openai, expected in ((10, 10, "opus"), (100, 10, "astra"),
                                                (100, 100, "spark")):
                with self.subTest(default=expected):
                    for path in (root / "orchhome/.agentkit/state").glob("session-*.json"):
                        path.unlink()
                    providers = {}
                    for provider, used in (("anthropic", anthropic), ("openai", openai), ("meta", 10)):
                        providers[provider] = {"meters": [{"name": "session", "used": used,
                            "exhausted": used >= 100, "resets_at": 9999999999, "window_secs": 18000,
                            "pace": None, "elapsed": None}],
                            "error": None, "notes": [], "exhausted": used >= 100}
                    (root / "usage.json").write_text(json.dumps({"providers": providers}))
                    script = 'set -uo pipefail\nok() { :; }; no() { echo "$*"; exit 1; };\n' + block
                    result = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr +
                                     (root / "orch-fable.log").read_text())
                    self.assertIn(f"orch: {expected} (", (root / "orch.log").read_text())

    def test_smoke_skips_spent_dependencies_before_github_and_mcp_calls(self):
        source = (REPO / "tests/smoke.sh").read_text()
        helpers = "spent_until()" + source.split("spent_until()", 1)[1].split("\nprintf 'Create", 1)[0]
        helpers = f'. "{REPO}/tests/acceptance.sh"\n' + helpers
        run_block = source[source.index("# --- 4:"):source.index("# --- 5:")]
        mcp_block = source[source.index("# 31d/31e:"):source.index("# --- 32:")]
        with tempfile.TemporaryDirectory(prefix=".v4l-", dir=REPO) as directory:
            root = Path(directory)
            for name, answer in (("gh", ""), ("claude", "BROWSER_TABS=0 DESKTOP=ok"),
                                 ("codex", "BROWSER_TABS=0")):
                fake = root / name
                fake.write_text(f'#!/bin/sh\necho {name} >> "$WORK/calls"\necho "{answer}"\n')
                fake.chmod(0o755)
            # The shared-browser precondition is a fixture too; no local service is required.
            fake = root / "python3"
            fake.write_text('#!/bin/sh\ncase "$*" in *urllib.request*) exit 0 ;; esac\n'
                            f'exec {shlex.quote(sys.executable)} "$@"\n')
            fake.chmod(0o755)
            env = {**os.environ, "HOME": directory, "WORK": directory, "REPO": str(REPO),
                   "PATH": f"{root}:{os.environ['PATH']}"}
            for spent in ("anthropic", "openai", None):
                providers = {provider: {"meters": [{"name": "weekly", "used": 100 if provider == spent else 10,
                    "exhausted": provider == spent, "resets_at": 9999999999}]}
                    for provider in ("anthropic", "openai")}
                (root / "usage-real.json").write_text(json.dumps({"providers": providers}))
                with self.subTest(spent=spent):
                    if spent:
                        result = subprocess.run(["bash", "-c", helpers + "\n" + run_block + '\nfinish'], env=env,
                                                text=True, capture_output=True)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        for label in ("4", "4b", "4c", "4d"):
                            self.assertIn(f"SKIP  {label}:", result.stdout)
                        self.assertIn("0 passed, 0 failed, 4 skipped", result.stdout)
                        self.assertFalse((root / "calls").exists())
                        self.assertFalse((root / "task.md").exists())
                    script = helpers + "\n" + mcp_block + '\nfinish'
                    result = subprocess.run(["bash", "-c", script], env=env, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn(f"{1 if spent else 2} passed, 0 failed, {1 if spent else 0} skipped",
                                  result.stdout)
                    expected = [name for name, provider in (("claude", "anthropic"), ("codex", "openai"))
                                if provider != spent]
                    self.assertEqual((root / "calls").read_text().splitlines(), expected)
                    (root / "calls").unlink()

    def test_muse_wrapped_error_is_joined_at_two_pane_widths(self):
        fixture = (REPO / "tests/fixtures/muse-stall-pane.txt").read_text()
        # The socket directory is the system temp's rather than the repo's: a unix socket path
        # is capped near 108 bytes, and `<repo>/.v4l-XXXXXXXX/tmux-<uid>/agentkit-test` is past
        # it from a worktree, where every run of this suite happens.
        with tempfile.TemporaryDirectory(prefix=".v4l-", dir=REPO) as directory, \
                tempfile.TemporaryDirectory(prefix="v4l-tmux-") as sockets:
            root = Path(directory)
            pane_file = root / "pane.txt"
            env = {**os.environ, "TMUX_TMPDIR": sockets, "AGENTKIT_TMUX_SOCKET": "agentkit-test"}
            env.pop("TMUX", None)
            def tmux(*args):
                return subprocess.run(["tmux", "-L", "agentkit-test", *args], env=env,
                                      text=True, capture_output=True, check=True)
            try:
                for width in (40, 100):
                    for progress in ("", "Reading the next file"):
                        with self.subTest(width=width, progress=progress):
                            name = f"muse-{width}-{bool(progress)}"
                            pane_file.write_text(fixture.rstrip() + "\n" + progress + "\n")
                            tmux("-f", "/dev/null", "new-session", "-d", "-s", name,
                                 "-x", str(width), "-y", "60",
                                 f"cat {shlex.quote(str(pane_file))}; cat")
                            deadline = time.monotonic() + 5
                            with patch.dict(os.environ, env, clear=True):
                                while True:
                                    pane = watch.pane_text({"name": name})
                                    if "YOLO" in pane and (not progress or progress in pane):
                                        break
                                    self.assertLess(time.monotonic(), deadline, pane)
                                    time.sleep(.05)
                            raw = tmux("capture-pane", "-p", "-t", f"={name}:").stdout
                            error = next(line for line in fixture.splitlines() if "429" in line)
                            self.assertNotIn(error, raw)
                            self.assertIn(error, pane)
                            logs = []
                            mark = watch.stalled_on("muse", watch.pane_tail(pane), name, logs.append)
                            self.assertEqual(mark, None if progress else "429")
                            self.assertEqual(len(logs), int(bool(progress)))
                            tmux("kill-session", "-t", f"={name}")
            finally:
                subprocess.run(["tmux", "-L", "agentkit-test", "kill-server"], env=env,
                               capture_output=True)

    def test_captured_claude_stream_reads_appends_and_waits_on_partial_lines(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import check_claude_stream
        fixture = (REPO / "tests/fixtures/claude-stream.jsonl").read_text().splitlines()
        with tempfile.TemporaryDirectory(prefix=".v4l-", dir=REPO) as directory:
            events = Path(directory) / "events.jsonl"
            self.assertEqual(check_claude_stream.read_events(events), [])
            events.write_text("\n".join(fixture[:2]) + "\n")
            seen = check_claude_stream.read_events(events)
            self.assertEqual(len(seen), 2)
            self.assertTrue(all(isinstance(event, dict) for event in seen))
            middle = len(fixture[2]) // 2
            with events.open("a") as output:
                output.write(fixture[2][:middle])
            self.assertEqual(len(check_claude_stream.read_events(events)), 2)
            with events.open("a") as output:
                output.write(fixture[2][middle:] + "\n")
            seen = check_claude_stream.read_events(events)
            self.assertEqual(len(seen), 3)
            self.assertEqual(seen[2], json.loads(fixture[2]))
            with events.open("a") as output:
                output.write("\n".join(fixture[3:]) + "\n")
            self.assertEqual(len(check_claude_stream.read_events(events)), len(fixture))

    def test_adapter_extracts_one_final_result_and_session_from_real_stream(self):
        fixture = (REPO / "tests/fixtures/claude-stream.jsonl").read_text()
        result = json.loads(fixture.splitlines()[-1])
        with tempfile.TemporaryDirectory(prefix=".v4l-", dir=REPO) as directory:
            root = Path(directory)
            (root / "prompt").write_text("smoke replay\n")
            replay = root / "replay"
            # More than one result, followed by another non-result event: only the last
            # result contributes final text. All events here came from the real call.
            replay.write_text(fixture + fixture + fixture.splitlines()[0] + "\n")
            fake = root / "claude"
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGS"\ncat "$REPLAY"\nexit "${RC:-0}"\n')
            fake.chmod(0o755)
            env = {**os.environ, "PATH": directory + ":" + os.environ["PATH"],
                   "ARGS": str(root / "args"), "REPLAY": str(replay)}
            command = ["bash", str(REPO / "adapters/claude.sh"), "run", "model", "effort",
                       directory, str(root / "prompt"), str(root / "out"), result["session_id"]]
            subprocess.run(command, env=env, check=True)
            self.assertEqual((root / "out/final.md").read_text(), result["result"] + "\n")
            self.assertEqual((root / "out/session_id").read_text(), result["session_id"] + "\n")
            args = (root / "args").read_text().splitlines()
            self.assertEqual(args[args.index("--output-format") + 1], "stream-json")
            self.assertIn("--verbose", args)
            self.assertEqual(args[args.index("--resume") + 1], result["session_id"])
            env["RC"] = "17"
            replay.write_text(fixture.splitlines()[0] + "\n")
            self.assertEqual(subprocess.run(command, env=env).returncode, 17)
            self.assertEqual((root / "out/final.md").read_text().strip(), "")
            self.assertEqual((root / "out/session_id").read_text().strip(), result["session_id"])

    def test_40_columns_preserves_every_run_field_on_two_lines(self):
        rows = [["1", "A very long title that used to hide everything else", "atoll",
                 "working", "opus/astra 2/3", "15m"],
                ["2", "Another title", "parser", "needs you", "spark/fable 1/1", "2h"]]
        rows.append(["3", "Title", "owner", "exited", "spark/fable 100/100", "125d"])
        with patch.object(menu.shutil, "get_terminal_size", return_value=os.terminal_size((40, 24))):
            out = io.StringIO()
            with redirect_stdout(out):
                menu.table(rows)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 6)
        self.assertTrue(all(len(line) <= 40 for line in lines), lines)
        for index, row in enumerate(rows):
            self.assertIn(row[2], lines[2 * index])
            self.assertIn(row[3], lines[2 * index])
            self.assertEqual(lines[2 * index + 1].split(), row[4].split() + [row[5]])

    def test_40_columns_always_uses_two_lines_even_for_short_titles(self):
        with patch.object(menu.shutil, "get_terminal_size", return_value=os.terminal_size((40, 24))):
            out = io.StringIO()
            with redirect_stdout(out):
                menu.table([["1", "t", "a", "done", "opus/astra 1/1", "1s"]])
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("done", lines[0])
        self.assertEqual(lines[1].split(), ["opus/astra", "1/1", "1s"])

    def test_smoke_exhaustion_is_scoped_to_the_tested_model(self):
        source = (REPO / "tests/smoke.sh").read_text()
        function = source.split("spent_until()", 1)[1].split("\nprintf 'Create", 1)[0]
        script = "spent_until()" + function + '\nspent_until "$1"\n'
        with tempfile.TemporaryDirectory(prefix=".v4l-", dir=REPO) as directory:
            work = Path(directory)
            data = {"providers": {"anthropic": {"exhausted": True, "meters": [
                {"name": "weekly_scoped", "used": 100, "exhausted": True, "resets_at": 9999999999},
                {"name": "weekly", "used": 10, "exhausted": False, "resets_at": 9999999999}]}}}
            (work / "usage-real.json").write_text(json.dumps(data))
            env = {**os.environ, "REPO": str(REPO), "WORK": directory}
            def spent(model):
                return subprocess.check_output(["bash", "-c", script, "smoke", model],
                                               env=env, text=True).strip()
            self.assertEqual(spent("opus"), "")
            self.assertTrue(spent("fable").startswith("anthropic "))
            data["providers"]["anthropic"]["meters"][1].update(used=100, exhausted=True)
            (work / "usage-real.json").write_text(json.dumps(data))
            self.assertTrue(spent("opus").startswith("anthropic "))
            for contents in ("", "{", "null", "[]", "{}", '{"providers":null}', None):
                with self.subTest(contents=contents):
                    path = work / "usage-real.json"
                    if contents is None:
                        path.unlink()
                    else:
                        path.write_text(contents)
                    result = subprocess.run(["bash", "-c", script, "smoke", "opus"],
                                            env=env, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
