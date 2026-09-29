"""A full 5h session window stops every model of its subscription, one with a meter of its own too.

Fable names `meter = "weekly_scoped"`, and its gate used to be that meter and the shared week
alone: a session window at 100% left it pickable, to be refused on its first request.  Fake
meters and the shipped default config under a temporary home; nothing is probed.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, usage

WEEK = 604800


def meter(name, used, window):
    return {"name": name, "used": used, "resets_at": time.time() + window, "window_secs": window,
            "pace": None}


class SessionWindow(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".session-window-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        for key in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, key, root / key.lower()))
        stack.enter_context(patch.dict(os.environ, {"HOME": str(root), "AGENTKIT_SESSION": ""}))
        config.ensure_dirs()
        self.cfg = config.load()

    def providers(self, session_used):
        return {"anthropic": {"meters": [meter("session", session_used, usage.SESSION_SECS),
                                         meter("weekly_all", 40, WEEK),
                                         meter("weekly_scoped", 20, WEEK)]}}

    def test_a_full_session_window_stops_a_model_with_its_own_meter(self):
        self.assertEqual(self.cfg["models"]["fable"].get("meter"), "weekly_scoped")
        for name in ("fable", "opus"):
            exhausted, why = usage.model_exhausted(self.cfg, name, self.providers(100))
            self.assertTrue(exhausted, name)
            self.assertIn("session 100% used", why)

    def test_a_session_window_with_room_stops_nothing(self):
        for name in ("fable", "opus"):
            self.assertFalse(usage.model_exhausted(self.cfg, name, self.providers(99))[0], name)


if __name__ == "__main__":
    unittest.main()
