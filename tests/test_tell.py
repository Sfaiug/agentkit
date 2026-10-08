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
QUEUED = f"{SEAT}: queued; ak types it as soon as it can take a line"
FIX = REPO / "tests/fixtures"
PROMPT = (FIX / "claude-prompt-pane.txt").read_text(encoding="utf-8")
# A real 2.1.289 turn running with one line already held above its composer, whose faint hint
# reads empty.
MIDTURN = (FIX / "claude-queued-midturn-pane.txt").read_text(encoding="utf-8")
HELD = next(row for row in MIDTURN.splitlines(True) if "Press up to edit queued messages" in row)


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
        self.pane = self.base = PROMPT
        self.empty = "❯\u00a0\n"      # the base pane's empty composer row
        stack.enter_context(patch.object(watch, "pane_text", side_effect=lambda *_a, **_kw: self.pane))
        stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        stack.enter_context(patch.object(watch.time, "sleep"))
        stack.enter_context(patch.object(watch.time, "time", return_value=NOW))

    def tmux(self, *args, **_kw):
        self.assertEqual(args[args.index("-t") + 1], f"={self.seat['name']}:")
        if args[0] == "display-message" and args[-1] == "#{pane_tty}":
            return 1, "no tty in this screen fixture"
        self.assertEqual(args[0], "send-keys")
        if "-l" in args:
            self.typed.append(args[-1])
            self.pane = self.base.replace(self.empty, "❯ " + args[-1] + "\n")
        elif args[-1] == "Enter":
            self.pane = self.base
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
        self.assertEqual([(row["source"], row["text"]) for row in self.receipts()],
                         [(f"seat:{SENDER}", line)])
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

    def test_a_long_line_drawn_slowly_gets_its_enter_in_the_same_pass(self):
        """A long conversation draws a typed line slower than KEY_GAP: the Enter waits until the
        composer shows it whole, not for the next tick, while the seat reads the owner's draft
        (judgment-redo, 6 Oct 13:42 and 13:54)."""
        typing, drawing = self.tmux, []

        def slow(*args, **kw):
            done = typing(*args, **kw)
            if "-l" in args:
                drawing[:] = [args[-1][:40]] * 2     # two reads see only its start
            return done

        def capture(*_a, **_kw):
            return (self.base.replace(self.empty, "❯ " + drawing.pop() + "\n") if drawing
                    else self.pane)
        line = "Parser merged; " * 20
        self.tell(SEAT, line)
        with patch.object(orch, "tmux_out", side_effect=slow), \
                patch.object(watch, "pane_text", side_effect=capture):
            self.tick()
        self.assertEqual(self.typed, [self.header() + " ".join(line.split())])
        self.assertEqual(self.waiting(), [])

    def test_every_waiting_message_goes_in_one_pass_oldest_first(self):
        for line in ("First.", "Second.", "Third."):
            self.tell(SEAT, line)
        self.tick()
        self.assertEqual(self.typed, [self.header() + line for line in ("First.", "Second.", "Third.")])
        self.assertEqual(self.waiting(), [])

    def test_a_seat_that_stops_taking_lines_keeps_the_rest_for_the_next_pass(self):
        self.tell(SEAT, "First.")
        self.tell(SEAT, "Second.")
        drafted = self.base.replace(self.empty, "❯ the owner's draft\n")

        def log(line):
            if "typed a message" in line:
                self.pane = drafted      # the owner starts typing once the first line went in

        tell.deliver(self.cfg, log)
        self.assertEqual(self.typed, [self.header() + "First."])
        self.assertEqual([message["line"] for message in self.waiting()], [self.header() + "Second."])
        self.tick()                      # the draft is still there: nothing is typed onto it
        self.assertEqual(self.typed, [self.header() + "First."])
        self.pane = self.base
        self.tick()
        self.assertEqual(self.typed, [self.header() + "First.", self.header() + "Second."])

    def turn_running(self, pane=MIDTURN, empty=HELD):
        """The seat mid-turn by its own hooks, `pane` on its screen with `empty` its composer."""
        config.hook_facts_path(SEAT).write_text(json.dumps(
            {"session": SEAT, "event": "UserPromptSubmit", "kind": "", "text": "", "at": NOW - 60}))
        self.free, self.pane, self.base, self.empty = False, pane, pane, empty

    def test_a_seat_whose_harness_holds_a_typed_line_gets_it_mid_turn(self):
        self.turn_running()
        self.tell(SEAT, "Parser merged.")
        self.tick()
        line = self.header() + "Parser merged."
        self.assertEqual(self.typed, [line])
        self.assertEqual([row["source"] for row in self.receipts()], [f"seat:{SENDER}"])
        self.assertEqual(self.waiting(), [])

    def test_mid_turn_it_waits_out_a_question_the_owners_draft_and_a_harness_that_drops_it(self):
        self.tell(SEAT, "Parser merged.")
        for pane in ("claude-question-pane.txt", "claude-draft-pane.txt"):
            with self.subTest(pane=pane):
                self.turn_running((FIX / pane).read_text(encoding="utf-8"))
                self.tick()
        # a harness whose manifest does not say it holds a typed line: every shipped one does
        # (tests/test_every_harness_queues_a_told_line.py), so the seat's Codex is told it does not
        adapters = self.root / "adapters"
        adapters.mkdir()
        for path in (REPO / "adapters").iterdir():
            (adapters / path.name).symlink_to(path)
        (adapters / "codex.toml").unlink()
        (adapters / "codex.toml").write_text(
            (REPO / "adapters/codex.toml").read_text().replace("queues_typing = true\n", ""))
        config.save_session(self.cfg, SEAT, "astra", ["opus"], {
            "cwd": str(self.root / SEAT), "conversation": "thread", "id_source": harness.LAUNCHER})
        self.turn_running()
        with patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}):
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
                         "acme-pages: queued; ak types it as soon as it can take a line")
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
        self.assertEqual(sent[0][:2], (0, "acme-pages: queued; ak types it as soon as it can take a line"))
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

    def test_a_told_line_never_reads_as_a_composers_placeholder(self):
        codex = (REPO / "tests/fixtures/codex-stall-pane.txt").read_text(encoding="utf-8")
        for harness, pane, empty, mark, text in (
                ("codex", codex, "› Ask Codex to do anything\n", "› ", "Ask Codex to do anything"),
                ("claude", PROMPT, "❯\u00a0\n", "❯ ", 'Try "fix the tests"')):
            line = self.header() + text
            with self.subTest(harness=harness):
                held = pane.replace(empty, mark + line + "\n")
                self.assertEqual(watch.composer_draft(harness, held), "".join(line.split()))

    def test_a_queue_that_cannot_be_read_keeps_its_messages(self):
        """Neither the tick nor a sender rewrites a queue file it could not read."""
        self.free = False
        self.tell(SEAT, "Parser merged.")
        path = config.seat_file("tell", SEAT)
        kept = path.read_text(encoding="utf-8")
        for broken in ("not json", '{"a": 1}'):
            with self.subTest(broken=broken):
                path.write_text(broken, encoding="utf-8")
                logs = []
                self.free = True
                tell.deliver(self.cfg, logs.append)
                self.assertEqual(path.read_text(encoding="utf-8"), broken)
                self.assertTrue(any("queue unread" in line for line in logs), logs)
                code, _, err = self.tell(SEAT, "Docs merged.")
                self.assertEqual(code, 1)
                self.assertIn("message queue cannot be read", err)
                self.assertEqual(path.read_text(encoding="utf-8"), broken)
        path.write_text(kept, encoding="utf-8")
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.typed, [self.header() + "Parser merged."])

    def test_a_seat_renamed_while_it_tells_still_cannot_tell_itself(self):
        limit = tell.longest(self.cfg)

        def renamed_meanwhile(_cfg):
            config.rename_session(SENDER, "fix-renamed")
            return limit

        with patch.object(tell, "longest", side_effect=renamed_meanwhile):
            code, _, err = self.tell(SENDER, "Parser merged.")
        self.assertEqual(code, 1)
        self.assertIn("fix-renamed is this seat", err)
        self.assertEqual(self.waiting("fix-renamed"), [])

    def test_aks_own_line_still_waiting_is_queued_once(self):
        self.free = False
        line = "[from ak, not the owner] Proven feature switches are yours to take out."
        self.assertIsNone(tell.queue(SEAT, line))
        self.assertIsNone(tell.queue(SEAT, line))
        self.assertEqual([message["line"] for message in self.waiting()], [line])
        self.free = True
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual((self.typed, self.waiting()), ([line], []))
        self.assertIsNone(tell.queue(SEAT, line))
        self.assertEqual([message["line"] for message in self.waiting()], [line])

    def test_a_queued_line_holds_no_key_but_its_own_enter(self):
        self.free = False
        self.assertIsNone(tell.queue(SEAT, "In ACME\ranswer, `new\x1bsearch`\n\tsince 6 Dec."))
        self.assertEqual([message["line"] for message in self.waiting()],
                         ["In ACME answer, `new search` since 6 Dec."])

    def test_what_cannot_be_told_is_refused_in_one_line(self):
        watch.seat_write("acme-closed", stopped_at=1)
        config.save_session(self.cfg, "acme-closed", "opus", ["astra"], {"cwd": str(self.root)})
        for argv, said in (
                ((SENDER, "hi"), f"ak tell: {SENDER} is this seat"),
                (("acme-nobody", "hi"), "ak tell: no session 'acme-nobody'; `ak orch list` shows them"),
                (("acme-closed", "hi"), "ak tell: acme-closed is closed"),
                ((SEAT, " \n "), "ak tell: nothing to say"),
                ((SEAT, "x" * tell.longest(self.cfg)), "more than a composer shows whole")):
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


