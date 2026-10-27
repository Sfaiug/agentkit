"""`/effort` typed inside a seat becomes that seat's own orchestrator effort: once ak has looked
at it, its record holds the effort its latest answer since the launch ran at, and its `c` shows
it beside the orchestrator mark (the owner, 20 Oct 2026).  Black-box: `AK_BIN` as the popup over
an akseat.py seat orchestrated by Opus 5.5 at `xhigh`, whose transcript, written where Claude
Code keeps it, ends on an answer at `low`; it fails against `/bin/false`."""

from datetime import datetime, timezone
import json
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import SERVER, Terminal


def stamp(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat()


def opus_effort(screen):
    """The effort Opus 5.5's row shows beside its orchestrator mark, after that mark's bar."""
    return next((line.split()[5] for line in screen.split("\n")
                 if line.lstrip("› ").startswith("Opus 5.5")), None)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class EffortFollowedFromInside(unittest.TestCase):
    def test_an_answer_at_another_effort_since_the_launch_becomes_the_seat_s_own(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        fakeadapter.install(home, claude="pass", codex="pass")
        now = time.time()
        seat = Seat(home, "acme-fix", record={"launched": now - 600,
                                              "efforts": {"opus": {"effort": "xhigh"}}})
        project = "".join(c if c.isascii() and c.isalnum() else "-" for c in str(seat.cwd))
        home.write(f".claude/projects/{project}/{seat.record['conversation']}.jsonl",
                   json.dumps({"type": "assistant", "timestamp": stamp(now - 60), "effort": "low",
                               "message": {"model": "claude-opus-5-5"}}) + "\n")
        term = Terminal(home, "attach", "--overlay", size=(100, 30),
                        env={"NO_COLOR": "1", "AGENTKIT_SESSION": "acme-fix"})
        self.addCleanup(home.tmux, "respawn-pane", "-k", "-t", term.pane, "sleep 86400",
                        server=SERVER)
        term.wait("esc leave")
        path = home.path / ".agentkit/state/session-acme-fix.json"
        deadline = time.monotonic() + 30
        while (json.loads(path.read_text()).get("efforts") or {}).get("opus", {}).get(
                "effort") != "low":
            self.assertLess(time.monotonic(), deadline, path.read_text())
            time.sleep(0.05)
        term.keys("c")
        term.wait(lambda screen: "esc back" in screen and opus_effort(screen) == "low")


if __name__ == "__main__":
    unittest.main()
