"""An effort step is drawn at once, and MiMo's two efforts reach OpenCode.

The step: `menu.show_config` runs in a child process on a pty of its own, through
tests/test_config_matrix.py's Screen, in a temporary HOME whose config.toml is the shipped
default.  The catalog waits until the test releases it, then lists Opus at `low high` alone:
every step taken while it waits must draw from the manifest, and the one after it answers
steps along its listing.  Completion markers keep process scheduling out of the check.

The run: adapters/opencode.sh with a stub `opencode` first on PATH that records its argv and the
config document it was launched with, so a MiMo model at `none` and at `high` is seen asking
for thinking off and on.  Nothing here contacts a provider or reads the owner's ~/.agentkit or
OpenCode config, and the only process signalled is the test's own child.
"""

import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from test_config_matrix import DOWN, ENTER, LEFT, REPO, RIGHT, Screen, highlighted
from agentkit import config

CHILD = r"""
import os, sys, time
sys.path.insert(0, os.environ["MATRIX_REPO"])
from contextlib import closing
from agentkit import config, menu, terminal, update

def catalog(harness):
    assert harness == "claude"
    print("<catalog asked>", flush=True)
    while not (config.HOME / "catalog-release").exists():
        time.sleep(.01)
    return [{"id": "claude-opus-5-5", "label": "Opus 5.5", "efforts": ["low", "high"]}]

config.catalog = catalog
ask_catalog = config._ask_catalog
def answered(harness):
    ask_catalog(harness)
    print("<catalog answered>", flush=True)
config._ask_catalog = answered

update.version = lambda harness: ""
update.agentkit_version = lambda: "abc1234"
update.agentkit_newer = lambda: ""
with closing(terminal.Keyboard()) as keyboard:
    menu.show_config(False, keyboard)
print("<left>", flush=True)
"""
STUB = """#!/usr/bin/env bash
# opencode for tests/test_effort_step.py: `run` records its argv and its config document
[ "$1" = run ] || exit 0
printf '%s' "$*" >"$STUB_DIR/argv"
printf '%s' "${OPENCODE_CONFIG_CONTENT:-}" >"$STUB_DIR/config"
"""
EFFORT_KEYS = "  ↑↓←→ move   ⏎ effort   esc back"


def step(screen, keys, shown):
    return screen.press(keys, lambda lines: shown in "\n".join(lines))


class EffortStep(unittest.TestCase):
    def test_a_step_is_drawn_while_the_listing_is_pending_and_the_next_reads_it(self):
        screen = Screen(self, child=CHILD)
        screen.frame()
        screen.press(DOWN + RIGHT * 3, lambda lines: lines[-1] == EFFORT_KEYS)   # opus's effort
        # The manifest's table while the listing waits: xhigh, max, then round to low.
        step(screen, ENTER, "‹ max ›")
        step(screen, ENTER, "‹ low ›")
        # And on the model's own screen, the listing still waits.
        screen.press(LEFT * 4 + ENTER, lambda lines: "agentkit · config · opus" in lines[0])
        screen.press(DOWN, lambda lines: "effort" in highlighted(lines))
        step(screen, RIGHT, "‹ medium ›")
        screen.saw("<catalog asked>")
        self.assertNotIn("<catalog answered>", screen.text())
        self.assertEqual(screen.saved()["models"]["opus"]["effort"], "medium")
        # once it answers, a step reads it: medium is not among `low high`, so it lands on low
        (screen.path.parent / "catalog-release").touch()
        screen.saw("<catalog answered>")
        step(screen, RIGHT, "‹ low ›")
        step(screen, RIGHT, "‹ high ›")
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