class Typing(Seats):
    """A real pane for the receiver: its composer shows what is typed, Enter takes it."""

    def setUp(self):
        super().setUp()
        self.opened(1.0)
        self.idle = PROMPT
        self.pane, self.taken, self.killed_after_text = self.idle, [], False
        self.killed_before_text, self.keys, self.after_enter = False, [], None
        for target, kwargs in ((watch, {"at_prompt": watch.at_prompt}),
                               (watch, {"pane_text": lambda *_a, **_kw: self.pane}),
                               (orch, {"tmux_out": self.render})):
            for attribute, value in kwargs.items():
                patcher = patch.object(target, attribute, side_effect=value)
                patcher.start()
                self.addCleanup(patcher.stop)

    EMPTY = "❯\u00a0\n"           # the composer's prompt row with nothing in it
    WIDTH = 60                    # the composer wraps a long line onto rows of this width

    def composed(self, text):
        """The empty pane with that text in its composer, wrapped as the harness wraps it."""
        rows = [text[at:at + self.WIDTH] for at in range(0, len(text), self.WIDTH)] or [""]
        return self.idle.replace(self.EMPTY, "❯ " + "\n  ".join(rows) + "\n")

    def echoed(self, text):
        """The pane once the harness took that line: its composer empty again."""
        return self.idle

    def render(self, *args, **kwargs):
        if args[0] != "send-keys":
            return self.tmux(*args, **kwargs)
        self.keys.append(args)
        if "-l" in args and self.killed_before_text:
            self.killed_before_text = False
            raise KeyboardInterrupt("killed before its keys reached tmux")
        was = self.pane
        self.tmux(*args, **kwargs)
        if "-l" in args:
            self.pane = self.composed(args[-1])
            if self.killed_after_text:
                self.killed_after_text = False
                raise KeyboardInterrupt("killed right after the text went in")
        elif args[-1] == "Enter" and was != self.idle:
            self.taken.append(self.typed[-1])
            self.pane = self.echoed(self.taken[-1])
        if args[-1] == "Enter" and self.after_enter is not None:
            self.pane, self.after_enter = self.after_enter(), None
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

    def enters(self):
        return [args for args in self.keys if args[-1] == "Enter"]


