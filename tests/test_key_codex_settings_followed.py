"""Settings changed inside Codex reach the seat's record, bar and open `c` without an answer,
in the thread the seat moved to with /new as in its first.

Black-box against AK_BIN: the fake server speaks Codex 0.166's settings notification and
rollout event, refusing the subscription until its rollout is available.
"""
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akseat import FIXTURES
from fixtures.akterm import Terminal

THREAD = "01a17700-0000-7000-8000-00000000acme"


def until(test, what):
    deadline = time.monotonic() + 30
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}")
        time.sleep(.05)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class CodexSettingsFollowed(unittest.TestCase):
    def test_settings_follow_without_a_new_answer_even_after_resume_was_refused(self):
        home = Home()
        self.addCleanup(home.close)
        home.env.update(FAKE_THREAD=THREAD, FAKE_HOLD="1",
                        FAKE_SCREEN=str(FIXTURES / "codex-prompt-pane.txt"),
                        https_proxy="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9")
        home.fake("codex", "#!/bin/sh\nexec " + shlex.join(
            [sys.executable, str(FIXTURES / "codex-remote-fake.py")]) + ' "$@"\n')
        home.write(".codex/auth.json", {"tokens": {"access_token": "acme-token",
                                                   "account_id": "acme-account"}})
        akconfig.write(home, {"astra": {}, "luna": {"harness": "codex", "model": "gpt-5.6-luna"}})
        gate = home.write("resume-blocked", "")
        terminal = Terminal(home, "orch", "acme", "--model", "astra", "--workers", "astra")
        until(lambda: list(home.path.rglob("fake-tui.json")), "opened the seat")
        until(lambda: list(home.path.rglob("fake-resume-failed.json")), "tried to subscribe")
        self.assertEqual(home.tmux("has-session", "-t", "=acme:").code, 0)
        gate.unlink()
        until(lambda: list(home.path.rglob("fake-subscribed.json")), "subscribed after the refusal")
        subscribed, = home.path.rglob("fake-subscribed.json")
        self.assertEqual(json.loads(subscribed.read_text())["threadId"], THREAD)
        record = home.path / ".agentkit/state/session-acme.json"
        terminal.wait("idle")
        terminal.keys("C-b", "m")
        terminal.wait("esc leave")
        terminal.keys("c")
        terminal.wait(lambda screen: "esc back" in screen and "6 Astra" in screen)

        def follows(thread, model, label, effort):
            with self.subTest(thread=thread, model=model, effort=effort):
                rollout, = home.path.rglob(f"rollout-{thread}.jsonl")
                model_id = akconfig.read(home)["models"][model]["model"]
                with rollout.open("a") as fh:
                    fh.write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
                        "type": "event_msg", "payload": {"type": "thread_settings_applied",
                        "thread_settings": {"model": model_id, "reasoning_effort": effort}}}) + "\n")
                event = {"method": "thread/settings/updated", "params": {
                    "threadId": thread, "threadSettings": {"model": model_id, "effort": effort}}}
                home.write("notification.tmp", event).replace(subscribed.parent / "settings-notification.json")

                def followed():
                    data = json.loads(record.read_text())
                    return (data["orchestrator"] == model
                            and data.get("efforts", {}).get(model, {}).get("effort") == effort)
                until(followed, f"followed {model} at {effort} without another answer")

                def bar_followed():
                    bar = home.tmux("show-options", "-v", "-t", "=acme:", "@ak_top").out
                    return label in bar and effort in bar
                until(bar_followed, f"put {label} at {effort} on the bar")
                terminal.wait(lambda screen: any(label in line and "●" in line and effort in line
                                                 for line in screen.splitlines()))

        for model, label, effort in (("luna", "5.6 Luna", "low"),
                                     ("luna", "5.6 Luna", "medium"),
                                     ("astra", "6 Astra", "high")):
            follows(THREAD, model, label, effort)
        # The seat moves to the thread /new opens at its first prompt, and its settings with it,
        # while the thread it left goes on printing a background terminal's output.
        for keys in (("-l", "/new"), ("Enter",), ("-l", "Go on."), ("Enter",)):
            self.assertEqual(home.tmux("send-keys", "-t", "=acme:", *keys).code, 0)
        lines = itertools.count()

        def moved():
            home.write("notification.tmp", {"method": "item/commandExecution/outputDelta",
                "params": {"threadId": THREAD, "delta": f"line {next(lines)}\n"}}).replace(
                subscribed.parent / "settings-notification.json")
            return json.loads(subscribed.read_text())["threadId"] != THREAD
        until(moved, "subscribed to the thread /new opened while the one left went on")
        follows(json.loads(subscribed.read_text())["threadId"], "luna", "5.6 Luna", "low")


if __name__ == "__main__":
    unittest.main()
