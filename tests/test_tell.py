"""`ak tell`: one seat's message reaches another, typed by ak, never as the owner's words.

Offline: a temporary HOME, a fake tmux and pane; no real seat, transcript or state.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import fcntl
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, harness, host, notify, orch, tell, watch
from agentkit.harness import claude

SENDER, SEAT = "fix-api", "acme-docs"
NOW = 1_000_000.0


def prompt(at, text):
    return {"type": "user", "timestamp": datetime.fromtimestamp(at, timezone.utc).isoformat(),
            "message": {"role": "user", "content": text}}


class Tell(unittest.TestCase):
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

    def test_a_seat_at_its_prompt_gets_it_at_once_headed_with_who_sent_it(self):
        code, out, _ = self.tell(SEAT, "Parser merged.\n  Leave parser.py alone.")
        self.assertEqual((code, out), (0, f"{SEAT}: told"))
        line = self.header() + "Parser merged. Leave parser.py alone."
        self.assertEqual(self.typed, [line])
        self.assertEqual([(row["source"], row["text"]) for row in self.receipts()],
                         [(f"seat:{SENDER}", line)])
        self.assertEqual(self.waiting(), [])

    def test_a_busy_seat_gets_it_once_at_its_next_quiet_prompt(self):
        self.free = False
        code, out, _ = self.tell(SEAT, "Parser merged.")
        self.assertEqual((code, out), (0, f"{SEAT}: busy; ak types this at its next quiet prompt"))
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.typed, [])
        self.free = True
        tell.deliver(self.cfg, lambda _: None)
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.typed, [self.header() + "Parser merged."])
        self.assertEqual(self.waiting(), [])

    def test_messages_go_in_oldest_first_one_per_quiet_prompt(self):
        self.free = False
        self.tell(SEAT, "First.")
        self.tell(SEAT, "Second.")
        self.free = True
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.typed, [self.header() + "First."])
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.typed, [self.header() + "First.", self.header() + "Second."])

    def test_an_open_owner_question_holds_it_until_answered(self):
        notify.record(SEAT, "needs", "Which schema should acme use?")
        code, out, _ = self.tell(SEAT, "Parser merged.")
        self.assertEqual((code, out), (0, f"{SEAT}: waits on the owner's answer; ak types this after it"))
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.typed, [])
        self.assertEqual(len(self.waiting()), 1)

    def test_a_told_line_is_never_the_owners_words(self):
        self.tell(SEAT, "Parser merged.")
        record = config.session_records()[SEAT]
        path = claude.transcript_path(record, "thread")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(prompt(101, self.typed[0])) + "\n"
                        + json.dumps(prompt(102, "Use the second schema.")) + "\n")
        plugin = orch.seat_plugin(record)
        self.assertEqual(plugin.user_messages(record, record["cwd"], "thread", seat=SEAT),
                         [{"at": 102, "text": "Use the second schema."}])

    def test_a_renamed_seat_gets_what_was_sent_to_its_old_name(self):
        self.free = False
        self.tell(SEAT, "Parser merged.")
        config.rename_session(SEAT, "acme-pages")
        self.seat = {"name": "acme-pages", "created": 10, "legacy": False}
        self.free = True
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.typed, [self.header() + "Parser merged."])
        self.tell(SEAT, "Docs too.")      # the old name still reaches it
        self.assertEqual(self.typed[-1], self.header() + "Docs too.")

    def test_a_message_sent_while_its_receiver_is_renamed_reaches_it(self):
        """A rename holds the seat's lock while a delivery holds its queue; the sender waits."""
        self.free = False
        queue = config.seat_file("tell", SEAT).with_suffix(".lock")
        sent = []
        with notify.session_lock(SEAT), queue.open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            sender = threading.Thread(target=lambda: sent.append(self.tell(SEAT, "Parser merged.")))
            sender.start()
            sender.join(0.5)
            config.rename_session(SEAT, "acme-pages")
            self.seat = {"name": "acme-pages", "created": 10, "legacy": False}
        sender.join(10)
        self.assertEqual(sent[0][0], 0, sent)
        self.free = True
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.typed, [self.header() + "Parser merged."])
        self.assertEqual(self.waiting("acme-pages"), [])
        self.assertFalse(config.seat_file("tell", SEAT).exists())

    def test_a_message_another_live_sender_is_typing_is_left_to_it_and_a_dead_ones_taken_over(self):
        self.free = False
        self.tell(SEAT, "Parser merged.")
        other = subprocess.Popen(["sleep", "30"])
        self.addCleanup(other.kill)
        claim = {"pid": other.pid, "identity": host.process_identity(other.pid)}
        tell.locked(SEAT, lambda messages: messages[0].update(claim=claim))
        self.free = True
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.typed, [])
        other.kill()
        other.wait()
        tell.deliver(self.cfg, lambda _: None)
        self.assertEqual(self.typed, [self.header() + "Parser merged."])
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
        self.assertEqual(self.typed, [])
        self.assertEqual(self.waiting(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