class TyperDied(Typing):
    """The tick typing a message dies at some key: the next tick finishes it, and only a line
    seen leaving its composer leaves the queue."""

    def test_a_line_typed_without_its_enter_gets_its_enter_once(self):
        self.died()
        self.assertEqual((self.taken, len(self.receipts())), ([], 1))
        for _ in range(3):
            tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.taken, [self.header() + "Parser merged."])
        self.assertEqual(len(self.typed), 1)
        self.assertEqual(self.waiting(), [])

    def test_a_tick_that_died_after_the_enter_has_it_typed_again_never_lost(self):
        """At least once: gone from its composer before its queue was rewritten, it goes again,
        in a restored tmux too."""
        self.died("_wait_sent")                       # after its Enter
        self.assertEqual(len(self.taken), 1)
        self.seat = dict(self.seat, created=11)
        for _ in range(3):
            tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.taken, [self.header() + "Parser merged."] * 2)
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


    def test_a_long_line_wrapped_over_many_rows_gets_its_enter_once(self):
        text = "Parser merged; " + "leave parser.py and its tests alone until then. " * 12
        self.assertEqual(self.tell(SEAT, text)[0], 0)
        self.killed_after_text = True
        with self.assertRaises(KeyboardInterrupt):
            tell.deliver(self.cfg, lambda _: None)
        self.assertGreater(len(self.pane.splitlines()) - len(self.idle.splitlines()), 8)
        for _ in range(3):
            tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.taken, [self.header() + " ".join(text.split())])
        self.assertEqual(len(self.typed), 1)
        self.assertEqual(self.waiting(), [])

    def test_text_the_owner_added_to_the_line_is_never_sent_with_it(self):
        """Killed before its mark, or after it and before its Enter: either way it waits."""
        for step in (None, "_send_enter"):
            with self.subTest(killed_in=step or "right after its text"):
                self.died(step)
                self.pane = self.composed(self.typed[-1] + " and also check the docs")
                before = len(self.enters())
                for _ in range(3):
                    tell.deliver(self.cfg, lambda _: None)
                self.assertEqual(len(self.enters()), before)
                self.assertEqual((self.taken, len(self.typed)), ([], 1))
                self.assertEqual(len(self.waiting()), 1)
                tell.write(config.seat_file("tell", SEAT), [])
                self.typed.clear()
                self.pane = self.idle

    def test_what_changes_before_an_enter_is_never_sent(self):
        """Read again under the typing lock right before each Enter: an owner's edit or a dialog
        that came after the first read, or the owner typing in the gap after a fresh line."""
        question = (REPO / "tests/fixtures/claude-question-pane.txt").read_text(
            encoding="utf-8")
        for case in ("edit", "dialog", "typed in the gap"):
            with self.subTest(case=case):
                self.keys.clear()
                tell.write(config.seat_file("tell", SEAT), [])
                if case == "typed in the gap":
                    self.tell(SEAT, "Parser merged.")
                    gap = lambda *_a: setattr(self, "pane", self.composed(
                        self.typed[-1] + " and the docs"))
                    with patch.object(watch.time, "sleep", side_effect=gap):
                        tell.deliver(self.cfg, lambda _: None)
                else:
                    self.died()                         # its line sits there, unsent
                    later = (self.composed(self.typed[-1] + " and the docs") if case == "edit"
                             else question)
                    real = watch.composer_holds
                    reads = []

                    def first_read_then_change(*args):
                        reads.append(real(*args))
                        if len(reads) == 1:
                            self.pane = later
                        return reads[-1]

                    with patch.object(watch, "composer_holds", side_effect=first_read_then_change):
                        tell.deliver(self.cfg, lambda _: None)
                self.assertEqual(self.enters(), [])
                self.assertEqual(self.taken, [])
                self.assertEqual(len(self.waiting()), 1)
                self.pane = self.idle

    def test_a_send_no_read_confirms_keeps_its_message(self):
        """A capture that fails right after the Enter says nothing: the message stays queued,
        and goes again once its composer is read empty -- at least once."""
        self.tell(SEAT, "Parser merged.")
        self.after_enter = lambda: ""
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual((len(self.taken), len(self.waiting())), (1, 1))
        self.pane = self.idle
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual((len(self.taken), self.waiting()), (2, []))

    def test_a_draft_the_owner_starts_after_the_first_read_is_never_typed_onto(self):
        """Read empty, then a long draft of the owner's before the typing lock: the composer is
        read again under the lock, right before the first key."""
        self.tell(SEAT, "Parser merged.")
        draft = "Fix the login redirect and run its tests again " * 3
        real = watch.composer_holds

        def empty_then_drafted(*args):
            found = real(*args)
            self.pane = self.composed(draft)
            return found

        with patch.object(watch, "composer_holds", side_effect=empty_then_drafted):
            tell.deliver(self.cfg, lambda _: None)
        self.assertEqual((self.typed, self.enters()), ([], []))
        self.assertEqual(len(self.waiting()), 1)

    def test_a_prompt_mark_at_the_head_of_a_wrapped_row_is_text(self):
        """A wrapped row is indented past the prompt mark: a mark at its head is the line's own
        text, so the told line still reads whole and gets its Enter, and an owner's draft
        ending in one is still a draft nothing is typed onto."""
        head = self.header()
        text = "x" * (2 * self.WIDTH - len(head)) + "❯ then the rest"
        self.tell(SEAT, text)
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual((self.taken, self.waiting()), ([head + text], []))
        self.pane = self.composed("y" * self.WIDTH + "❯")
        self.tell(SEAT, "Docs merged.")
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.typed, [head + text])
        self.assertEqual(len(self.waiting()), 1)

    def test_a_line_killed_before_its_keys_is_typed_again(self):
        self.died(before_text=True)
        self.assertEqual((self.typed, len(self.receipts())), ([], 1))
        for _ in range(3):
            tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.taken, [self.header() + "Parser merged."])
        self.assertEqual(self.waiting(), [])

    def test_a_line_lost_from_its_composer_is_typed_again(self):
        self.died()
        self.pane = self.idle                          # the composer's text gone, never sent
        tell.deliver(self.cfg, lambda _: None)
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.taken, [self.header() + "Parser merged."])
        self.assertEqual(self.waiting(), [])


