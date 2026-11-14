"""A model picked inside a seat that its harness lists and the shipped table lacks is added by the
watch's pass, which asks that listing once; a look asks none.  Measured on 13 Nov 2026, Claude's
listing named 15 models and its table 7: a seat moved inside to one of the other 8 kept the model
it left.  Once added, an entry runs it, and every other seat's look moves to it at once.

Black-box against AK_BIN, as test_key_model_added_where_no_entry_runs_it: the launch's status
command runs as Claude Code runs it, and `adapters/claude.sh models` asks Anthropic's models API
through a fake `curl` that answers its listing and logs each ask.
"""

import json
import shlex
import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.akterm import Terminal

NOVA, VEGA = "claude-nova-9", "claude-vega-3"   # the listing names Nova, and nothing names Vega
LEVELS = ("low", "medium", "high", "xhigh", "max")
PAGE = {"data": [{"type": "model", "id": model, "display_name": label, "capabilities": {
    "effort": {"supported": True, **{level: {"supported": True} for level in LEVELS}}}}
    for model, label in ((NOVA, "Claude Nova 9"), ("claude-opus-5-5", "Claude Opus 5.5"))],
    "has_more": False}
# Logs each call, then answers the models API's page and refuses anything else.
CURL = """#!{python}
import json, sys
with open({log!r}, "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
sys.stdin.read()
if "/v1/models?" not in sys.argv[-1]:
    sys.exit(7)
print({page!r})
"""


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class ModelAddedFromItsHarnessSListing(unittest.TestCase):
    def test_a_pass_adds_a_model_only_its_listing_names_and_a_look_then_follows_it(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {"opus": {}})
        home.write(".agentkit/secrets/claude_oauth_token", "sk-ant-oat01-acme-worker\n")
        home.fake("curl", CURL.format(python=sys.executable, log=str(home.log("curl")),
                                      page=json.dumps(PAGE)))
        seats = {}
        for name in ("acme-fix", "acme-web", "acme-api"):
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

        def orchestrator(name):
            path = home.path / f".agentkit/state/session-{name}.json"
            return json.loads(path.read_text())["orchestrator"]

        def asks():
            return [argv for argv in home.calls("curl") if "/v1/models?" in argv[-1]]

        def bar(name, shows):
            term = Terminal(home, "orch", name, size=(100, 30))
            term.wait(name)
            term.wait(shows)

        models = akconfig.read(home)["models"]
        render("acme-fix", NOVA, "low")
        render("acme-web", VEGA, "high")
        for name in ("acme-fix", "acme-web"):
            self.assertEqual(home.ak("orch", "why", name).code, 0)
            self.assertEqual(orchestrator(name), "opus")
        self.assertEqual(akconfig.read(home)["models"], models)
        self.assertEqual(asks(), [])                     # a look asks none
        bar("acme-fix", "Opus 5.5 xhigh")

        done = home.tick()
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertEqual(len(asks()), 1)                 # one listing, for both seats
        self.assertEqual(orchestrator("acme-fix"), "nova")      # named from the label, Nova 9
        self.assertEqual(akconfig.read(home)["models"], {**models, "nova": {
            "harness": "claude", "model": NOVA, "effort": "low", "provider": "anthropic"}})
        self.assertEqual(orchestrator("acme-web"), "opus")
        bar("acme-fix", "Nova 9 low")
        bar("acme-web", "Opus 5.5 xhigh")

        render("acme-api", NOVA, "high")      # the same model, now an entry runs it: no pass
        deadline = time.monotonic() + 30
        while orchestrator("acme-api") == "opus":
            self.assertLess(time.monotonic(), deadline, "acme-api never moved")
            time.sleep(0.05)
        self.assertEqual(orchestrator("acme-api"), "nova")
        self.assertEqual(list(akconfig.read(home)["models"]), [*models, "nova"])
        self.assertEqual(len(asks()), 1)
        bar("acme-api", "Nova 9 high")


if __name__ == "__main__":
    unittest.main()
