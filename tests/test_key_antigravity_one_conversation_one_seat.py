"""One conversation two Antigravity launches hold open is one seat's, though one read of the
menu's asks both.

Two seats tmux lost, each launched on no conversation yet, whose agy both hold one conversation's
database open.  The menu's first read asks each which conversation it resumes: one learns that
one and writes it down, and the other, asked in that same read, finds it taken.  Black-box: the
program `AK_BIN` names is the menu from a pipe, beside two seat records and, as each seat's agy,
a process carrying its launch's token with that database open; judged by what the records then
name.  It fails against `/bin/false`.
"""

import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home

CONVERSATION = "5e8a1c3f-7b2d-4f6a-9c0e-2d4b6a8c0e1f"
# What ak reads of a running agy: its conversation's database, held open.  The line it prints
# says the database is open, and the end of its input ends it.
AGY = "import sys; held = open(sys.argv[1], 'ab'); print(flush=True); sys.stdin.read()"


class OneConversationOneSeat(unittest.TestCase):
    def test_the_menu_s_first_read_gives_it_to_one_seat_alone(self):
        home = self.enterContext(Home())
        database = home.path / ".gemini/antigravity-cli/conversations" / f"{CONVERSATION}.db"
        database.parent.mkdir(parents=True)
        records = []
        for name in ("acme", "beta"):
            token = f"{name}-launch"
            records.append(home.write(f".agentkit/state/session-{name}.json",
                                      {"orchestrator": "gemini", "antigravity_launch": token}))
            agy = self.enterContext(subprocess.Popen(
                [sys.executable, "-c", AGY, str(database)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, env={**home.env, "AGENTKIT_ANTIGRAVITY_LAUNCH": token}))
            agy.stdout.readline()
        done = home.ak(input="\n")
        self.assertEqual(done.code, 0, done.out + done.err)
        learned = [(json.loads(record.read_text()).get("antigravity_open") or {})
                   .get("conversation") for record in records]
        self.assertCountEqual(learned, [CONVERSATION, None])


if __name__ == "__main__":
    unittest.main()
