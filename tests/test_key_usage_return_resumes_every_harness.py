"""One usage refresh reopens all six parked seats and publishes their words in the same tick."""

import json
import shlex
import sys
import time
import unittest
from urllib.parse import quote

from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, PANE, Seat
from fixtures.hookdrive import conversation
from test_key_a_refill_resumes_waiting_seats_in_the_same_tick import reading

MODELS = {"claude": "opus", "codex": "astra", "antigravity": "gemini",
          "opencode": "mimo", "muse": "spark", "grokbuild": "grok"}
ACCOUNT_LINE = ("Your turn was cut off when its usage ran out, and there is usage again. "
                "Continue that turn and finish it; do not start over.")


def parked(home, harness, now, continuing=True):
    name = f"fix-api-{harness}"
    cwd = home.path / "code" / name
    sid = "ses_acme" if harness == "opencode" else f"conv-{name}"
    record = {"conversation": sid}
    if harness == "codex":
        launch = "a" * 32
        rollout = home.write("rollout-acme.jsonl", json.dumps({
            "type": "session_meta", "payload": {"id": sid, "cwd": str(cwd)}}) + "\n")
        record["codex_launch"] = launch
        home.write(f".agentkit/state/codex-launch-{launch}.json", {
            "launch": launch, "cwd": str(cwd), "event": {
                "hook_event_name": "SessionStart", "source": "startup", "session_id": sid,
                "cwd": str(cwd), "transcript_path": str(rollout)}})
        home.write(".codex/session_index.jsonl",
                   json.dumps({"id": sid, "thread_name": name}) + "\n")
    elif harness == "muse":
        record["id_source"] = "muse-hook"
    screen = "grok" if harness == "grokbuild" else harness
    screen_turn = harness in ("antigravity", "muse")
    screen += "-working-pane.txt" if continuing and screen_turn else "-prompt-pane.txt"
    if continuing and not screen_turn:
        home.write(f".agentkit/state/hook-{name}.json", {
            "session": name, "event": "UserPromptSubmit", "at": now - 700, "kind": "", "text": ""})
    seat = Seat(home, name, model=MODELS[harness], screen=screen, record=record)
    if harness == "claude":
        home.write(conversation(home, seat),
                   '{"type":"user","message":{"role":"user","content":"fix the api"}}\n')
    elif harness == "grokbuild":
        home.write(f".grok/sessions/{quote(str(cwd), safe='')}/{sid}/chat_history.jsonl", "")
    usage_wait(home, seat, harness, now, continuing, "working" if continuing else "at_prompt")
    return seat


def usage_wait(home, seat, harness, now, continuing, state):
    provider = akconfig.PROVIDER[harness]
    return home.write(f".agentkit/state/seat-{seat.name}.json", {
        "session": seat.name, "word": "out of usage", "state": state,
        "began": now - 700, "since": now - 700, "usage_wait": {
            "reason": f"{provider} out of usage", "continue": continuing,
            "since": now - 600, "until": now + 10800}})


def refill(home, fakes, now):
    spent = {}
    for harness, adapter in fakes.items():
        adapter.answer("usage", json.dumps(reading(now, 10)))
        provider = akconfig.PROVIDER[harness]
        spent[provider] = {**reading(now, 100), "provider": provider, "resets": 0,
                           "probed_at": now - 3600}
        home.write(f".agentkit/state/{provider}-probe.lock", repr(now - 3600))
    home.write(".agentkit/state/usage.json", {"providers": spent, "fetched_at": now,
                                              "reset_checked_at": now})
    return home.tick()


