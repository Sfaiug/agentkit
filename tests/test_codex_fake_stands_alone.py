"""The fake Codex opens a thread as the remote TUI on its own app server with nothing of ak beside
it, as tests/test_go_keys.py runs the Codex keys in a copy of the checkout without agentkit/."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

FAKE = Path(__file__).resolve().parent / "fixtures/codex-remote-fake.py"


class StandsAlone(unittest.TestCase):
    def test_tui_starts_a_thread_with_no_agentkit_or_tools_beside_it(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            codex = shutil.copy(FAKE, root / "codex")
            (root / ".codex/sessions").mkdir(parents=True)
            socket = root / "app.sock"
            # Only what the fake reads: no PYTHONPATH that could lead back to agentkit.
            env = {"HOME": str(root), "CODEX_HOME": str(root / ".codex"),
                   "FAKE_THREAD": "acme-thread", "AGENTKIT_SESSION": "acme-seat"}
            server = subprocess.Popen([sys.executable, codex, "app-server", "--remote-control",
                                       "--listen", f"unix://{socket}"], cwd=root, env=env)
            try:
                while not socket.exists():
                    self.assertIsNone(server.poll(), "the app server exited")
                    time.sleep(.05)
                tui = subprocess.run([sys.executable, codex, "--remote", f"unix://{socket}"],
                                     cwd=root, env=env, timeout=60)
            finally:
                server.kill()
                server.wait()
            self.assertEqual(tui.returncode, 0)
            self.assertTrue((root / ".codex/sessions/rollout-acme-thread.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
