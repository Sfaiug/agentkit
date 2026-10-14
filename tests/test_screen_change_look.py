"""A seat is looked at again when its screen comes to rest, starts moving, or its harness exits.

Nothing else tells ak about an answered question, an Esc, an error that ended a turn, or any
change on a harness without a hook for it: tools/idle-compact.py, which every seat's harness runs
under, sees the screen move and stop.  Offline: the wrapper runs under a pty around a fake
harness, with a fake tmux on PATH that writes down every call and answers a capture with a
fixture pane; the look itself is replaced in-process where the test counts looks.
"""

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
WRAPPER = REPO / "tools/idle-compact.py"
FIXTURES = REPO / "tests/fixtures"

spec = importlib.util.spec_from_file_location("idle_compact", WRAPPER)
idle_compact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(idle_compact)

# Writes every call down; a capture is answered with the pane the test named.
FAKE_TMUX = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_TMUX_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if "capture-pane" in sys.argv:
    sys.stdout.write(open(os.environ["FAKE_PANE"]).read())
'''

# Draws `bursts` of output, each `frames` frames `gap` seconds apart, `rest` seconds between
# bursts, then exits.
FAKE_HARNESS = '''#!/usr/bin/env python3
import os, sys, time
bursts, frames = int(os.environ["BURSTS"]), int(os.environ["FRAMES"])
gap, rest = float(os.environ["GAP"]), float(os.environ["REST"])
for burst in range(bursts):
    for frame in range(frames):
        sys.stdout.write(f"frame {burst}.{frame}\\r\\n")
        sys.stdout.flush()
        time.sleep(gap)
    time.sleep(rest)
'''


class Check(unittest.TestCase):
    """What the pane reads decides whether the seat is looked at."""

    def looks(self, panes):
        made = []
        looks = idle_compact.Looks("acme", "claude", "/tmp/acme-sock", "%5",
                                   look=lambda wait=True: made.append(wait))
        reads = iter(panes)
        looks.read = lambda: next(reads)
        return looks, made

    def pane(self, name):
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_a_changed_reading_is_looked_at_and_an_unchanged_one_is_not(self):
        looks, made = self.looks([self.pane("claude-question-pane.txt"),
                                  self.pane("claude-question-pane.txt"),
                                  self.pane("claude-prompt-pane.txt"),
                                  self.pane("claude-working-pane.txt"),
                                  self.pane("claude-working-pane.txt")])
        looks.check()                      # the question went up
        self.assertEqual(made, [True])
        looks.check()                      # the same question, redrawn
        self.assertEqual(made, [True])
        looks.check()                      # answered: its composer
        looks.check()                      # its turn runs on
        looks.check()                      # ... and keeps drawing its spinner
        self.assertEqual(made, [True, True, True])

    def test_a_pane_that_cannot_be_read_is_not_a_change(self):
        looks, made = self.looks([self.pane("claude-prompt-pane.txt"), None,
                                  self.pane("claude-prompt-pane.txt")])
        looks.check()
        looks.check()
        looks.check()
        self.assertEqual(made, [True])

    def test_an_exited_harness_is_looked_at_without_waiting_for_the_look(self):
        looks, made = self.looks([])
        looks.ended()
        self.assertEqual(made, [False])

    def test_only_a_named_seat_in_its_own_pane_is_looked_at(self):
        seat = {"AGENTKIT_SESSION": "acme", "TMUX": "/tmp/acme-sock,1,0", "TMUX_PANE": "%5"}
        for missing in ("AGENTKIT_SESSION", "TMUX", "TMUX_PANE"):
            env = {key: value for key, value in seat.items() if key != missing}
            with patch.dict(os.environ, env, clear=True):
                self.assertIsNone(idle_compact.seat_looks("claude"), missing)
        with patch.dict(os.environ, {**seat, "AGENTKIT_SESSION": "../acme"}, clear=True):
            self.assertIsNone(idle_compact.seat_looks("claude"))


class Screen(unittest.TestCase):
    """The wrapper reads the pane each time the screen comes to rest or starts moving."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-look-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "tmux").write_text(FAKE_TMUX)
        (bin_dir / "tmux").chmod(0o755)
        self.harness = self.root / "harness.py"
        self.harness.write_text(FAKE_HARNESS)
        self.log = self.root / "tmux.jsonl"
        self.log.write_text("")
        self.bin = bin_dir

    def run_seat(self, **draw):
        env = {key: value for key, value in os.environ.items()
               if key not in ("IDLE_COMPACT_STATE", "AK_RUN_ROLE", "XDG_DATA_HOME")}
        env.update(HOME=str(self.root), PATH=f"{self.bin}{os.pathsep}{env['PATH']}",
                   AGENTKIT_SESSION="acme", TMUX=f"{self.root / 'sock'},1,0", TMUX_PANE="%5",
                   AGENTKIT_TMUX_SOCKET="agentkit-test", TMUX_TMPDIR=str(self.root),
                   FAKE_TMUX_LOG=str(self.log),
                   FAKE_PANE=str(FIXTURES / "claude-prompt-pane.txt"),
                   **{key: str(value) for key, value in draw.items()})
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 100, 0, 0))
        proc = subprocess.Popen(
            [sys.executable, str(WRAPPER), "--harness", "claude", "--",
             sys.executable, str(self.harness)],
            stdin=slave, stdout=slave, stderr=subprocess.DEVNULL, env=env, cwd=str(self.root))
        os.close(slave)
        self.addCleanup(proc.kill)
        try:
            while proc.poll() is None:
                if select.select([master], [], [], 0.05)[0]:
                    try:
                        if not os.read(master, 65536):
                            break
                    except OSError:
                        break
        finally:
            os.close(master)
        proc.wait(timeout=30)
        return [json.loads(line) for line in self.log.read_text().splitlines() if line]

    def captures(self, calls):
        return [call for call in calls if "capture-pane" in call]

    def test_each_burst_of_drawing_is_read_when_it_starts_and_when_it_stops(self):
        rest = idle_compact.SETTLE * 4
        calls = self.run_seat(BURSTS=3, FRAMES=1, GAP=0, REST=rest)
        captures = self.captures(calls)
        # three bursts: each starts the screen moving and each comes to rest
        self.assertGreaterEqual(len(captures), 6, calls)
        self.assertEqual(captures[0], ["-S", str(self.root / "sock"), "capture-pane", "-p",
                                       "-e", "-J", "-t", "%5"])

    def test_a_screen_that_keeps_drawing_is_read_only_when_it_starts_and_stops(self):
        # a spinner: frames well inside the settle time, for as long as three bursts above
        frames = 30
        calls = self.run_seat(BURSTS=1, FRAMES=frames, GAP=idle_compact.SETTLE / 5,
                              REST=idle_compact.SETTLE * 2)
        self.assertLessEqual(len(self.captures(calls)), 2, calls)


if __name__ == "__main__":
    unittest.main()