@unittest.skipUnless(REAL_TMUX and boxable(), "needs tmux and a boxed watch tick")
class UsageReturnResumesEveryHarness(unittest.TestCase):
    def test_each_seat_publishes_and_continues_on_the_refresh(self):
        with Home() as home:
            akconfig.write(home, list(MODELS.values()))
            fakes = fakeadapter.install(home, **dict.fromkeys(MODELS, "pass"))
            now = time.time()
            seats = {}
            for harness, adapter in fakes.items():
                seat = seats[harness] = parked(home, harness, now)
                if harness == "muse":
                    # Its prompt turns into a working screen only after Enter lands.
                    screens = home.write("acme-screens.json", {ACCOUNT_LINE: seat.screen})
                    pane = [FIXTURES / "muse-prompt-pane.txt", seat.typed_file, "❯", screens]
                else:
                    pane = [seat.screen_file, seat.typed_file]
                adapter.answer("interactive", shlex.join(
                    [sys.executable, str(PANE), *map(str, pane)]))

            tick = refill(home, fakes, now)
            self.assertEqual(tick.code, 0, tick.out + tick.err)
            for harness, seat in seats.items():
                with self.subTest(harness=harness):
                    path = home.path / f".agentkit/state/seat-{seat.name}.json"
                    state = json.loads(path.read_text())
                    self.assertIsNone(state["usage_wait"], tick.out + tick.err)
                    self.assertEqual(state["word"], "working")
                    self.assertTrue(fakes[harness].calls("usage"))
                    launch, = fakes[harness].calls("interactive")
                    self.assertIn(seat.record["conversation"], launch["argv"])
                    if harness == "muse":
                        self.assertEqual(seat.lines(), [ACCOUNT_LINE])
                        self.assertIn("Thinking", seat.capture())
                    else:
                        self.assertEqual(launch["env"]["AGENTKIT_FIRST_PROMPT"], ACCOUNT_LINE)
                        self.assertEqual(seat.lines(), [])

    def test_idle_seats_stay_idle_while_their_relaunched_panes_are_loading(self):
        with Home() as home:
            harnesses = ("muse", "antigravity")
            akconfig.write(home, [MODELS[harness] for harness in harnesses])
            fakes = fakeadapter.install(home, **dict.fromkeys(harnesses, "pass"))
            now = time.time()
            loading = home.write("acme-startup.txt", "Starting session\n")
            seats = {}
            for harness, adapter in fakes.items():
                seat = seats[harness] = parked(home, harness, now, continuing=False)
                adapter.answer("interactive", shlex.join(
                    [sys.executable, str(PANE), str(loading), str(seat.typed_file)]))

            tick = refill(home, fakes, now)
            self.assertEqual(tick.code, 0, tick.out + tick.err)
            for harness, seat in seats.items():
                with self.subTest(harness=harness):
                    launch, = fakes[harness].calls("interactive")
                    self.assertFalse(launch["env"].get("AGENTKIT_FIRST_PROMPT"))
                    self.assertEqual(seat.lines(), [])
                    path = home.path / f".agentkit/state/seat-{seat.name}.json"
                    state = json.loads(path.read_text())
                    self.assertIsNone(state["usage_wait"])
                    self.assertEqual(state["word"], "idle")

    def test_a_turn_continued_in_its_existing_pane_publishes_working(self):
        with Home() as home:
            akconfig.write(home, ["spark"])
            fakes = fakeadapter.install(home, muse="pass")
            now = time.time()
            seat = Seat(home, "fix-api", model="spark", screen="muse-prompt-pane.txt",
                        asks={"continue": "muse-working-pane.txt"})
            path = usage_wait(home, seat, "muse", now, continuing=True, state="at_prompt")
            tick = refill(home, fakes, now)
            self.assertEqual(tick.code, 0, tick.out + tick.err)
            self.assertEqual(fakes["muse"].calls("interactive"), [])
            self.assertEqual(seat.lines(), ["continue"])
            self.assertIn("Thinking", seat.capture())
            state = json.loads(path.read_text())
            self.assertIsNone(state["usage_wait"])
            self.assertEqual(state["word"], "working")

    def test_an_owned_seat_explains_its_wait_for_an_empty_field_once(self):
        with Home() as home:
            akconfig.write(home, ["opus"])
            adapter = fakeadapter.install(home, claude="pass")["claude"]
            now = time.time()
            seat = parked(home, "claude", now)
            seat.show("claude-draft-pane.txt")
            adapter.answer("usage", json.dumps(reading(now, 10)))

            # Both health and the usage refresh see room on both ticks.
            messages = []
            for _ in range(2):
                tick = home.tick()
                self.assertEqual(tick.code, 0, tick.out + tick.err)
                messages.extend(line for line in tick.out.splitlines() if seat.name in line
                                and "empty input field" in line)
            self.assertEqual(len(messages), 1, messages)
            self.assertEqual(adapter.calls("interactive"), [])
            self.assertIn("Fix the login redirect", seat.capture())
            self.assertEqual(seat.typed(), "")


if __name__ == "__main__":
    unittest.main()
