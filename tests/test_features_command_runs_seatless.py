"""A project's features command runs under no seat's name: the ak screen reads each shown
project's switches every minute, and a screen opened inside a seat carries that seat's
AGENTKIT_SESSION, so a features command's `ssh` to the live host went through the seat's ssh
shim and was written down as that seat reaching it (`guard.reached_live`).  Its stop then asked
the seat to record a change on the live host it never made.

`menu.features_run` runs in-process under a seat's name, over a features command that answers
with the seat name it was given, for a `list` and a `set`.  Nothing here reaches ssh, a seat or
a real project.
"""

import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu

# Answers as a features command does, in JSON: the seat name it ran under, None for none.
SAYS_SEAT = shlex.join([sys.executable, "-c", "import json, os; print(json.dumps("
                        f"{{'seat': os.environ.get({config.SESSION_ENV!r})}}))"])


class FeaturesCommandRunsSeatless(unittest.TestCase):
    def test_a_list_and_a_set_run_under_no_seat_name(self):
        with tempfile.TemporaryDirectory() as checkout, \
                mock.patch.dict(os.environ, {config.SESSION_ENV: "acme-seat"}), \
                mock.patch.object(menu, "switches_command", lambda _checkout: SAYS_SEAT):
            for words in (["list"], ["set", "dark-mode", "you", "on"]):
                self.assertEqual(menu.features_run(Path(checkout), *words), ({"seat": None}, ""),
                                 words)


if __name__ == "__main__":
    unittest.main()
