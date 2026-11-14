"""The fake Codex opens a thread as the remote TUI on its own app server with nothing of ak beside
it, as tests/test_go_keys.py runs the Codex keys in a copy of the checkout without agentkit/."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

FAKE = Path(__file__).resolve().parent / "fixtures/codex-remote-fake.py"


def until(test, what):
    deadline = time.monotonic() + 60
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}")
        time.sleep(.05)


def running(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class StandsAlone(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        self.codex = shutil.copy(FAKE, root / "codex")
        (root / ".codex/sessions").mkdir(parents=True)
        self.socket = root / "app.sock"
        # Only what the fake reads: no PYTHONPATH that could lead back to agentkit.
        self.env = {"HOME": str(root), "CODEX_HOME": str(root / ".codex"),
                    "FAKE_THREAD": "acme-thread", "AGENTKIT_SESSION": "acme-seat"}
        # Each start's hook writes its event down, a line each.
        starts = json.dumps(shlex.join(["sh", "-c", "cat >>starts.jsonl; echo >>starts.jsonl"]))
        self.server = subprocess.Popen([
            sys.executable, self.codex, "app-server", "--remote-control", "--listen",
            f"unix://{self.socket}", "-c", f"hooks.SessionStart=[{{hooks=[{{command={starts}}}]}}]"],
            cwd=root, env=self.env)
        self.addCleanup(self.server.wait)
        self.addCleanup(self.server.kill)
        until(lambda: self.socket.exists() or self.server.poll() is not None, "served")
        self.assertIsNone(self.server.poll(), "the app server exited")
        self.tui = [sys.executable, self.codex, "--remote", f"unix://{self.socket}"]

    def test_tui_starts_a_thread_with_no_agentkit_or_tools_beside_it(self):
        tui = subprocess.run(self.tui, cwd=self.root, env=self.env, timeout=60)
        self.assertEqual(tui.returncode, 0)
        self.assertTrue((self.root / ".codex/sessions/rollout-acme-thread.jsonl").exists())

    def test_tui_takes_prompts_new_and_resume_and_its_server_ends_with_its_entry_point(self):
        tui = subprocess.Popen(self.tui, stdin=subprocess.PIPE, cwd=self.root,
                               env={**self.env, "FAKE_HOLD": "1", "FAKE_SCREEN": os.devnull})
        self.addCleanup(tui.wait)
        self.addCleanup(tui.kill)
        # its first prompt longer than one read of what is typed
        typed = ["fix the api " * 400, "/new", "add a test", "/resume acme-thread", "ship it"]
        tui.stdin.write("".join(line + "\n" for line in typed).encode())
        tui.stdin.close()
        heard = self.root / ".codex/fake-heard.jsonl"
        until(lambda: heard.exists() and len(heard.read_text().splitlines()) == len(typed),
              "heard each line")
        lines = [json.loads(line) for line in heard.read_text().splitlines()]
        first, second = "acme-thread", lines[1][1]
        self.assertNotEqual(second, first)
        self.assertEqual(lines, [[line, thread] for line, thread in
                                 zip(typed, (first, second, second, first, first))])
        for thread, words in ((first, [typed[0], "ship it"]), (second, ["add a test"])):
            with self.subTest(thread=thread):
                meta, *said = (self.root / f".codex/sessions/rollout-{thread}.jsonl").read_text(
                    ).splitlines()
                self.assertEqual(json.loads(meta)["type"], "session_meta")
                self.assertEqual(json.loads(meta)["payload"]["thread_source"], "user")
                for word in words:
                    self.assertIn(json.dumps(word), "".join(said))
        # The TUI's first thread starts as it opens, and one /new opened at its next prompt; /resume
        # back to the first, which its server still holds, starts nothing (0.169).
        starts = [json.loads(line) for line in (self.root / "starts.jsonl").read_text().splitlines()]
        self.assertEqual([(start["session_id"], start["source"]) for start in starts],
                         [(first, "startup"), (second, "startup")])

        native = json.loads((self.root / ".codex/fake-server.json").read_text())["pid"]
        self.assertNotEqual(native, self.server.pid)
        self.server.kill()
        until(lambda: not running(native), "ended the native app server with its entry point")


if __name__ == "__main__":
    unittest.main()
