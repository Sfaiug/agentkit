"""Finding 4: durable required notifications, with fresh processes and mocked HTTP only."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from email.parser import BytesParser
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, orch, run, watch

URL = "http://127.0.0.1:9/hook/fixture-secret?thread_id=42"
PR = "https://example.invalid/other/repo/pull/7"


def child():
    """Every operation imports the toolkit anew against the same private fixture HOME."""
    args = json.load(sys.stdin)
    root = Path(os.environ["NOTIFICATION_FIXTURE"])
    assert config.HOME == root / ".agentkit"
    output, errors = io.StringIO(), io.StringIO()

    def http(req, **kwargs):
        assert req.full_url.startswith("http://127.0.0.1:9/"), req.full_url
        if req.get_method() == "POST":
            events = [json.loads(p.read_text()) for p in notify.outbox().glob("*.json")]
            assert any(e["status"] == "pending" and e["attempts"] > 0 for e in events)
        raw = req.data
        files = []
        if "multipart/form-data" in req.headers.get("Content-type", ""):
            mail = BytesParser().parsebytes(
                f"Content-Type: {req.headers['Content-type']}\r\n\r\n".encode() + raw)
            parts = mail.get_payload()
            raw = parts[0].get_payload(decode=True)
            files = [{"name": p.get_filename(), "data": base64.b64encode(
                p.get_payload(decode=True)).decode()} for p in parts[1:]]
        with (root / "http.jsonl").open("a") as fh:
            fh.write(json.dumps({"method": req.get_method(), "url": req.full_url,
                                 "payload": json.loads(raw), "files": files}) + "\n")
        if req.get_method() == "PATCH":
            return io.BytesIO(b'{}')
        outcome = args.get("http", "success")
        if outcome == "crash":
            os._exit(17)
        if outcome == "timeout":
            raise TimeoutError("do not log fixture-secret or the query string")
        if outcome == "network":
            raise urllib.error.URLError("fixture-secret")
        if isinstance(outcome, int):
            raise urllib.error.HTTPError(req.full_url, outcome, "fixture-secret",
                                         {"Retry-After": str(args.get("retry_after", 900))},
                                         io.BytesIO(json.dumps({"retry_after": args.get(
                                             "retry_after", 900)}).encode()))
        return io.BytesIO(b'{"id":"1234"}')

    with ExitStack() as stack, redirect_stdout(output), redirect_stderr(errors):
        stack.enter_context(patch.object(notify.time, "time", return_value=args.get("now", 10000)))
        stack.enter_context(patch.object(notify.urllib.request, "urlopen", side_effect=http))
        if not args.get("real_number"):
            stack.enter_context(patch.object(notify, "session_number", return_value=2))
        stack.enter_context(patch.object(orch, "sessions", return_value=[]))
        if args.get("persist_error"):
            stack.enter_context(patch.object(notify, "_write_event", side_effect=OSError("disk full")))
        if args.get("record_error"):
            stack.enter_context(patch.object(notify, "record", side_effect=OSError("disk full")))
        if args.get("result_error"):
            write = notify._write_event

            def fail_result(event):
                if event["status"] == "delivered":
                    raise OSError("disk full after POST")
                write(event)
            stack.enter_context(patch.object(notify, "_write_event", side_effect=fail_result))
        op = args.get("op", "send")
        result = 0
        if op == "send":
            result = notify.shaped(args.get("kind", "needs"), args.get("text", "Continue the job?"),
                                   session=args.get("session", "seat"), pr=args.get("pr"),
                                   paths=args.get("paths", []), event_id=args.get("event_id"),
                                   dry_run=args.get("dry", False))
        elif op == "retry":
            notify.retry_pending(dry_run=args.get("dry", False))
        elif op == "clear":
            notify.clear("seat")
        elif op in ("orphan", "recovery"):
            directory = config.RUNS / "job"
            directory.mkdir(parents=True, exist_ok=True)
            state = run.read_state(directory) or {
                "state": "pass", "title": "Finish task", "launched_session": "seat",
                "started_at": 9000, "finished_at": 9500, "reported": False}
            if op == "orphan":
                run.announce(state, directory, print)
            else:
                # persisted first, the way `reap` -- the one caller in the loop -- does:
                # `notify_recovery` writes what its own delivery decided and nothing else
                state.update(state="interrupted", interrupted_at=9600)
                run.save_state(directory, state)
                run.notify_recovery(directory, state)
        elif op == "stall":
            state = watch.load_state()
            pane = "API Error: 500"
            state["stalls"].setdefault("seat", {"since": 1, "pane": pane, "changed_at": 1,
                                               "stall_line": pane, "stall_at": 1})
            # The seat is mid-turn: its hook said a turn began and nothing has ended
            # it.  Without that fact the classifier reads this pane as idle, and an
            # idle seat is never asked -- which is rule 2, not this stall.
            config.ensure_dirs()
            config.hook_facts_path("seat").write_text(json.dumps(
                {"event": "UserPromptSubmit", "session": "seat", "at": 9990}))
            stack.enter_context(patch.object(orch, "sessions", return_value=[{"name": "seat"}]))
            stack.enter_context(patch.object(watch, "seat_model", return_value=("claude", "anthropic")))
            stack.enter_context(patch.object(watch, "pane_text", return_value=pane))
            stack.enter_context(patch.object(watch, "type_into", side_effect=AssertionError("tmux")))
            watch.health({}, state, args.get("dry", False), print)
            if not args.get("dry"):
                watch.save_state(state)
        elif op == "outgoing":
            state = watch.load_state()
            session = "seat" if args.get("seat") else None
            stack.enter_context(patch.object(watch, "own_prs", return_value={PR: session}))
            if session:
                stack.enter_context(patch.object(orch, "find", return_value={"name": session}))
            if args.get("typed"):
                stack.enter_context(patch.object(watch, "type_into", return_value=True))
            stack.enter_context(patch.object(watch, "gh_json", return_value=({
                "state": args.get("pr_state", "MERGED"), "reviewDecision": args.get("decision"),
                "title": "Fixture PR", "number": 7}, "")))
            watch.outgoing(state, "fixture", args.get("dry", False), print)
            if not args.get("dry"):
                watch.save_state(state)
        elif op == "watch":
            stack.enter_context(patch.object(watch, "health"))
            stack.enter_context(patch.object(run, "schedule_gc"))
            stack.enter_context(patch.object(watch, "gh_json", return_value=(None, "offline")))
            assert watch.main(["--dry-run"] if args.get("dry") else []) == 0
            assert "PR checks skipped" in output.getvalue()
        else:
            raise AssertionError(op)
    print(json.dumps({"result": result, "stdout": output.getvalue(), "stderr": errors.getvalue()}))


class RequiredNotifications(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".retry-notify-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "sockets").mkdir(mode=0o700)
        binaries = self.root / "bin"
        binaries.mkdir()
        adapters = self.root / "adapters"
        adapters.mkdir()
        for name in ("gh", "claude", "codex", "muse"):
            path = binaries / name
            path.write_text(f'#!{sys.executable}\nraise AssertionError("external call forbidden")\n')
            path.chmod(0o755)
        tmux = binaries / "tmux"
        tmux.write_text(f'#!{sys.executable}\nimport os, sys\n'
                        'assert sys.argv[1:3] == ["-L", "agentkit-test"]\n'
                        'assert os.environ["TMUX_TMPDIR"].startswith(os.environ["NOTIFICATION_FIXTURE"])\n'
                        'sys.exit(1)\n')
        tmux.chmod(0o755)
        for harness in ("claude", "codex", "muse"):
            adapter = adapters / f"{harness}.sh"
            adapter.write_text('#!/bin/sh\n[ "$1" = usage ] || exit 97\n'
                               'echo \'{"meters":[],"error":"offline fixture"}\'\n')
            adapter.chmod(0o755)
        self.env = {**os.environ, "HOME": str(self.root), "NOTIFICATION_FIXTURE": str(self.root),
                    "PATH": f"{binaries}:{os.environ['PATH']}", "AGENTKIT_DISCORD_WEBHOOK": URL,
                    "AGENTKIT_DISCORD_USER_ID": "42", "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
                    "AK_RUN_ROLE": "", "AK_RUN_LOG": "", "AGENTKIT_ADAPTER_DIR": str(adapters),
                    "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(self.root / "sockets"),
                    "TMUX": "", "PYTHONDONTWRITEBYTECODE": "1"}

    def call(self, *, env=None, exit_code=0, **args):
        # Every destination here is this fixture's own -- a private HOME, a webhook on a dead
        # local port, and urlopen patched besides -- so the suite's sink marker stays out of
        # the way: a queued event may only ever reach the destination it was queued for.
        env = {"AK_NOTIFY_SINK": "", **(env or {})}
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child"],
                                input=json.dumps(args), cwd=REPO, env={**self.env, **env},
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)
        return json.loads(result.stdout) if exit_code == 0 else None

    def events(self):
        return [json.loads(p.read_text()) for p in
                (self.root / ".agentkit/state/notification-outbox").glob("*.json")]

    def event(self):
        events = self.events()
        self.assertEqual(len(events), 1, events)
        return events[0]

    def posts(self):
        path = self.root / "http.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def state(self, path):
        return json.loads((self.root / ".agentkit" / path).read_text())

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes() if p.is_file() else None,
                                               p.stat().st_mtime_ns, p.stat().st_mode)
                for p in self.root.rglob("*")}

    def test_timeout_503_429_success_survive_restarts_and_obey_backoff(self):
        self.assertEqual(self.call(http="timeout")["result"], 0)
        first = self.event()
        self.assertEqual((first["status"], first["attempts"], first["next_attempt"]),
                         ("pending", 1, 10060))
        self.assertEqual(first["payload"]["embeds"][0]["title"], "Needs you · seat")
        self.assertNotIn("fields", first["payload"]["embeds"][0])
        for now in (10001, 10059):
            self.call(op="retry", now=now)
            self.call(now=now)
        self.assertEqual(len(self.posts()), 1)
        self.call(op="retry", now=10060, http=503)
        self.assertEqual((self.event()["attempts"], self.event()["next_attempt"]), (2, 10240))
        self.call(op="retry", now=10239)
        self.assertEqual(len(self.posts()), 2)
        self.call(op="retry", now=10240, http=429)
        self.assertEqual(self.event()["next_attempt"], 11140)
        self.call(op="retry", now=11139)
        self.assertEqual(len(self.posts()), 3)
        self.call(op="watch", now=11140)  # retry precedes even a failing GitHub login check
        event = self.event()
        self.assertEqual((event["status"], event["attempts"], event["id"]), ("delivered", 4, first["id"]))
        self.assertEqual(event["receipt"]["message_id"], "1234")
        self.assertEqual([p["payload"] for p in self.posts()], [first["payload"]] * 4)
        self.call(op="retry", now=50000)
        self.assertEqual(len(self.posts()), 4)

    def test_rate_limit_and_repeated_failures_have_bounded_delays(self):
        self.call(http=429, retry_after=999999)
        self.assertEqual(self.event()["next_attempt"], 13600)
        now = 13600
        for _ in range(8):
            self.call(op="retry", now=now, http=503)
            event = self.event()
            self.assertGreater(event["next_attempt"], now)
            self.assertLessEqual(event["next_attempt"] - now, notify.RETRY_BACKOFF[-1])
            now = event["next_attempt"]
        self.assertEqual(self.event()["status"], "pending")

    def test_success_and_disabled_are_acknowledged_without_future_posts(self):
        self.call(op="orphan")
        self.assertEqual(self.event()["status"], "delivered")
        self.assertTrue(self.state("runs/job/run.json")["reported"])
        self.call(op="orphan", now=50000)
        self.assertEqual(len(self.posts()), 1)
        for disabled in ("", "off"):
            with self.subTest(disabled=disabled):
                self.call(kind="done", session=f"disabled-{disabled}",
                          env={"AGENTKIT_DISCORD_WEBHOOK": disabled})
        self.assertEqual([e["status"] for e in self.events()].count("disabled"), 2)
        self.call(op="retry", now=50000)
        self.assertEqual(len(self.posts()), 1)

    def test_configuration_error_is_retained_and_resumes_after_fix(self):
        result = self.call(env={"AGENTKIT_DISCORD_WEBHOOK": "bad-secret-url"})
        self.assertEqual(result["result"], 1)
        self.assertNotIn("bad-secret-url", result["stderr"])
        before = self.event()
        self.assertEqual(before["status"], "blocked")
        # A second declaration records again, but the episode is already queued:
        # the command succeeds and the outbox still owns the one retry.
        self.assertEqual(self.call(env={"AGENTKIT_DISCORD_WEBHOOK": "bad-secret-url"})["result"], 0)
        self.call(op="retry", now=50000, env={"AGENTKIT_DISCORD_WEBHOOK": "bad-secret-url"})
        self.assertEqual(self.event()["attempts"], 1)
        self.assertEqual(self.posts(), [])
        self.call(op="retry", now=50001)
        self.assertEqual((self.event()["status"], self.event()["id"]), ("delivered", before["id"]))

    def test_missing_webhook_in_background_cannot_disable_a_queued_event(self):
        self.call(http="timeout")
        self.call(op="retry", now=10060, env={"AGENTKIT_DISCORD_WEBHOOK": ""})
        self.assertEqual(self.event()["status"], "blocked")
        self.assertEqual(len(self.posts()), 1)
        self.call(op="retry", now=10061)
        self.assertEqual(self.event()["status"], "delivered")

    def test_unreadable_webhook_is_not_mistaken_for_disabled(self):
        secret = self.root / ".agentkit/secrets/discord_webhook"
        secret.mkdir(parents=True)  # read_text raises, without relying on the effective uid
        result = self.call(env={"AGENTKIT_DISCORD_WEBHOOK": ""})
        self.assertEqual(result["result"], 1)
        self.assertEqual(self.event()["status"], "blocked")
        self.assertEqual(self.posts(), [])
        self.call(op="clear", env={"AGENTKIT_DISCORD_WEBHOOK": ""})
        self.assertTrue(self.state("state/notify-seat.json")["seen"])
        secret.rmdir()
        secret.write_text(URL)
        self.call(op="retry", env={"AGENTKIT_DISCORD_WEBHOOK": ""})
        self.assertEqual(self.event()["status"], "delivered")

    def test_permanent_http_error_does_not_latch_or_spin(self):
        self.call(op="orphan", http=403)
        self.assertFalse(self.state("runs/job/run.json")["reported"])
        self.assertTrue(self.state("runs/job/run.json")["notification_pending"])
        self.assertEqual(self.event()["status"], "blocked")
        self.call(op="watch", now=50000)
        self.assertEqual(len(self.posts()), 1)
        self.call(op="watch", now=50001, env={"AGENTKIT_DISCORD_WEBHOOK": URL + "&fixed=1"})
        self.assertTrue(self.state("runs/job/run.json")["reported"])
        self.assertNotIn("notification_pending", self.state("runs/job/run.json"))
        self.assertEqual(self.event()["status"], "delivered")

    def test_declaration_metadata_is_durable_and_attachments_are_refused(self):
        attachment = self.root / "result.bin"
        attachment.write_bytes(bytes(range(256)) + b"\x00\xffdeliverable")
        self.call(kind="done", text="Whole job shipped", paths=[str(attachment)],
                  exit_code=1)
        self.assertEqual((self.events(), self.posts()), ([], []))
        self.assertFalse((self.root / ".agentkit/state/notify-seat.json").exists())
        self.call(kind="done", text="Whole job shipped", pr=PR,
                  http="network", event_id="whole-job:123")
        first = self.event()
        self.call(op="retry", now=10060)
        event = self.event()
        self.assertEqual((event["status"], event["session"], event["kind"], event["pr"]),
                         ("delivered", "seat", "done", PR))
        self.assertEqual(event["files"], [])
        self.assertEqual(first["payload"], self.posts()[1]["payload"])
        self.assertTrue(event["source"].startswith("card:"))
        for path in (self.root / ".agentkit/state").rglob("*.json"):
            self.assertNotIn("fixture-secret", path.read_text())
        path = next((self.root / ".agentkit/state/notification-outbox").glob("*.json"))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_concurrent_callers_and_retry_ticks_share_one_event(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.call(http="timeout"), range(6)))
        self.assertTrue(all(r["result"] == 0 for r in results))
        first = self.event()
        self.assertEqual((first["attempts"], len(self.posts())), (1, 1))
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda _: self.call(op="retry", now=10060), range(6)))
        self.assertEqual((self.event()["id"], self.event()["status"], len(self.posts())),
                         (first["id"], "delivered", 2))

    def test_no_latches_before_persistence_and_watcher_recovers_orphan(self):
        for op in ("orphan", "recovery", "stall"):
            with self.subTest(op=op):
                self.call(op=op, persist_error=True)
                self.assertEqual(self.events(), [])
                self.assertEqual(self.posts(), [])
                if op in ("orphan", "recovery"):
                    self.assertFalse(self.state("runs/job/run.json").get("reported"))
                    self.assertFalse(self.state("runs/job/run.json").get("recovery_notified"))
                else:
                    st = self.state("state/watch.json")
                    self.assertFalse(st["stalls"].get("seat", {}).get("told"))
        self.call(op="watch", http="timeout")
        self.assertEqual(self.event()["status"], "pending")
        self.assertEqual(self.state("runs/job/run.json")["recovery_notified"], "needs")

    def test_stall_latches_on_the_record_and_outgoing_queues_nothing(self):
        self.call(op="stall", http="timeout")
        self.assertTrue(self.state("state/watch.json")["stalls"]["seat"]["told"])
        self.assertEqual(self.state("state/notify-seat.json")["kind"], "needs")
        # The seat is mid-turn, so the word is working: the question is asked and
        # latched, but no card is queued until the word turns.
        self.assertEqual((self.events(), self.posts()), ([], []))
        # A PR of ours moving is not a notification at all: nothing is queued and nothing
        # is posted, and the decision is simply recorded as followed.
        self.call(op="outgoing", http=503)
        self.assertTrue(self.state("state/watch.json")["own"][PR]["done"])
        self.assertEqual(len(self.events()), 0)
        self.call(op="retry", now=10060)
        self.assertEqual(self.posts(), [])

    def test_changes_requested_is_not_acknowledged_until_its_seat_has_it(self):
        self.call(op="outgoing", pr_state="OPEN", decision="CHANGES_REQUESTED", seat=True)
        self.assertIsNone(self.state("state/watch.json")["own"][PR]["decision"])
        self.call(op="outgoing", pr_state="OPEN", decision="CHANGES_REQUESTED", seat=True,
                  typed=True)
        self.assertEqual(self.state("state/watch.json")["own"][PR]["decision"], "CHANGES_REQUESTED")
        self.assertEqual((self.events(), self.posts()), ([], []))

    def test_crash_during_first_post_keeps_record_id_and_retry_deadline(self):
        self.call(http="crash", exit_code=17)
        first = self.event()
        # The question is recorded before the card is attempted, so the crash
        # loses only the delivery, which the retry still owns.
        self.assertEqual(self.state("state/notify-seat.json")["text"], "Continue the job?")
        self.call(now=10001)
        self.assertEqual((len(self.posts()), self.event()["id"]), (1, first["id"]))
        self.call(op="retry", now=10060)
        self.assertEqual((self.event()["status"], len(self.posts())), ("delivered", 2))

    def test_failed_receipt_save_leaves_retryable_event(self):
        self.assertEqual(self.call(result_error=True)["result"], 1)
        first = self.event()
        self.assertEqual(first["status"], "pending")
        self.assertEqual(self.state("state/notify-seat.json")["text"], "Continue the job?")
        self.call(now=10001)
        self.call(op="retry", now=10060)
        self.assertEqual((self.event()["id"], self.event()["status"]), (first["id"], "delivered"))

    def test_watcher_recovers_a_crash_before_local_record_without_claiming_an_answer(self):
        self.call(http="crash", exit_code=17)
        self.call(op="retry", now=10060)
        self.assertEqual(self.event()["status"], "delivered")
        self.assertEqual([p["method"] for p in self.posts()], ["POST", "POST"])
        self.assertEqual(self.state("state/notify-seat.json")["message_id"], "1234")

    def test_local_acknowledgment_does_not_consume_external_delivery(self):
        self.call(http="timeout")
        self.call(op="clear")
        before = self.state("state/notify-seat.json")
        self.assertTrue(before["seen"])
        self.call(op="retry", now=10060)
        self.assertEqual(self.state("state/notify-seat.json"), before)
        self.assertEqual(self.event()["status"], "delivered")
        self.assertEqual([p["method"] for p in self.posts()], ["POST", "POST", "PATCH"])
        self.assertEqual(self.posts()[-1]["payload"]["content"], "")

    def test_dry_runs_do_not_create_or_change_state_or_post(self):
        before = self.snapshot()
        self.call(dry=True)
        self.call(op="retry", dry=True)
        self.call(op="watch", dry=True)
        self.assertEqual(self.snapshot(), before)
        self.call(http="timeout")
        before = self.snapshot()
        self.call(kind="done", dry=True)
        self.call(op="retry", dry=True, now=50000)
        self.call(op="watch", dry=True, now=50000)
        self.call(op="outgoing", dry=True)
        self.call(dry=True, env={"AK_RUN_ROLE": "worker", "AK_RUN_LOG": str(self.root / "log")})
        self.assertEqual(self.snapshot(), before)

    def test_dry_run_number_lookup_does_not_reconcile_session_records(self):
        record = self.root / ".agentkit/state/session-seat.json"
        record.parent.mkdir(parents=True)
        model = next(name for name, entry in config.load()["models"].items()
                     if entry["harness"] == "codex")
        record.write_text(json.dumps({"orchestrator": model, "conversation": "unverified",
                                      "resumable": True}))
        before = self.snapshot()
        result = self.call(dry=True, real_number=True)
        self.assertEqual(json.loads(result["stdout"])["embeds"][0]["title"], "Needs you · seat")
        self.assertNotIn("fields", json.loads(result["stdout"])["embeds"][0])
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    if sys.argv[1:] == ["--child"]:
        child()
    else:
        unittest.main(verbosity=2)
