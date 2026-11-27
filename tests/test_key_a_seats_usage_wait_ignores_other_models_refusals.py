"""A seat's advertised usage wait uses only refusals that park its model, earlier ones included.

A login's snapshot keeps the newest refusal at its top level and earlier in-force refusals beside
it in `exhausted_earlier`.  When an Opus seat waits for usage:
- a Fable refusal alone on its login does not postpone Opus's earlier session reset;
- a newer Fable refusal naming a shorter time does not hide an earlier Opus refusal that still has
  longer left;
- a live Opus refusal on a login already holding a longer Fable refusal advertises Opus's own
  deadline, not Fable's or another spent login's.

Black-box: the program `AK_BIN` names runs `ak watch` and `ak orch why` from outside through
tests/fixtures/akbin.py, beside a seat of tests/fixtures/akseat.py on a fake Claude harness of
fakeadapter.py and the usage readings the test writes.  Fails against /bin/false.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import socket
import sys
import time
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import PANE, Seat

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


def refused(text):
    """A Claude transcript turn ending on a usage-limit refusal saying `text`."""
    return {"type": "assistant", "isApiErrorMessage": True, "apiError": "usage_limit_reached",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class ASeatsUsageWaitIgnoresOtherModelsRefusals(unittest.TestCase):
    def setUp(self):
        self.home = home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file", TZ="UTC")
        akconfig.write(home, ["opus", "fable"],
                       providers={"anthropic": {"accounts": ["default", "second"]}})
        self.fake = fakeadapter.install(home, claude="pass")["claude"]

    def seat(self, name="acme", last=None):
        conversation = str(uuid.uuid4())
        seat = Seat(self.home, name, model="opus", record={
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

    def wait_after_tick(self, default_reading, second_reset, now):
        second = {"provider": "anthropic", "resets": 0, "meters": [
            {"name": "weekly_all", "used": 100, "window_secs": 604800, "resets_at": second_reset}]}
        accounts = {"default": default_reading, "second": second}
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"anthropic": {
                **default_reading, "accounts": accounts}}})
        done = self.home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.err)
        seat_state = json.loads((self.home.path / ".agentkit/state/seat-acme.json").read_text())
        return seat_state["usage_wait"], why.out

    def test_fable_refusal_alone_does_not_postpone_opus_session_reset(self):
        self.seat()
        now = float(int(time.time()))
        reset, fable_reset = now + 1800, now + 86400
        default = {
            "provider": "anthropic", "resets": 0,
            "meters": [
                {"name": "weekly_all", "used": 60, "window_secs": 604800, "resets_at": now + 86400},
                {"name": "session", "used": 100, "window_secs": 18000, "resets_at": reset},
                {"name": "weekly_scoped", "used": 100, "window_secs": 604800,
                 "resets_at": fable_reset, "scope": "Fable"}],
            "exhausted_until": fable_reset, "exhausted_at": now - 30,
            "exhausted_ends": {"weekly_scoped": fable_reset},
            "exhausted_used": {"weekly_scoped": 100},
            "exhausted_by": ["weekly_scoped", "Fable"],
            "exhausted_meters": [["weekly_scoped", "Fable"]]}
        wait, why = self.wait_after_tick(default, now + 172800, now)
        self.assertEqual(wait["until"], reset)
        when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(reset))
        self.assertIn(f"out of usage until {when}", why)

    def test_newer_fable_refusal_does_not_hide_earlier_opus_refusal(self):
        self.seat()
        now = float(int(time.time()))
        reset, fable_reset, opus_ready = now + 1800, now + 3600, now + 7200
        default = {
            "provider": "anthropic", "resets": 0,
            "meters": [
                {"name": "weekly_all", "used": 60, "window_secs": 604800, "resets_at": now + 86400},
                {"name": "session", "used": 100, "window_secs": 18000, "resets_at": reset},
                {"name": "weekly_scoped", "used": 100, "window_secs": 604800,
                 "resets_at": fable_reset, "scope": "Fable"}],
            "exhausted_until": fable_reset, "exhausted_at": now - 30,
            "exhausted_ends": {"weekly_scoped": fable_reset},
            "exhausted_used": {"weekly_scoped": 100},
            "exhausted_by": ["weekly_scoped", "Fable"],
            "exhausted_meters": [["weekly_scoped", "Fable"]],
            "exhausted_earlier": [{
                "exhausted_until": opus_ready, "exhausted_at": now - 60,
                "exhausted_ends": {"session": reset}, "exhausted_used": {"session": 100},
                "exhausted_by": ["session", None], "exhausted_meters": [["session", None]]}]}
        wait, why = self.wait_after_tick(default, now + 172800, now)
        self.assertEqual(wait["until"], opus_ready)
        when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(opus_ready))
        self.assertIn(f"out of usage until {when}", why)

    def test_live_opus_refusal_beside_longer_fable_refusal_advertises_opus_deadline(self):
        now = float(int(time.time()))
        reset, fable_reset = now + 1800, now + 86400
        iso = datetime.fromtimestamp(reset, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.seat(last=refused(f"Usage limit reached; try again at {iso}"))
        default = {
            "provider": "anthropic", "resets": 0,
            "meters": [
                {"name": "weekly_all", "used": 60, "window_secs": 604800, "resets_at": now + 86400},
                {"name": "weekly_scoped", "used": 100, "window_secs": 604800,
                 "resets_at": fable_reset, "scope": "Fable"}],
            "exhausted_until": fable_reset, "exhausted_at": now - 30,
            "exhausted_ends": {"weekly_scoped": fable_reset},
            "exhausted_used": {"weekly_scoped": 100},
            "exhausted_by": ["weekly_scoped", "Fable"],
            "exhausted_meters": [["weekly_scoped", "Fable"]]}
        wait, why = self.wait_after_tick(default, now + 172800, now)
        self.assertEqual(wait["until"], reset)
        when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(reset))
        self.assertIn(f"out of usage until {when}", why)


if __name__ == "__main__":
    unittest.main()
