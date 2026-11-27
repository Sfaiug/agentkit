"""Local shell commands in a Grok Build seat's `updates.jsonl` are never read as the owner's words.

Grok Build 1.0.92 marks local shell input in `content._meta` with `bash_command` (earlier builds
used `bashCommand`).  Neither is an instruction to the model: a conversation holding only local
shell commands owes `ak orch check SEAT` no model turn, and local shell commands beside a real
owner message stay out of the check's workspace (`owner/` and `conversation.md`) and cannot back a
gap.  Black-box: the program `AK_BIN` names runs from outside through tests/fixtures/akbin.py, on
a Grok Build seat of tests/fixtures/akseat.py with a fake harness of fakeadapter.py for the model.
"""

import json
import shlex
import sys
import unittest
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import AK, Home
from fixtures.akseat import Seat

CONVERSATION = "3a9f7c12-5e4b-4d8a-9c2e-6b1f4a8d0e37"
AT = 1_795_726_461
OWNER_ASK = "Add a retry button to the upload page."
SHELL_1092 = "pwd --acme"
SHELL_LEGACY = "ls --acme"


def shell_1092_row(command, at=AT):
    """A local shell command as Grok Build 1.0.92 writes it to updates.jsonl."""
    return {"timestamp": at, "method": "session/update",
            "params": {"sessionId": CONVERSATION, "update": {
                "sessionUpdate": "user_message_chunk",
                "content": {"type": "text", "text": command,
                            "_meta": {"bash_command": command}},
                "_meta": {"modelId": "grok-4.6"}}}}


def shell_legacy_row(command, at=AT + 1):
    """A local shell command as earlier Grok Build versions wrote it to updates.jsonl."""
    return {"timestamp": at, "method": "session/update",
            "params": {"sessionId": CONVERSATION, "update": {
                "sessionUpdate": "user_message_chunk",
                "content": {"type": "text", "text": command,
                            "_meta": {"bashCommand": command}},
                "_meta": {"promptIndex": 0}}}}


def owner_row(text, at=AT + 2):
    return {"timestamp": at, "method": "session/update",
            "params": {"sessionId": CONVERSATION, "update": {
                "sessionUpdate": "user_message_chunk",
                "content": {"type": "text", "text": text},
                "_meta": {"promptIndex": 1, "modelId": "grok-4.6"}}}}


def write_updates(home, cwd, rows):
    home.write(f".grok/sessions/{quote(str(cwd), safe='')}/{CONVERSATION}/updates.jsonl",
               "".join(json.dumps(row) + "\n" for row in rows))


class GrokShellCommandsAreNotOwnerWords(unittest.TestCase):
    def test_shell_commands_alone_give_the_done_check_no_owner_words(self):
        with Home() as home:
            fake = fakeadapter.install(home, grokbuild="pass", claude="pass")["claude"]
            seat = Seat(home, "acme", model="grok", alive=False,
                        record={"conversation": CONVERSATION})
            write_updates(home, seat.cwd, [shell_1092_row(SHELL_1092),
                                           shell_legacy_row(SHELL_LEGACY)])
            akconfig.write(home, ["grok", "opus"], extra='[done_check]\nmodel = "opus"')
            done = home.ak("orch", "check", "acme")
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual(fake.n, 0)

    def test_shell_commands_beside_owner_words_are_left_out_of_the_check(self):
        with Home() as home:
            fake = fakeadapter.install(home, grokbuild="pass", claude="pass")["claude"]
            seat = Seat(home, "acme", model="grok", alive=False,
                        record={"conversation": CONVERSATION})
            write_updates(home, seat.cwd, [shell_1092_row(SHELL_1092),
                                           shell_legacy_row(SHELL_LEGACY),
                                           owner_row(OWNER_ASK)])
            akconfig.write(home, ["grok", "opus"], extra='[done_check]\nmodel = "opus"')
            sh = [f"! grep -rqF -- {shlex.quote(cmd)} . || exit 1"
                  for cmd in (SHELL_1092, SHELL_LEGACY)]
            sh += [f"grep -rqF -- {shlex.quote(OWNER_ASK)} owner/ || exit 1"]
            sh += [f"printf '%s\\n%s\\n' {shlex.quote(SHELL_1092)} {shlex.quote(SHELL_LEGACY)}"
                   " > notes.md"]
            sh += [f"grep -rlF -- {shlex.quote(quote)} . | head -n 1 | while read -r file; do "
                   f"{shlex.quote(AK)} hand-in finding \"$file:1\" 'not in the work' "
                   f"'the owner asked for it' --quote {shlex.quote(quote)}; done"
                   for quote in (OWNER_ASK, SHELL_1092, SHELL_LEGACY)]
            fake.behave({"sh": "; ".join(sh), "final": "Checked.", "hand_in": [["done"]]})
            done = home.ak("orch", "check", "acme")
            self.assertEqual(done.code, 1, done.out + done.err)
            self.assertIn(OWNER_ASK, done.out)
            self.assertNotIn(SHELL_1092, done.out + done.err)
            self.assertNotIn(SHELL_LEGACY, done.out + done.err)
            self.assertEqual(fake.n, 1)


if __name__ == "__main__":
    unittest.main()
