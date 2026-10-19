"""A seat is looked at again once its Stop is on record, however long judging the Stop took.

Claude Code runs hooks/orchestrator-stop.sh beside hooks/seat-state.sh on every Stop, and the stop
hook is the one that writes the Stop down, once it has judged whether the turn may end.  The look
that publishes the seat's word is started by the stop hook itself, then: a look started anywhere
else could run before the Stop is written and publish the turn as still running.  Offline: the
harness of tests/test_live_status.py -- a temporary HOME, a fake tmux that writes down every
option it is told to set.
"""

import json
import os
import shutil
import subprocess
import time
import unittest

import test_live_status as live
from agentkit import watch

REPO = live.REPO


class StopHookLooks(live.LiveStatus):

    def test_the_stop_hook_alone_moves_the_bar(self):
        if not shutil.which("jq"):
            self.skipTest("the hook needs jq")
        fake = self.root / "bin" / "tmux"
        fake.parent.mkdir()
        fake.write_text(live.FAKE_TMUX)
        fake.chmod(0o755)
        log = self.root / "tmux.log"
        env = {key: value for key, value in os.environ.items()
               if key not in ("AK_RUN_ROLE", "NO_COLOR")}
        env.update({"PATH": f"{fake.parent}:{os.environ['PATH']}", "AGENTKIT_SESSION": "herdr",
                    "FAKE_TMUX_LOG": str(log), "FAKE_TMUX_SLOW": "0"})

        def run(script, payload):
            subprocess.run(["bash", str(REPO / "hooks" / script)], input=json.dumps(payload),
                           env=env, text=True, capture_output=True, timeout=30, check=True)

        def title():
            text = log.read_text(encoding="utf-8") if log.exists() else ""
            return dict(line.split("\t", 1) for line in text.split("\n")[:-1]).get(
                "set-titles-string")

        def published(word):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if title() == f"herdr · {word}":
                    return
                time.sleep(0.05)
            self.fail(f"the bar never said {word!r}: {title()!r}")

        run("seat-state.sh", {"hook_event_name": "UserPromptSubmit", "prompt": "go"})
        published("working")
        # The stop hook judges the Stop and writes it down; nothing else happens after it.
        run("orchestrator-stop.sh", {"hook_event_name": "Stop", "background_tasks": []})
        published("idle")
        self.assertEqual(watch.seat_read("herdr")["word"], "idle")


def load_tests(loader, tests, pattern):
    """Only this file's own case: the harness's own run in tests/test_live_status.py."""
    return unittest.TestSuite([StopHookLooks("test_the_stop_hook_alone_moves_the_bar")])


if __name__ == "__main__":
    unittest.main()
