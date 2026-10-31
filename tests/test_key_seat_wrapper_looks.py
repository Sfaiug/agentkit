"""Inside a seat's pane, the wrapper on its line names its harness's terminal and looks at the
seat when its screen settles and when its harness exits, once its pane has ended.

The line a harness's adapter prints for `ak orch` runs the harness inside a wrapper of ak's.  In
a seat's own pane on ak's tmux server, the wrapper names the harness's terminal in the pane's
`@ak_input_tty` before the harness starts, so ak never types in while the harness has input it
has not read.  It looks at the seat whenever the screen comes to rest, and again when the harness
exits, so the seat's published word follows its screen with no hook and no tick.  That last look
reads the seat closed even where the pane's own process outlives the wrapper a moment.

Black-box: as in tests/test_key_seat_relay.py, the adapter beside the program `AK_BIN` names (or
`AK_ROOT`'s) prints the line, with a fake harness first on PATH under the harness's own name.
Here the line runs in the pane of a seat tests/fixtures/akseat.py opened, respawned as ak
respawns a seat's pane, under a shell that holds the pane HOLD seconds past the wrapper's end: a
look that read the pane before it ended would find the seat at its prompt.  The fake shows
captures of real screens from tests/fixtures, fires no hook, and writes down its own terminal and
what the pane named when it started.  Nothing here runs ak, whose own look would publish a word
too.  This test fails against `/bin/false`.
"""

import json
from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import FIXTURES, Seat
from fixtures.hookdrive import ROOT

WORKING, PROMPT = "claude-working-pane.txt", "claude-prompt-pane.txt"
BOUND = 60      # seconds any change may take on a loaded host
HOLD = 2        # seconds the pane outlives its wrapper: far longer than a look takes to start
# Each screen at rest as its word and the rule that gave it; a harness gone, as its word and why.
WORKED = ("working", "working.spinner")
IDLE = ("idle", "prompt.composer")
CLOSED = ("idle", "session closed: press 1 to reopen")
# Writes down its terminal and what the pane names as the harness's once it shows a turn at work,
# and holds that still.  Told to rest, it turns that turn's spinner for a second and ends it at
# the prompt with no pause: the prompt arrives while the screen moves, so only a look once it
# settles can see it.  It holds the prompt still until told to exit.
FAKE = """#!{python}
import json, os, subprocess, time
named = subprocess.run(["tmux", "show-options", "-pv", "-t", os.environ.get("TMUX_PANE", ""),
                        "@ak_input_tty"], capture_output=True, text=True).stdout.strip()

def show(screen):
    with open(screen, encoding="utf-8") as text:
        frame = text.read().rstrip("\\n").replace("\\n", "\\r\\n")
    os.write(1, ("\\x1b[H\\x1b[2J" + frame).encode())

show({working!r})
with open({part!r}, "w") as out:
    json.dump({{"tty": os.ttyname(0), "named": named}}, out)
os.replace({part!r}, {saw!r})
while not os.path.exists({rest!r}):
    time.sleep(0.05)
for _ in range(20):
    time.sleep(0.05)
    show({working!r})
show({prompt!r})
while not os.path.exists({leave!r}):
    time.sleep(0.05)
"""


def read(path):
    """A JSON file's object, or {} until one is there."""
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def waited(path, holds=bool):
    """`read(path)` once `holds` it, or as it stands after BOUND seconds."""
    deadline = time.monotonic() + BOUND
    while not holds(got := read(path)) and time.monotonic() < deadline:
        time.sleep(0.1)
    return got


def said(record):
    """A seat's published word, and the rule that gave it."""
    return record.get("word"), record.get("rule")


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class TheWrapperInASeatsPane(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        saw, rest, leave = (home.root / name for name in ("saw.json", "rest", "exit"))
        home.fake("claude", FAKE.format(
            python=sys.executable, saw=str(saw), part=f"{saw}.part", rest=str(rest),
            leave=str(leave), working=str(FIXTURES / WORKING), prompt=str(FIXTURES / PROMPT)))
        # A turn at work until the fake draws: no screen left from before reads as a prompt.
        seat = Seat(home, "acme", screen=WORKING)
        # what `orch.command` hands the verb
        told = {"AGENTKIT_SESSION": "acme", "AGENTKIT_ACCOUNT": "",
                "AGENTKIT_RULEBOOK": str(home.write("rb.md", "rb\n")),
                "AGENTKIT_FIRST_PROMPT": "", "AGENTKIT_CLAUDE_CHECKED": "1"}
        printed = home.run("bash", str(ROOT / "adapters" / "claude.sh"), "interactive",
                           "claude-opus-5-5", "high", env=told, cwd=seat.cwd)
        assert printed.code == 0 and printed.out.strip(), printed.err
        # parsed as `ak orch` parses it, and run in the seat's pane as its launch runs it, the
        # pane held past the wrapper's end
        done = home.tmux("respawn-pane", "-k", "-t", seat.pane, "-c", str(seat.cwd),
                         f"{shlex.join(shlex.split(printed.out))}; sleep {HOLD}")
        assert done.code == 0, done.err
        published = home.path / ".agentkit" / "state" / "seat-acme.json"
        cls.saw = waited(saw)
        cls.worked = waited(published, lambda got: said(got) == WORKED)
        rest.touch()
        cls.rested = waited(published, lambda got: said(got) == IDLE)
        leave.touch()
        cls.left = waited(published, lambda got: (got.get("word"), got.get("reason")) == CLOSED)

    def test_the_pane_names_the_harness_s_terminal_before_the_harness_starts(self):
        self.assertTrue(self.saw.get("tty"), "the harness never started")
        self.assertEqual(self.saw.get("named"), self.saw["tty"])

    def test_the_published_word_follows_the_screen_from_work_to_the_prompt_with_its_rule(self):
        self.assertEqual([said(self.worked), said(self.rested)], [WORKED, IDLE],
                         [self.worked, self.rested])

    def test_the_seat_is_looked_at_again_when_its_harness_exits(self):
        self.assertEqual((self.left.get("word"), self.left.get("reason")), CLOSED, self.left)


if __name__ == "__main__":
    unittest.main()
