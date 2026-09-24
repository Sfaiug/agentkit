"""Auth watchdog smoke checks: captured pane replay, real notify outbox, no auth/model calls.

The `auth` verb is stubbed (see `authed`): what decides a seat's login is that verb's answer,
and no real adapter may be asked about a real token here.  The stub answers for the fixture
harness exactly what its own pane says, so these captures keep driving the checks -- the pane
is what makes the tick ask, and asking is what decides.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, notify, orch, watch, worker


class AuthWatch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".auth-watch-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "AK_RUN_ROLE": "orchestrator",
            "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": "",
        }))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.now = 10000
        self.stack.enter_context(patch.object(watch.time, "time", lambda: self.now))
        self.seats = [{"name": "auth-seat"}]
        self.stack.enter_context(patch.object(orch, "sessions", lambda: self.seats))
        self.stack.enter_context(patch.object(orch, "records", return_value={}))
        self.stack.enter_context(patch.object(notify, "session_number", return_value=3))
        self.harness = "claude"
        self.stack.enter_context(patch.object(watch, "seat_model", lambda *_: (self.harness, "test")))
        self.pane = self.fixture("claude")
        self.capture = self.stack.enter_context(patch.object(watch, "pane_text", lambda _: self.pane))
        self.typed = self.stack.enter_context(patch.object(watch, "type_into", return_value=True))
        self.meters = self.stack.enter_context(patch.object(watch, "window_ends", return_value=None))
        self.reset = self.stack.enter_context(patch.object(watch, "spend_reset"))
        self.sent = self.stack.enter_context(patch.object(notify, "shaped", wraps=notify.shaped))
        self.token_ok = None
        self.stack.enter_context(patch.object(worker, "auth_ok", side_effect=self.authed))
        self.data = watch.load_state()
        self.logs = []

    def authed(self, harness, seat=False):
        """The stubbed `auth` verb: this fixture's harness is logged out exactly when its
        own pane says so, unless a check has said otherwise with `self.token_ok`.

        One login here, so the seat's view and a worker's are the same answer -- which is
        what every harness without a worker credential of its own says too.
        """
        if self.token_ok is not None:
            return self.token_ok, f"{harness}: stub"
        mark = watch.auth_expired_on(harness, watch.pane_tail(self.pane))
        return (not mark), (f"{harness}: {mark}" if mark else f"{harness}: token present")

    def fixture(self, harness):
        return (REPO / f"tests/fixtures/{harness}-auth-pane.txt").read_text()

    def tick(self, seconds=0, dry=False):
        self.now += seconds
        watch.health({}, self.data, dry, self.logs.append)
        if not dry:
            watch.save_state(self.data)

    def events(self):
        return [json.loads(p.read_text()) for p in notify.outbox().glob("*.json")]

    def test_claude_login_expired_alert_names_session_and_login_remedy_without_nudge(self):
        self.assertEqual(watch.auth_expired_on("claude", watch.pane_tail(self.pane)),
                         "Login expired · Please run /login")
        self.tick()
        self.sent.assert_called_once()
        notice = notify.last("auth-seat")
        self.assertEqual(notice["kind"], "needs")
        for text in ("auth-seat", "Claude Code", "open the host", "number", "/login"):
            self.assertIn(text, notice["text"])
        self.assertEqual(len(self.events()), 1)
        embed = self.events()[0]["payload"]["embeds"][0]
        self.assertIn("Needs you", embed["title"])
        self.assertNotIn("fields", embed)   # the card is two words and the seat
        self.assertEqual(menu.state(self.seats[0]), "needs you")
        self.typed.assert_not_called()
        self.meters.assert_not_called()
        self.reset.assert_not_called()

    def test_second_tick_and_watcher_restart_do_not_duplicate_logout_alert(self):
        self.tick()
        self.tick()
        self.data = watch.load_state()
        self.tick(watch.GIVE_UP * 2)
        self.sent.assert_called_once()
        self.assertEqual(len(self.events()), 1)
        self.typed.assert_not_called()

    def test_progress_clears_login_state_and_a_new_logout_asks_within_the_episode(self):
        self.tick()
        stale = copy.deepcopy(self.data)
        self.pane += "\nReading the next file"
        self.tick(1)
        self.assertEqual(menu.state(self.seats[0]), "needs you")
        self.assertIsNone(notify.last("auth-seat"))
        watch.save_state(stale)
        self.assertNotIn("auth-seat", watch.load_state()["stalls"])
        self.pane = self.fixture("claude")
        self.tick(1)
        self.assertEqual(self.sent.call_count, 2)
        # The word never left needs you, so the new question joins the standing
        # episode instead of queueing a second card.
        self.assertEqual(len(self.events()), 1)
        self.assertIn("needs login", notify.last("auth-seat")["text"])
        self.typed.assert_not_called()

    def test_auth_recovery_preserves_a_newer_unrelated_question(self):
        self.tick()
        self.now += 1
        notify.shaped("needs", "May I merge this PR?", session="auth-seat")
        self.pane += "\nReading the next file"
        self.tick(1)
        self.assertEqual(notify.last("auth-seat")["text"], "May I merge this PR?")
        self.assertEqual(menu.state(self.seats[0]), "needs you")

    def test_opening_the_seat_clears_needs_login_and_stale_watcher_cannot_restore_it(self):
        self.tick()
        stale = copy.deepcopy(self.data)
        orch.seen_by_user("auth-seat")
        watch.save_state(stale)
        # the alert is gone, and the seat reads as what it now is: at its prompt, his
        self.assertEqual(menu.state(self.seats[0]), "needs you")
        self.assertNotIn("auth-seat", watch.load_state()["stalls"])

    def test_blank_or_failed_capture_keeps_the_auth_episode(self):
        # The capture failed; the token is exactly as expired as it was, and the verb still
        # says so.  A screen nobody could read is not recovery, and does not start a
        # second episode when it comes back.
        self.tick()
        self.pane, self.token_ok = "", False
        self.tick(watch.GIVE_UP)
        self.assertEqual(menu.state(self.seats[0]), "needs you")
        self.pane, self.token_ok = self.fixture("claude"), None
        self.tick()
        self.sent.assert_called_once()
        self.typed.assert_not_called()

    def test_a_login_that_comes_back_clears_a_seat_with_no_screen_to_read(self):
        # The other half: the seat is gone or its pane cannot be captured, and the login is
        # back.  Nothing can be read off a blank screen, so the verb is the only evidence --
        # and the alert it raised has to come off, or the seat says `needs you` forever.
        self.tick()
        self.assertEqual(menu.state(self.seats[0]), "needs you")
        self.pane, self.token_ok = "", True
        self.tick(1)
        self.assertNotIn("auth-seat", self.data["stalls"])
        self.assertIsNone(notify.last("auth-seat"))
        self.assertIs(watch.load_state()["auth_out"]["claude"]["ok"], True)
        self.typed.assert_not_called()

    def test_notification_persistence_failure_retries_without_ever_nudging(self):
        with patch.object(notify, "_write_event", side_effect=OSError("disk unavailable")):
            self.tick()
        self.assertNotIn("told", self.data["stalls"]["auth-seat"])
        self.assertEqual(menu.state(self.seats[0]), "needs you")
        self.tick(watch.GIVE_UP)
        self.assertEqual(len(self.events()), 1)
        self.assertTrue(self.data["stalls"]["auth-seat"]["told"])
        self.typed.assert_not_called()

    # The seat is mid-turn when the error lands: these words are the new
    # classifier's `idle` for a bare pane, and an idle seat is never asked.
    @patch.object(watch, "live_state", return_value={"state": "working"})
    def test_auth_supersedes_a_saved_capacity_give_up_latch(self, _live):
        self.pane = "API Error: 500"
        self.tick()
        self.tick(watch.GIVE_UP)
        self.assertTrue(self.data["stalls"]["auth-seat"]["told"])
        self.pane = self.fixture("claude")
        self.tick(1)
        self.assertEqual(menu.state(self.seats[0]), "needs you")
        self.data = watch.load_state()
        self.tick(1)
        self.assertEqual(self.sent.call_count, 2)
        self.assertEqual(self.data["stalls"]["auth-seat"]["kind"], "auth")
        self.typed.assert_not_called()

    def test_auth_and_capacity_on_the_same_pane_never_resume(self):
        self.pane += "\nAPI Error: 500"
        self.tick()
        self.tick(watch.GIVE_UP)
        self.assertEqual(menu.state(self.seats[0]), "needs you")
        self.typed.assert_not_called()

    def test_codex_and_muse_verified_auth_panes_have_their_own_login_remedy(self):
        for harness in ("codex", "muse"):
            with self.subTest(harness=harness):
                self.harness = harness
                self.pane = self.fixture(harness)
                self.assertIsNotNone(watch.auth_expired_on(harness, watch.pane_tail(self.pane)))
                self.tick(1)
                self.assertIn(f"{harness} login", notify.last("auth-seat")["text"])
                self.assertEqual(menu.state(self.seats[0]), "needs you")
        self.typed.assert_not_called()

    def test_required_claude_signatures_are_recognised_but_quoted_instructions_are_not(self):
        for mark in watch.auth_expiry("claude")[2]:
            with self.subTest(mark=mark):
                self.assertEqual(watch.auth_expired_on("claude", mark), mark)
                self.assertIsNone(watch.auth_expired_on("claude", f'❯ Explain "{mark}"'))
                self.assertIsNone(watch.auth_expired_on("claude", mark + "\nReading tests"))

    def test_installed_logout_variants_alert_immediately_once_with_no_resume(self):
        variants = json.loads((REPO / "tests/fixtures/auth-expiry-variants.json").read_text())
        for harness, messages in variants.items():
            for number, message in enumerate(messages):
                with self.subTest(harness=harness, message=message):
                    self.harness = harness
                    name = f"{harness}-{number}"
                    self.seats = [{"name": name}]
                    self.sent.reset_mock()
                    template = self.fixture(harness) if harness != "muse" else (
                        REPO / "tests/fixtures/muse-stall-pane.txt").read_text()
                    line = next(line for line in template.splitlines() if line.startswith(("● ", "■ ", "◆ ")))
                    self.pane = template.replace(line, textwrap.fill("Error: " + message, width=65))
                    self.assertIsNotNone(watch.auth_expired_on(harness, watch.pane_tail(self.pane)))
                    self.tick(1)
                    self.data = watch.load_state()
                    self.tick(watch.GIVE_UP)
                    self.sent.assert_called_once()
                    notice = notify.last(name)
                    self.assertEqual(notice["kind"], "needs")
                    self.assertIn(name, notice["text"])
                    self.assertIn("/login" if harness == "claude" else f"{harness} login", notice["text"])
                    self.assertEqual(menu.state(self.seats[0]), "needs you")
                    self.typed.assert_not_called()
                    self.meters.assert_not_called()
                    self.reset.assert_not_called()
                    self.assertIsNone(watch.auth_expired_on(harness, f'❯ Explain "{message}"'))
                    self.assertIsNone(watch.auth_expired_on(harness, self.pane + "\nReading tests"))

    def test_captured_401_panes_never_get_a_nudge(self):
        for harness in ("claude", "codex"):
            with self.subTest(harness=harness):
                self.harness = harness
                self.pane = (REPO / f"tests/fixtures/{harness}-auth-401-pane.txt").read_text()
                self.tick(1)
                self.assertEqual(menu.state(self.seats[0]), "needs you")
        self.typed.assert_not_called()

    def test_claude_captured_login_wrapper_accepts_arbitrary_401_and_403_server_messages(self):
        template = (REPO / "tests/fixtures/claude-auth-401-pane.txt").read_text()
        messages = (
            "OAuth token has expired. Please obtain a new token to continue using the API.",
            "invalid x-api-key",
            "OAuth token has been revoked",
            '{"error":{"type":"authentication_error","message":"The credential was rejected"}}',
        )
        for status in (401, 403):
            for number, message in enumerate(messages):
                with self.subTest(status=status, message=message):
                    name = f"auth-{status}-{number}"
                    self.seats = [{"name": name}]
                    self.sent.reset_mock()
                    # Keep Claude's captured wrapper and chrome. Only the server's
                    # status/message vary; capture-pane -J joins soft-wrapped lines.
                    self.pane = template.replace("401 Invalid API key", f"{status} {message}")
                    self.tick(1)
                    self.assertEqual(menu.state(self.seats[0]), "needs you")
                    self.assertIn("/login", notify.last(name)["text"])
                    self.assertIn(name, notify.last(name)["text"])
                    self.data = watch.load_state()
                    for seconds in (watch.NUDGE_EVERY,) * 3 + (watch.GIVE_UP,):
                        self.tick(seconds)
                    self.sent.assert_called_once()
                    self.typed.assert_not_called()
                    self.meters.assert_not_called()
                    self.reset.assert_not_called()
                    self.pane += "\nReading the next file"
                    self.tick(1)
                    self.assertEqual(menu.state(self.seats[0]), "needs you")

    def test_claude_login_instruction_inside_reworded_output_alerts_immediately(self):
        self.pane = self.fixture("claude").replace(
            "Login expired · Please run /login", "Session expired · Please run /login again")
        self.tick()
        self.tick(watch.GIVE_UP)
        self.sent.assert_called_once()
        self.assertEqual(menu.state(self.seats[0]), "needs you")
        self.typed.assert_not_called()

    def test_auth_is_read_even_on_exited_or_legacy_recorded_seats(self):
        self.seats[0].update(exited=True, legacy=True)
        self.tick()
        self.assertEqual(menu.state(self.seats[0]), "needs you")
        self.sent.assert_called_once()
        self.typed.assert_not_called()

    def test_unrecorded_seats_are_never_alerted_or_typed_into(self):
        self.harness = None
        self.tick()
        self.tick(watch.GIVE_UP)
        self.sent.assert_not_called()
        self.typed.assert_not_called()

    def test_one_adapter_manifest_extends_auth_watch_to_a_new_harness(self):
        """A harness plugs in with adapters/<h>.toml and no change to any Python file."""
        self.harness = "new-harness"
        self.pane = "Session login expired"
        adapters = self.root / "adapters"
        adapters.mkdir(parents=True, exist_ok=True)
        (adapters / "new-harness.toml").write_text(
            'version = 1\n[auth]\ntitle = "New harness"\n'
            'remedy = "run new-harness login"\nsignatures = ["Session login expired"]\n')
        with patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}):
            self.tick()
        self.assertIn("new-harness login", notify.last("auth-seat")["text"])
        self.assertEqual(menu.state(self.seats[0]), "needs you")
        self.typed.assert_not_called()

    @patch.object(watch, "live_state", return_value={"state": "working"})
    def test_unknown_stuck_pane_past_retry_budget_escalates_once_to_check_this_session(self, _live):
        self.pane = (REPO / "tests/fixtures/unknown-stuck-pane.txt").read_text()
        self.tick()
        self.tick(watch.GIVE_UP - 1)
        self.sent.assert_not_called()
        self.tick(1)
        self.sent.assert_called_once()
        notice = notify.last("auth-seat")
        self.assertEqual(notice["kind"], "needs")
        self.assertIn("auth-seat", notice["text"])
        self.assertIn("check this session", notice["text"])
        # The turn is still in flight, so the row keeps saying so; the card went out anyway.
        self.assertEqual(menu.state(self.seats[0]), "working")
        self.data = watch.load_state()
        self.tick(watch.GIVE_UP)
        self.sent.assert_called_once()
        self.typed.assert_not_called()

    @patch.object(watch, "live_state", return_value={"state": "working"})
    def test_unknown_logout_pane_without_an_error_prefix_escalates_on_every_harness(self, _live):
        template = (REPO / "tests/fixtures/unknown-logout-pane.txt").read_text()
        for harness in ("claude", "codex", "muse"):
            with self.subTest(harness=harness):
                self.harness = harness
                name = f"unknown-{harness}"
                self.seats = [{"name": name}]
                self.sent.reset_mock()
                # The failure wording is synthetic; retain each harness's captured chrome.
                self.pane = template if harness == "claude" else (
                    REPO / f"tests/fixtures/{harness}-stall-pane.txt").read_text()
                line = next(line for line in self.pane.splitlines() if line.startswith(("● ", "■ ", "◆ ")))
                self.pane = self.pane.replace(line, "Your session has expired · Run /login to continue")
                self.assertIsNone(watch.auth_expired_on(harness, watch.pane_tail(self.pane)))
                self.tick(1)
                self.tick(watch.GIVE_UP - 1)
                self.sent.assert_not_called()
                self.tick(1)
                self.data = watch.load_state()
                self.tick(watch.GIVE_UP)
                self.sent.assert_called_once()
                self.assertIn("check this session", notify.last(name)["text"])
                self.typed.assert_not_called()

    @patch.object(watch, "live_state", return_value={"state": "working"})
    def test_unknown_auth_cues_alongside_api_error_never_receive_capacity_nudges(self, _live):
        for number, text in enumerate(("API Error: 401 credentials refused",
                                       "API Error: 403 request rejected",
                                       "API Error: sign in to proceed",
                                       "API Error: access revoked",
                                       "API Error: unauthorized")):
            with self.subTest(text=text):
                name = f"suspected-{number}"
                self.seats = [{"name": name}]
                self.sent.reset_mock()
                self.pane = text
                self.assertIsNone(watch.auth_expired_on("claude", self.pane))
                self.tick(1)
                self.tick(watch.STALL_WAIT)
                self.tick(watch.GIVE_UP)
                self.sent.assert_called_once()
                self.assertIn("check this session", notify.last(name)["text"])
                self.typed.assert_not_called()

    @patch.object(watch, "live_state", return_value={"state": "working"})
    def test_capacity_retries_then_unknown_stall_escalates_without_blind_nudges(self, _live):
        self.pane = "API Error: 500"
        self.tick()
        self.tick(watch.STALL_WAIT)
        self.typed.assert_called_once()
        self.pane = "Error: session transport closed unexpectedly"
        self.tick()
        self.tick(watch.GIVE_UP)
        self.assertIn("check this session", notify.last("auth-seat")["text"])
        self.typed.assert_called_once()

    def test_idle_prompts_completed_answers_and_run_waits_never_alert(self):
        for harness in ("claude", "codex", "muse"):
            template = (REPO / f"tests/fixtures/{harness}-stall-pane.txt").read_text()
            line = next(line for line in template.splitlines() if line.startswith(("● ", "■ ", "◆ ")))
            for content in ("", "Completed the requested changes.", "Reading the next file",
                            "Waiting for ak run to finish", "No PRs awaiting a decision.",
                            "Error: test_menu, test_watch", "Tests failed: test_menu, test_watch",
                            "● Tests failed: test_menu, test_watch",
                            'Updated the message "Your session has expired · Run /login to continue".',
                            "Documented `Please run /login` for the help page."):
                with self.subTest(harness=harness, content=content):
                    self.harness = harness
                    self.pane = template.replace(line, content)
                    self.tick()
                    self.tick(watch.GIVE_UP * 2)
                    self.assertNotIn("auth-seat", self.data["stalls"])
                    self.sent.assert_not_called()
                    if watch.stop_enforced(harness):
                        # neither a stall nor an alert: a harness with no blocking end-of-turn
                        # hook has the three-way rule typed at it instead, once for each new
                        # thing it is seen to have stopped on
                        self.assertLessEqual(self.typed.call_count, 1)
                        self.assertTrue(all(call.args[1] == "continue"
                                            for call in self.typed.call_args_list))
                        self.typed.reset_mock()
                    else:
                        self.typed.assert_not_called()

    def test_exited_and_legacy_seats_never_get_catch_all_alerts(self):
        self.pane = "Error: session transport closed unexpectedly"
        for flags in ({"exited": True}, {"legacy": True}):
            with self.subTest(flags=flags):
                self.seats = [{"name": "auth-seat", **flags}]
                self.tick()
                self.tick(watch.GIVE_UP * 2)
                self.sent.assert_not_called()
                self.typed.assert_not_called()
                self.assertNotIn("auth-seat", self.data["stalls"])

    def test_idle_hour_then_capacity_error_still_resumes_every_three_minutes(self):
        self.pane = "Completed the requested changes.\n❯"
        self.tick()
        self.tick(watch.GIVE_UP)
        self.sent.assert_not_called()
        self.pane = "API Error: 500"
        self.tick()
        self.tick(watch.STALL_WAIT)
        self.tick(watch.NUDGE_EVERY)
        self.assertEqual(self.typed.call_count, 2)
        self.assertEqual(self.typed.call_args.args[1], "continue")

    @patch.object(watch, "live_state", return_value={"state": "working"})
    def test_quiet_alert_releases_on_progress_and_cannot_block_capacity_recovery(self, _live):
        self.pane = "Error: session transport closed unexpectedly"
        self.tick()
        self.tick(watch.GIVE_UP)
        self.sent.assert_called_once()
        stale = copy.deepcopy(self.data)
        self.pane = "API Error: 500"
        self.tick(1)
        self.assertIsNone(notify.last("auth-seat"))
        watch.save_state(stale)
        self.assertFalse(watch.load_state()["stalls"]["auth-seat"].get("told"))
        self.data = watch.load_state()
        self.tick(watch.STALL_WAIT)
        self.tick(watch.NUDGE_EVERY)
        self.assertEqual(self.typed.call_count, 2)
        self.tick(watch.GIVE_UP)
        self.assertEqual(self.sent.call_count, 2)
        self.assertIn("stalled on API Error", notify.last("auth-seat")["text"])

    def test_previous_false_idle_alert_is_cleared_without_erasing_a_newer_notice(self):
        self.pane = "Completed the requested changes.\n❯"
        notice = watch.stuck_notice("auth-seat", "claude")
        for newer in (None, "May I merge this PR?"):
            with self.subTest(newer=newer):
                self.now += 1
                notify.shaped("needs", notice, session="auth-seat")
                self.data["stalls"]["auth-seat"] = {
                    "kind": "quiet", "pane": self.pane, "since": 1, "told": self.now}
                watch.save_state(self.data)
                stale = copy.deepcopy(self.data)
                if newer:
                    self.now += 1
                    notify.shaped("needs", newer, session="auth-seat")
                self.tick()
                watch.save_state(stale)
                self.assertNotIn("auth-seat", watch.load_state()["stalls"])
                last = notify.last("auth-seat")
                self.assertEqual(last["text"] if last else None, newer)

    def test_progress_anywhere_in_the_pane_restarts_unknown_stuck_clock(self):
        self.pane = ("Reading the first file\n" + "line\n" * 20 +
                     "Error: session transport closed unexpectedly")
        self.tick()
        self.pane = self.pane.replace("first", "second")
        self.tick(watch.GIVE_UP)
        self.tick(watch.GIVE_UP - 1)
        self.sent.assert_not_called()
        self.typed.assert_not_called()

    def test_attach_during_capture_prevents_a_new_auth_alert(self):
        def capture(_):
            orch.seen_by_user("auth-seat")
            return self.pane
        with patch.object(watch, "pane_text", side_effect=capture):
            self.tick()
        self.sent.assert_not_called()
        self.typed.assert_not_called()

    def test_auth_appearing_during_meter_io_cannot_receive_a_capacity_nudge(self):
        self.harness = "codex"
        self.pane = "usage limit reached"
        self.tick()
        self.reset.side_effect = lambda *_: setattr(self, "pane", self.fixture("codex"))
        self.tick(watch.STALL_WAIT)
        self.typed.assert_not_called()
        self.tick()
        self.assertEqual(menu.state(self.seats[0]), "needs you")

    def test_dry_run_never_notifies_types_or_persists_login_state(self):
        before = watch.load_state()
        self.tick(dry=True)
        self.assertEqual(watch.load_state(), before)
        self.assertTrue(any("would notify needs" in line for line in self.logs))
        self.sent.assert_not_called()
        self.typed.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
