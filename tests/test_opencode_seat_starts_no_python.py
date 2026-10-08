"""An OpenCode seat's command line is built without starting a Python.

The adapter's `interactive` started one to write the config document its seat is opened with:
more than half of what a launch waited on that adapter.  Here a `python3` that refuses to run
stands first on PATH, and the launch has handed the adapter its rulebook, as `orch.command` does.
"""

import json
import os
from pathlib import Path
import shlex
import subprocess
import unittest

from fixtures.sandbox import Sandbox
from agentkit import config

REPO = Path(__file__).resolve().parent.parent
REFUSING = '#!/bin/sh\necho "a python was started: $*" >&2\nexit 97\n'
# what a shell, JSON or tmux would each read as more than text
RULES = ('Rules for "acme": it\'s \\ a $HOME `id` #{pane}\n'
         "second line, with é, 漢字 and 🙂\n")


class NoPython(Sandbox):
    def document(self, model, effort):
        handed = self.root / "handed.md"
        handed.write_text(RULES, encoding="utf-8")
        refusing = self.root / "bin"
        refusing.mkdir(exist_ok=True)
        (refusing / "python3").write_text(REFUSING)
        (refusing / "python3").chmod(0o755)
        # the usual login: a seat this runs from may be on another, which OpenCode has none of
        env = {**{key: value for key, value in os.environ.items() if key != "AGENTKIT_ACCOUNT"},
               config.SESSION_ENV: "acme", config.RULEBOOK_ENV: str(handed),
               "PATH": os.pathsep.join([str(refusing), os.environ["PATH"]])}
        line = subprocess.run([str(REPO / "adapters/opencode.sh"), "interactive", model, effort],
                              env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(line.returncode, 0, line.stderr)
        # plain on the command line, whatever the rulebook says
        self.assertTrue(line.stdout.isascii(), line.stdout)
        return json.loads(next(word for word in shlex.split(line.stdout)
                               if word.startswith("OPENCODE_CONFIG_CONTENT=")).split("=", 1)[1])

    def test_the_document_is_whole_for_a_model_with_no_variants_of_its_own(self):
        self.assertEqual(self.document("acme/big", "high"),
                         {"model": "acme/big#high", "agents": {"build": {"system": RULES}},
                          "plugins": [str(REPO / "hooks/opencode-seat")]})

    def test_a_mimo_model_s_variants_are_beside_it(self):
        thinking = {"none": {"extraBody": {"thinking": {"type": "disabled"}}},
                    "high": {"extraBody": {"thinking": {"type": "enabled"}}}}
        self.assertEqual(
            self.document("mimo/mimo-v2.6-pro", "high"),
            {"model": "mimo/mimo-v2.6-pro#high", "agents": {"build": {"system": RULES}},
             "plugins": [str(REPO / "hooks/opencode-seat")],
             "provider": {"mimo": {"models": {"mimo-v2.6-pro": {"variants": thinking}}}}})


if __name__ == "__main__":
    unittest.main(verbosity=2)
