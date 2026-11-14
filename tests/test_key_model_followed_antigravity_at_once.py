"""An agy status render moves its seat's model and effort without another answer.

Black-box against AK_BIN, running the launch's status command with agy's JSON on stdin.
"""

import json
import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from fixtures.akterm import Terminal


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelFollowedAntigravityAtOnce(unittest.TestCase):
    def test_the_status_line_moves_only_its_conversation(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {"gemini": {}, "argon": {"harness": "antigravity",
                                                      "model": "gemini-4-argon"}})
        owner = """jq -r '"owner: " + .model.id + " " + .model.effort' # owner comment"""
        home.write(".gemini/antigravity-cli/settings.json",
                   {"statusLine": {"type": "command", "command": owner}})
        seat = Seat(home, "acme-fix", model="gemini", screen="antigravity-prompt-pane.txt",
                    alive=False, record={"launched": time.time() - 600,
                                         "efforts": {"gemini": {"effort": "high"}}})
        done = home.ak("orch", seat.name, "--dry-run", cwd=home.path)
        self.assertEqual(done.code, 0, done.err)
        words = shlex.split(done.out.splitlines()[-1])
        command = json.loads(words[words.index("--settings") + 1])["statusLine"]["command"]
        seat.start()
        socket = home.tmux("display-message", "-p", "-t", seat.pane, "#{socket_path}").out.strip()
        env = {"AGENTKIT_SESSION": seat.name, "AK_RUN_ROLE": "",
               "TMUX": socket + ",0,0", "TMUX_PANE": seat.pane}
        term = Terminal(home, "orch", seat.name, size=(100, 30))
        term.wait(seat.name)
        done = home.ak("orch", "why", seat.name)
        self.assertEqual(done.code, 0, done.err)
        term.wait("3.8 Flash high")

        def render(conversation, label, effort):
            done = home.run("sh", "-c", command, cwd=seat.cwd, env=env, input=json.dumps({
                "session_id": conversation, "conversation_id": conversation,
                "model": {"id": label, "display_name": label, "effort": effort}}))
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(done.out, f"owner: {label} {effort}\n")

        render("", "Gemini 4 Argon (Low)", "low")
        self.assertFalse((home.path / ".agentkit/state/model-.json").exists())
        path = home.path / f".agentkit/state/session-{seat.name}.json"
        render(seat.record["conversation"], "Gemini 4 Argon (Low)", "low")
        deadline = time.monotonic() + 30
        while json.loads(path.read_text()).get("efforts", {}).get("argon", {}).get("effort") != "low":
            self.assertLess(time.monotonic(), deadline, path.read_text())
            time.sleep(0.05)
        self.assertEqual(json.loads(path.read_text())["orchestrator"], "argon")
        term.wait("4 Argon low")
        render("another-conversation", "Gemini 3.8 Flash (High)", "high")
        done = home.ak("orch", "why", seat.name)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(path.read_text())["orchestrator"], "argon")
        self.assertEqual(json.loads(path.read_text())["efforts"]["argon"]["effort"], "low")


if __name__ == "__main__":
    unittest.main()
