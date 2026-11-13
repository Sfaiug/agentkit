"""The fresh-install gate knows each harness's prompt as ak launches a seat on it.

Check d of tests/e2e-fresh.sh waits for its seat's prompt by its `PROMPT`, and that seat is on
whichever model the picker chose from live quota.  ak has launched a Muse seat with
`--disable-approval`, not `--yolo`, since #1500, so its footer ends `Launch overrides`; the gate
still waited for `YOLO` and failed on 12 Nov 2026, the first time its seat landed on Muse.  Here
the gate's own `PROMPT`, read as its driver reads a screen, finds the prompt in a pane of each
harness at rest.
"""

import re
import sys
from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parent.parent
GATE = (REPO / "tests" / "e2e-fresh.sh").read_text()
PROMPT = re.search(r"^PROMPT='([^']*)'$", GATE, re.M)[1]
# the driver's own reading of a screen, out of the gate and never copied
READING = {"re": re}
exec(re.search(r"^ANSI = .*$", GATE, re.M)[0], READING)
exec(re.search(r"^def seen\(.*?\n(?=\n\n)", GATE, re.M | re.S)[0], READING)
# a pane of each harness at its prompt, a Muse seat's launched as adapters/muse.sh launches it
PANES = {"claude": "claude-prompt-pane.txt", "codex": "codex-prompt-pane.txt",
         "muse": "muse-overrides-idle-pane.txt"}


class GatePrompt(unittest.TestCase):
    def test_the_gate_finds_each_harness_at_its_prompt(self):
        for harness, pane in PANES.items():
            screen = (REPO / "tests" / "fixtures" / pane).read_text()
            with self.subTest(harness=harness):
                self.assertTrue(READING["seen"](PROMPT, READING["ANSI"].sub("", screen)),
                                f"{PROMPT!r} is not on {pane}")


if __name__ == "__main__":
    unittest.main()
