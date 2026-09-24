"""What a live seat is doing, and who has the authority to say it.

Offline and deterministic: the captured panes under tests/fixtures/ and hook facts written by
hand, with the real adapters/<harness>.toml deciding what each one means.  No harness, no
network and no tmux is involved -- `ak orch`'s tmux calls are answered by the fixture itself.
The shell half of the same behaviour -- a hook writing nothing for a worker, and every
adapter's `hooks` verb being idempotent -- is `seat_state_check` in tests/smoke.sh, which runs
this file for everything Python can hold.
"""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, notify, orch, terminal, watch

FIXTURES = config.REPO / "tests/fixtures"


class SeatStates(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(
            prefix=".seat-state-", dir=config.REPO)))
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(root),
            "AK_RUN_ROLE": "orchestrator", "AGENTKIT_DISCORD_WEBHOOK": "",
            notify.SINK_ENV: "",   # this fixture is the one naming the destination
            "AGENTKIT_DISCORD_USER_ID": "", config.SESSION_ENV: "seat"}))
        config.ensure_dirs()
        self.cfg = config.load()
        config.save_session(self.cfg, "seat", "opus", ["astra"])     # a Claude seat
        self.seat = {"name": "seat", "attached": False, "exited": False,
                     "created": time.time() - 86400, "path": str(root)}
        self.seats = [self.seat]
        self.options = {}
        self.pane = self.fixture("claude", "prompt")
        self.stack.enter_context(patch.object(orch, "sessions", lambda: self.seats))
        self.stack.enter_context(patch.object(orch, "listing", lambda *_a, **_k: self.seats))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(orch, "inside", return_value=True))

    def fixture(self, harness, kind):
        return (FIXTURES / f"{harness}-{kind}-pane.txt").read_text()

    def tmux(self, *args, **kwargs):
        if args[0] == "set-option":
            self.options[args[3]] = args[4]      # set-option -t <seat> <option> <value>
        return 0, self.pane if args[0] == "capture-pane" else ""

    def fact(self, event, kind="", text="", at=None):
        """What a lifecycle hook would have written for this seat."""
        config.hook_facts_path("seat").write_text(json.dumps(
            {"session": "seat", "event": event, "kind": kind, "text": text,
             "at": time.time() if at is None else at}))

    def open_seat(self):
        # redirect first: the isatty patches have to land on the stdout attach will look at
        with redirect_stdout(io.StringIO()), patch("sys.stdin.isatty", return_value=True), \
                patch("sys.stdout.isatty", return_value=True):
            self.assertEqual(orch.attach("seat", wait=True), 0)

    # --- (a) ---------------------------------------------------------------
    def test_a_turn_ended_reads_needs_you(self):
        ended = time.time() - 3 * 3600
        self.fact("Stop", at=ended)
        self.assertEqual(menu.status(self.seat), ("needs you", ended))
        self.assertEqual(menu.row(self.cfg, 1, self.seat)[3:],
                         ["needs you", "waiting for you", "3h"])
        self.assertEqual(orch.state_word(self.seat, self.cfg), "needs you")
        self.open_seat()                      # the same open v4x records, and nothing else
        word, since = menu.status(self.seat)
        self.assertEqual(word, "needs you")
        self.assertGreaterEqual(since, ended)
        self.assertEqual(watch.seat_read("seat")["authority"], "hook")

    # --- (b) ---------------------------------------------------------------
    def test_b_a_turn_begun_after_the_last_one_ended_reads_working_since_it_began(self):
        began = time.time() - 12 * 60
        self.fact("Stop", at=began - 600)     # the newest fact is the one that counts
        self.fact("UserPromptSubmit", at=began)
        for pane in (self.fixture("claude", "working"), "thinking about the parser"):
            with self.subTest(pane=pane[:20]):
                self.pane = pane
                self.assertEqual(menu.status(self.seat), ("working", began))
                self.assertEqual(orch.age(began), "12m")
                self.assertEqual(watch.seat_read("seat")["authority"], "hook")
                self.assertEqual(watch.seat_read("seat")["rule"], "UserPromptSubmit")

    def test_b2_a_question_the_harness_never_retracts_is_retired_by_its_own_screen(self):
        """Claude 2.1.263 reports a prompt going up and nothing when it comes down."""
        self.fact("Notification", kind="permission_prompt",
                  text="Claude needs your permission to use Bash")
        self.assertEqual(menu.state(self.seat), "needs you")   # the screen has moved on
        self.pane = self.fixture("claude", "working")
        self.assertEqual(menu.state(self.seat), "working")
        self.pane = "streaming an answer"     # nothing positive on the screen: the hook stands
        self.assertEqual(menu.state(self.seat), "needs you")
        self.assertEqual(watch.seat_read("seat")["evidence"],
                         "Claude needs your permission to use Bash")

    # --- (c) ---------------------------------------------------------------
    def test_c_every_dialog_fixture_reads_asking_and_a_transcript_quoting_it_does_not(self):
        for harness in ("claude", "codex", "muse"):
            with self.subTest(harness=harness):
                dialog = self.fixture(harness, "dialog")
                state, rule, evidence = watch.screen_state(harness, watch.pane_tail(dialog))
                self.assertEqual(state, "asking", rule)
                self.assertTrue(rule.startswith("asking."), rule)
                self.assertTrue(evidence.strip(), evidence)
                # the same words, quoted back in the transcript above a composer at the prompt
                quoted = "\n".join(f"● it said {line.strip()!r}" for line in dialog.splitlines()
                                   if line.strip()) + "\n" + self.fixture(harness, "prompt")
                self.assertEqual(watch.screen_state(harness, watch.pane_tail(quoted))[0],
                                 "at_prompt")

    # --- (d) ---------------------------------------------------------------
    def test_d_notified_and_unnotified_seats_never_borrow_each_other_s_word(self):
        self.fact("Stop", at=time.time() - 600)
        self.assertEqual(menu.state(self.seat), "needs you")
        self.assertIsNone(notify.last("seat"))          # and nothing here ever posts one
        with redirect_stdout(io.StringIO()):
            self.assertEqual(notify.shaped("needs", "May I merge?", session="seat"), 0)
        self.assertEqual(menu.state(self.seat), "needs you")
        self.assertEqual(menu.row(self.cfg, 1, self.seat)[4], "May I merge?")
        self.pane = self.fixture("claude", "prompt")
        self.assertEqual(menu.state(self.seat), "needs you")
        self.pane = self.fixture("claude", "working")
        self.assertEqual(menu.state(self.seat), "working")
        self.pane = self.fixture("claude", "dialog")
        self.assertEqual(menu.state(self.seat), "needs you")

    # --- (e) ---------------------------------------------------------------
    def test_e_two_renders_and_a_watch_tick_agree_on_the_word_and_the_since(self):
        self.fact("Stop", at=time.time() - 7200)
        first = menu.status(self.seat)
        self.assertEqual(first, menu.status(self.seat))
        with patch.object(watch, "seat_model", lambda *_: ("claude", "anthropic")), \
                patch.object(notify, "progress", return_value=None):
            watch.health(self.cfg, {"stalls": {}}, False, lambda _: None)
        self.assertEqual(menu.status(self.seat), first)
        self.assertEqual(self.options[orch.STATE_OPTION], "needs you")

    def test_e2_a_live_state_is_never_a_reason_to_type_into_a_seat(self):
        """Classifying is looking. Only a harness's own stall signature moves the babysitter."""
        with patch.object(watch, "seat_model", lambda *_: ("claude", "anthropic")), \
                patch.object(notify, "progress", return_value=None), \
                patch.object(watch, "type_into", return_value=True) as typed:
            for kind, word in (("prompt", "needs you"), ("dialog", "needs you"),
                               ("working", "working")):
                with self.subTest(kind=kind):
                    self.pane = self.fixture("claude", kind)
                    state = {"stalls": {}}
                    for _ in range(2):          # well past STALL_WAIT on an unchanged pane
                        watch.health(self.cfg, state, False, lambda _: None)
                        for entry in state["stalls"].values():
                            for key in ("since", "stall_at", "changed_at"):
                                entry[key] = entry.get(key, 0) - watch.GIVE_UP
                    self.assertEqual(menu.state(self.seat), word)
                    typed.assert_not_called()
                    self.assertEqual(state["stalls"], {})

    # --- (f) ---------------------------------------------------------------
    def test_f_the_babysitter_reads_every_signature_from_the_adapter_manifests(self):
        for harness in ("claude", "codex", "muse"):
            with self.subTest(harness=harness):
                with (config.REPO / f"adapters/{harness}.toml").open("rb") as fh:
                    data = tomllib.load(fh)
                self.assertEqual(watch.stalls(harness), tuple(data["stall"]["signatures"]))
                self.assertEqual(watch.quotas(harness), tuple(data["stall"]["quotas"]))
                self.assertEqual(watch.auth_expiry(harness)[:2],
                                 (data["auth"]["title"], data["auth"]["remedy"]))
                self.assertEqual(watch.auth_expiry(harness)[2],
                                 tuple(data["auth"]["signatures"]))
                stall = (FIXTURES / f"{harness}-stall-pane.txt").read_text()
                self.assertIn(watch.stalled_on(harness, watch.pane_tail(stall), harness,
                                               lambda _: None), watch.stalls(harness))
                auth = (FIXTURES / f"{harness}-auth-pane.txt").read_text()
                self.assertIsNotNone(watch.auth_expired_on(harness, watch.pane_tail(auth)))
        goal = (FIXTURES / "codex-stall-pane.txt").read_text().replace(
            "exceeded retry limit, last status: 429 Too Many Requests", "Goal stalled")
        self.assertEqual(watch.keystroke("codex", goal), "/goal resume")
        self.assertEqual(watch.keystroke("claude", goal), "continue")
        self.assertTrue(watch.reset_policy("codex"))
        self.assertFalse(watch.reset_policy("claude") or watch.reset_policy("muse"))
        # and no harness is named in the babysitter any more, for a signature or anything else
        source = (config.REPO / "agentkit/watch.py").read_text()
        for harness in ("claude", "codex", "muse"):
            self.assertNotIn(f'"{harness}"', source)

    # --- (h) ---------------------------------------------------------------
    def test_h_orch_list_why_names_the_authority_the_rule_and_the_evidence(self):
        self.fact("Stop", at=time.time() - 5400)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(orch.cmd_list(["--why"]), 0)
        text = out.getvalue()
        self.assertIn("needs you", text)
        self.assertIn("authority: hook", text)
        self.assertIn("rule: Stop", text)
        self.assertIn("evidence:", text)
        self.assertRegex(text, r"since:\s+\d{4}-\d\d-\d\d \d\d:\d\d \(1h ago\)")
        self.pane = self.fixture("claude", "dialog")
        config.hook_facts_path("seat").unlink()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(orch.cmd_why(["seat"]), 0)
        text = out.getvalue()
        self.assertIn("needs you", text)
        self.assertIn("authority: screen", text)
        self.assertIn("rule: asking.trust", text)
        self.assertIn("Enter to confirm", text)
        with self.assertRaises(config.Error):
            orch.cmd_list(["extra"])
        with self.assertRaises(config.Error):
            orch.cmd_why([])

    # --- the row still fits, with the longest word on it --------------------
    def test_the_longest_live_word_is_drawn_whole_at_forty_and_a_hundred_columns(self):
        rows = [["1", "atoll-fix", "fable", "needs you", "", "3h"],
                ["2", "web-portal", "astra", "working", "", "12m"]]
        for width in (40, 100):
            with self.subTest(width=width):
                lines = terminal.seats(rows, width - 1)
                self.assertIn("needs you", "\n".join(lines))
                self.assertTrue(all(terminal.cells(line) <= width for line in lines))


if __name__ == "__main__":
    unittest.main(verbosity=2)