class TyperDiedMuse(TyperDied):
    """The same deaths on a Muse seat, whose composer is drawn without a box of rules."""

    EMPTY = "❯\n"

    def setUp(self):
        super().setUp()
        config.update_session(SEAT, orchestrator="spark")
        self.idle = (REPO / "tests/fixtures/muse-prompt-pane.txt").read_text(encoding="utf-8")
        self.pane = self.idle


class TyperDiedEchoAbove(Typing):
    """Antigravity draws the line it took right above its empty composer."""

    EMPTY = "\n>\n"

    def setUp(self):
        super().setUp()
        config.update_session(SEAT, orchestrator="gemini")
        self.assertEqual(orch.seat_plugin(config.session_records()[SEAT]).name, "antigravity")
        self.idle = (REPO / "tests/fixtures/antigravity-prompt-pane.txt").read_text(encoding="utf-8")
        self.assertEqual(self.idle.count(self.EMPTY), 1)
        self.pane = self.idle

    def composed(self, text):
        return self.idle.replace(self.EMPTY, "\n> " + text + "\n")

    def echoed(self, text):
        return self.idle.replace("> Say hello in one short sentence.", "> " + text)

    def test_a_blank_capture_is_no_empty_composer(self):
        """Its composer is found by a pattern of its own: no composer on the screen read is
        nothing read, never an empty composer, so the message stays queued."""
        self.tell(SEAT, "Parser merged.")
        line = self.header() + "Parser merged."
        real_render = self.render

        def enter_not_taken_then_blank(*args, **kwargs):
            if args[-1] == "Enter":
                self.keys.append(args)
                self.pane = ""
                return 0, ""
            return real_render(*args, **kwargs)

        with patch.object(orch, "tmux_out", side_effect=enter_not_taken_then_blank):
            tell.deliver(self.cfg, lambda _: None)
        self.assertIsNone(watch.composer_draft("antigravity", ""))
        self.assertEqual((self.taken, len(self.waiting())), ([], 1))
        self.pane = self.composed(line)                  # the capture back, the line unsent
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual((self.taken, self.waiting()), ([line], []))

    def test_a_line_echoed_above_its_empty_composer_is_not_in_it(self):
        """Antigravity draws the line it took above its composer: the composer is empty."""
        self.died("_wait_sent")                       # after its Enter, echoed above
        self.assertIn("> " + self.typed[-1], self.pane)
        self.assertEqual(watch.composer_draft("antigravity", self.pane), "")
        for _ in range(3):
            tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.taken, [self.header() + "Parser merged."] * 2)
        self.assertEqual(len(self.enters()), 2)
        self.assertEqual(self.waiting(), [])


