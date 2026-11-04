"""A Claude status render moves its seat's model and effort without another answer.

Black-box against AK_BIN: the launch's command runs as Claude Code runs it, in a shell
with its JSON on stdin; the owner's command still prints its own status line.
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
class ModelFollowedAtOnce(unittest.TestCase):
    def test_the_status_line_moves_only_its_conversation(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {"opus": {}, "sonnet": {"harness": "claude",
                       "model": "claude-sonnet-5-5", "effort": "high"}})
        owner = """jq -r '"owner: " + .model.id + " " + .effort.level' # owner comment"""
        home.write(".claude/settings.json", {"statusLine": {"type": "command", "command": owner}})
        seat = Seat(home, "acme-fix", record={"launched": time.time() - 600,
                                              "efforts": {"opus": {"effort": "xhigh"}}})
        done = home.ak("orch", "preview", "--model", "opus", "--dry-run", cwd=seat.cwd)
        self.assertEqual(done.code, 0, done.err)
        words = shlex.split(done.out.splitlines()[-1])
        settings = json.loads(words[words.index("--settings") + 1])
        command = settings["statusLine"]["command"]
        socket = home.tmux("display-message", "-p", "-t", seat.pane, "#{socket_path}").out.strip()
        env = {"AGENTKIT_SESSION": seat.name, "AK_RUN_ROLE": "",
               "TMUX": socket + ",0,0", "TMUX_PANE": seat.pane}
        term = Terminal(home, "orch", seat.name, size=(100, 30))
        term.wait(seat.name)
        done = home.ak("orch", "why", seat.name)
        self.assertEqual(done.code, 0, done.err)
        term.wait("Opus 5.5 xhigh")

        def render(conversation, model, effort):
            done = home.run("sh", "-c", command, cwd=seat.cwd, env=env, input=json.dumps({
                "session_id": conversation, "model": {"id": model}, "effort": {"level": effort}}))
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(done.out, f"owner: {model} {effort}\n")

        path = home.path / f".agentkit/state/session-{seat.name}.json"
        render(seat.record["conversation"], "claude-sonnet-5-5", "low")
        deadline = time.monotonic() + 30
        while json.loads(path.read_text()).get("efforts", {}).get("sonnet", {}).get("effort") != "low":
            self.assertLess(time.monotonic(), deadline, path.read_text())
            time.sleep(0.05)
        self.assertEqual(json.loads(path.read_text())["orchestrator"], "sonnet")
        term.wait("Sonnet 5.5 low")
        render("another-conversation", "claude-opus-5-5", "max")
        done = home.ak("orch", "why", seat.name)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(json.loads(path.read_text())["orchestrator"], "sonnet")
        self.assertEqual(json.loads(path.read_text())["efforts"]["sonnet"]["effort"], "low")


if __name__ == "__main__":
    unittest.main()
