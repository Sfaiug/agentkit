"""Resolved Antigravity status labels for live-listed models move the seat without an answer.

Black-box against AK_BIN, running the launch's status command with agy's JSON on stdin for
models listed in the held catalog (both effort-suffixed and bracketed no-effort labels) as
well as shipped catalog models absent from that cache.
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
class AntigravityLiveLabelFollowed(unittest.TestCase):
    def test_status_labels_resolve_through_the_held_and_shipped_catalogs(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {
            "gemini": {},
            "flash": {"harness": "antigravity", "model": "gemini-3.7-flash", "effort": "low"},
            "sonnet": {"harness": "antigravity", "model": "claude-sonnet-4-6", "effort": "none"},
        })
        home.write(".agentkit/state/listings/antigravity/default.json", {"models": [
            {"id": "gemini-3.7-flash", "label": "Gemini 3.7 Flash",
             "efforts": ["low", "medium", "high"]},
            {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (Thinking)",
             "efforts": ["none"]},
        ]})
        seat = Seat(home, "acme-live", model="gemini", screen="antigravity-prompt-pane.txt",
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

        def record():
            return json.loads((home.path / f".agentkit/state/session-{seat.name}.json").read_text())

        def render(label, effort=None):
            model = {"id": label, "display_name": label}
            if effort is not None:
                model["effort"] = effort
            done = home.run("sh", "-c", command, cwd=seat.cwd, env=env, input=json.dumps({
                "session_id": seat.record["conversation"],
                "conversation_id": seat.record["conversation"],
                "model": model}))
            self.assertEqual(done.code, 0, done.err)

        def wait_for(model_key, effort):
            deadline = time.monotonic() + 30
            while True:
                got = record()
                if (got.get("orchestrator") == model_key
                        and got.get("efforts", {}).get(model_key, {}).get("effort") == effort):
                    return
                self.assertLess(time.monotonic(), deadline, got)
                time.sleep(0.05)

        before_models = akconfig.read(home)["models"]
        # A live-listed model with a bracketed effort resolves via the held catalog.
        render("Gemini 3.7 Flash (High)", "high")
        wait_for("flash", "high")
        # A live-listed no-effort model whose own label ends in brackets resolves as-is.
        render("Claude Sonnet 4.6 (Thinking)")
        wait_for("sonnet", "none")
        # A shipped-catalog model omitted from the held listing still resolves.
        render("Gemini 3.8 Flash (Low)", "low")
        wait_for("gemini", "low")
        self.assertEqual(akconfig.read(home)["models"], before_models)


if __name__ == "__main__":
    unittest.main()
