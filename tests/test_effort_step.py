"""An effort step is drawn at once, and MiMo's two efforts reach OpenCode.

The step: `menu.show_config` runs in a child process on a pty of its own, through
tests/test_config_matrix.py's Screen, in a temporary HOME whose config.toml is the shipped
default.  Claude's adapter is a fake in a directory of its own ($AGENTKIT_ADAPTER_DIR) whose
`models` sleeps five seconds before it lists Opus at `low high` alone: every step taken while it
sleeps must still be on the screen within 100 ms, off the catalog in hand, and the one after it
answers steps along its listing.

The run: adapters/opencode.sh with a stub `opencode` first on PATH that records its argv and the
config document it was launched with, so a MiMo model at `none` and at `high` is seen asking
for thinking off and on.  Nothing here contacts a provider or reads the owner's ~/.agentkit or
OpenCode config, and the only process signalled is the test's own child.
"""

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from test_config_matrix import DOWN, ENTER, LEFT, REPO, RIGHT, Screen, highlighted
from agentkit import config, terminal

CHILD = r"""
import os, sys, time
sys.path.insert(0, os.environ["MATRIX_REPO"])
from contextlib import closing
from agentkit import menu, terminal, update

# Measure in the child: the parent's reader can be scheduled after the frame is drawn.
read_key, frame, pressed = terminal.read_key, terminal.frame, None
def measured_key(*args, **kwargs):
    global pressed
    key = read_key(*args, **kwargs)
    if key is not None:
        pressed = time.monotonic()
    return key
def measured_frame(*args, **kwargs):
    spots = frame(*args, **kwargs)
    if pressed is not None:
        print(f"<frame {time.monotonic() - pressed:.6f}>", flush=True)
    return spots
terminal.read_key, terminal.frame = measured_key, measured_frame

update.version = lambda harness: ""
update.agentkit_version = lambda: "abc1234"
update.agentkit_newer = lambda: ""
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard)
print("<left>", flush=True)
"""
SLOW = """#!/usr/bin/env bash
# a Claude adapter whose listing takes five seconds, for tests/test_effort_step.py
[ "$1" = models ] || exit 2
here=$(dirname -- "$0")
: >"$here/asked"
sleep 5
printf 'claude-opus-5-5\\tOpus 5.5\\tlow high\\n'
: >"$here/answered"
"""
STUB = """#!/usr/bin/env bash
# opencode for tests/test_effort_step.py: `run` records its argv and its config document
[ "$1" = run ] || exit 0
printf '%s' "$*" >"$STUB_DIR/argv"
printf '%s' "${OPENCODE_CONFIG_CONTENT:-}" >"$STUB_DIR/config"
"""
EFFORT_KEYS = "  ↑↓←→ move   ⏎ effort   esc back"


def timed(screen, keys, shown):
    """The child's seconds from reading `keys` to drawing the frame showing `shown`."""
    mark = len(screen.text())
    os.write(screen.master, keys)

    def ready(text):
        text = terminal.ANSI.sub("", text[mark:])
        at = text.find(shown)
        return re.search(r"<frame ([\d.]+)>", text[at:]) if at >= 0 else None
    found = screen.until(ready, f"{shown} drawn")
    return float(found.group(1))


class EffortStep(unittest.TestCase):
    def test_a_step_is_drawn_while_the_listing_sleeps_and_the_next_reads_it(self):
        adapters = Path(tempfile.mkdtemp(prefix="effort-step-"))
        self.addCleanup(subprocess.run, ["rm", "-rf", str(adapters)])
        (adapters / "claude.sh").write_text(SLOW)
        (adapters / "claude.sh").chmod(0o755)
        with patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(adapters)}):
            screen = Screen(self, child=CHILD)
        screen.frame()
        screen.press(DOWN + RIGHT * 3, lambda lines: lines[-1] == EFFORT_KEYS)   # opus's effort
        # the manifest's table while the listing sleeps: xhigh, max, then round to low
        self.assertLess(timed(screen, ENTER, "‹ max ›"), 0.1)
        self.assertLess(timed(screen, ENTER, "‹ low ›"), 0.1)
        # and on the model's own screen, the listing still asleep
        screen.press(LEFT * 4 + ENTER, lambda lines: "agentkit · config · opus" in lines[0])
        screen.press(DOWN, lambda lines: "effort" in highlighted(lines))
        self.assertLess(timed(screen, RIGHT, "‹ medium ›"), 0.1)
        self.assertTrue((adapters / "asked").exists(), "the listing was asked for")
        self.assertFalse((adapters / "answered").exists(), "the listing is still asleep")
        self.assertEqual(screen.saved()["models"]["opus"]["effort"], "medium")
        # once it answers, a step reads it: medium is not among `low high`, so it lands on low
        deadline = time.monotonic() + 15
        while not (adapters / "answered").exists():
            self.assertLess(time.monotonic(), deadline, "the listing never answered")
            time.sleep(0.05)
        time.sleep(0.2)
        self.assertLess(timed(screen, RIGHT, "‹ low ›"), 0.1)
        self.assertLess(timed(screen, RIGHT, "‹ high ›"), 0.1)
        self.assertEqual(screen.saved()["models"]["opus"]["effort"], "high")
        screen.press(b"\x1b", lambda lines: "opus" in highlighted(lines))  # back to the matrix
        screen.leave()

    def test_a_mimo_run_and_seat_at_each_effort_ask_opencode_for_it(self):
        root = Path(tempfile.mkdtemp(prefix="effort-step-"))
        self.addCleanup(subprocess.run, ["rm", "-rf", str(root)])
        (root / "bin").mkdir()
        (root / "home").mkdir()
        (root / "bin/opencode").write_text(STUB)
        (root / "bin/opencode").chmod(0o755)
        (root / "prompt.md").write_text("hi\n")
        env = {"HOME": str(root / "home"), "PATH": f"{root / 'bin'}:/usr/bin:/bin",
               "STUB_DIR": str(root), "AGENTKIT_SESSION": "acme"}
        adapter = str(REPO / "adapters/opencode.sh")
        model = "mimo/mimo-v2.6-pro"
        self.assertEqual(config.catalog_table("opencode")[0]["efforts"], ["none", "high"])
        for effort, thinking in (("none", "disabled"), ("high", "enabled")):
            proc = subprocess.run([adapter, "run", model, effort, str(root),
                                   str(root / "prompt.md"), str(root / f"out-{effort}")],
                                  capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            argv = (root / "argv").read_text().split()
            self.assertEqual(argv[argv.index("-m") + 1], f"{model}#{effort}")
            variants = json.loads((root / "config").read_text())
            want = {"extraBody": {"thinking": {"type": thinking}}}
            self.assertEqual(
                variants["provider"]["mimo"]["models"]["mimo-v2.6-pro"]["variants"][effort], want)
            # a seat opened at that effort is launched with the same variant
            proc = subprocess.run([adapter, "interactive", model, effort], capture_output=True,
                                  text=True, env=env, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            seat = json.loads(next(word for word in shlex.split(proc.stdout)
                                   if word.startswith("OPENCODE_CONFIG_CONTENT="))
                              .split("=", 1)[1])
            self.assertEqual(seat["model"], f"{model}#{effort}")
            self.assertEqual(seat["provider"], variants["provider"])
            self.assertIn("build", seat["agents"])


if __name__ == "__main__":
    unittest.main()
