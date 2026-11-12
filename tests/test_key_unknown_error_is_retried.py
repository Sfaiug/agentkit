"""A Claude seat at its prompt with a finished plan, prompted since it finished: a conversation
ending on an error in words no list holds reads `working`, `retrying` in those words and stays
open; one ending on an answer in the same words, `done`.  Black-box against `AK_BIN`
(tests/fixtures/akbin.py)."""

import json
import re
import socket
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import Seat
from fixtures.hookdrive import Hooks

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
FINE = {"mem_total_mb": 16000, "cpus": 8, "load": 0.1, "free_mb": 12000}
RESTED = 2 * 3600
PROMPT = {"type": "user", "message": {"role": "user", "content": "the run ended"}}


def assistant(text, **fields):
    return {"type": "assistant", **fields,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


WORDS = "The flux capacitor declined this request"     # in no list of ak's
# as Claude Code records each, the error over two lines
ENDINGS = {"failed": assistant(WORDS.replace("capacitor ", "capacitor\n   "),
                               isApiErrorMessage=True),
           "answered": assistant(WORDS)}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class UnknownErrorIsRetried(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file")
        del home.env["AK_MAX_RUNS"]       # its host gates on: memory is read as injected
        akconfig.write(home, ["opus"])
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        fakeadapter.install(home, claude="pass")
        hooks, now = Hooks(home), time.time()
        for name, ending in ENDINGS.items():
            home.write(f".agentkit/state/plan-{name}.md", "- [x] Shipped it\n")
            seat = Seat(home, name, screen="claude-prompt-pane.txt")
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            home.write(f".claude/projects/{folder}/conv-{name}.jsonl",
                       "".join(json.dumps(entry) + "\n" for entry in (PROMPT, ending)))
            hooks.fire("UserPromptSubmit", {"prompt": "the run ended"}, seat=name, pane=seat)
            hooks.fire("Stop", {"background_tasks": [], "transcript_path": "",
                                "last_assistant_message": "Done."}, seat=name, pane=seat,
                       finished=True)
            fact = home.path / f".agentkit/state/hook-{name}.json"
            home.write(fact, {**json.loads(fact.read_text()), "at": now - RESTED})
        done = home.ak("watch", boxed=True, env={"AK_HOST_READINGS": json.dumps(FINE)})
        assert done.code == 0, done.out + done.err
        cls.awake = home.tmux("list-sessions", "-F", "#{session_name}").out.split()

    def why(self, name):
        """`ak orch why`'s word and its reason."""
        done = self.home.ak("orch", "why", name)
        self.assertEqual(done.code, 0, done.err)
        lines = done.out.splitlines()
        reason = next(line for line in lines if line.startswith("  reason:"))
        return lines[0].split(None, 1)[1], reason.split(":", 1)[1].strip()

    def test_an_error_in_unknown_words_is_retried_awake(self):
        word, reason = self.why("failed")
        self.assertEqual(word, "working")
        self.assertIn(WORDS, reason)
        self.assertIn("failed", self.awake)

    def test_an_answer_in_the_same_words_is_done(self):
        self.assertEqual(self.why("answered")[0], "done")


if __name__ == "__main__":
    unittest.main()
