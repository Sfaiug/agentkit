"""v5p: a typed line waits out its composer, and proves it left.

Offline: `orch.tmux_out` is a fake recording an event log and serving a scripted pane,
and `watch.time.sleep` only records its pauses.  The composer patterns and screen rules
are the real adapters/<harness>.toml ones, read through `watch.screen`/`classify`, and
the held-text and dialog cases drive the real tests/fixtures/*-pane.txt captures.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import fcntl
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, orch, watch

SENT = "API Error: 500\n\u276f"
UNSENT = "API Error: 500\n\u276f continue"
WORKING = "thinking\nesc to interrupt\nworking on it"
HARNESSES = ("claude", "codex", "muse")


def fixture(harness, kind):
    return (REPO / f"tests/fixtures/{harness}-{kind}-pane.txt").read_text()


def held(harness):
    """That harness's stall capture with `continue` sitting unsent in its composer."""
    pane = fixture(harness, "stall")
    if harness == "claude":
        return pane.replace("\u276f\u00a0", "\u276f continue")
    if harness == "muse":
        return pane.replace("\n\u27e9\n", "\n\u27e9 continue\n")
    return pane.replace("\u203a Ask Codex to do anything\n",
                        "\u203a Ask Codex to do anything continue\n")


class V5p(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-v5p-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root),
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "AK_RUN_ROLE": "orchestrator",
            "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": "",
        }))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        self.events = []
        self.stack.enter_context(
            patch.object(watch.time, "sleep", lambda s: self.events.append(("sleep", s))))
        self.panes = []
        self.session = {"name": "seat"}
        self.logs = []

    def fake_tmux(self, panes):
        self.panes = list(panes)

        def out(*args, socket=None, client=False, **_kw):
            if args[0] == "send-keys":
                self.events.append(("send", args))
                return 0, ""
            if args[0] == "capture-pane":
                self.events.append(("capture",))
                return 0, self.panes.pop(0) if len(self.panes) > 1 else self.panes[0]
            return 0, ""

        return patch.object(orch, "tmux_out", side_effect=out)

    def sends(self, *want):
        return [e[1] for e in self.events
                if e[0] == "send" and all(w in e[1] for w in want)]

    def test_v5p_sequence_is_text_gap_then_enter(self):
        with self.fake_tmux([SENT, SENT]):
            self.assertTrue(watch.type_checked(self.session, "continue", self.logs.append,
                                              "claude"))
        text_at = next(i for i, e in enumerate(self.events)
                       if e[0] == "send" and "-l" in e[1])
        gap_at = next(i for i, e in enumerate(self.events) if e[0] == "sleep")
        enter_at = next(i for i, e in enumerate(self.events)
                        if e[0] == "send" and e[1][-1] == "Enter")
        self.assertLess(text_at, gap_at, self.events)
        self.assertLess(gap_at, enter_at, self.events)
        self.assertGreaterEqual(self.events[gap_at][1], watch.KEY_GAP)

    def test_v5p_composer_emptied_on_first_enter_returns_true_without_second_enter(self):
        with self.fake_tmux([SENT] * 11):
            self.assertTrue(watch.type_checked(self.session, "continue", self.logs.append,
                                              "claude"))
        self.assertEqual(len(self.sends("-l")), 1)
        self.assertEqual(len(self.sends("Enter")), 1)

    def test_v5p_holding_composer_gets_one_more_enter_then_true(self):
        panes = [SENT] + [UNSENT] * int(watch.SENT_WAIT / watch.SENT_POLL) + [SENT]
        with self.fake_tmux(panes):
            self.assertTrue(watch.type_checked(self.session, "continue", self.logs.append,
                                              "claude"))
        self.assertEqual(len(self.sends("-l")), 1)
        self.assertEqual(len(self.sends("Enter")), 2)

    def test_v5p_still_held_after_second_warns_and_returns_false(self):
        text = "continue " + "x" * 71
        stuck = f"API Error: 500\n\u276f {text}"
        with self.fake_tmux([SENT] + [stuck] * 30):
            self.assertFalse(watch.type_checked(self.session, text, self.logs.append,
                                               "claude"))
        self.assertEqual(len(self.sends("-l")), 1)
        self.assertEqual(len(self.sends("Enter")), 2)
        warned = [line for line in self.logs if "unsent in its composer" in line]
        self.assertEqual(len(warned), 1)
        self.assertIn("seat", warned[0])
        self.assertIn(text[:60], warned[0])

    def test_v5p_inbox_and_type_into_share_helper(self):
        seen = []
        with patch.object(watch, "type_checked",
                          side_effect=lambda *a, **k: seen.append((a, k)) or True), \
                patch.object(watch, "seat_model", return_value=("claude", "test")), \
                patch.object(orch, "ensure", return_value=False), \
                patch.object(orch, "find", return_value={"name": "inbox"}), \
                patch.object(notify, "shaped", return_value=0):
            watch.ask_inbox({}, "Merge? yes/no", "https://example.test/pr/7",
                            "abc123def456", self.logs.append)
            self.assertTrue(watch.type_into({"name": "seat"}, "continue", self.logs.append))
        self.assertEqual([a[0]["name"] for a, _ in seen], ["inbox", "seat"])

    def test_v5p_working_counts_as_sent_without_composer(self):
        with self.fake_tmux([SENT] + [WORKING] * 10):
            self.assertTrue(watch.type_checked(self.session, "continue", self.logs.append,
                                              "claude"))
        self.assertEqual(len(self.sends("Enter")), 1)

    def test_v5p_seat_with_no_composer_counts_a_delivered_send_as_sent(self):
        with self.fake_tmux(["just a shell\n$ "] * 3):
            self.assertTrue(watch.type_checked(self.session, "continue", self.logs.append,
                                              "claude"))
        self.assertEqual(len(self.sends("-l")), 1)
        self.assertEqual(len(self.sends("Enter")), 1)
        self.assertEqual([e[1] for e in self.events if e[0] == "sleep"], [watch.KEY_GAP])
        self.assertFalse(any("unsent in its composer" in line for line in self.logs))

    def test_v5p_lock_covers_text_gap_and_enters_not_confirmation_waits(self):
        class Rec:
            def __enter__(inner):
                self.events.append(("guard", "enter"))
                return "seat"

            def __exit__(inner, *args):
                self.events.append(("guard", "exit"))
                return False

        polls = int(watch.SENT_WAIT / watch.SENT_POLL)
        panes = [SENT] + [UNSENT] * (polls + 1) + [SENT]
        with self.fake_tmux(panes):
            self.assertTrue(watch.type_checked(self.session, "continue", self.logs.append,
                                              "claude", guard=lambda: Rec()))
        depth, spans = 0, []
        for event in self.events:
            if event == ("guard", "enter"):
                depth += 1
            elif event == ("guard", "exit"):
                depth -= 1
            elif event[0] == "sleep":
                spans.append((event[1], depth))
            elif event[0] == "send":
                self.assertEqual(depth, 1, event)
            elif event[0] == "capture":
                self.assertEqual(depth, 0, event)
        self.assertEqual(spans, [(watch.KEY_GAP, 1)] + [(watch.SENT_POLL, 0)] * (polls + 1))
        self.assertEqual(len(self.sends("Enter")), 2)

    def test_v5p_second_sender_waits_for_first_enter(self):
        waiting = threading.Event()
        senders = []

        def second():
            with config.notify_path("seat").with_suffix(".lock").open("a") as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    locked = True
                else:
                    locked = False
                    fcntl.flock(handle, fcntl.LOCK_UN)
            waiting.set()
            sent = watch.type_checked(self.session, "/rename quay", self.logs.append,
                                      "claude", guard=lambda: notify.session_lock("seat"))
            return locked, sent

        def sleep(seconds):
            if len(self.sends("-l")) == 1:
                senders.append(pool.submit(second))
                self.assertTrue(waiting.wait(5), "second sender never reached the lock")

        with ThreadPoolExecutor(max_workers=1) as pool, self.fake_tmux([SENT]), \
                patch.object(watch.time, "sleep", side_effect=sleep):
            self.assertTrue(watch.type_checked(self.session, "continue", self.logs.append,
                                              "claude", guard=lambda: notify.session_lock("seat")))
            self.assertEqual(senders[0].result(timeout=5), (True, True))
        self.assertEqual([args[-1] for args in self.sends()],
                         ["continue", "Enter", "/rename quay", "Enter"])

    def test_v5p_veto_after_typing_does_not_strand_the_line(self):
        vetoes = []

        def veto(name):
            vetoes.append(name)
            return bool(self.sends("-l"))

        with self.fake_tmux([SENT]):
            self.assertTrue(watch.type_checked(self.session, "continue", self.logs.append,
                                              "claude", guard=lambda: notify.session_lock("seat"),
                                              veto=veto))
        self.assertEqual(vetoes, ["seat"])
        self.assertEqual([args[-1] for args in self.sends()], ["continue", "Enter"])

    def test_v5p_real_stall_fixture_with_held_text_retries_then_warns(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                del self.events[:], self.logs[:]
                stall, held_pane = fixture(harness, "stall"), held(harness)
                self.assertNotEqual(held_pane, stall)
                self.assertTrue(watch._holds_text(held_pane, "continue"))
                self.assertFalse(watch._holds_text(stall, "continue"))
                with self.fake_tmux([stall] + [held_pane] * 25):
                    self.assertFalse(watch.type_checked({"name": "seat"}, "continue",
                                                        self.logs.append, harness))
                self.assertEqual(len(self.sends("-l")), 1)
                self.assertEqual(len(self.sends("Enter")), 2)
                self.assertTrue(any("unsent in its composer" in line for line in self.logs))

    def test_v5p_dialog_after_landing_gets_no_second_enter(self):
        for harness in HARNESSES:
            with self.subTest(harness=harness):
                del self.events[:], self.logs[:]
                with self.fake_tmux([fixture(harness, "stall")] +
                                     [fixture(harness, "dialog")] * 11):
                    self.assertTrue(watch.type_checked({"name": "seat"}, "continue",
                                                       self.logs.append, harness))
                self.assertEqual(len(self.sends("-l")), 1)
                self.assertEqual(len(self.sends("Enter")), 1)
                self.assertFalse(any("unsent in its composer" in line for line in self.logs))

    def test_v5p_gaps_match_the_compaction_pause_and_wait(self):
        self.assertEqual(watch.KEY_GAP, 0.5)
        self.assertEqual(watch.SENT_WAIT, 5.0)
        self.assertEqual(watch.SENT_POLL, 0.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
