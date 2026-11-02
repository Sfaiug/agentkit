"""A Claude seat refused by any usage limit reads `out of usage`, whatever words the refusal uses.

Seen on 31 Oct 2026 with Claude Code 2.1.314: `You've hit your 5-hour limit` was in no list, so a
refused seat read `done` off its finished plan and nothing resumed it.  Three seats on one
subscription, each with a finished plan: the refusal's typed kind says so in any words, its usual
opening says so with no kind, and a conversation ending on an answer was refused nothing.
Black-box against `AK_BIN`, as tests/test_key_idle_seat_holds_no_memory.py; conversations have
the shape Claude Code writes, under invented ids, and no provider is reached.
"""

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


def entry(text, **fields):
    return {"type": "assistant", **fields,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


# what each seat's conversation ends on, and the word that makes it.  `answered` sorts first, and
# must: a tick looks at seats in name order, and a refusal marks the subscription spent, which
# reads `out of usage` on every seat looked at from then on (tests/test_seat_account.py).
ENDS = {"typed": (entry("Back after a little rest", isApiErrorMessage=True,
                        apiError="usage_limit_reached"), "out of usage"),
        "worded": (entry("You've hit your 5-hour limit · resets 4:10am (Europe/Berlin)",
                         isApiErrorMessage=True), "out of usage"),
        "answered": (entry("Shipped it."), "done")}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class LimitInAnyWords(unittest.TestCase):
    def test_each_seat_reads_what_its_conversation_ended_on(self):
        home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"))
        akconfig.write(home, ["opus"])
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        fakeadapter.install(home, claude="pass")
        hooks = Hooks(home)
        for name, (end, _) in ENDS.items():
            seat = Seat(home, name)
            home.write(f".agentkit/state/plan-{name}.md", "- [x] Shipped it\n")
            said = [{"type": "user", "message": {"role": "user", "content": "go"}}, end]
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            home.write(f".claude/projects/{folder}/conv-{name}.jsonl",
                       "".join(json.dumps(line) + "\n" for line in said))
            hooks.fire("UserPromptSubmit", {"prompt": "go"}, seat=name, pane=seat)
            hooks.fire("Stop", {"background_tasks": [], "transcript_path": "",
                                "last_assistant_message": "Done."}, seat=name, pane=seat,
                       finished=True)
        done = home.ak("watch", boxed=True, env={"AK_HOST_READINGS": json.dumps(FINE)})
        self.assertEqual(done.code, 0, done.out + done.err)
        for name, (_, word) in ENDS.items():
            with self.subTest(name):
                why = home.ak("orch", "why", name)
                self.assertEqual(why.code, 0, why.err)
                self.assertEqual(why.out.splitlines()[0].split(None, 1)[1], word, why.out)


if __name__ == "__main__":
    unittest.main()
