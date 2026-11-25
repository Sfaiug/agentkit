"""An Antigravity seat's first status renders name the model it was launched on, so nothing moves.

Black-box against AK_BIN, running the launch's status command with agy's pre-resolution JSON
(its `--settings` `model` id, no effort) and then a resolved label on stdin.
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


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class AntigravitySeatOpensOnItsModel(unittest.TestCase):
    def test_first_render_keeps_the_launched_model_and_a_later_label_still_moves_it(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {
            "argon": {"harness": "antigravity", "model": "gemini-4-argon", "effort": "high"},
            "solo": {"harness": "antigravity", "model": "acme-solo-high", "effort": "none"},
        })
        # A held listing naming both a no-effort model whose id ends in `-high` and a bare id of
        # the same stem: folding the no-effort id would add `acme-solo` to config.toml and move
        # the seat to it.
        home.write(".agentkit/state/listings/antigravity/default.json", {"models": [
            {"id": "acme-solo-high", "label": "Acme Solo", "efforts": ["none"]},
            {"id": "acme-solo", "label": "Acme Solo", "efforts": ["low", "medium", "high"]},
        ]})
        owner = """jq -r '"owner: " + .model.id'"""
        original_settings = {"model": "Gemini 3.8 Flash (High)",
                             "statusLine": {"type": "command", "command": owner}}
        home.write(".gemini/antigravity-cli/settings.json", original_settings)

        def launch(name, model, effort):
            seat = Seat(home, name, model=model, screen="antigravity-prompt-pane.txt",
                        alive=False, record={"launched": time.time() - 600,
                                             "efforts": {model: {"effort": effort}}})
            done = home.ak("orch", seat.name, "--dry-run", cwd=home.path)
            self.assertEqual(done.code, 0, done.err)
            words = shlex.split(done.out.splitlines()[-1])
            launched_id = words[words.index("--model") + 1]
            settings = json.loads(words[words.index("--settings") + 1])
            self.assertEqual(settings.get("model"), launched_id)
            seat.start()
            socket = home.tmux("display-message", "-p", "-t", seat.pane,
                               "#{socket_path}").out.strip()
            env = {"AGENTKIT_SESSION": seat.name, "AK_RUN_ROLE": "",
                   "TMUX": socket + ",0,0", "TMUX_PANE": seat.pane}
            return seat, launched_id, settings["statusLine"]["command"], env

        def render(seat, command, env, model_id, effort=None):
            model = {"id": model_id, "display_name": model_id}
            if effort is not None:
                model["effort"] = effort
            done = home.run("sh", "-c", command, cwd=seat.cwd, env=env, input=json.dumps({
                "session_id": seat.record["conversation"],
                "conversation_id": seat.record["conversation"],
                "model": model}))
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(done.out, f"owner: {model_id}\n")

        def record(name):
            return json.loads((home.path / f".agentkit/state/session-{name}.json").read_text())

        before_models = akconfig.read(home)["models"]
        # 1. A model with an effort suffix: pre-resolution render names the full id with no effort.
        seat, launched_id, command, env = launch("acme-argon", "argon", "high")
        self.assertEqual(launched_id, "gemini-4-argon-high")
        render(seat, command, env, launched_id)
        done = home.ak("orch", "why", seat.name)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(record(seat.name)["orchestrator"], "argon")
        self.assertEqual(record(seat.name)["efforts"]["argon"]["effort"], "high")
        self.assertEqual(akconfig.read(home)["models"], before_models)

        # 2. A model listed at no effort whose id ends in `-high`: stays on itself, nothing added.
        solo, solo_id, solo_cmd, solo_env = launch("acme-solo", "solo", "none")
        self.assertEqual(solo_id, "acme-solo-high")
        render(solo, solo_cmd, solo_env, solo_id)
        done = home.ak("orch", "why", solo.name)
        self.assertEqual(done.code, 0, done.err)
        self.assertEqual(record(solo.name)["orchestrator"], "solo")
        self.assertEqual(akconfig.read(home)["models"], before_models)

        # Login's settings.json is untouched.
        self.assertEqual(json.loads((home.path / ".gemini/antigravity-cli/settings.json").read_text()),
                         original_settings)

        # 3. A later render of another model's label still moves the seat (and takes it in).
        render(seat, command, env, "Gemini 3.8 Flash (High)", "high")
        deadline = time.monotonic() + 30
        while record(seat.name)["orchestrator"] == "argon":
            self.assertLess(time.monotonic(), deadline, record(seat.name))
            time.sleep(0.05)
        moved = record(seat.name)["orchestrator"]
        self.assertEqual(akconfig.read(home)["models"][moved]["model"], "gemini-3.8-flash")


if __name__ == "__main__":
    unittest.main()
