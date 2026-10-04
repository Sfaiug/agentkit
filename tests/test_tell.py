"""`ak tell`: one seat's message reaches another, typed by the tick, never as the owner's words.

The sender only queues it; `tell.deliver` is the tick's pass.  Offline: a temporary HOME, a
fake tmux and pane; no real seat, transcript or state.
"""

from contextlib import ExitStack, nullcontext, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, harness, notify, orch, tell, watch
from agentkit.harness import claude

SENDER, SEAT = "fix-api", "acme-docs"
NOW = 1_000_000.0
QUEUED = f"{SEAT}: queued; ak types it at its next quiet prompt"


def prompt(at, text):
    return {"type": "user", "timestamp": datetime.fromtimestamp(at, timezone.utc).isoformat(),
            "message": {"role": "user", "content": text}}


class Seats(unittest.TestCase):
    """Two seats in a temporary HOME, the receiver's pane and tmux faked."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-tell-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": SENDER, "AGENTKIT_RUN": "",
            "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AK_NOTIFY_SINK": "dry-run"}))
        for name in ("HOME", "STATE", "RUNS", "WT", "WORK", "TMP", "SECRETS", "ENV", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / ".agentkit" / name.lower()))
        self.cfg = config.load()
        config.ensure_dirs()
        for name in (SENDER, SEAT):
            config.save_session(self.cfg, name, "opus", ["astra"], {
                "cwd": str(self.root / name), "conversation": "thread",
                "id_source": harness.LAUNCHER})
        self.seat = {"name": SEAT, "created": 10, "legacy": False}
        self.free, self.typed = True, []
        stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        stack.enter_context(patch.object(orch, "find", side_effect=lambda name:
                                         self.seat if name == self.seat["name"] else None))
        stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        stack.enter_context(patch.object(watch, "at_prompt", side_effect=lambda *_a, **_kw: self.free))
        stack.enter_context(patch.object(watch, "pane_text", return_value=""))
        stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        stack.enter_context(patch.object(watch.time, "sleep"))
        stack.enter_context(patch.object(watch.time, "time", return_value=NOW))

    def tmux(self, *args, **_kw):
        self.assertEqual(args[0], "send-keys")
        self.assertEqual(args[args.index("-t") + 1], f"={self.seat['name']}:")
        if "-l" in args:
            self.typed.append(args[-1])
        return 0, ""

    def tell(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = tell.main(list(argv))
        return code, out.getvalue().strip(), err.getvalue().strip()

    def header(self, sender=SENDER):
        return (f"[from seat {sender} at {time.strftime('%H:%M', time.localtime(NOW))}, not the owner; "
                f"reply with ak tell {sender}] ")

    def receipts(self, name=SEAT):
        return list(harness.entries(config.seat_file("input", name)))

    def waiting(self, name=SEAT):
        return tell.read(config.seat_file("tell", name))

    def opened(self, created):
        """The seat named SEAT, opened at `created`: a new one where that differs."""
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {
            "cwd": str(self.root / SEAT), "conversation": f"thread-{created}",
            "id_source": harness.LAUNCHER, "created": created})
        watch.seat_write(SEAT, stopped_at=None)


class Tell(Seats):
    def tick(self):
        tell.deliver(self.cfg, lambda _: None)

    def test_the_sender_queues_and_the_tick_types_it_headed_with_who_sent_it(self):
        code, out, _ = self.tell(SEAT, "Parser merged.\n  Leave parser.py alone.")
        self.assertEqual((code, out), (0, QUEUED))
        self.assertEqual(self.typed, [])
        queued = self.waiting()[0]["id"]
        self.tick()
        line = self.header() + "Parser merged. Leave parser.py alone."
        self.assertEqual(self.typed, [line])
        self.assertEqual([(row["source"], row["ref"], row["text"]) for row in self.receipts()],
                         [(f"seat:{SENDER}", queued, line)])
        self.assertEqual(self.waiting(), [])

    def test_a_busy_seat_gets_it_once_at_its_next_quiet_prompt(self):
        self.free = False
        self.tell(SEAT, "Parser merged.")
        self.tick()
        self.assertEqual(self.typed, [])
        self.free = True
        self.tick()
        self.tick()
        self.assertEqual(self.typed, [self.header() + "Parser merged."])
        self.assertEqual(self.waiting(), [])

    def test_messages_go_in_oldest_first_one_per_quiet_prompt(self):
        self.tell(SEAT, "First.")
        self.tell(SEAT, "Second.")
        self.tick()
        self.assertEqual(self.typed, [self.header() + "First."])
        self.tick()
        self.assertEqual(self.typed, [self.header() + "First.", self.header() + "Second."])

    def test_an_open_owner_question_holds_it_until_answered(self):
        notify.record(SEAT, "needs", "Which schema should acme use?")
        code, out, _ = self.tell(SEAT, "Parser merged.")
        self.assertEqual((code, out),
                         (0, f"{SEAT}: queued; ak types it after the owner answers its question"))
        self.tick()
        self.assertEqual(self.typed, [])
        self.assertEqual(len(self.waiting()), 1)

    def test_a_told_line_is_never_the_owners_words(self):
        self.tell(SEAT, "Parser merged.")
        self.tick()
        record = config.session_records()[SEAT]
        path = claude.transcript_path(record, "thread")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(prompt(101, self.typed[0])) + "\n"
                        + json.dumps(prompt(102, "Use the second schema.")) + "\n")
        plugin = orch.seat_plugin(record)
        self.assertEqual(plugin.user_messages(record, record["cwd"], "thread", seat=SEAT),
                         [{"at": 102, "text": "Use the second schema."}])

    def test_a_renamed_seat_gets_what_was_sent_to_its_old_name(self):
        self.tell(SEAT, "Parser merged.")
        config.rename_session(SEAT, "acme-pages")
        self.seat = {"name": "acme-pages", "created": 10, "legacy": False}
        self.tick()
        self.assertEqual(self.typed, [self.header() + "Parser merged."])
        self.assertEqual(self.tell(SEAT, "Docs too.")[1],
                         "acme-pages: queued; ak types it at its next quiet prompt")
        self.tick()
        self.assertEqual(self.typed[-1], self.header() + "Docs too.")

    def test_a_message_sent_while_its_receiver_is_renamed_reaches_it(self):
        """The sender waits on the receiver's lock, the one a rename takes, and queues under
        the name it goes by once that is free."""
        sent = []
        with notify.session_lock(SEAT):
            sender = threading.Thread(target=lambda: sent.append(self.tell(SEAT, "Parser merged.")))
            sender.start()
            sender.join(0.5)
            self.assertEqual(sent, [])
            config.rename_session(SEAT, "acme-pages")
            self.seat = {"name": "acme-pages", "created": 10, "legacy": False}
        sender.join(10)
        self.assertEqual(sent[0][:2], (0, "acme-pages: queued; ak types it at its next quiet prompt"))
        self.tick()
        self.assertEqual(self.typed, [self.header() + "Parser merged."])
        self.assertEqual(self.waiting("acme-pages"), [])
        self.assertFalse(config.seat_file("tell", SEAT).exists())

    def test_a_receiver_closed_while_the_sender_waits_is_refused_then(self):
        self.opened(1.0)
        sent = []
        with notify.session_lock(SEAT):
            sender = threading.Thread(target=lambda: sent.append(self.tell(SEAT, "Parser merged.")))
            sender.start()
            sender.join(0.5)
            watch.seat_write(SEAT, stopped_at=NOW)
        sender.join(10)
        code, _, err = sent[0]
        self.assertEqual(code, 1, sent)
        self.assertIn(f"{SEAT} is closed", err)
        self.assertEqual(self.waiting(), [])

    def test_a_message_for_a_seat_closed_and_opened_again_never_reaches_the_new_one(self):
        self.opened(1.0)
        self.tell(SEAT, "Parser merged.")
        self.opened(2.0)
        self.tick()
        self.assertEqual(self.typed, [])
        self.assertEqual(self.waiting(), [])

    def test_a_receiver_replaced_while_its_message_is_typed_never_gets_it(self):
        self.opened(1.0)
        self.tell(SEAT, "Docs merged.")
        real_type = watch.type_at_prompt

        def replace_then_type(*args, **kwargs):
            self.opened(3.0)
            return real_type(*args, **kwargs)

        with patch.object(watch, "type_at_prompt", side_effect=replace_then_type):
            self.tick()
        self.assertEqual(self.typed, [])
        self.tick()
        self.assertEqual(self.typed, [])
        self.assertEqual(self.waiting(), [])

    def test_what_cannot_be_told_is_refused_in_one_line(self):
        watch.seat_write("acme-closed", stopped_at=1)
        config.save_session(self.cfg, "acme-closed", "opus", ["astra"], {"cwd": str(self.root)})
        for argv, said in (
                ((SENDER, "hi"), f"ak tell: {SENDER} is this seat"),
                (("acme-nobody", "hi"), "ak tell: no session 'acme-nobody'; `ak orch list` shows them"),
                (("acme-closed", "hi"), "ak tell: acme-closed is closed"),
                ((SEAT, " \n "), "ak tell: nothing to say"),
                ((SEAT, "x" * tell.MAX_BYTES), "more than one typed line holds")):
            with self.subTest(argv=argv[0]):
                code, out, err = self.tell(*argv)
                self.assertEqual((code, out), (1, ""))
                self.assertIn(said, err)
        with patch.dict(os.environ, {"AGENTKIT_SESSION": ""}):
            self.assertEqual(self.tell(SEAT, "hi")[0], 1)
        with self.assertRaises(config.Error):
            tell.main([SEAT])
        self.tick()
        self.assertEqual(self.typed, [])
        self.assertEqual(self.waiting(), [])


class TyperDied(Seats):
    """The tick typing a message dies at some key: the next tick finishes it, once.

    A real pane: the composer shows what is typed, Enter takes it into the conversation."""

    def setUp(self):
        super().setUp()
        self.opened(1.0)
        self.idle = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text(encoding="utf-8")
        self.pane, self.taken, self.killed_after_text = self.idle, [], False
        self.killed_before_text = False
        record = config.session_records()[SEAT]
        self.transcript = claude.transcript_path(record, record["conversation"])
        self.transcript.parent.mkdir(parents=True)
        for target, kwargs in ((watch, {"at_prompt": watch.at_prompt}),
                               (watch, {"pane_text": lambda *_a, **_kw: self.pane}),
                               (orch, {"tmux_out": self.render})):
            for attribute, value in kwargs.items():
                patcher = patch.object(target, attribute, side_effect=value)
                patcher.start()
                self.addCleanup(patcher.stop)

    EMPTY = "❯\u00a0\n"           # the composer's prompt row with nothing in it

    def render(self, *args, **kwargs):
        if "-l" in args and self.killed_before_text:
            self.killed_before_text = False
            raise KeyboardInterrupt("killed before its keys reached tmux")
        self.tmux(*args, **kwargs)
        if "-l" in args:
            self.pane = self.idle.replace(self.EMPTY, "❯ " + args[-1] + "\n")
            if self.killed_after_text:
                self.killed_after_text = False
                raise KeyboardInterrupt("killed right after the text went in")
        elif args[-1] == "Enter" and self.pane != self.idle:
            self.taken.append(self.typed[-1])
            if self.transcript:
                with self.transcript.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(prompt(NOW + len(self.taken), self.taken[-1])) + "\n")
            self.pane = self.idle
        return 0, ""

    def died(self, step=None, before_text=False):
        """The tick typing a queued message killed in that step of watch's, else right before
        or after its text went in."""
        self.assertEqual(self.tell(SEAT, "Parser merged.")[0], 0)
        self.killed_after_text = step is None and not before_text
        self.killed_before_text = before_text
        killed = KeyboardInterrupt("killed")
        with (patch.object(watch, step, side_effect=killed) if step else nullcontext()), \
                self.assertRaises(KeyboardInterrupt):
            tell.deliver(self.cfg, lambda _: None)

    def test_a_line_typed_without_its_enter_gets_its_enter_once(self):
        self.died()
        self.assertEqual((self.taken, len(self.receipts())), ([], 1))
        for _ in range(3):
            tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.taken, [self.header() + "Parser merged."])
        self.assertEqual(len(self.typed), 1)
        self.assertEqual(self.waiting(), [])

    def test_a_line_that_went_in_is_never_typed_again_even_in_a_restored_tmux(self):
        self.died("_wait_sent")                       # after its Enter
        self.assertEqual(len(self.taken), 1)
        self.seat = dict(self.seat, created=11)       # its tmux restored, the same seat
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual((len(self.taken), len(self.typed)), (1, 1))
        self.assertEqual(self.waiting(), [])

    def test_two_messages_with_the_same_line_both_go_in(self):
        """The same words twice within a minute: two messages, each typed once."""
        self.pane = self.idle.replace(self.EMPTY, "❯ The owner's own words\n")
        self.tell(SEAT, "Still working?")
        self.tell(SEAT, "Still working?")
        self.pane = self.idle
        for _ in range(3):
            tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.taken, [self.header() + "Still working?"] * 2)
        self.assertEqual(self.waiting(), [])

    def test_a_line_lost_from_its_composer_is_typed_again(self):
        self.died()
        self.pane = self.idle                          # the composer's text gone, never sent
        tell.deliver(self.cfg, lambda _: None)
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.taken, [self.header() + "Parser merged."])
        self.assertEqual(self.waiting(), [])


class TyperDiedNoConversation(TyperDied):
    """The same deaths on a seat whose harness keeps no conversation ak reads."""

    EMPTY = "❯\n"

    def setUp(self):
        super().setUp()
        config.update_session(SEAT, orchestrator="spark")
        self.assertFalse(orch.seat_plugin(config.session_records()[SEAT]).keeps_messages)
        self.idle = (REPO / "tests/fixtures/muse-prompt-pane.txt").read_text(encoding="utf-8")
        self.pane, self.transcript = self.idle, None

    def test_a_line_killed_before_its_keys_is_typed_again(self):
        self.died(before_text=True)
        self.assertEqual((self.typed, len(self.receipts())), ([], 1))
        for _ in range(3):
            tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.taken, [self.header() + "Parser merged."])
        self.assertEqual(self.waiting(), [])

    def test_a_line_that_went_in_is_never_typed_again_even_in_a_restored_tmux(self):
        self.died("_wait_sent")                       # after its Enter
        self.seat = dict(self.seat, created=11)
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual((len(self.taken), len(self.typed)), (1, 1))
        self.assertEqual(self.waiting(), [])

    def test_a_line_lost_from_its_composer_is_typed_again(self):
        """Its keys went in, and with no conversation to read, the gone line counts as taken."""
        self.died()
        self.pane = self.idle
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.waiting(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
