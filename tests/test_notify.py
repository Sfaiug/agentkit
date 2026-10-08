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
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-notify-", dir=REPO)
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

    def cli(self, *args, env=None):
        result = subprocess.run([sys.executable, str(REPO / "bin/ak"), "notify", *args],
                                env={**os.environ, **(env or {})}, cwd=REPO,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def open_and_progress(self, between=lambda: None):
        """Open the seat, then produce the fresh output that answers what it was asked;
        `between` runs after the open and before that output."""
        with patch.object(orch, "find", return_value={"name": "seat"}), \
                patch.object(orch, "inside", return_value=True), \
                patch.object(orch, "tmux_out", return_value=(0, "")), \
                patch.object(watch, "pane_text", return_value="Waiting for a decision"), \
                patch("sys.stdin.isatty", return_value=True), \
                patch("sys.stdout.isatty", return_value=True):
            menu.open_session(config.load(), {"name": "seat"}, False)
        between()
        notify.progress("seat", lambda: "Fresh output after the answer", None)

    def interleaved_declarations(self, kind, text, newer):
        """A newer declaration reaches publication while the older answer waits."""
        old_ready, new_ready, old_finished = (threading.Event() for _ in range(3))
        transition = notify.transition

        def interleave(*args, **kwargs):
            if threading.current_thread().name.startswith("old-decision"):
                old_ready.set()
                if not new_ready.wait(10):
                    raise RuntimeError("new declaration did not reach publication")
                try:
                    return transition(*args, **kwargs)
                finally:
                    old_finished.set()
            new_ready.set()
            if not old_finished.wait(10):
                raise RuntimeError("old publication did not finish")
            return transition(*args, **kwargs)

        with patch.object(notify, "transition", side_effect=interleave), \
                patch.object(notify, "terminal_notice"):
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="old-decision") as pool:
                old = pool.submit(notify.shaped, kind, text, session="seat")
                try:
                    self.assertTrue(old_ready.wait(10))
                    newer()
                    self.assertEqual(old.result(10), 0)
                finally:
                    new_ready.set()

    def cards(self, kind):
        return [payload for method, _, payload in self.requests
                if method == "POST" and payload["embeds"][0]["title"]
                == f"{notify.TITLES[kind]} · seat"]

    def test_quiet_answers_do_not_write_notification_state(self):
        for previous in ("empty", "pending", "question", "retired", "sent"):
            with self.subTest(previous=previous):
                self.setUp()
                if previous != "empty":
                    notify.record("seat", "needs" if previous == "question" else "done",
                                  "Which export?" if previous == "question" else "Export shipped",
                                  runs=["acme-run"], seen=previous == "retired",
                                  completion={"created": 1, "outcomes": [["Export shipped"]]})
                    notify._card_write("seat", {"word": "done", "since": 1, "began": 1,
                                               "episode": "ordinary", "sent": previous == "sent"})
                paths = (config.notify_path("seat"), config.card_path("seat"))
                before = [path.read_bytes() if path.exists() else None for path in paths]
                events = list(notify.outbox().glob("*.json"))
                self.cli("done", "Explained the schema", "--quiet")
                self.assertEqual([path.read_bytes() if path.exists() else None for path in paths],
                                 before)
                self.assertEqual(list(notify.outbox().glob("*.json")), events)
                self.assertEqual(self.requests, [])
                self.assertEqual(watch.seat_read("seat")["quiet_done"]["text"],
                                 "Explained the schema")

    def test_quiet_answers_preserve_a_job_completion_waiting_for_its_run(self):
        pending = config.RUNS / "acme-run"
        pending.mkdir()
        state = {"run_id": pending.name, "state": "running", "launched_session": "seat",
                 "started_at": time.time(), "pid": 0}
        (pending / "run.json").write_text(json.dumps(state))
        self.cli("done", "Export shipped")
        original = config.notify_path("seat").read_bytes()
        self.cli("done", "Explained why it waits", "--quiet")
        self.assertEqual(config.notify_path("seat").read_bytes(), original)
        self.assertEqual(self.cards("done"), [])
        state.update(state="pass", verdict="PASS", reported=True, finished_at=time.time())
        (pending / "run.json").write_text(json.dumps(state))
        self.assertEqual(notify.transition("seat"), 0)
        self.assertEqual(len(self.cards("done")), 1)
        self.assertEqual(notify.last("seat")["text"], "Export shipped")

    def test_quiet_answer_keeps_answered_question_edits_without_a_job_card(self):
        self.cli("needs", "Which export format?")
        notify.answered("seat", time.time() + 1)
        self.edit_status = 503
        self.cli("done", "Explained the format", "--quiet")
        self.assertEqual(notify.transition("seat"), 0)
        self.assertTrue(notify._card_read("seat")["open_needs"])
        self.edit_status = 200
        self.assertEqual(notify.transition("seat"), 0)
        self.assertEqual(notify._card_read("seat")["open_needs"], [])
        self.assertEqual(notify._card_read("seat")["closed"], "Answered")
        self.assertEqual(self.cards("done"), [])

    def test_quiet_dry_runs_and_workers_change_no_state(self):
        self.cli("done", "Explained the schema", "--quiet", "--dry-run")
        self.cli("done", "Explained the schema", "--quiet", env={"AK_RUN_ROLE": "worker"})
        self.assertEqual(watch.seat_read("seat"), {})
        self.assertIsNone(notify.last("seat", include_seen=True))
        self.assertFalse(config.card_path("seat").exists())
        self.assertEqual(list(notify.outbox().glob("*.json")), [])
        self.assertEqual(self.requests, [])

    def test_a_cached_done_cannot_announce_a_running_job(self):
        self.assertEqual(notify.shaped("needs", "Which API route?", session="seat"), 0)
        pending = config.RUNS / "acme-run"
        state = {"run_id": pending.name, "state": "running", "launched_session": "seat",
                 "started_at": time.time(), "pid": 0}

        def newer():
            pending.mkdir()
            (pending / "run.json").write_text(json.dumps(state))
            self.assertEqual(notify.shaped("done", "Export ready pending its run",
                                           session="seat"), 0)

        self.interleaved_declarations("done", "Old API handback", newer)
        self.assertEqual(len(self.cards("done")), 0)
        state.update(state="pass", verdict="PASS", reported=True, finished_at=time.time())
        (pending / "run.json").write_text(json.dumps(state))
        self.assertEqual(notify.transition("seat"), 0)
        self.assertEqual(len(self.cards("done")), 1)

    def test_a_cached_done_cannot_replace_a_new_question(self):
        self.interleaved_declarations("done", "Old API handback", lambda:
            self.assertEqual(notify.shaped("needs", "Which export format?", session="seat"), 0))
        self.assertEqual(len(self.cards("done")), 0)
        self.assertEqual(len(self.cards("needs")), 1)
        self.assertEqual(notify.last("seat")["text"], "Which export format?")

    def test_input_before_a_new_question_does_not_suppress_it(self):
        for kind in ("done", "needs"):
            with self.subTest(older=kind):
                config.card_path("seat").unlink(missing_ok=True)
                config.notify_path("seat").unlink(missing_ok=True)
                self.requests.clear()
                watch.seat_write("seat", word="working", word_since=100.0)
                clock = [200.0]

                def tmux(*args, **kwargs):
                    return (0, "seat\t250") if args[:1] == ("list-clients",) else (1, "")

                def newer():
                    clock[0] = 300.0
                    self.assertEqual(notify.shaped("needs", "Which export format?",
                                                   session="seat"), 0)

                with patch.object(notify.time, "time", side_effect=lambda: clock[0]), \
                        patch.object(notify, "installed_at", return_value=250.0), \
                        patch.object(orch, "tmux_out", side_effect=tmux):
                    self.interleaved_declarations(kind, "Which export format?", newer)
                self.assertEqual(len(self.cards("needs")), 1)
                self.assertEqual(notify.last("seat")["time"], 300.0)

    def test_a_cached_question_cannot_page_for_completed_work(self):
        self.interleaved_declarations("needs", "Which API route?", lambda:
            self.assertEqual(notify.shaped("done", "API shipped", session="seat"), 0))
        self.assertEqual(len(self.cards("needs")), 0)
        self.assertEqual(len(self.cards("done")), 1)
        self.assertEqual(notify.last("seat")["text"], "API shipped")

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

    def typed(self, source, into="claude"):
        """ak's typing receipt for a line it typed into the seat, as watch writes it."""
        with config.seat_file("input", "seat").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": time.time(), "text": "run 20260101-0900-parser finished",
                                 "source": source, "harness": into}) + "\n")

    def test_output_after_a_line_ak_typed_since_the_open_answers_nothing(self):
        """A hand-back, a told line or an idle `/compact` starts a turn of the seat's own: its
        output after the open is no answer, and only the owner's own prompt then is."""
        self.cli("needs", "Merge PR #7? yes/no")
        self.open_and_progress(between=lambda: self.typed("ak"))
        self.assertEqual(notify.last("seat")["text"], "Merge PR #7? yes/no")
        self.assertEqual(menu.state({"name": "seat"}), "needs you")
        notify.answered("seat", time.time())
        self.assertIsNone(notify.last("seat"))

    def test_output_after_the_owners_relayed_words_or_lines_from_before_the_open_answers(self):
        """review 20261006-1740: a seat with no hooks gets an idle `/compact` while its question
        waits; the owner opens it later and answers, and that output is the only answer there."""
        self.cli("needs", "Merge PR #7? yes/no")
        self.typed("ak")                           # before the open: history
        self.open_and_progress(between=lambda: self.typed("owner"))   # relayed unchanged
        self.assertIsNone(notify.last("seat"))

    def test_output_after_a_line_typed_where_no_prompt_hook_reports_still_answers(self):
        """review 20261006-1740 round 2: Muse runs no hooks, so nothing reports the owner's
        prompt; an idle `/compact` typed after the open leaves the output as its only answer."""
        self.assertIsNone(notify.harness.load("muse").prompt_hook)
        self.cli("needs", "Merge PR #7? yes/no")
        self.open_and_progress(between=lambda: self.typed("ak", into="muse"))
        self.assertIsNone(notify.last("seat"))

    def test_episodes_are_scoped_to_the_session(self):
        self.cli("needs", "Straße?")
        self.cli("needs", "STRASSE?")              # same word: recorded again, posted once
        self.assertEqual(len(self.requests), 1)
        self.cli("needs", "STRASSE?", "--session", "other")
        self.assertEqual(len(self.requests), 2)    # another seat is another episode
        self.cli("done", "Finished")
        count = len(self.requests)
        # Old records without a timestamp can still be displayed and replaced safely.
        config.notify_path("seat").write_text('{"kind":"needs","text":"Legacy?"}')
        self.cli("needs", "Legacy?")
        self.assertEqual(len(self.requests), count + 1)

    def test_concurrent_cli_repeats_post_once(self):
        for kind in ("needs", "done"):
            with ThreadPoolExecutor(max_workers=5) as pool:
                list(pool.map(lambda _: self.cli(kind, "Same message?"), range(5)))
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
