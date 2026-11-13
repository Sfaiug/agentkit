"""A model picked inside a seat that no entry runs is added to the config and becomes the seat's:
the owner's "Add it to AK's models" (12 Nov 2026).  A model no table names moves nothing.

Black-box against AK_BIN, as test_key_model_followed_at_once runs Claude's status command: the
launch's command runs as Claude Code runs it, in a shell with its JSON on stdin.
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

SONNET = "claude-sonnet-5-5"      # the shipped table names it; the config here runs only Opus


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelAddedWhereNoEntryRunsIt(unittest.TestCase):
    def test_a_model_no_entry_runs_is_added_once_and_one_no_table_names_moves_nothing(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {"opus": {}})
        seats = {}
        for name in ("acme-fix", "acme-api", "acme-web"):
            seat = Seat(home, name, alive=False, record={"launched": time.time() - 600})
            done = home.ak("orch", name, "--dry-run", cwd=home.path)
            self.assertEqual(done.code, 0, done.err)
            words = shlex.split(done.out.splitlines()[-1])
            seat.start()
            seats[name] = seat, json.loads(words[words.index("--settings") + 1])

        def render(name, model, effort):
            seat, settings = seats[name]
            socket = home.tmux("display-message", "-p", "-t", seat.pane,
                               "#{socket_path}").out.strip()
            done = home.run("sh", "-c", settings["statusLine"]["command"], cwd=seat.cwd, env={
                "AGENTKIT_SESSION": name, "AK_RUN_ROLE": "", "TMUX": socket + ",0,0",
                "TMUX_PANE": seat.pane}, input=json.dumps({
                    "session_id": seat.record["conversation"], "model": {"id": model},
                    "effort": {"level": effort}}))
            self.assertEqual(done.code, 0, done.err)

        def record(name):
            return json.loads((home.path / f".agentkit/state/session-{name}.json").read_text())

        def moved(name):
            deadline = time.monotonic() + 30
            while record(name)["orchestrator"] == "opus":
                self.assertLess(time.monotonic(), deadline, record(name))
                time.sleep(0.05)
            return record(name)["orchestrator"]

        def running(model):
            return {name: entry for name, entry in akconfig.read(home)["models"].items()
                    if entry["model"] == model}

        term = Terminal(home, "orch", "acme-fix", size=(100, 30))
        term.wait("acme-fix")
        self.assertEqual(home.ak("orch", "why", "acme-fix").code, 0)
        term.wait("Opus 5.5 xhigh")
        render("acme-fix", SONNET, "low")
        added = moved("acme-fix")
        self.assertEqual(running(SONNET), {added: {"harness": "claude", "model": SONNET,
                                                   "effort": "low", "provider": "anthropic"}})
        term.wait("Sonnet 5.5 low")

        render("acme-api", SONNET, "high")       # the same model, at another effort
        self.assertEqual(moved("acme-api"), added)
        self.assertEqual(list(running(SONNET)), [added])

        models = akconfig.read(home)["models"]
        term = Terminal(home, "orch", "acme-web", size=(100, 30))
        term.wait("acme-web")
        self.assertEqual(home.ak("orch", "why", "acme-web").code, 0)
        term.wait("Opus 5.5 xhigh")
        render("acme-web", "claude-nova-9", "high")      # no table names it
        self.assertEqual(home.ak("orch", "why", "acme-web").code, 0)
        self.assertEqual(record("acme-web")["orchestrator"], "opus")
        self.assertEqual(akconfig.read(home)["models"], models)
        term.wait("Opus 5.5 xhigh")


if __name__ == "__main__":
    unittest.main()
