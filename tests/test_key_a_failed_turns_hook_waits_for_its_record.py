"""A failed turn's hook waits for its words on record before it settles the seat's account.

Claude Code fires a turn's `StopFailure` before it records what the turn failed on (2.1.328,
19 Nov 2026: the record landed 0.14 s after the hook began).  Settled at once, a seat whose
login was spent moved as an idle one, told nothing to go on, and the next tick read the refusal
as the new login's: it parked a login with room and the seat read `out of usage`.  The hook's
look now first waits for the record to hold the words its fact keeps (#3926), then settles on
that record, as every later look reads it.  Black-box: the program `AK_BIN` names, through
tests/fixtures/akbin.py, beside a seat of tests/fixtures/akseat.py whose hooks are fired as
Claude fires them (tests/fixtures/hookdrive.py) and whose failure is recorded only once that
hook's fact is in place, on fake harnesses of fakeadapter.py and the usage readings the test
writes.
"""

import json
import re
import shlex
import socket
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, Seat
from fixtures.hookdrive import Hooks

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
FINE = {"mem_total_mb": 16000, "cpus": 8, "load": 0.1, "free_mb": 12000}
CONVERSATION = "3e7a9c1b-5d2f-4b8e-a6c0-9f1d3b5e7a2c"
LIMIT = "You've hit your session limit · resets 6:59pm"
REFUSED = {"type": "assistant", "isApiErrorMessage": True, "apiError": "usage_limit_reached",
           "message": {"role": "assistant", "content": [{"type": "text", "text": LIMIT}]}}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class FailedTurnsHookWaitsForItsRecord(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"))
        akconfig.write(home, ["opus"], providers={"anthropic": {"accounts": ["default", "second"]}})
        self.claude = fakeadapter.install(home, claude="pass")["claude"]
        self.seat = Seat(home, "acme", record={"conversation": CONVERSATION, "account": "default"})
        self.claude.answer("interactive", shlex.join(
            [sys.executable, str(PANE), str(self.seat.screen_file), str(self.seat.typed_file)]))
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(self.seat.cwd))
        self.conversation = home.path / f".claude/projects/{folder}/{CONVERSATION}.jsonl"
        self.conversation.parent.mkdir(parents=True)
        # every login reads the usual one's conversations, as Claude's adapter links them
        (home.path / ".claude-second").mkdir()
        (home.path / ".claude-second/projects").symlink_to(home.path / ".claude/projects")
        self.hooks = Hooks(home)

    def readings(self, used):
        """The first login `used`% into its session window, the second 10%, read a moment ago."""
        now = time.time()

        def reading(used):
            return {"provider": "anthropic", "resets": 0, "meters": [
                {"name": "session", "used": used, "window_secs": 18000, "resets_at": now + 10800},
                {"name": "weekly_all", "used": 30, "window_secs": 604800,
                 "resets_at": now + 3 * 86400}]}
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"anthropic": {
                **reading(used), "accounts": {"default": reading(used), "second": reading(10)}}}})

    def fire(self, event, payload):
        """The seat's harness fires that event, returning once all it started has ended: its
        exit code."""
        return self.hooks.fire(event, payload, seat="acme", pane=self.seat, finished=True).code

    def failed_mid_turn(self):
        """The owner's prompt, then its turn failing on the limit: the hook fired while the
        conversation ends on the prompt, the failure recorded once the hook's fact is down."""
        self.conversation.write_text(json.dumps(
            {"type": "user", "message": {"role": "user", "content": "go"}}) + "\n")
        self.assertEqual(self.fire("UserPromptSubmit", {"prompt": "go"}), 0)
        codes = []
        hook = threading.Thread(target=lambda: codes.append(self.fire(
            "StopFailure", {"error": "rate_limit", "last_assistant_message": LIMIT})))
        hook.start()
        fact = self.home.path / ".agentkit/state/hook-acme.json"
        deadline = time.monotonic() + 120
        while json.loads(fact.read_text()).get("event") != "StopFailure":
            self.assertLess(time.monotonic(), deadline, "the hook never wrote its fact")
            time.sleep(0.01)
        with self.conversation.open("a") as conversation:
            conversation.write(json.dumps(REFUSED) + "\n")
        hook.join()
        self.assertEqual(codes, [0])

    def usage(self, account):
        """Whether that login is parked, as `ak usage` reads it."""
        done = self.home.ak("usage", "--json")
        self.assertEqual(done.code, 0, done.out + done.err)
        return json.loads(done.out)["providers"]["anthropic"]["accounts"][account]["exhausted"]

    def moves_on_and_goes_on(self):
        """The hook's look reopens the seat on the second login, told to go on; that line's
        prompt heard, two ticks leave the second login unparked and the seat in usage."""
        self.failed_mid_turn()
        record = json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())
        self.assertEqual(record.get("account"), "second")
        [opened] = self.claude.calls("interactive")
        self.assertEqual(opened["env"].get("AGENTKIT_ACCOUNT"), "second")
        line = opened["env"].get("AGENTKIT_FIRST_PROMPT")
        self.assertIn("Continue that turn", line or "")
        self.assertEqual(self.fire("UserPromptSubmit", {"prompt": line}), 0)
        for _ in range(2):
            done = self.home.ak("watch", boxed=True, env={"AK_HOST_READINGS": json.dumps(FINE)})
            self.assertEqual(done.code, 0, done.out + done.err)
        self.assertFalse(self.usage("second"), "the second login parked")
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.err)
        self.assertNotEqual(why.out.splitlines()[0].split(None, 1)[1], "out of usage")
        self.assertEqual(len(self.claude.calls("interactive")), 1)

    def test_a_spent_login_moves_the_seat_on_with_a_line_to_go_on(self):
        self.readings(100)
        self.moves_on_and_goes_on()

    def test_a_login_whose_meters_show_room_moves_it_the_same_and_is_parked(self):
        self.readings(20)
        self.moves_on_and_goes_on()
        self.assertTrue(self.usage("default"), "the first login unparked")


if __name__ == "__main__":
    unittest.main()
