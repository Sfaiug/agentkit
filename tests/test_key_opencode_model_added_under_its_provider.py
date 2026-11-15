"""A model picked inside an OpenCode seat that no entry runs, of the provider of the entry the seat
leaves, is added under that provider by a look, with that entry's `mode`, and becomes the seat's:
OpenCode records each answer's model as `<provider>/<model>`.  One of another provider a look
leaves as it is, the config's table for that provider or not: its login's mode is OpenCode's to
say, which only the watch's pass asks (test_key_pass_takes_in_opencode_provider).

Black-box against AK_BIN, as test_key_model_followed_opencode_muse writes OpenCode's answers and
test_key_model_added_where_no_entry_runs_it reads what was added.
"""

import json
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import Seat
from test_key_model_followed_opencode_muse import MESSAGES

# The shipped table names each; the config runs only DeepSeek
DEEPSEEK = "opencode/deepseek-v4.1-flash-free"
GLM, GLM_NAMED = "opencode/glm-5.3-flash-free", "GLM-5.3-Flash Free"
FLASH = "mimo/mimo-v2.6-flash"


def answered(db, session, seq, at, model, variant):
    """An OpenCode answer of `model` (`<provider>/<id>`) at that variant, `at` seconds."""
    provider, _, model = model.partition("/")
    ms = int(at * 1000)
    data = {"time": {"created": ms, "completed": ms + 400}, "agent": "build",
            "model": {"id": model, "providerID": provider, "variant": variant},
            "content": [{"type": "text", "text": "Renamed the acme report."}], "finish": "stop"}
    db.execute("INSERT INTO session_message VALUES (?, ?, 'assistant', ?, ?, ?, ?)",
               (f"msg_0fa1c2d3e4ff{seq:010d}", session, seq, ms, ms + 400, json.dumps(data)))


def seats(home, ran):
    """An OpenCode seat on each entry `ran` names, its latest answer since its launch on the
    model it names there."""
    now = time.time()
    db_path = home.path / ".local/share/opencode/opencode.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute(MESSAGES)
    for n, (name, (model, latest)) in enumerate(ran.items()):
        token, session = f"{n:x}" * 32, f"ses_0fa1c2d3e4ffAcmeAdded{n}"
        with closing(sqlite3.connect(db_path)) as db, db:
            answered(db, session, n + 1, now - 60, latest, "high")
        home.write(f".agentkit/state/opencode-launch-{token}/session", session)
        Seat(home, name, model=model, screen="opencode-prompt-pane.txt",
             record={"launched": now - 600, "opencode_launch": token})


def record(home, name):
    return json.loads((home.path / f".agentkit/state/session-{name}.json").read_text())


def bar(home, name):
    return home.tmux("show-options", "-v", "-t", f"={name}:", "@ak_top").out


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OpencodeModelAddedUnderItsProvider(unittest.TestCase):
    def test_a_look_adds_one_of_the_left_entry_s_provider_with_its_mode_and_no_other(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {
            "deep": {"harness": "opencode", "model": DEEPSEEK, "effort": "low",
                     "provider": "opencode", "mode": "payg"},
            "coder": {"harness": "opencode", "model": "acme/acme-coder", "effort": "low",
                      "provider": "acme"},
            "mimo": {}})
        seats(home, {"acme-deep": ("deep", GLM), "acme-code": ("coder", FLASH)})
        models = akconfig.read(home)["models"]

        for name in ("acme-deep", "acme-code"):
            self.assertEqual(home.ak("orch", "why", name).code, 0)

        # the one entry added is acme-deep's, under its entry's provider with its mode
        added = {name: entry for name, entry in akconfig.read(home)["models"].items()
                 if name not in models}
        self.assertEqual(list(added.values()), [{"harness": "opencode", "model": GLM,
                                                 "effort": "high", "provider": "opencode",
                                                 "mode": "payg"}])
        self.assertEqual(record(home, "acme-deep")["orchestrator"], next(iter(added)))
        self.assertIn(GLM_NAMED, bar(home, "acme-deep"))

        # MiMo's table is the config's, and a look still adds none of its models for acme
        self.assertEqual(record(home, "acme-code")["orchestrator"], "coder")
        self.assertIn("Acme Coder low", bar(home, "acme-code"))


if __name__ == "__main__":
    unittest.main()
