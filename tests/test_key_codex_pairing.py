"""A Codex seat pages nobody about pairing as it opens or reopens; a code comes only on request.

Pairing the provider's app with a seat is optional and never blocks terminal work, so opening or
resuming a Codex seat sends no setup alert and asks Codex for no pairing code (owner rules).
Older seats paged the owner with optional setup as if it were a question.  The owner who wants
app access asks on the host, `python3 <ak>/tools/codex-seat.py --pair <seat>` (docs/guide.md),
by the seat's name, a name it had before or the Codex home an older card named; the code is
printed there and paged nowhere, and the seat works on.

Black-box: the program `AK_BIN` names opens each seat from a person's terminal
(tests/fixtures/akterm.py), paging tests/fixtures/sink.py; `codex` is
tests/fixtures/codex-remote-fake.py, Codex's app server and remote TUI with no device paired,
which writes down each pairing it is asked for.  The seat names itself to its provider over
HTTPS; that call meets a loopback proxy whose stand-in provider, trusted through SSL_CERT_FILE,
accepts it, so the seat goes on to read the connected status where pairing would begin.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import shlex
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, REAL_TMUX, REPO, Home
from fixtures.akseat import FIXTURES, Seat
from fixtures.akterm import Terminal
from fixtures.sink import Sink

PAIR = Path(AK).resolve().parents[1] / "tools" / "codex-seat.py"   # beside the program
CODE = "Pairing code: ACME-1234\n"      # the stand-in's manual code
OPEN = ("--model", "astra", "--workers", "astra")     # the shipped config's Codex model


def running(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def until(test, what, bound=30):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}")
        time.sleep(0.05)


class Provider(BaseHTTPRequestHandler):
    """A proxy that opens every tunnel onto the stand-in provider, which accepts each call and
    writes it down: the seat names itself to the provider before it reads the connected status."""

    def do_CONNECT(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.flush()
        self.request = self.connection = self.server.tls.wrap_socket(self.connection,
                                                                     server_side=True)
        self.setup()
        self.close_connection = False    # the tunnel's request comes next

    def do_PATCH(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.calls.append((self.command, self.path, body))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    do_DELETE = do_PATCH

    def log_message(self, *_args):
        pass


class CodexHost:
    """A Home whose `codex` is the stand-in, logged in, with a sink for pages."""

    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        cls.sink = Sink(home)
        cls.addClassCleanup(cls.sink.close)
        home.fake("codex", "#!/bin/sh\nexec " + shlex.join(
            [sys.executable, str(FIXTURES / "codex-remote-fake.py")]) + ' "$@"\n')
        home.write(".codex/auth.json", {"tokens": {"access_token": "acme-token",
                                                   "account_id": "acme-account"}})
        cert, key = home.path / "provider.pem", home.path / "provider.key"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=chatgpt.com", "-addext", "subjectAltName=DNS:chatgpt.com",
                        "-keyout", key, "-out", cert], check=True, capture_output=True)
        cls.provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        cls.provider.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.provider.tls.load_cert_chain(cert, key)
        cls.provider.calls = []
        threading.Thread(target=cls.provider.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.provider.server_close)
        cls.addClassCleanup(cls.provider.shutdown)
        proxy = f"http://127.0.0.1:{cls.provider.server_port}"
        home.env.update({"FAKE_CODEX_REPO": str(REPO), "FAKE_THREAD": "acme-thread",
                         "FAKE_HOLD": "1", "FAKE_PAIRING": "1",
                         "https_proxy": proxy, "HTTPS_PROXY": proxy,
                         "SSL_CERT_FILE": str(cert)})

    @classmethod
    def found(cls, name):
        """A file the stand-in writes in its Codex home, wherever ak keeps that home."""
        return list(cls.home.path.rglob(name))

    @classmethod
    def open_seat(cls, *args):
        """`ak orch` typed in a person's terminal, once its Codex is up and the seat has named
        itself to the provider and read its connected status: where a pairing alert would start.
        Each status read is named before its connection closes, and the provider accepts each."""
        for mark in cls.found("fake-tui.json") + cls.found("fake-monitor-closed"):
            mark.unlink()
        named = len(cls.provider.calls)
        terminal = Terminal(cls.home, "orch", *args)
        until(lambda: cls.found("fake-tui.json") and cls.found("fake-monitor-closed")
              and len(cls.provider.calls) > named,
              f"saw `ak orch {' '.join(args)}` start Codex, name its seat and read its status")
        return terminal

    def pairings(self):
        """Each pairing the stand-in was asked for, oldest first."""
        path = self.home.path / "pairings.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def assertPagedNothing(self, terminal):
        self.assertEqual(self.sink.requests, [])
        outbox = self.home.path / ".agentkit/state/notification-outbox"
        self.assertEqual(sorted(outbox.glob("*.json")), [])
        self.assertEqual(self.pairings(), [])
        self.assertNotIn("needs you", terminal.wait("idle"))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OpeningAndReopening(CodexHost, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.first = cls.open_seat("acme", *OPEN)

    def test_opening_a_codex_seat_nobody_paired_pages_nothing_and_asks_for_no_code(self):
        self.assertPagedNothing(self.first)

    def test_reopening_it_after_tmux_lost_it_resumes_it_and_still_pages_nothing(self):
        server, = self.found("fake-server.json")
        pid = json.loads(server.read_text())["pid"]
        self.assertEqual(self.home.tmux("kill-session", "-t", "=acme").code, 0)
        until(lambda: not running(pid), "saw the lost seat's Codex end")
        terminal = self.open_seat("acme")
        argv = json.loads((self.home.path / "last-command.json").read_text())
        self.assertIn("resume acme-thread", shlex.join(argv))
        self.assertPagedNothing(terminal)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class PairingOnRequest(CodexHost, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.open_seat("fix-api", *OPEN)
        renamed = cls.home.ak("orch", "rename", "fix-api", "acme")
        assert renamed.code == 0, renamed.err
        # Project folders often carry a seat's name; a bare name still names the seat.
        for name in ("acme", "fix-api"):
            (cls.home.path / name).mkdir()

    def pair(self, target):
        return tuple(self.home.run("python3", str(PAIR), "--pair", target))

    def test_its_name_a_name_it_had_or_its_codex_home_prints_a_code_and_pages_nothing(self):
        before = len(self.pairings())
        server, = self.found("fake-server.json")
        for target in ("acme", "fix-api", str(server.parent)):
            with self.subTest(target=target):
                self.assertEqual(self.pair(target), (0, CODE, ""))
        self.assertEqual(self.pairings()[before:], [{"manualCode": True}] * 3)
        self.assertEqual(self.sink.requests, [])
        # terminal work goes on: the seat and its Codex still run
        self.assertEqual(self.home.tmux("has-session", "-t", "=acme").code, 0)
        tui, = self.found("fake-tui.json")
        self.assertTrue(running(json.loads(tui.read_text())["pid"]))

    def test_a_seat_not_on_codex_or_no_seat_at_all_has_no_code_to_give(self):
        Seat(self.home, "beta")
        before = self.pairings()
        for name in ("beta", "nobody"):
            with self.subTest(name=name):
                self.assertEqual(self.pair(name), (1, "", f"codex seat: {name} has no Codex "
                                                   "remote connection; open its Codex seat "
                                                   "first\n"))
        self.assertEqual(self.pairings(), before)
        self.assertEqual(self.sink.requests, [])


if __name__ == "__main__":
    unittest.main()
