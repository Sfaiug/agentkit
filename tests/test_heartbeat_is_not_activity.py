"""A hung tool call ends its turn after the silence limit, heartbeats or not.

A harness that writes an event every half minute while one tool call blocks keeps its
events.jsonl growing for ever; `[worker] heartbeats` in its adapters/<harness>.toml names
those events, and the silence watchdog counts only the others.  One executor's wait loop
matched its own shell and held a run slot for nine hours this way.

Offline: a temporary HOME and a fake harness `acme` in a temporary adapter directory, whose
turn writes one event of the kind it is told, every 0.2 s, until it is stopped.  No sandbox,
no login: the box and the auth check are patched to pass through.
"""

from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, worker

ADAPTER = """#!/bin/sh
out=$6
: >"$out/events.jsonl"
while :; do printf '{"type":"%s"}\\n' "$ACME_EVENT" >>"$out/events.jsonl"; sleep 0.2; done
"""
MANIFEST = """version = 1
[worker]
state = []
{heartbeats}
"""
CONFIG = """[defaults]
orchestrator = "acme"
workers = ["acme"]

[models.acme]
harness = "acme"
model = "acme-1"
effort = "low"
provider = "acme"

[providers.acme]
mode = "subscription"
"""
SILENCE = 2


@contextmanager
def unboxed(cmd, env, _out_dir, *, cwd=None, **_kw):
    yield cmd, env, {"cwd": cwd}


class HeartbeatIsNotActivity(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="heartbeat-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.adapters = self.root / "adapters"
        self.adapters.mkdir()
        (self.adapters / "acme.sh").write_text(ADAPTER)
        (self.adapters / "acme.sh").chmod(0o755)
        home = self.root / "home"
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(home), config.ADAPTER_DIR_ENV: str(self.adapters), "AGENTKIT_RUN": ""}))
        stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, home / name.lower()))
        stack.enter_context(patch.dict(config._MANIFESTS))
        stack.enter_context(patch.object(worker, "auth_ok", return_value=(True, "")))
        stack.enter_context(patch.object(worker.box, "command", unboxed))
        stack.enter_context(patch.object(worker.box, "returncode", lambda _out, code: code))
        stack.enter_context(patch.object(worker, "kill_marked", return_value=True))
        config.ensure_dirs()
        (home / "config.toml").write_text(CONFIG)
        self.cfg = config.load()
        self.workspace = self.root / "ws"
        self.workspace.mkdir()

    def turn(self, event, heartbeats, ends_by):
        """Whether a turn writing only `event`s was killed, given the declared heartbeats;
        one still running at `ends_by` seconds is stopped by the test's own ceiling."""
        (self.adapters / "acme.toml").write_text(MANIFEST.format(heartbeats=heartbeats))
        limited = worker.limited

        def ceiling(cmd, _limit, **kw):
            kw["on_timeout"] = lambda reason, _pid: reasons.append(reason)
            return limited(cmd, ends_by, **kw)

        reasons = []
        with patch.dict(os.environ, {"ACME_EVENT": event}), \
                patch.object(worker, "limited", ceiling):
            worker.call(self.cfg, "acme", "do it", self.workspace, self.root / f"out-{event}",
                        limit=SILENCE)
        return reasons

    def test_a_turn_writing_only_heartbeats_is_killed_as_silent(self):
        self.assertEqual(self.turn("tool_progress", 'heartbeats = ["tool_progress"]', 30),
                         ["silence"])

    def test_a_turn_writing_other_events_at_that_pace_is_not(self):
        self.assertEqual(self.turn("assistant", 'heartbeats = ["tool_progress"]', SILENCE * 3),
                         ["ceiling"])

    def test_a_harness_declaring_no_heartbeats_counts_every_event_as_today(self):
        self.assertEqual(self.turn("tool_progress", "", SILENCE * 3), ["ceiling"])


if __name__ == "__main__":
    unittest.main()
