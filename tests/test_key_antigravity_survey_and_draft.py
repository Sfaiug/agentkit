"""An agy feedback survey leaves the transcript visible and takes the composer's place."""
import json
from pathlib import Path
import shlex
import sys
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, PANE, Seat

RULE = "─" * 64
SURVEY = (" How's the CLI experience so far? Help us improve:\n"
          " [1] Good  [2] Fine  [3] Bad  [0] Skip")
TIP = "└ Tip: Use /skills to browse and manage agent skills."
HISTORY = (f"{RULE}\n> check acme\n  Ready.\n{RULE}\n> finish acme\n"
           "⚠ You have exhausted your quota on this model.\nError ID: acme-1\n")
COMPOSER = f"{RULE}\n>\n{RULE}"


class AntigravitySurvey(unittest.TestCase):
    def test_fresh_and_resumed_launches_disable_the_survey(self):
        with Home() as home:
            book = home.write("rulebook-acme.md", "Finish acme.")
            for resume in ([], ["conv-acme"]):
                with self.subTest(resume=resume):
                    done = home.run(REPO / "adapters/antigravity.sh", "interactive",
                                    "gemini-3.8-flash", "low", *resume,
                                    env={"AGENTKIT_RULEBOOK": str(book)})
                    self.assertEqual(done.code, 0, done.err)
                    args = shlex.split(done.out)
                    settings = json.loads(args[args.index("--settings") + 1])
                    self.assertIs(settings["showFeedbackSurvey"], False)

    def test_composer_absent_below_historical_prompts(self):
        from agentkit import watch

        permission = ("Run this command?\n> 1. Yes, run command\n  2. No, cancel\n"
                      "  ↑/↓ Navigate · tab Amend · ctrl+g edit/expand command")
        question = ("Question 1/1: Which acme task?\n> 1. Build\n  2. Test\n"
                    "  ↑/↓ Navigate · enter Select · esc Skip")
        for bottom in (SURVEY, permission + "\nesc to cancel", question + "\nesc to cancel"):
            with self.subTest(bottom=bottom.splitlines()[-1]):
                self.assertIsNone(watch.composer_draft("antigravity", HISTORY + bottom))

    def test_tip_preserves_the_quota_refusal(self):
        from agentkit import watch

        self.assertEqual(watch.stalled_on("antigravity", HISTORY + TIP + "\n" + COMPOSER,
                                          None, self.fail), "exhausted your quota")
        typed = f"{TIP}\n{RULE}\n> finish acme\n{RULE}\n  acme  /agents"
        self.assertEqual(watch.screen_state("antigravity", typed), ("draft", "draft.typed",
                                                                    "finish acme"))

    @unittest.skipUnless(REAL_TMUX, "no tmux installed")
    def test_dismiss_ignores_a_quoted_survey_above_the_composer(self):
        with Home() as home:
            seat = Seat(home, model="gemini", composer=">", screen=SURVEY + "\n" + COMPOSER)
            done = home.run(sys.executable, "-c",
                            "from agentkit import watch; watch.dismiss({'name': 'acme'}, 'antigravity')",
                            cwd=REPO)
            self.assertEqual(done.code, 0, done.err)
            self.assertEqual(seat.typed(), "")

    @unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
    def test_parked_seat_skips_survey_and_continues_when_google_refills(self):
        with Home() as home:
            akconfig.write(home, ["gemini"])
            agy = fakeadapter.install(home, antigravity="pass")["antigravity"]
            seat = Seat(home, model="gemini", planned=True, alive=False, composer=">",
                        screen=HISTORY + SURVEY)
            prompt = home.write("prompt", HISTORY + TIP + "\n" + COMPOSER)
            # This pane accepts Skip as one key and then redraws the empty composer.
            seat.program = home.write("survey.py", f"""
import os, sys, tty
from pathlib import Path
sys.path.insert(0, {str(FIXTURES)!r})
from akpane import drawn, stamp
tty.setraw(0)
screen = Path(sys.argv[1]).read_bytes()
with open(sys.argv[2], 'ab', buffering=0) as keys:
    while True:
        frame = drawn(screen.decode(), '', '>', os.get_terminal_size().lines)
        print(f'{{frame}}\\x1b]2;{{stamp(screen, keys.tell())}}\\x07', end='', flush=True)
        key = os.read(0, 1)
        if not key:
            break
        keys.write(key)
        if key == b'0':
            screen = Path({str(prompt)!r}).read_bytes()
""")
            seat.start()
            agy.answer("interactive", shlex.join([sys.executable, str(PANE), str(prompt),
                                                  str(seat.typed_file) + ".reopened", ">"]))
            now = time.time()
            wait = home.write(".agentkit/state/seat-acme.json", {"usage_wait": {
                "reason": "google out of usage", "since": now - 600, "until": now + 3600,
                "continue": True}})
            meter = {"name": "session", "window_secs": 18000, "resets_at": now + 3600}
            home.write(".agentkit/state/usage.json", {
                "fetched_at": now - 60, "reset_checked_at": now, "providers": {"google": {
                    "provider": "google", "probed_at": now - 3600, "resets": 0,
                    "meters": [{**meter, "used": 100}]}}})
            home.write(".agentkit/state/google-probe.lock", repr(now - 3600))
            agy.answer("usage", json.dumps({"meters": [{**meter, "used": 10}], "error": None}))

            done = home.tick()
            self.assertEqual(done.code, 0, done.out + done.err)
            self.assertEqual(seat.typed(), "0")
            self.assertTrue(agy.calls("usage"))
            self.assertFalse(json.loads(wait.read_text()).get("usage_wait"))
            opened, = agy.calls("interactive")
            self.assertIn("Continue that turn", opened["env"]["AGENTKIT_FIRST_PROMPT"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
