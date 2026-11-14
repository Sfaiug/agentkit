"""A Codex seat follows each thread its own Codex starts and keeps each one it left for its done
check.  In its launch's thread A the owner asks for a retry button and a receipt email; nothing
reads the seat before they open B with /new and say only "thanks" there.  The plan holds the
button alone, every line done.  The seat does not read done, `ak orch check` names the email from
a workspace holding A and B once each, and a reopen resumes B; after /resume A and a prompt there
the check still reads each once, and after /resume B and a prompt a reopen resumes B.  Black-box on `AK_BIN`, a fake model (fakeadapter.py), and its
`codex` tests/fixtures/codex-remote-fake.py as npm installs it: a script named `codex` whose app
server runs a native `codex` under it, which fires the seat's hooks as 0.167 does.
"""

import json
import shlex
import shutil
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, REAL_TMUX, REPO, Home
from fixtures.akseat import FIXTURES
from fixtures.akterm import Terminal

A = "5b8e2d14-7c3a-4f69-9e1d-2a6c8f0b4d37"
SECOND = "Also email me a receipt after every upload."


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CodexSeatKeepsEveryThread(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: no provider is reached
            probe.bind(("127.0.0.1", 0))
            dead = f"http://127.0.0.1:{probe.getsockname()[1]}"
        home.env.update({"FAKE_THREAD": A, "FAKE_HOLD": "1",
                         "FAKE_SCREEN": str(FIXTURES / "codex-prompt-pane.txt"),
                         "https_proxy": dead, "HTTPS_PROXY": dead})
        fake = (FIXTURES / "codex-remote-fake.py").read_text()      # npm's `codex`, a script
        home.fake("codex", f"#!{sys.executable}\n{fake}")
        home.write(".codex/auth.json", {"tokens": {"access_token": "acme-token",
                                                   "account_id": "acme-account"}})
        model = fakeadapter.install(home, claude="pass")["claude"]
        adapters = Path(home.env["AGENTKIT_ADAPTER_DIR"])     # Codex's own beside the fake
        (adapters / "codex.sh").write_text(
            f'#!/bin/sh\nexec {shlex.quote(str(REPO / "adapters/codex.sh"))} "$@"\n')
        (adapters / "codex.sh").chmod(0o755)
        shutil.copy(REPO / "adapters/codex.toml", adapters)
        akconfig.write(home, ["astra", "opus"], workers=["astra"],
                       extra='[done_check]\nmodel = "opus"')
        home.write(".agentkit/state/plan-acme.md", "- [x] The upload page has a retry button · "
                   "check: `true` · acme · written 2026-11-09 10:05 · done 0123456789ab\n")
        self.checked = model.dir / "checked.md"
        model.behave({"sh": f"cp conversation.md {shlex.quote(str(self.checked))}; "
                           f"{shlex.quote(AK)} hand-in finding \"$(grep -rlF -- "
                           f"{shlex.quote(SECOND)} . | head -n 1):1\" 'no receipt email' "
                           f"'the owner asked for it' --quote {shlex.quote(SECOND)}",
                     "final": "Checked.", "hand_in": [["done"]]})

    def until(self, found, what):
        deadline = time.monotonic() + 120
        while not (it := found()):
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)
        return it

    def open(self, *args):
        """`ak orch` with `args` from a person's terminal: its Codex's command line, once up."""
        tuis = lambda: {path: path.read_text() for path in self.home.path.rglob("fake-tui.json")}
        before = tuis()
        Terminal(self.home, *args)
        up = self.until(lambda: set(tuis().items()) - set(before.items()), "the seat never opened")
        return json.loads(up.pop()[1])["argv"]

    def type(self, text):
        """The owner enters `text` in the seat's Codex: the thread it went to, once answered."""
        heard = lambda: [json.loads(line) for path in self.home.path.rglob("fake-heard.jsonl")
                         for line in path.read_text().splitlines()]
        before = len(heard())
        for keys in (("-l", text), ("Enter",)):
            self.assertEqual(self.home.tmux("send-keys", "-t", "=acme:", *keys).code, 0)
        (said, thread), *_ = self.until(lambda: heard()[before:], "the Codex never answered")
        self.assertEqual(said, text)
        return thread

    def check(self):
        """The seat not done, its check naming the email from A and B read once each."""
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.out + why.err)
        self.assertNotEqual(why.out.splitlines()[0], "acme  done")
        done = self.home.ak("orch", "check", "acme")
        self.assertEqual(done.code, 1, done.out + done.err)
        self.assertIn(SECOND, done.out)
        read = self.checked.read_text()
        self.assertEqual((read.count(SECOND), read.count(" thanks\n")), (1, 1), read)

    def test_the_seat_goes_with_each_thread_of_the_owner_s_and_checks_every_one(self):
        self.open("orch", "acme", "--model", "astra", "--workers", "astra")
        typed = ["Add a retry button to the upload page.", SECOND, "/new", "thanks"]
        a, second, _, b = [self.type(text) for text in typed]
        self.assertEqual((a, second), (A, A))
        self.assertNotEqual(b, A, "/new opened no thread of its own")
        self.check()
        self.assertEqual(self.home.tmux("kill-session", "-t", "=acme").code, 0)
        argv = self.open("orch", "acme")
        self.assertEqual(argv[argv.index("resume") + 1], b)
        self.assertEqual([self.type(text) for text in (f"/resume {A}", "Go on.")], [A, A])
        self.check()
        # back in this launch's thread, which its Codex starts no second time: its prompt names it
        self.assertEqual([self.type(text) for text in (f"/resume {b}", "Go on.")], [b, b])
        self.assertEqual(self.home.tmux("kill-session", "-t", "=acme").code, 0)
        argv = self.open("orch", "acme")
        self.assertEqual(argv[argv.index("resume") + 1], b)


if __name__ == "__main__":
    unittest.main()
