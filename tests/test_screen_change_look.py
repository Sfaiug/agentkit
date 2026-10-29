"""A seat is looked at again when its screen comes to rest, starts moving, or its harness exits.

Nothing else tells ak about an answered question, an Esc, an error that ended a turn, or any
change on a harness without a hook for it: tools/idle-compact.py, which every seat's harness runs
under, sees the screen move and stop.  Offline: the wrapper runs under a pty around a fake
harness, with a fake tmux on PATH that writes down every call and answers a capture with a
fixture pane; where a test counts looks, the seat's own look runs in-process on
test_live_status's seat, its record, hooks and pane faked.
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
from agentkit import config, watch  # noqa: E402
import test_live_status  # noqa: E402

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
    """What the pane reads, against what the seat's published word was decided from, decides
    whether it is looked at."""

    def setUp(self):
        self.seat = test_live_status.LiveStatus()
        self.seat.setUp()
        self.addCleanup(lambda: self.assertTrue(self.seat.doCleanups()))

    def looks(self, harness="claude"):
        """The seat's `Looks`, its look the seat's own, each one counted; its capture reads the
        pane its look reads."""
        made = []

        def look(wait=True):
            made.append(wait)
            watch.hook_look("herdr")
        with patch.object(idle_compact.threading.Thread, "start"):
            looks = idle_compact.Looks("herdr", harness, "/fake/agentkit-test", "%7", look=look)
        looks.read = lambda: self.seat.pane.return_value
        return looks, made

    def show(self, name, *swap):
        """Put that fixture pane on the seat's screen, each (old, new) of `swap` replaced."""
        text = (FIXTURES / name).read_text(encoding="utf-8")
        for old, new in swap:
            text = text.replace(old, new)
        self.seat.pane.return_value = text
        return text

    def test_a_reading_its_word_was_not_decided_from_is_looked_at_and_one_it_was_is_not(self):
        looks, made = self.looks()
        self.show("claude-question-pane.txt")
        looks.check()                      # the question went up
        self.assertEqual(made, [True])
        looks.check()                      # the same question, redrawn
        self.assertEqual(made, [True])
        self.show("claude-prompt-pane.txt")
        looks.check()                      # answered: its composer
        self.show("claude-working-pane.txt")
        looks.check()                      # its turn runs on
        looks.check()                      # ... and keeps drawing its spinner
        self.assertEqual(made, [True, True, True])
        self.assertEqual(watch.seat_read("herdr")["state"], "working")

    def test_a_screen_that_moved_under_the_look_is_looked_at_where_it_settles(self):
        # the edge's capture still shows the composer, the look's the turn it began
        looks, made = self.looks()
        prompt = self.show("claude-prompt-pane.txt")
        looks.read = lambda: prompt
        self.show("claude-working-pane.txt")
        looks.check()
        self.assertEqual(watch.seat_read("herdr")["state"], "working")
        # the turn ended, back on the composer the edge read: the record says otherwise
        self.show("claude-prompt-pane.txt")
        looks.check()
        self.assertEqual(made, [True, True])
        self.assertEqual(watch.seat_read("herdr")["state"], "at_prompt")

    def test_another_draft_is_looked_at_and_a_redrawn_timer_is_not(self):
        looks, made = self.looks()
        self.show("claude-draft-pane.txt")
        looks.check()
        self.show("claude-draft-pane.txt", ("Fix the login redirect", "Fix the search filter"))
        looks.check()
        self.assertEqual(made, [True, True])
        self.assertEqual(watch.seat_read("herdr")["unsent"], "Fix the search filter")
        # a codex seat's timer line is what its working rule reads, and no news a second on
        config.save_session(self.seat.cfg, "herdr", "astra", ["opus", "astra"],
                            {"repo": self.seat.repo, "cwd": self.seat.repo})
        looks, made = self.looks("codex")
        self.show("codex-working-pane.txt")
        looks.check()
        self.show("codex-working-pane.txt", ("(0s", "(1s"))
        looks.check()
        self.assertEqual(made, [True])
        self.assertEqual(watch.seat_read("herdr")["state"], "working")

    def test_a_reading_only_a_typing_preflight_wrote_down_is_still_looked_at(self):
        looks, made = self.looks()
        self.show("claude-working-pane.txt")
        looks.check()
        # the preflight before a typed line reads the question and writes it down, and
        # publishes nothing
        self.show("claude-question-pane.txt")
        self.assertFalse(watch.at_prompt(self.seat.seat, cfg=self.seat.cfg))
        self.assertEqual(watch.seat_read("herdr")["word"], "working")
        looks.check()
        self.assertEqual(made, [True, True])
        self.assertEqual(watch.seat_read("herdr")["word"], "needs you")

    def test_a_turn_the_owner_interrupted_is_read_as_its_look_reads_it(self):
        # a turn its hook began, which an Esc ended with no Stop: the harness recorded that
        config.hook_facts_path("herdr").write_text(json.dumps(
            {"event": "UserPromptSubmit", "at": time.time() - 9, "text": "Run the acme tests."}))
        looks, made = self.looks()
        self.show("claude-interrupted-pane.txt")
        with patch.object(watch, "interrupted_at", return_value=time.time() - 7):
            looks.check()
            looks.check()                  # the same pane, redrawn
        self.assertEqual(made, [True])
        self.assertEqual(watch.seat_read("herdr")["state"], "at_prompt")

    def test_an_error_the_tick_retries_is_looked_at_and_so_is_the_prompt_that_answers_it(self):
        # both read as Muse's composer: only the error tells them apart
        config.save_session(self.seat.cfg, "herdr", "spark", ["opus", "astra"],
                            {"repo": self.seat.repo, "cwd": self.seat.repo})
        looks, made = self.looks("muse")
        self.show("muse-stall-pane.txt")
        looks.check()
        self.assertEqual(watch.seat_read("herdr")["reason"], "retrying: 429")
        self.show("muse-prompt-pane.txt")
        looks.check()
        self.assertEqual(made, [True, True])
        self.assertEqual(watch.seat_read("herdr")["word"], "idle")

    def test_login_words_the_tick_types_past_are_looked_at_and_so_is_the_prompt_without_them(self):
        # both read as Claude's composer: only the login words tell them apart
        state = watch.load_state()
        state["stalls"]["herdr"] = {"kind": "login", "signature": "Please run /login",
                                    "since": time.time()}
        watch.save_state(state)
        looks, made = self.looks()
        self.show("claude-auth-401-pane.txt")
        looks.check()
        self.assertEqual(watch.seat_read("herdr")["reason"], "retrying: its login works again")
        self.show("claude-prompt-pane.txt")
        looks.check()
        self.assertEqual(made, [True, True])
        self.assertEqual(watch.seat_read("herdr")["word"], "idle")

    def test_a_pane_that_cannot_be_read_is_not_a_change(self):
        looks, made = self.looks()
        looks.read = lambda: None
        looks.check()
        self.assertEqual(made, [])

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
        # the seat's word was already decided from what the fixture pane reads, so no edge
        # starts a look and each is one capture
        record = self.root / ".agentkit" / config.seat_state_path("acme").relative_to(config.HOME)
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"word_from": ["at_prompt", "prompt.composer", ""]}))

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
