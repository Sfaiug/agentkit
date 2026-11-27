"""A seat of another model leaves, between turns, a login where only the part of its week held
for a cap is left.

A Claude login's kept reading holds its shared week (`weekly_all`) and Fable's own cap
(`weekly_scoped`, scope `Fable`), which carries `held`: the points of that week held for it.  To
an open seat of any other model the login runs low by what it has left past that part, and the
rule for a login running low holds: an idle Opus seat moves to a login with room past the part
held there, and stays where every other login is as low, its next turn running there.  That part
parks no seat: one waiting for usage on a login only it fills goes on there.  A Fable seat reads
the week as it is.

The owner (26 Nov 2026): "ideally we want all to run out when both fable and other model usage
are at 0. Fable should not still have usage left".

Black-box: the program `AK_BIN` names runs `ak watch` from outside through
tests/fixtures/akbin.py, beside seats of tests/fixtures/akseat.py whose owner's prompt is fired
as Claude fires it (tests/fixtures/hookdrive.py), on fake harnesses of fakeadapter.py and the
usage readings the test writes.  Fails against /bin/false.
"""

import json
import os
import re
import shlex
import socket
import sys
import time
import unittest
from pathlib import Path
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, Seat
from fixtures.hookdrive import Hooks

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
REFUSED = {"type": "assistant", "isApiErrorMessage": True, "apiError": "usage_limit_reached",
           "message": {"role": "assistant", "content": [
               {"type": "text", "text": "Back after a little rest"}]}}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ASeatLeavesALoginOnlyACapsPartIsLeftOn(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file")
        akconfig.write(home, ["opus", "fable"],
                       providers={"anthropic": {"accounts": ["default", "second"]}})
        self.fake = fakeadapter.install(home, claude="pass")["claude"]

    def seat(self, name, model="opus", last=None):
        """A seat of `model` at its prompt on the usual login, its home, with a conversation of
        its own whose last turn ended on `last`, else on the owner's word: the seat made last is
        the one whose pane a relaunch draws."""
        conversation = str(uuid.uuid4())
        seat = Seat(self.home, name, model=model, record={
            "account": "default", "home_account": "default", "conversation": conversation})
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        turns = [{"type": "user", "message": {"role": "user", "content": "go"}}, last]
        self.home.write(f".claude/projects/{folder}/{conversation}.jsonl",
                        "".join(json.dumps(turn) + "\n" for turn in turns if turn))
        tty = self.home.tmux("display-message", "-p", "-t", seat.pane, "#{pane_tty}").out.strip()
        os.utime(tty, (time.time() - 600,) * 2)      # its terminal untouched for ten minutes
        self.fake.answer("interactive", shlex.join(
            [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]))
        return seat

    def tick(self, **logins):
        """One tick over logins each given (week used%, points of it its Fable cap holds, or
        None): the login and first prompt of each seat the tick opened again."""
        now = time.time()

        def reading(week, held):
            meter = {"window_secs": 604800, "resets_at": now + 3 * 86400}
            cap = {**meter, "name": "weekly_scoped", "scope": "Fable", "used": 20}
            return {"provider": "anthropic", "resets": 0, "meters": [
                {**meter, "name": "weekly_all", "used": week},
                {**cap, "held": held} if held is not None else cap]}
        accounts = {login: reading(*pair) for login, pair in logins.items()}
        # the readings of a moment ago, which a tick reads again only once they are stale
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"anthropic": {
                **accounts["default"], "accounts": accounts}}})
        done = self.home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        return [(call["env"].get("AGENTKIT_ACCOUNT") or "default",
                 bool(call["env"].get("AGENTKIT_FIRST_PROMPT")))
                for call in self.fake.calls("interactive")]

    def state(self, name):
        """The login the seat's record names, and its word (`ak orch why`), which reads `out of
        usage` while it waits for usage."""
        why = self.home.ak("orch", "why", name)
        self.assertEqual(why.code, 0, why.err)
        record = json.loads((self.home.path / f".agentkit/state/session-{name}.json").read_text())
        return record.get("account"), why.out.splitlines()[0].split(None, 1)[1]

    def test_another_models_seat_moves_to_room_past_its_held_part_and_the_caps_own_stays(self):
        self.seat("acme-fable", model="fable")
        self.seat("acme")
        self.assertEqual(self.tick(default=(60, 40), second=(30, 20)), [("second", False)])
        self.assertEqual(self.state("acme"), ("second", "idle"))
        self.assertEqual(self.state("acme-fable"), ("default", "idle"))

    def test_with_every_other_login_as_low_it_stays_and_its_next_turn_runs(self):
        seat = self.seat("acme")
        self.assertEqual(self.tick(default=(60, 40), second=(60, 40)), [])
        self.assertEqual(self.state("acme"), ("default", "idle"))
        # the owner's next prompt, as Claude fires it: its turn runs where the seat is
        fired = Hooks(self.home).prompt("Add a retry button to the upload page.", seat)
        self.assertEqual(fired.code, 0, fired)
        seat.show("claude-working-pane.txt")
        self.assertEqual(self.tick(default=(60, 40), second=(60, 40)), [])
        self.assertEqual(self.state("acme"), ("default", "working"))
        self.assertEqual(seat.lines(), [])      # nothing typed into it

    def test_a_login_only_its_held_part_fills_is_not_waited_on_for_a_reset(self):
        self.seat("acme", last=REFUSED)
        now = time.time()
        self.home.write(".agentkit/state/seat-acme.json", {"session": "acme", "usage_wait": {
            "reason": "anthropic out of usage", "since": now - 600, "until": now + 3 * 86400,
            "continue": True}})
        self.assertEqual(self.tick(default=(60, 40), second=(100, None)), [("default", True)])
        self.assertEqual(self.state("acme"), ("default", "working"))


if __name__ == "__main__":
    unittest.main()
