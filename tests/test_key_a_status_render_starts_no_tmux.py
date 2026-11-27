"""A status render starts no tmux: an Antigravity seat is read off its screen, not a pane option."""

import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

HOOK = Path(__file__).resolve().parents[1] / "hooks/claude-status.sh"


class StatusRenderStartsNoTmux(unittest.TestCase):
    def test_a_render_carrying_agent_state_calls_no_tmux(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp, "tmux")
            fake.write_text('#!/bin/sh\necho "$@" >>"$HOME/called"\n')
            fake.chmod(0o755)
            env = {**os.environ, "HOME": tmp, "PATH": f"{tmp}:{os.environ['PATH']}",
                   "AK_RUN_ROLE": "", "AGENTKIT_SESSION": "acme", "TMUX": "s,1,0", "TMUX_PANE": "%1"}
            hook = subprocess.Popen([str(HOOK)], env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, text=True, start_new_session=True)
            hook.communicate('{"agent_state": "working"}', timeout=30)
            for _ in range(600):     # what the hook started behind itself ends before the look
                try:
                    os.killpg(hook.pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            self.assertEqual((hook.returncode, list(Path(tmp).glob("called"))), (0, []))


if __name__ == "__main__":
    unittest.main()
