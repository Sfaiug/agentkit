"""The report a Muse model call's hook keeps stands until later news, and while a seat names its
conversation.

Muse runs the PreLLMCall hook beside the call (`adapters/muse.sh call`), so a hook held up after
it read its call can finish after the next call's hook, or after a `/model` change: each report
is named by the moment its hook began, and `muse.running` reads the latest.  The held hook waits
at its `mv`, the step that publishes its report, on a wrapper put first on its PATH.  Collection
reads the conversation in that name.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO
from agentkit import config, gc
from agentkit.harness import muse

SPARK, WONDER = "muse-spark-1.3-contributor", "muse-wonder-full-1.0"
SESSION = "01a18c52-a770-75a1-9576-acme00000004"
HELD = '#!/bin/sh\n: >"$0.held"\nread -r go <"$0.go"\nexec /bin/mv "$@"\n'


class CallOrder(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.log = self.home / f".local/share/muse/sessions/2026/11/12/{SESSION}/session.jsonl"
        self.log.parent.mkdir(parents=True)
        self.log.write_text("")
        self.state = self.home / ".agentkit/state"
        self.state.mkdir(parents=True)
        self.wrapper = self.home / "held/mv"
        self.wrapper.parent.mkdir()
        self.wrapper.write_text(HELD)
        self.wrapper.chmod(0o755)
        os.mkfifo(f"{self.wrapper}.go")

    def call(self, effort, held=False):
        """That call's hook, run as Muse runs it; held, once it waits at its `mv`."""
        path = f"{self.wrapper.parent}:{os.environ['PATH']}" if held else os.environ["PATH"]
        hook = subprocess.Popen(["bash", str(REPO / "adapters/muse.sh"), "call"],
                                stdin=subprocess.PIPE, text=True,
                                env={"HOME": str(self.home), "PATH": path, "AGENTKIT_SESSION": "acme"})
        hook.stdin.write(json.dumps({"session_id": SESSION, "model": SPARK, "messages": [],
                                     "options": {"meta.reasoning.effort": effort}}))
        hook.stdin.close()
        if not held:
            self.assertEqual(hook.wait(timeout=30), 0)
            return None
        self.addCleanup(hook.kill)
        deadline = time.monotonic() + 30
        while not Path(f"{self.wrapper}.held").exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        return hook

    def release(self, hook):
        with open(f"{self.wrapper}.go", "w") as go:
            go.write("go\n")
        self.assertEqual(hook.wait(timeout=30), 0)

    def running(self):
        with patch.object(config, "STATE", self.state), \
                patch.dict(os.environ, {"HOME": str(self.home), "XDG_DATA_HOME": ""}):
            return muse.running({"orchestrator": "spark", "efforts": {"spark": {"effort": "max"}}},
                                None, SESSION)

    def test_an_earlier_calls_hook_finishing_last_leaves_the_later_calls_effort(self):
        earlier = self.call("low", held=True)
        self.call("high")
        self.release(earlier)
        self.assertEqual(self.running()[:2], (SPARK, "high"))

    def test_an_earlier_calls_hook_finishing_after_a_model_change_leaves_that_change(self):
        self.call("low")
        earlier = self.call("low", held=True)
        self.log.write_text(json.dumps({
            "recorded_at": int(time.time() * 1_000_000),
            "payload_type": "runtime.model_reconfigure.completed",
            "payload": {"record": {"effective": {"model_id": WONDER}}}}) + "\n")
        self.release(earlier)
        self.assertEqual(self.running()[:2], (WONDER, "max"))

    def test_collection_leaves_it_while_a_seat_names_its_conversation(self):
        self.call("low")
        (report,) = self.state.glob(f"model-{SESSION}.*.json")
        seat = self.state / "session-acme.json"
        with patch.object(config, "STATE", self.state):
            for conversation, stale in ((SESSION, []), ("conv-acme", [str(report)])):
                seat.write_text(json.dumps({"orchestrator": "spark", "conversation": conversation}))
                self.assertEqual([item["path"] for item in gc.stale_model_reports()], stale)


if __name__ == "__main__":
    unittest.main()
