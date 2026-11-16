"""`ak models` names each row of ak's own numbers as every screen names that model at its effort:
a run recorded at effort `none` is the model's name alone, and a configured name holding ` @ `
is a name, never a model and an effort.

Black-box: the program `AK_BIN` names, set up as tests/test_key_models_answer.py sets it up, one
judged run written into the Home's history; judged by the output and exit code.  Fails against
/bin/false.
"""

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import Home
from test_key_models_answer import ENV, boards
from agentkit import config, history

HAIKU = {"harness": "claude", "model": "claude-haiku-4-5", "effort": "none"}


class OwnRunsNamed(unittest.TestCase):
    def test_effort_none_and_a_name_holding_an_at_are_said_as_the_model_s_name(self):
        with Home() as home:
            fakeadapter.install(home, claude="pass")
            akconfig.write(home, {"haiku": HAIKU, "haiku @ custom": HAIKU})
            home.write(".agentkit/state/boards.json", boards())
            with patch.object(config, "HOME", home.path / ".agentkit"), \
                    patch.object(config, "RUNS", home.path / ".agentkit/runs"):
                history.start_run("acme-none", repo="acme", executor="haiku", started_at=1)
                history.update_run("acme-none", executor_effort="none")
                history.finish_run("acme-none", final_state="pass", verdict="PASS", rounds_used=1,
                                   finished_at=2, changed_lines=1)
            done = home.ak("models", env={**ENV, "COLUMNS": "100"})
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual([" ".join(line.split()) for line in done.out.splitlines()[-2:]],
                         ["Haiku 4.5 - 100% of 1 -", "Haiku 4.5 - - -"])


if __name__ == "__main__":
    unittest.main()
