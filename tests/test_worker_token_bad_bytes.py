"""A worker-token file that cannot be decoded is a bad token, never the end of the tick.

One non-UTF-8 byte in the file used to raise out of the tick's health pass -- no resume,
no recovery, no reap on any tick after -- and out of the `i` screen.  It reads now as a
blank or unreadable file does: no token, so nothing to date and nothing to ask.

Offline: a temporary HOME whose secrets file holds the bad byte; the real
~/.agentkit/secrets is never read, and the `auth` verb is never asked.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, watch, worker


class WorkerTokenBadBytes(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".token-bytes-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        stack = ExitStack()
        self.addCleanup(stack.close)
        home = Path(tmp.name) / "home"
        ak = home / ".agentkit"
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, ak / name.lower()))
        stack.enter_context(patch.object(config, "HOME", ak))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(home), "AGENTKIT_DISCORD_WEBHOOK": "",
            "AGENTKIT_DISCORD_USER_ID": "", "NO_COLOR": "1"}))
        self.asked = stack.enter_context(patch.object(worker, "auth_ok"))
        config.ensure_dirs()
        (config.SECRETS / "claude_oauth_token").write_bytes(b"sk-ant-oat01-\xff\n")

    def test_the_tick_reads_it_as_no_token(self):
        state = {"worker_tokens": {}}
        self.assertEqual(watch.poll_worker_token(state), {})
        self.assertNotIn("worker_tokens", state)
        self.asked.assert_not_called()

    def test_the_config_screen_carries_on(self):
        self.assertIsNone(watch.worker_token_note())
        tips = menu.config_tips(config.load(), watch.worker_token_note())
        self.assertNotIn("worker token", "\n".join(tips.values()))


if __name__ == "__main__":
    unittest.main()
