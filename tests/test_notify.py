"""Notification enforcement against a local webhook; stdlib, no credentials or model calls."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, notify, orch, run, watch


class Notifications(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".notify-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        home = self.root / ".agentkit"
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name,
                                                  home if name == "HOME" else home / name.lower()))
        self.stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        config.ensure_dirs()
        self.requests = []
        self.edit_status = 200
        owner = self

        class Hook(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                if "multipart/form-data" in self.headers.get("Content-Type", ""):
                    mail = BytesParser().parsebytes(
                        f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode() + raw)
                    raw = mail.get_payload()[0].get_payload(decode=True)
                data = json.loads(raw) if raw else None
                owner.requests.append((self.command, self.path, data))
                status = owner.edit_status if self.command == "PATCH" else 200
                if status == 0:
                    self.wfile.write(b"not an HTTP response\r\n\r\n")
                    return
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"id": str(len(owner.requests))}).encode())

            do_GET = do_POST = do_PATCH = handle_request

        server = ThreadingHTTPServer(("127.0.0.1", 0), Hook)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.url = f"http://127.0.0.1:{server.server_port}/hook?thread_id=42&wait=false"
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_DISCORD_WEBHOOK": self.url,
            notify.SINK_ENV: self.url,
            "AGENTKIT_DISCORD_USER_ID": "123456789012345678", "AK_RUN_ROLE": "",
            "AK_RUN_LOG": "", config.RUN_DIR_ENV: "", config.SESSION_ENV: "seat",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(self.root),
        }))
        binaries = self.root / "bin"
        binaries.mkdir()
        tmux = binaries / "tmux"
        tmux.write_text(f'#!{sys.executable}\nimport sys\n'
                        'assert sys.argv[1:3] == ["-L", "agentkit-test"]\nsys.exit(1)\n')
        tmux.chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {"PATH": f"{binaries}:{os.environ['PATH']}"}))
        self.stack.enter_context(patch.object(notify, "session_number", return_value=1))

    def cli(self, *args, env=None):
        result = subprocess.run([sys.executable, str(REPO / "bin/ak"), "notify", *args],
                                env={**os.environ, **(env or {})}, cwd=REPO,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def open_and_progress(self):
        """Open the seat, then produce the fresh output that answers what it was asked."""
        with patch.object(orch, "find", return_value={"name": "seat"}), \
                patch.object(orch, "inside", return_value=True), \
                patch.object(orch, "tmux_out", return_value=(0, "")), \
                patch.object(watch, "pane_text", return_value="Waiting for a decision"), \
                patch("sys.stdin.isatty", return_value=True), \
                patch("sys.stdout.isatty", return_value=True):
            menu.open_session(config.load(), {"name": "seat"}, False)
        notify.progress("seat", lambda: "Fresh output after the answer")

    def test_lifecycle_and_approved_payload(self):
        self.cli("needs", "Merge PR #7? yes/no")
        self.assertEqual(self.requests[0][0:2], ("POST", "/hook?thread_id=42&wait=true"))
        payload = self.requests[0][2]
        self.assertEqual(payload["content"], "<@123456789012345678>")
        self.assertEqual(payload["embeds"][0]["title"], "Needs you · seat")
        self.assertEqual(payload["embeds"][0]["color"], 0xF5A623)
        before = config.notify_path("seat").read_bytes()
        result = self.cli("needs", "  MERGE\nPR   #7? YES/NO ")
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(self.requests), 1)   # same episode: recorded again, posted once
        self.assertEqual(notify.last("seat")["open_needs"][0]["message_id"], "1")
        self.assertNotIn(self.url, before.decode())

        self.cli("needs", "Which branch?")
        self.assertEqual(len(self.requests), 1)   # one card per episode, whatever it asks
        self.assertEqual(menu.state({"name": "seat"}), "needs you")
        # The menu's actual attach path calls seen_by_user after a successful client switch;
        # the question is answered by the output that follows it, not by the open.
        self.open_and_progress()
        # The question is answered, so the row is back to a seat at its prompt: his again,
        # with nothing to say about it.
        self.assertEqual(menu.state({"name": "seat"}), "needs you")
        self.assertIsNone(notify.last("seat"))
        self.assertEqual([r[1] for r in self.requests[1:]],
                         ["/hook/messages/1?thread_id=42"])
        for method, _, payload in self.requests[1:]:
            self.assertEqual(method, "PATCH")
            self.assertEqual(payload["embeds"][0]["title"], "Answered · seat")
            self.assertEqual(payload["content"], "")
            self.assertEqual(payload["allowed_mentions"], {"parse": []})
            self.assertNotIn("fields", payload["embeds"][0])

        self.cli("needs", "Which branch?")   # the word never left: still the same episode
        self.assertEqual(len(self.requests), 2)
        self.cli("done", "Shipped", "--pr", "https://github.com/me/repo/pull/7")
        self.assertEqual([r[0] for r in self.requests[-2:]], ["PATCH", "POST"])
        self.assertEqual(self.requests[-2][2]["embeds"][0]["title"], "Done · seat")
        payload = self.requests[-1][2]
        self.assertEqual(payload["content"], "<@123456789012345678>")
        self.assertEqual(payload["username"], "agentkit")
        self.assertEqual(payload["embeds"][0]["title"], "Done · seat")
        self.assertEqual(payload["embeds"][0]["color"], 0x2ECC71)
        self.assertNotIn("fields", payload["embeds"][0])   # the card is two words and the seat
        self.assertNotIn("description", payload["embeds"][0])
        self.assertEqual(notify.last("seat")["text"], "Shipped")   # the words stay on the record
        self.assertEqual(menu.state({"name": "seat"}), "done")
        count = len(self.requests)
        self.cli("done", "Another job, another summary")     # same word: the episode stands
        self.assertEqual(len(self.requests), count)
        self.open_and_progress()
        # a done is no question: opening and reading it leave it, and its episode, standing
        self.assertEqual(menu.state({"name": "seat"}), "done")
        self.cli("done", "Another job, another summary")
        self.assertEqual(len(self.requests), count)
        self.cli("needs", "One more decision?")
        self.cli("done", "Second job finished")
        self.assertEqual(len(self.requests), count + 3)

    def test_worker_guard_and_check_exception(self):
        log = self.root / "log.txt"
        env = {"AK_RUN_ROLE": "worker", "AK_RUN_LOG": str(log)}
        for args in (("needs", "Please answer"), ("done", "Finished"),
                     ("needs", "Preview", "--dry-run")):
            result = self.cli(*args, env=env)
            self.assertIn("AK_RUN_ROLE=worker", result.stdout)
            self.assertEqual(len(result.stdout.splitlines()), 1)
            self.assertEqual(result.stderr, "")
        self.assertEqual(len(log.read_text().splitlines()), 2)  # dry-run does not append to the log
        self.assertFalse(config.notify_path("seat").exists())
        self.assertEqual(self.requests, [])
        self.assertIn("ok (200)", self.cli("--check", env=env).stdout)
        self.assertEqual(self.requests, [("GET", "/hook?thread_id=42&wait=false", None)])

    def test_each_run_role_and_descendants_are_marked_but_fallback_is_not(self):
        adapter = self.root / "adapter"
        adapter.write_text(f'''#!{sys.executable}
import json, os, pathlib, subprocess, sys
out = pathlib.Path(sys.argv[6])
(out / "env.json").write_text(json.dumps({{k: os.environ[k] for k in
    ("AK_RUN_ROLE", "AK_RUN_LOG", "AGENTKIT_RUN_DIR") if k in os.environ}}))
p = subprocess.run([sys.executable, {str(REPO / 'bin/ak')!r}, "notify", "needs", "Worker asks"],
                   capture_output=True, text=True)
(out / "attempt.txt").write_text(p.stdout + p.stderr)
if out.name == "executor":
    (out / "final.md").write_text("API Error: 500")
    sys.exit(1)
(out / "final.md").write_text("VERDICT: PASS")
sys.exit(p.returncode)
''')
        adapter.chmod(0o755)
        cfg = config.load()
        model = cfg["defaults"]["workers"][0]
        run_dir = self.root / "run"
        roles = ("executor", "reviewer", "fixer", "reviewer-pr", "executor-scratch",
                 "reviewer-scratch", "fixer-scratch")
        # run's own clock, not the time module: subprocess polls a closing child with the same
        # time.sleep, as often as the host's load makes it, and only the backoff is counted here
        sleep = Mock()
        with patch.object(config, "adapter", return_value=adapter), \
                patch.object(run, "time", SimpleNamespace(**{**vars(time), "sleep": sleep})):
            for role in roles:
                out = run_dir / "round-1" / role
                code, _, _, dead = run.call_retrying(cfg, model, "task", self.root, out,
                                                     role, None, lambda _: None)
                self.assertEqual((code, dead), (0, False))
                env = json.loads((out / "env.json").read_text())
                self.assertEqual(env["AK_RUN_ROLE"], "worker")
                self.assertNotIn(config.RUN_DIR_ENV, env)
                self.assertIn("suppressed", (out / "attempt.txt").read_text())
        sleep.assert_called_once_with(run.TRANSIENT_BACKOFF[0])
        self.assertEqual(len((run_dir / "log.txt").read_text().splitlines()), len(roles) + 1)
        self.assertEqual(self.requests, [])
        self.assertNotEqual(os.environ.get("AK_RUN_ROLE"), "worker")
        state = {"launched_session": "seat", "state": "pass", "title": "The task"}
        with patch.object(orch, "watching", return_value=False):
            run.announce(state, run_dir, lambda _: None)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0][2]["embeds"][0]["title"], "Needs you · seat")
        self.assertTrue(state["reported"])

    def test_episodes_are_scoped_to_the_session(self):
        self.cli("needs", "Straße?")
        self.cli("needs", "STRASSE?")              # same word: recorded again, posted once
        self.assertEqual(len(self.requests), 1)
        self.cli("needs", "STRASSE?", "--session", "other")
        self.assertEqual(len(self.requests), 2)    # another seat is another episode
        self.cli("done", "Finished")
        count = len(self.requests)
        # Old records without a timestamp can still be displayed and replaced safely.
        config.notify_path("seat").write_text('{"kind":"needs","text":"Legacy"}')
        self.cli("needs", "Legacy")
        self.assertEqual(len(self.requests), count + 1)

    def test_concurrent_cli_repeats_post_once(self):
        for kind in ("needs", "done"):
            with ThreadPoolExecutor(max_workers=5) as pool:
                list(pool.map(lambda _: self.cli(kind, "Same message"), range(5)))
        self.assertEqual([r[0] for r in self.requests], ["POST", "PATCH", "POST"])

    def test_edit_failures_are_silent_and_do_not_block_completion(self):
        for status in (404, 500, 0):
            self.cli("needs", f"Question {status}?")
            self.edit_status = status
            result = self.cli("done", f"Finished anyway after {status}")   # a job apiece
            self.assertEqual((result.stdout, result.stderr), ("", ""))
            self.assertEqual([r[0] for r in self.requests[-2:]], ["PATCH", "POST"])
            self.assertEqual(notify.last("seat")["open_needs"], [])
        self.cli("needs", "A changed webhook?")
        count = len(self.requests)
        changed = self.url.replace("/hook", "/new")
        with patch.dict(os.environ, {"AGENTKIT_DISCORD_WEBHOOK": changed,
                                     notify.SINK_ENV: changed}), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            self.open_and_progress()
        self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))
        self.assertEqual(len(self.requests), count)
        self.assertIsNone(notify.last("seat"))

    def test_dry_run_does_not_record_or_close_questions(self):
        self.cli("needs", "Waiting?")
        before = config.notify_path("seat").read_bytes()
        payload = json.loads(self.cli("done", "FAIL: tests", "--dry-run").stdout)
        self.assertEqual(payload["embeds"][0]["color"], 0xE74C3C)
        self.assertEqual(config.notify_path("seat").read_bytes(), before)
        self.assertEqual(len(self.requests), 1)

    def test_freeform_and_file_arguments_are_removed(self):
        with self.assertRaises(config.Error):
            notify.main(["plain message"])
        with self.assertRaises(config.Error):
            notify.main(["needs", "Q", "--file", "report.txt"])


if __name__ == "__main__":
    unittest.main()
