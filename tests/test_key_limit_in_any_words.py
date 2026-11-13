"""A Claude seat refused by any usage limit reads `out of usage`, whatever words the refusal uses,
and a seat with nothing to continue keeps its own word while that usage is gone.

Seen on 31 Oct 2026 with Claude Code 2.1.314: `You've hit your 5-hour limit` was in no list, so a
refused seat read `done` off its finished plan and nothing resumed it.  The refusal's typed kind
says so in any words and its usual opening says so with no kind.  The owner, 2 Nov 2026: "Out of
usage should be when there is no more usage from the provider to continue."  Black-box against
`AK_BIN`, as tests/test_key_unknown_error_is_retried.py; conversations have the shape Claude Code
writes, under invented ids, and no provider is reached.
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


ANSWER = entry("Shipped it.")
TYPED = entry("Back after a little rest", isApiErrorMessage=True, apiError="usage_limit_reached")
WORDED = entry("You've hit your 5-hour limit · resets 4:10am (Europe/Berlin)",
               isApiErrorMessage=True)
# One model's own cap, spent in a week with room (2.1.322, 12 Nov 2026): a kind and an opening of
# its own, and no time.  In no list, its seats sat at their prompts until the owner typed.
CAPPED = entry("That model is resting", isApiErrorMessage=True,
               apiError="model_requires_usage_credits")
CAP_WORDED = entry("You've reached your Fable limit. Run /usage-credits to continue or switch "
                   "models with /model.", isApiErrorMessage=True)
FINISHED, OWING = "- [x] Shipped it\n", "- [x] Shipped it\n- [ ] Ship the rest\n"


# `out of usage`: until it comes back or the owner moves it. [14, 20 Oct 2026]
# A seat with nothing to continue keeps its own word while that usage is gone.
@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class LimitInAnyWords(unittest.TestCase):
    def words(self, seats, ticks=1, acted=None, renamed=False):
        """Each seat's word after `ticks` ticks, on one subscription; `seats` gives each name what
        its conversation ends on and its plan.  With `acted`, ak acted on a refusal in the words
        each ends on that many seconds before its turn ends: before its prompt, or since.  With
        `renamed`, `ak orch rename` gives each `<name>-now` before its hooks fire under the name
        it was launched with."""
        home = Home()
        self.addCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"))
        akconfig.write(home, ["opus"])
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        fakeadapter.install(home, claude="pass")
        hooks = Hooks(home)
        for name, (end, plan) in seats.items():
            seat = Seat(home, name)
            home.write(f".agentkit/state/plan-{name}.md", plan)
            said = [{"type": "user", "message": {"role": "user", "content": "go"}}, end]
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            home.write(f".claude/projects/{folder}/conv-{name}.jsonl",
                       "".join(json.dumps(line) + "\n" for line in said))
            now = f"{name}-now" if renamed else name
            if renamed:
                done = home.ak("orch", "rename", name, now)
                self.assertEqual(done.code, 0, done.out + done.err)
            hooks.fire("UserPromptSubmit", {"prompt": "go"}, seat=name, pane=seat, finished=True)
            if acted is not None:
                home.write(f".agentkit/state/seat-{now}.json", {"session": now, "usage_refusal": {
                    "line": f'{end["message"]["content"][0]["text"]}\n{end["apiError"]}',
                    "at": time.time() - acted, "handled": True}})
            if end.get("isApiErrorMessage"):    # Claude Code ends a refused turn so
                hooks.fire("StopFailure", {"error": "rate_limit"}, seat=name, pane=seat,
                           finished=True)
            else:
                hooks.fire("Stop", {"background_tasks": [], "transcript_path": "",
                                    "last_assistant_message": "Done."}, seat=name, pane=seat,
                           finished=True)
        for _ in range(ticks):
            done = home.ak("watch", boxed=True, env={"AK_HOST_READINGS": json.dumps(FINE)})
            self.assertEqual(done.code, 0, done.out + done.err)
        words = {}
        for name in seats:
            why = home.ak("orch", "why", f"{name}-now" if renamed else name)
            self.assertEqual(why.code, 0, why.err)
            words[name] = why.out.splitlines()[0].split(None, 1)[1]
        return words

    def test_a_refusal_reads_out_of_usage_in_any_words(self):
        # A home each: one refusal spends the subscription for every seat after it.
        for end in (TYPED, WORDED, CAPPED, CAP_WORDED):
            with self.subTest(end["message"]["content"][0]["text"]):
                self.assertEqual(self.words({"refused": (end, FINISHED)}),
                                 {"refused": "out of usage"})

    def test_a_refusal_in_the_words_of_one_acted_on_before_its_prompt_is_a_new_one(self):
        # 12 Nov 2026: a seat prompted an hour after its refusal was refused in the same words,
        # taken for the one before, and stood for six hours.
        self.assertEqual(self.words({"refused": (TYPED, FINISHED)}, acted=3600),
                         {"refused": "out of usage"})
        self.assertEqual(self.words({"refused": (TYPED, FINISHED)}, acted=0),
                         {"refused": "working"})    # acted on since that turn: it goes on

    def test_a_seat_renamed_since_its_launch_is_refused_anew_all_the_same(self):
        # 12 Nov 2026: five of 34 seats held their prompt's stamp only under an earlier name.
        for plan in (FINISHED, OWING):
            with self.subTest(plan=plan):
                self.assertEqual(self.words({"refused": (TYPED, plan)}, acted=3600, renamed=True),
                                 {"refused": "out of usage"})

    def test_a_conversation_ending_on_an_answer_was_refused_nothing(self):
        self.assertEqual(self.words({"answered": (ANSWER, FINISHED)}), {"answered": "done"})

    def test_out_of_usage_is_for_a_seat_with_something_to_continue(self):
        # Two ticks, so that each is looked at once the refusal has spent the subscription.
        self.assertEqual(self.words({"refused": (TYPED, FINISHED), "finished": (ANSWER, FINISHED),
                                     "owing": (ANSWER, OWING)}, ticks=2),
                         {"refused": "out of usage", "finished": "done", "owing": "out of usage"})


if __name__ == "__main__":
    unittest.main()
