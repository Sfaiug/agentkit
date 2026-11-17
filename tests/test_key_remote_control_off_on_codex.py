"""`remote_control = false` at the top of config.toml holds on a Codex seat: its app server, which
the seat's TUI still runs on, starts without `--remote-control`, so nothing is enrolled with the
provider or named after the seat and no pairing card goes out, and `ak orch pair` refuses, naming
the setting.  `true`, or no such line, starts it with Remote Control, which names the seat to the
provider.  The seat follows its config, not a setting its pane inherits.

Black-box: the program `AK_BIN` names opens each seat on the Home's tmux, paging
tests/fixtures/sink.py; `codex` is tests/fixtures/codex-remote-fake.py, Codex's app server and
remote TUI, which writes down how its server was started and each pairing it is asked for.  Every
call to the provider meets a loopback proxy that writes it down and refuses it.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shlex
import sys
import threading
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import FIXTURES
from fixtures.sink import Sink

SEAT = "acme"


def until(test, what, bound=30):
    deadline = time.monotonic() + bound
    while not (found := test()):
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}")
        time.sleep(0.05)
    return found


def running(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class Provider(BaseHTTPRequestHandler):
    """The proxy every call to the provider goes through: each tunnel asked for, written down
    and refused."""

    def do_CONNECT(self):
        self.server.calls.append(self.path)
        self.send_error(502)

    def log_message(self, *_args):
        pass


class CodexSeat:
    """A Home whose `codex` is the stand-in, logged in, under a config.toml holding `settings`
    at its top, opening one seat on it from a pane that inherits `inherited` as its setting."""

    def open(self, inherited, **settings):
        self.home = home = Home()
        self.addCleanup(home.close)
        self.sink = Sink(home)
        self.addCleanup(self.sink.close)
        akconfig.write(home, ["astra"], settings=settings)
        home.fake("codex", "#!/bin/sh\nexec " + shlex.join(
            [sys.executable, str(FIXTURES / "codex-remote-fake.py")]) + ' "$@"\n')
        home.write(".codex/auth.json", {"tokens": {"access_token": "acme-token",
                                                   "account_id": "acme-account"}})
        self.provider = provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        provider.calls = []
        threading.Thread(target=provider.serve_forever, daemon=True).start()
        self.addCleanup(provider.server_close)
        self.addCleanup(provider.shutdown)
        proxy = f"http://127.0.0.1:{provider.server_port}"
        home.env.update({"FAKE_THREAD": "acme-thread", "FAKE_HOLD": "1",
                         "https_proxy": proxy, "HTTPS_PROXY": proxy,
                         "AGENTKIT_REMOTE_CONTROL": inherited})
        done = home.ak("orch", SEAT, "--model", "astra", "--workers", "astra", tty=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        # the TUI is up once its server has answered it
        until(lambda: list(home.path.rglob("fake-tui.json")), "saw the seat's Codex start")
        server, = home.path.rglob("fake-server.json")
        return json.loads(server.read_text())

    def pairings(self):
        """Each pairing the stand-in was asked for, oldest first."""
        path = self.home.path / "pairings.jsonl"
        return path.read_text().splitlines() if path.exists() else []


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class Off(CodexSeat, unittest.TestCase):
    def test_the_server_runs_without_remote_control_and_nothing_is_enrolled_or_paged(self):
        server = self.open("on", remote_control=False)
        self.assertIn("app-server", server["argv"])
        self.assertNotIn("--remote-control", server["argv"])
        paired = self.home.ak("orch", "pair", SEAT)
        self.assertNotEqual(paired.code, 0, paired.out)
        self.assertIn("remote_control", paired.err)
        # whatever the seat would ask the provider it asks before it ends
        self.assertEqual(self.home.tmux("kill-session", "-t", f"={SEAT}").code, 0)
        until(lambda: not running(server["pid"]), "saw the seat's Codex end")
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.pairings(), [])
        self.assertEqual(self.sink.requests, [])
        outbox = self.home.path / ".agentkit/state/notification-outbox"
        self.assertEqual(sorted(outbox.glob("*.json")), [])


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class On(CodexSeat, unittest.TestCase):
    def test_true_or_unset_starts_the_server_with_remote_control_naming_the_seat(self):
        for settings in ({"remote_control": True}, {}):
            with self.subTest(**settings):
                server = self.open("off", **settings)
                self.assertIn("--remote-control", server["argv"])
                until(lambda: self.provider.calls, "saw the seat name itself to the provider")


if __name__ == "__main__":
    unittest.main()