class TyperDiedGrok(Typing):
    """Grok Build keeps its composer drawn under its trust question: an Enter there answers it."""

    def setUp(self):
        super().setUp()
        config.update_session(SEAT, orchestrator="grok")
        self.assertEqual(orch.seat_plugin(config.session_records()[SEAT]).name, "grokbuild")
        self.idle = (REPO / "tests/fixtures/grok-prompt-pane.txt").read_text(encoding="utf-8")
        self.dialog = (REPO / "tests/fixtures/grok-dialog-pane.txt").read_text(encoding="utf-8")
        self.row = next(row for row in self.idle.split("\n") if "│ ❯" in row)
        self.pane = self.idle

    def holding(self, pane, text):
        return pane.replace(self.row, ("  │ ❯ " + text).ljust(len(self.row) - 1) + "│")

    def composed(self, text):
        return self.holding(self.idle, text)

    def test_a_dialog_over_the_unsent_line_after_its_enter_keeps_the_message(self):
        self.tell(SEAT, "Parser merged.")
        line = self.header() + "Parser merged."
        self.after_enter = lambda: self.holding(self.dialog, line)
        self.taken.clear()
        real_render = self.render

        def enter_not_taken(*args, **kwargs):
            if args[-1] == "Enter" and self.after_enter is not None:
                self.keys.append(args)
                self.pane, self.after_enter = self.after_enter(), None
                return 0, ""
            return real_render(*args, **kwargs)

        with patch.object(orch, "tmux_out", side_effect=enter_not_taken):
            tell.deliver(self.cfg, lambda _: None)
        self.assertEqual((self.taken, len(self.waiting())), ([], 1))
        self.pane = self.holding(self.idle, line)       # the question answered, the line still there
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual((self.taken, self.waiting()), ([line], []))

    def test_no_key_goes_onto_a_screen_the_first_read_did_not_see(self):
        """Read empty, then -- before the typing lock -- a question over the empty composer, or a
        screen with no composer to read: one capture under the lock decides, and no key goes in."""
        for later in (self.dialog, "  Loading the workspace…\n"):
            with self.subTest(later=later[:20]):
                tell.write(config.seat_file("tell", SEAT), [])
                self.keys.clear()
                self.pane = self.idle
                self.tell(SEAT, "Parser merged.")
                real = watch.composer_holds

                def empty_then_changed(*args):
                    found = real(*args)
                    self.pane = later
                    return found

                with patch.object(watch, "composer_holds", side_effect=empty_then_changed):
                    tell.deliver(self.cfg, lambda _: None)
                self.assertEqual(self.keys, [])
                self.assertEqual(len(self.waiting()), 1)

    def test_no_enter_answers_a_question_that_keeps_the_composer_drawn(self):
        self.died()                                   # its line sits there, unsent
        self.pane = self.holding(self.dialog, self.typed[-1])
        for _ in range(2):
            tell.deliver(self.cfg, lambda _: None)
        self.assertEqual((self.enters(), self.taken), ([], []))
        self.assertEqual(len(self.waiting()), 1)
        tell.write(config.seat_file("tell", SEAT), [])
        self.pane = self.idle
        self.tell(SEAT, "Docs merged.")
        gap = lambda *_a: setattr(self, "pane", self.holding(self.dialog, self.typed[-1]))
        with patch.object(watch.time, "sleep", side_effect=gap):
            tell.deliver(self.cfg, lambda _: None)
        self.assertEqual((self.enters(), self.taken), ([], []))
        self.assertEqual(len(self.waiting()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
