"""A full 5h window its provider names for one model spends that model alone.

Anthropic's usage endpoint says whose limit is whose, and `adapters/claude.sh usage` keeps that
name as the meter's `scope`.  A session window scoped to Fable that reads 100% used passes the
Fable seat over to Opus, which still has its shared week, and one scoped to Opus leaves Fable
its seat though Fable names its own weekly `meter`; a full session window naming no scope stops
every model of the login, so the seat goes to the default anyway with a WARN.

Black-box: the program `AK_BIN` names opens a seat by `ak orch cr-seat --dry-run` from outside
through tests/fixtures/akbin.py, its Claude adapter over a fake `curl` answering the endpoint.
This test fails against `/bin/false`.
"""

from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import Home

OPUS, FABLE = "claude-opus-5-5", "claude-fable-5-2"
FABLE_ONLY = {"model": {"id": None, "display_name": "Fable"}, "surface": None}
OPUS_ONLY = {"model": {"id": None, "display_name": "Opus"}, "surface": None}


def seat_said(case, scope, meter=None):
    """The `orch:` line a dry-run seat prints on one Claude login, Fable its default
    orchestrator naming `meter`, whose shared week is 40% used beside a full session window in
    `scope`."""
    made = Home()
    case.addCleanup(made.close)
    akconfig.write(made, {FABLE: {"harness": "claude", **({"meter": meter} if meter else {})},
                          OPUS: "claude"})

    def at(secs):
        return time.strftime("%Y-%m-%dT%H:%M:%S.667575+00:00", time.gmtime(time.time() + secs))

    limits = [{"kind": "weekly_all", "group": "weekly", "percent": 40, "severity": "normal",
               "resets_at": at(3 * 86400), "scope": None, "is_active": False},
              {"kind": "session", "group": "session", "percent": 100, "severity": "critical",
               "resets_at": at(7200), "scope": scope, "is_active": True}]
    made.write(".agentkit/secrets/claude_oauth_token", "tok-acme")
    answer = made.write("answer.json", {"limits": limits})
    made.fake("curl", f"#!/bin/sh\ncat '{answer}'\nprintf '\\n200'\n")
    made.fake("security", "#!/bin/sh\nexit 1\n")     # no Keychain login on any host
    done = made.ak("orch", "cr-seat", "--dry-run")
    case.assertEqual(done.code, 0, done.out + done.err)
    return next(line for line in done.out.splitlines() if line.startswith("orch: "))


class ScopedSessionWindow(unittest.TestCase):
    def test_a_full_window_scoped_to_fable_hands_the_seat_to_opus(self):
        said = seat_said(self, FABLE_ONLY)
        self.assertTrue(said.startswith(f"orch: {OPUS} ("), said)
        self.assertNotIn("WARN", said)

    def test_a_full_window_scoped_to_opus_leaves_fable_naming_its_meter_the_seat(self):
        said = seat_said(self, OPUS_ONLY, meter="weekly_scoped")
        self.assertTrue(said.startswith(f"orch: {FABLE} ("), said)
        self.assertNotIn("WARN", said)

    def test_a_full_window_naming_no_scope_stops_both(self):
        said = seat_said(self, None)
        self.assertTrue(said.startswith(f"orch: {FABLE} (WARN "), said)


if __name__ == "__main__":
    unittest.main()
