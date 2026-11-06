"""A seat at rest past its harness's prompt cache sleeps only once its composer reads whole and
empty: one holding a draft of ten rows, which Claude Code 2.1.318's screen reads as an empty
prompt, or of seventeen it has scrolled, stays awake, and once the composer is empty a tick puts it
to sleep.  Black-box against `AK_BIN`, as tests/test_key_idle_seat_holds_no_memory.py."""

import json
import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks

DRAFTS = ("claude-ten-row-draft-pane.txt", "claude-scrolled-draft-pane.txt")


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class DraftKeepsASeatAwake(unittest.TestCase):
    def test_a_draft_keeps_it_awake_until_the_composer_is_empty(self):
        home = Home()
        self.addCleanup(home.close)
        akconfig.write(home, ["opus"])
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        fakeadapter.install(home, claude="pass")
        seat = Seat(home, "acme", screen=DRAFTS[0])
        # a conversation Claude filed under the seat's path, which the seat resumes
        folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
        home.write(f".claude/projects/{folder}/conv-acme.jsonl",
                   '{"type":"user","message":{"role":"user","content":"hello"}}\n')
        hooks = Hooks(home)
        hooks.fire("UserPromptSubmit", {"prompt": "go"}, pane=seat)
        hooks.fire("Stop", {"background_tasks": [], "transcript_path": "",
                            "last_assistant_message": "Done."}, pane=seat, finished=True)
        # its turn ended two hours ago, past Claude's hour of prompt cache
        fact = home.path / ".agentkit/state/hook-acme.json"
        home.write(fact, {**json.loads(fact.read_text()), "at": time.time() - 7200})

        def awake():
            done = home.tick()
            self.assertEqual(done.code, 0, done.out + done.err)
            return "acme" in home.tmux("list-sessions", "-F", "#{session_name}").out.split()

        for screen in DRAFTS:
            seat.show(screen)
            self.assertTrue(awake(), screen)
        seat.show("claude-prompt-pane.txt")
        self.assertFalse(awake())


if __name__ == "__main__":
    unittest.main()
