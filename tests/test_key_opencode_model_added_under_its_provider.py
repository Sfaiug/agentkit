"""A model picked inside an OpenCode seat that no entry runs is added under the provider its id
names, where the config has that provider's table, and becomes the seat's: OpenCode records each
answer's model as `<provider>/<model>`.  The entry left behind lends its `mode` to none on another
provider.  One of a provider the config has no table for moves nothing.

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

# The shipped table names both; the config runs neither
FLASH, FLASH_NAMED = "mimo/mimo-v2.6-flash", "MiMo V2.6 Flash"
GLM = "opencode/glm-5.3-flash-free"


def answered(db, session, seq, at, model, variant):
    """An OpenCode answer of `model` (`<provider>/<id>`) at that variant, `at` seconds."""
    provider, _, model = model.partition("/")
    ms = int(at * 1000)
    data = {"time": {"created": ms, "completed": ms + 400}, "agent": "build",
            "model": {"id": model, "providerID": provider, "variant": variant},
            "content": [{"type": "text", "text": "Renamed the acme report."}], "finish": "stop"}
    db.execute("INSERT INTO session_message VALUES (?, ?, 'assistant', ?, ?, ?, ?)",
               (f"msg_0fa1c2d3e4ff{seq:010d}", session, seq, ms, ms + 400, json.dumps(data)))


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class OpencodeModelAddedUnderItsProvider(unittest.TestCase):
    def test_a_model_of_a_configured_provider_is_added_and_one_of_another_moves_nothing(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, {
            "coder": {"harness": "opencode", "model": "acme/acme-coder", "effort": "low",
                      "provider": "acme", "mode": "payg"},
            "mimo": {}})
        now = time.time()
        db_path = home.path / ".local/share/opencode/opencode.db"
        db_path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute(MESSAGES)
        seats = {}
        for n, (name, model, ran) in enumerate([("acme-code", "coder", FLASH),
                                                ("acme-mimo", "mimo", GLM)]):
            token, session = f"{n:x}" * 32, f"ses_0fa1c2d3e4ffAcmeAdded{n}"
            with closing(sqlite3.connect(db_path)) as db, db:
                answered(db, session, n + 1, now - 60, ran, "high")
            home.write(f".agentkit/state/opencode-launch-{token}/session", session)
            seats[name] = Seat(home, name, model=model, screen="opencode-prompt-pane.txt",
                               record={"launched": now - 600, "opencode_launch": token})
        models = akconfig.read(home)["models"]

        def record(name):
            return json.loads((home.path / f".agentkit/state/session-{name}.json").read_text())

        def bar(name):
            return home.tmux("show-options", "-v", "-t", f"={name}:", "@ak_top").out

        for name in seats:
            self.assertEqual(home.ak("orch", "why", name).code, 0)

        # the one entry added is acme-code's: acme-mimo's GLM adds none
        added = {name: entry for name, entry in akconfig.read(home)["models"].items()
                 if name not in models}
        self.assertEqual(list(added.values()), [{"harness": "opencode", "model": FLASH,
                                                 "effort": "high", "provider": "mimo"}])
        self.assertEqual(record("acme-code")["orchestrator"], next(iter(added)))
        self.assertIn(FLASH_NAMED, bar("acme-code"))

        self.assertEqual(record("acme-mimo")["orchestrator"], "mimo")
        self.assertIn("MiMo V2.6 Pro", bar("acme-mimo"))


if __name__ == "__main__":
    unittest.main()
