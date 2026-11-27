"""A Grok Build seat's refused turn is read from its session's `updates.jsonl`, even when its
pane shows only an empty composer and its provider has no meters.

Grok Build 1.0.92 draws its allowance card over the composer without the server's words, and
dismissing it leaves an empty composer; its `updates.jsonl` still ends in a `turn_completed`
update with `stop_reason: "error"` and `agent_result` holding the API error.  A tick reads that
error, parks the login, and `ak orch why` reads `out of usage` with nothing typed into the pane.
Black-box for the seat and tick (tests/fixtures/akbin.py, akseat.py, fakeadapter.py); a child
python3 checks the plugin's `error` and `Harness.failure` contract on the same record shapes.
"""

import json
from pathlib import Path
import sys
import time
import unittest
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat

REPO = Path(__file__).resolve().parents[1]
SESSION = "01a219a3-43f3-73b2-a4f2-400124f501ba"
PROMPT_ID = "f8dd7484-1b3f-474e-8b5e-64f076039816"
REFUSAL_402 = ("API error (status 402 Payment Required): usage_limit_reached: "
               "You have run out of credits for this week. Usage resets at 2026-11-27T00:00:00Z.")
REFUSAL_FREE = ("API error (status 429 Too Many Requests): subscription:free-usage-exhausted: "
                "Free allowance spent.")
# A child python3 reading the plugin's `error` and `failure` in a Home's environment, so this key
# keeps no import of agentkit itself (tests/test_keys_run_ak_from_outside.py).
ASK_ERROR = ("import json, sys; sys.path.insert(0, sys.argv[1]); from agentkit import harness; "
             "plugin = harness.load('grokbuild'); "
             "print(json.dumps(plugin.error({'cwd': sys.argv[2]}, sys.argv[2], sys.argv[3])))")
ASK_FAILURE = ("import json, sys; sys.path.insert(0, sys.argv[1]); from agentkit import harness; "
               "print(json.dumps(list(harness.load('grokbuild').failure(sys.argv[2]))))")


def user_row(text, session=SESSION, **extra):
    return {"timestamp": 1795726461, "timestamp_us": 1795726461507860, "method": "session/update",
            "params": {"sessionId": session, "update": {
                "sessionUpdate": "user_message_chunk",
                "content": {"type": "text", "text": text}, **extra}}}


def refused_rows(message=REFUSAL_402, http_status=402, session=SESSION):
    return [
        user_row("say hi", session=session),
        {"timestamp": 1795726461, "timestamp_us": 1795726461532508,
         "method": "_x.ai/session/update",
         "params": {"sessionId": session, "update": {
             "sessionUpdate": "retry_state", "type": "failed", "error_type": "api",
             "message": message}}},
        {"timestamp": 1795726461, "timestamp_us": 1795726461575204,
         "method": "_x.ai/session/update",
         "params": {"sessionId": session, "update": {
             "sessionUpdate": "turn_completed", "prompt_id": PROMPT_ID,
             "stop_reason": "error", "agent_result": message,
             "error": {"code": -32603, "message": "Internal error",
                       "data": {"message": message, "http_status": http_status}},
             "elapsed_ms": 147}}},
    ]


def write_updates(home, cwd, session, rows):
    path = home.path / ".grok/sessions" / quote(str(cwd), safe="") / session / "updates.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


class GrokBuildsRefusedTurnIsReadFromItsRecord(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)

    def plugin_error(self, cwd, session=SESSION):
        done = self.home.run(sys.executable, "-c", ASK_ERROR, str(REPO), str(cwd), session)
        self.assertEqual(done.code, 0, done.err)
        return json.loads(done.out)

    def plugin_failure(self, text):
        done = self.home.run(sys.executable, "-c", ASK_FAILURE, str(REPO), text)
        self.assertEqual(done.code, 0, done.err)
        return tuple(json.loads(done.out))

    def refused_seat(self, message=REFUSAL_402, http_status=402):
        """A Grok Build seat on a meterless provider at an empty composer, its record ending on
        `message`, after one `ak watch` tick; returns (seat, `ak orch why` output)."""
        akconfig.write(self.home, ["grok"])
        fakeadapter.install(self.home, grokbuild="pass")
        now = time.time()
        # No meters on the provider: ak learns of the refusal only from the session's record.
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now,
            "providers": {"xai": {"provider": "xai", "meters": [], "none": True,
                                  "none_reason": "no meter", "resets": 0}}})
        seat = Seat(self.home, "acme", model="grok", screen="grok-prompt-pane.txt",
                    record={"conversation": SESSION, "launched": now - 600})
        write_updates(self.home, seat.cwd, SESSION, refused_rows(message, http_status=http_status))
        tick = self.home.tick()
        self.assertEqual(tick.code, 0, tick.out + tick.err)
        why = self.home.ak("orch", "why", "acme")
        self.assertEqual(why.code, 0, why.err)
        return seat, why.out

    @unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
    def test_a_seat_at_an_empty_composer_reads_out_of_usage(self):
        seat, why = self.refused_seat()
        self.assertEqual(why.splitlines()[:1], ["acme  out of usage"], why)
        self.assertIn("xai out of usage", why)
        self.assertEqual(seat.typed(), "")

    @unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
    def test_a_free_refusal_at_an_empty_composer_reads_out_of_usage(self):
        seat, why = self.refused_seat(REFUSAL_FREE, http_status=429)
        self.assertEqual(why.splitlines()[:1], ["acme  out of usage"], why)
        self.assertEqual(seat.typed(), "")

    def test_plugin_error_reads_the_last_turn_completed_error(self):
        cwd = self.home.path / "code" / "acme"
        cwd.mkdir(parents=True)
        # No updates.jsonl -> None.
        self.assertIsNone(self.plugin_error(cwd))
        # Refused turn -> agent_result.
        write_updates(self.home, cwd, SESSION, refused_rows())
        self.assertEqual(self.plugin_error(cwd), REFUSAL_402)
        # A newer user_message_chunk after it -> "".
        write_updates(self.home, cwd, SESSION, [*refused_rows(), user_row("try again")])
        self.assertEqual(self.plugin_error(cwd), "")
        # A turn_completed with another stop_reason -> "".
        ended = {"timestamp": 1795726465, "method": "_x.ai/session/update",
                 "params": {"sessionId": SESSION, "update": {
                     "sessionUpdate": "turn_completed", "stop_reason": "end_turn"}}}
        write_updates(self.home, cwd, SESSION, [*refused_rows(), ended])
        self.assertEqual(self.plugin_error(cwd), "")

    def test_manifest_reads_both_refusals_as_spent(self):
        self.assertEqual(self.plugin_failure("API error (status 402 Payment Required): declined"),
                         ("spent", "402 Payment Required"))
        self.assertEqual(
            self.plugin_failure("API error (status 429 Too Many Requests): "
                                "subscription:free-usage-exhausted: declined"),
            ("spent", "subscription:free-usage-exhausted"))


if __name__ == "__main__":
    unittest.main()
