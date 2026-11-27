"""A Home where a Stop can unpark a login: a provider with two logins and room on every meter,
and an orchestrator seat on the second.

Black-box: the harness's hooks fired in a seat's pane (tests/fixtures/hookdrive.py,
tests/fixtures/akseat.py) with no harness behind it (tests/fixtures/fakeadapter.py).  Each
refusal is made by `usage.mark_exhausted` itself in a child python3, at the moment
tests/fixtures/clock.py stands it at; what is parked is read back by `ak usage --json`.  No real
login or meter is reached.
"""

import json
from pathlib import Path
import sys
import time
import unittest
from urllib.parse import quote

from . import akconfig, fakeadapter
from .akbin import REAL_TMUX, Home
from .akseat import Seat
from .hookdrive import Hooks, conversation

TESTS = Path(__file__).resolve().parents[1]
LOGINS = ["default", "second"]
SECOND = {"AGENTKIT_ACCOUNT": "second"}     # the seat's harness, as ak launched it on that login
# A refusal on the provider and login named that no meter showed, at the moment named, of the
# model named: of none where that is "".
MARK = ("import sys; sys.path[:0] = sys.argv[1:3]; from agentkit import config, usage; "
        "from fixtures.clock import Clock; usage.time = clock = Clock(None); "
        "clock.time = lambda: float(sys.argv[5]); usage.mark_exhausted("
        "config.load(), sys.argv[3], account=sys.argv[4], model=sys.argv[6] or None)")


@unittest.skipUnless(REAL_TMUX, "no tmux")
class Unparking(unittest.TestCase):
    HARNESS, PROVIDER, MODEL, SCREEN = "claude", "anthropic", "opus", "claude-prompt-pane.txt"

    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, [self.MODEL], providers={
            self.PROVIDER: {"mode": "subscription", "accounts": LOGINS}})
        fakeadapter.install(home, **{self.HARNESS: "pass"})
        now = time.time()
        room = {"provider": self.PROVIDER, "resets": 0, "meters": [
            {"name": "session", "used": 25, "window_secs": 18000, "resets_at": now + 10800},
            {"name": "weekly_all", "used": 25, "window_secs": 604800,
             "resets_at": now + 3 * 86400}]}
        home.write(".agentkit/state/usage.json", {"fetched_at": now, "providers": {self.PROVIDER: {
            **room, "accounts": {login: room for login in LOGINS}}}})
        self.hooks = Hooks(home, self.HARNESS)

    def mark(self, login, at=None, model=None):
        """A refusal of `model` (the seat's model where None, none where "") on `login` at `at`,
        now where None."""
        done = self.home.run(sys.executable, "-c", MARK, str(TESTS.parent), str(TESTS),
                             self.PROVIDER, login, repr(time.time() if at is None else at),
                             self.MODEL if model is None else model)
        self.assertEqual(done.code, 0, done.err)

    def parked(self):
        """{login: whether it is parked}, as `ak usage --json` shows it."""
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        logins = json.loads(done.out)["providers"][self.PROVIDER]["accounts"]
        return {login: logins[login]["exhausted"] for login in LOGINS}

    def seat(self, name):
        """A seat whose record names the second login, and an open line in its plan: its Stop
        goes back, which says something."""
        return Seat(self.home, name, model=self.MODEL, screen=self.SCREEN,
                    record={"account": "second"}, planned=True)

    def updates(self, seat):
        """Where Grok Build keeps `seat`'s durable UI record (`updates.jsonl`)."""
        return (self.home.path / ".grok/sessions" / quote(str(seat.cwd), safe="")
                / seat.record["conversation"] / "updates.jsonl")

    def prompt(self, seat):
        if self.HARNESS == "claude":
            fired = self.hooks.prompt("fix the api", seat, env=SECOND, finished=True)
        elif self.HARNESS == "grokbuild":
            path = self.updates(seat)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as kept:
                kept.write(json.dumps({
                    "timestamp": int(time.time()), "method": "session/update",
                    "params": {"sessionId": seat.record["conversation"], "update": {
                        "sessionUpdate": "user_message_chunk",
                        "content": {"type": "text", "text": "fix the api"}}}}) + "\n")
            fired = self.hooks.fire("UserPromptSubmit", {"prompt": "fix the api"},
                                    seat=seat.name, pane=seat, env=SECOND, finished=True)
        elif self.HARNESS == "antigravity":
            fired = self.hooks.fire("PreInvocation", {"invocationNum": 0,
                                                      "lastUserInput": "fix the api"},
                                    seat=seat.name, pane=seat, env=SECOND, finished=True)
        else:
            fired = self.hooks.fire("UserPromptSubmit", {"prompt": "fix the api"},
                                    seat=seat.name, pane=seat, env=SECOND, finished=True)
        self.assertEqual(fired.code, 0, fired)

    def stop(self, seat, *said, env=SECOND, event="Stop", **payload):
        """The turn ends on `said`, the lines its record then holds -- an entry, or bytes as they
        are written, for a harness that keeps one -- its `event` (Stop) heard in `env` with
        `payload`; what the hook printed."""
        if self.HARNESS == "claude":
            path = conversation(self.home, seat)
            with path.open("ab") as kept:
                kept.write(b"".join((line if isinstance(line, bytes) else json.dumps(line).encode())
                                    + b"\n" for line in said))
            payload = {"background_tasks": [], "transcript_path": str(path), **payload}
        elif self.HARNESS == "grokbuild":
            if said:
                path = self.updates(seat)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("ab") as kept:
                    kept.write(b"".join(
                        (line if isinstance(line, bytes) else json.dumps(line).encode()) + b"\n"
                        for line in said))
        else:
            assert not said, f"{self.HARNESS} keeps no conversation lines here"
        fired = self.hooks.fire(event, payload, seat=seat.name, pane=seat, env=env, finished=True)
        self.assertEqual(fired.code, 0, fired)
        return fired
