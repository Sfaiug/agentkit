"""v5d: Discord hears only an orchestrator needing the owner, and a job that is done.

Offline: every send is a patched urlopen, every seat state is a fake, every pane write is a
patched tmux call.  Nothing here touches a real webhook, a real tmux server or the network.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, notify, orch, run, watch

PR = "https://github.com/other/theirs/pull/7"
SHA = "b" * 40
WEBHOOK = "https://discord.invalid/api/webhooks/owner/secret?thread_id=42"
SINK = "https://sink.invalid/api/webhooks/suite/token"
TASK = """---
repo: /nowhere
base: main
---
# Fix the parser

## Goal
Nothing: this run is a fixture.

## Done when
```bash
true
```
"""


class Rule(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5d-", dir=REPO)
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
        self.diversions = self.root / "notify-diversions.log"
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_DISCORD_WEBHOOK": WEBHOOK,
            "AGENTKIT_DISCORD_USER_ID": "42", "AK_RUN_ROLE": "", "AK_RUN_LOG": "",
            notify.SINK_ENV: "", config.RUN_DIR_ENV: "", config.SESSION_ENV: "seat",
            notify.SINK_LOG_ENV: str(self.diversions),
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(self.root / "sockets")}))
        (self.root / "sockets").mkdir(mode=0o700)
        self.requests = []          # (url, payload) of every HTTP request that was attempted
        self.tmux = []              # every tmux command the watcher ran
        self.log = []
        self.stack.enter_context(patch.object(notify.urllib.request, "urlopen",
                                              side_effect=self.urlopen))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux_out))
        self.stack.enter_context(patch.object(notify, "session_number", return_value=1))
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[]))
        self.out = self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.err = self.stack.enter_context(redirect_stderr(io.StringIO()))

    # --- the fixtures the rule is measured against --------------------------

    def urlopen(self, req, **kwargs):
        self.requests.append((req.full_url, json.loads(req.data) if req.data else None))
        return io.BytesIO(b'{"id":"1234"}')

    def tmux_out(self, *args, **kwargs):
        self.tmux.append(list(args))
        return 0, ""

    @property
    def posts(self):
        """Every Discord card that was actually sent, whatever webhook it went to."""
        return [payload for url, payload in self.requests if payload and "embeds" in payload]

    def typed(self):
        """The literal lines the watcher typed into a seat."""
        return [args[-1] for args in self.tmux if args[:2] == ["send-keys", "-t"] and "-l" in args]

    def seat(self, name="seat"):
        return {"name": name, "legacy": False}

    def stall_tick(self, word, pane="API Error: 500", auth=None, dry_run=False):
        """One watch tick over a seat that has been showing the same error for an hour."""
        now = time.time()
        state = watch.load_state()
        state["stalls"]["seat"] = {"since": now - watch.GIVE_UP - 1, "pane": pane,
                                   "changed_at": now - watch.GIVE_UP - 1, "stall_line": pane,
                                   "stall_at": now - watch.GIVE_UP - 1}
        with patch.object(orch, "sessions", return_value=[self.seat()]), \
                patch.object(watch, "seat_model", return_value=("claude", "anthropic")), \
                patch.object(watch, "pane_text", return_value=pane), \
                patch.object(watch, "live_state", return_value={"state": word}), \
                patch.object(watch, "seat_read", return_value={"state": word}), \
                patch.object(watch, "auth_expired_on", return_value=auth), \
                patch.object(watch, "type_into", side_effect=AssertionError("typed into a seat")):
            watch.health(config.load(), state, dry_run, self.log.append)
        return state

    def decision(self, pr_state, decision=None, session="seat", seat=None):
        """One watch tick over one of our own PRs the maintainer has decided about."""
        state = {"reviewed": {}, "own": {}}
        view = {"state": pr_state, "reviewDecision": decision, "title": "Fix the parser",
                "number": 7}
        with patch.object(watch, "own_prs", return_value={PR: session}), \
                patch.object(watch, "gh_json", return_value=(view, "")), \
                patch.object(orch, "find", return_value=seat):
            watch.outgoing(state, "me", False, self.log.append)
        return state

    def finished_run(self, name="20260915-0001-fix-the-parser", worktree=True):
        """A run that opened a PR from a fork and is waiting for the maintainer."""
        run_dir = config.RUNS / name
        run_dir.mkdir(parents=True)
        (run_dir / "task.md").write_text(TASK)
        wt = self.root / "wt" / name
        if worktree:
            wt.mkdir(parents=True)
        state = {"run_id": run_dir.name, "title": "Fix the parser", "state": "pass",
                 "verdict": "PASS", "rounds": 1, "round_summaries": [], "findings": "",
                 "branch": "ak/fix-the-parser", "base_sha": "a" * 40, "pr": PR, "foreign": True,
                 "merged": False, "merge_note": "waiting for the maintainer",
                 "worktree": str(wt), "executor": "opus", "reviewer": "astra",
                 "launched_session": "seat"}
        run.save_state(run_dir, state)
        run.write_result(run_dir, state, ["true"])
        return run_dir

    # --- (a) our own PRs ----------------------------------------------------

    def test_v5d_pr_lifecycle_never_reaches_discord_and_lands_in_a_live_seat(self):
        for pr_state, decision, expected in (
                ("MERGED", None, "merged by the maintainer"),
                ("CLOSED", None, "closed by the maintainer without a merge"),
                ("OPEN", "CHANGES_REQUESTED", "the maintainer requested changes")):
            with self.subTest(pr_state=pr_state):
                self.tmux.clear()
                state = self.decision(pr_state, decision, seat=self.seat())
                lines = self.typed()
                self.assertEqual(len(lines), 1, lines)
                self.assertIn(expected, lines[0])
                self.assertIn(PR, lines[0])
                self.assertIn("PR #7 Fix the parser", lines[0])
                own = state["own"][PR]
                self.assertEqual(own["done"] if pr_state != "OPEN" else own["decision"],
                                 True if pr_state != "OPEN" else "CHANGES_REQUESTED")
        self.assertEqual(self.requests, [])
        self.assertFalse(list(notify.outbox().glob("*.json")) if notify.outbox().exists() else [])
        self.assertIsNone(notify.last("seat"))

    def test_v5d_pr_lifecycle_without_a_live_seat_lands_on_the_run(self):
        for pr_state, expected, worktree in (
                ("MERGED", "merged by the maintainer", True),
                ("CLOSED", "closed by the maintainer without a merge", False)):
            with self.subTest(pr_state=pr_state):
                for stale in config.RUNS.glob("*"):
                    shutil.rmtree(stale)
                run_dir = self.finished_run(f"20260915-0001-{pr_state.lower()}", worktree)
                state = self.decision(pr_state, seat=None)
                saved = run.read_state(run_dir)
                self.assertEqual(saved["merge_note"], f"PR #7 Fix the parser: {expected}")
                self.assertEqual(saved["merged"], pr_state == "MERGED")
                result = (run_dir / "result.md").read_text()
                self.assertIn(expected, result)
                # a run whose worktree is gone keeps the result it had and adds to it
                self.assertIn("## Diff stat", result)
                self.assertEqual("## The maintainer decided" in result, not worktree)
                self.assertTrue(state["own"][PR]["done"])
        self.assertEqual((self.requests, self.typed()), ([], []))

    # --- (b, c) the hourly alerts ------------------------------------------

    def test_v5d_an_hour_of_stall_on_an_idle_seat_says_nothing(self):
        state = self.stall_tick("at_prompt")
        self.assertEqual(self.posts, [])
        self.assertIsNone(notify.last("seat"))
        self.assertTrue(state["stalls"]["seat"]["told"])   # and the nudging still stops
        self.assertIn("sitting at its own prompt", " ".join(self.log))

    def test_v5d_an_hour_of_stall_on_a_working_seat_asks_once(self):
        state = self.stall_tick("working")
        # the seat is mid-turn, so the word is working: the question is asked and
        # latched, but no card is queued until the word turns
        self.assertEqual(self.posts, [])
        # the stuck words still reach the record and the log, never Discord
        self.assertIn("API Error", notify.last("seat")["text"])
        self.assertIn("press this session's number", notify.last("seat")["text"])
        self.assertEqual(notify.last("seat")["kind"], "needs")
        self.assertTrue(state["stalls"]["seat"]["told"])
        self.stall_tick("working")            # a second tick latches nothing new
        self.assertEqual(self.posts, [])
        self.assertEqual(notify.last("seat")["kind"], "needs")

    def test_v5d_an_hour_of_no_progress_at_all_obeys_the_same_gate(self):
        pane = "Error: unable to continue; the connection was lost"
        for word, expected in (("at_prompt", 0), ("asking", 1)):
            with self.subTest(word=word):
                self.requests.clear()
                config.notify_path("seat").unlink(missing_ok=True)
                watch.save_state({"reviewed": {}, "own": {}, "stalls": {}, "seen_at": {}})
                self.stall_tick(word, pane=pane)
                self.assertEqual(len(self.posts), expected, self.posts)
        self.assertNotIn("description", self.posts[0]["embeds"][0])
        self.assertIn("is stuck with no progress for an hour", notify.last("seat")["text"])

    # --- (d, e) the needs-you the rule keeps -------------------------------

    def test_v5d_auth_expiry_asks_the_owner_even_on_an_idle_seat(self):
        state = self.stall_tick("at_prompt", pane="Please run /login",
                                auth="Please run /login")
        self.assertEqual(len(self.posts), 1, self.posts)
        self.assertEqual(self.posts[0]["embeds"][0]["title"], "Needs you · seat")
        self.assertNotIn("description", self.posts[0]["embeds"][0])
        self.assertIn("needs login", notify.last("seat")["text"])
        self.assertEqual(state["stalls"]["seat"]["kind"], "auth")

    def test_v5d_the_inbox_merge_question_asks_the_owner(self):
        question = "Merge PR #9 by bob? yes/no"
        with patch.object(orch, "ensure", return_value=False), \
                patch.object(orch, "find", return_value=self.seat("inbox")), \
                patch.object(config, "resolve_session", side_effect=lambda name: name):
            self.assertEqual(watch.ask_inbox(config.load(), question, PR, SHA, self.log.append), 0)
        self.assertEqual(len(self.posts), 1, self.posts)
        self.assertEqual(self.posts[0]["embeds"][0]["title"], "Needs you · inbox")
        self.assertIn(question, self.typed()[0])

    # --- (g) nothing that stood before the install, nor a seat he closed ----

    def test_v5d_the_first_tick_after_an_upgrade_cards_nothing_that_stood_before_it(self):
        # 2026-09-22 12:03: nine cards in seven seconds from the first tick after an install:
        # seats closed days before -- some of them by the owner -- and a done already sent.
        now = time.time()
        (config.STATE / "installed-at").write_text(f"{now - 60}\n")
        cfg = config.load()
        seats = []
        for name in ("closed-1", "closed-2", "paused"):
            config.save_session(cfg, name, "fable", ["opus"], {"exited_since": now - 3 * 86400})
            seats.append({"name": name, "exited": True, "legacy": False})
        orch.mark_owner_closed("paused")
        notify.record("test", "done", "Shipped", time=now - 86400)
        watch.seat_write("test", word="done", reason="Shipped", word_since=now - 86400)
        seats.append({"name": "test", "legacy": False})
        with patch.object(orch, "listing", return_value=seats):
            for at in (now, now + notify.CARD_WAIT):
                with patch.object(notify.time, "time", return_value=at):
                    notify.tick_cards(log=self.log.append)
        self.assertEqual(self.posts, [])
        # A seat that goes after the install is news, and is carded after its minute --
        # unless the owner closed it himself.
        for name, closed in (("crashed", False), ("stopped", True)):
            config.save_session(cfg, name, "fable", ["opus"], {"exited_since": now})
            seats.append({"name": name, "exited": True, "legacy": False})
            if closed:
                orch.mark_owner_closed(name)
        with patch.object(orch, "listing", return_value=seats):
            for at in (now + 2 * notify.CARD_WAIT, now + 3 * notify.CARD_WAIT):
                with patch.object(notify.time, "time", return_value=at):
                    notify.tick_cards(log=self.log.append)
        self.assertEqual([post["embeds"][0]["title"] for post in self.posts],
                         ["Needs you · crashed"])

    # --- (f) workers stay silent -------------------------------------------

    def test_v5d_a_worker_posts_nothing_at_all(self):
        with patch.dict(os.environ, {"AK_RUN_ROLE": "worker"}):
            self.assertEqual(notify.shaped("needs", "May I?", session="seat"), 0)
            self.assertEqual(notify.shaped("done", "Shipped", session="seat"), 0)
            self.stall_tick("working")
            self.stall_tick("working", pane="Please run /login", auth="Please run /login")
        self.assertEqual(self.requests, [])
        self.assertIsNone(notify.last("seat"))

    def test_v5d_a_queued_test_notification_never_reaches_the_owner_later(self):
        with patch.dict(os.environ, {notify.SINK_ENV: SINK}), \
                patch.object(notify.urllib.request, "urlopen",
                             side_effect=TimeoutError("the sink is down")):
            self.assertEqual(notify.shaped("done", "A scratch run finished", session="seat"), 0)
        event = json.loads(next(notify.outbox().glob("*.json")).read_text())
        self.assertEqual((event["status"], event["sink"]), ("pending", True))
        with patch.object(notify.time, "time", return_value=time.time() + 3600):
            notify.retry_pending()                     # the suite is over and the marker is gone
        self.assertEqual(self.requests, [])
        self.assertEqual(json.loads((notify.outbox() / f"{event['id']}.json").read_text())["status"],
                         "disabled")
        self.assertIn(f"queued under {notify.SINK_ENV}", self.err.getvalue())

    def test_v5d_a_notification_queued_before_any_marker_is_the_owners(self):
        with patch.object(notify.urllib.request, "urlopen", side_effect=TimeoutError("down")):
            self.assertEqual(notify.shaped("needs", "May I merge?", session="seat"), 0)
        path = next(notify.outbox().glob("*.json"))
        event = json.loads(path.read_text())
        del event["sink"]                  # an event from before this rule existed
        path.write_text(json.dumps(event))
        with patch.dict(os.environ, {notify.SINK_ENV: "dry-run"}), \
                patch.object(notify.time, "time", return_value=time.time() + 3600):
            notify.retry_pending()
        self.assertEqual(json.loads(path.read_text())["status"], "pending")   # not disabled
        self.assertEqual(self.requests, [])
        with patch.object(notify.time, "time", return_value=time.time() + 3600):
            notify.retry_pending()         # and the owner still gets it
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(json.loads(path.read_text())["status"], "delivered")

    def test_v5d_a_queued_notification_of_the_owners_is_not_drained_into_a_sink(self):
        with patch.object(notify.urllib.request, "urlopen", side_effect=TimeoutError("down")):
            self.assertEqual(notify.shaped("needs", "May I merge?", session="seat"), 0)
        event = json.loads(next(notify.outbox().glob("*.json")).read_text())
        self.assertEqual((event["status"], event["sink"]), ("pending", False))
        with patch.dict(os.environ, {notify.SINK_ENV: SINK}), \
                patch.object(notify.time, "time", return_value=time.time() + 3600):
            notify.retry_pending()
        self.assertEqual(self.requests, [])            # not to the sink, and not dropped either
        self.assertEqual(json.loads((notify.outbox() / f"{event['id']}.json").read_text())["status"],
                         "pending")
        with patch.object(notify.time, "time", return_value=time.time() + 3600):
            notify.retry_pending()                     # and it is delivered once the suite ends
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.requests[0][0].startswith(WEBHOOK.split("?")[0]), self.requests[0][0])

    # --- (h) a test never reaches the owner --------------------------------

    def test_v5d_the_suites_sink_wins_over_the_owners_webhook(self):
        with patch.dict(os.environ, {notify.SINK_ENV: "dry-run"}):
            self.assertEqual(notify.shaped("done", "A scratch run finished", session="seat"), 0)
        self.assertEqual(self.requests, [])
        self.assertIn(f"{notify.SINK_ENV} is set", self.err.getvalue())
        self.assertIn("went to the test sink", self.err.getvalue())
        # and the suite is told where to fail on it, not only on stderr
        self.assertIn("went to the test sink", self.diversions.read_text())
        # one card per episode, so the sink half of the check gets its own seat
        with patch.dict(os.environ, {notify.SINK_ENV: SINK}):
            self.assertEqual(notify.shaped("done", "And another one", session="other"), 0)
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.requests[0][0].startswith(SINK), self.requests[0][0])
        self.assertNotIn(WEBHOOK, [url for url, _ in self.requests])

    # --- (i) the card names its seat ---------------------------------------

    def test_v5d_the_footer_and_sender_name_the_seat_not_the_host(self):
        self.assertEqual(notify.shaped("needs", "Which branch?", session="seat"), 0)
        payload = self.posts[0]
        self.assertNotIn("footer", payload["embeds"][0])
        self.assertEqual(payload["username"], "agentkit")
        self.assertNotIn(socket.gethostname(), json.dumps(payload))
        self.assertNotIn("gethostname", (REPO / "agentkit/notify.py").read_text())
        self.assertEqual(notify.embed("done", None, "No seat behind it")["title"],
                         "Done · No seat behind it")

    # --- and the watcher's own vocabulary ----------------------------------

    def test_v5d_the_watcher_never_sends_a_done(self):
        source = (REPO / "agentkit/watch.py").read_text()
        self.assertEqual(re.findall(r"""shaped\(\s*["']done""", source), [])
        with patch.object(notify, "shaped", side_effect=AssertionError("posted")) as shaped:
            for pr_state, decision in (("MERGED", None), ("CLOSED", None),
                                       ("OPEN", "CHANGES_REQUESTED")):
                self.decision(pr_state, decision, seat=self.seat())
            shaped.assert_not_called()

    # --- (rule 10) a card is two words and the seat --------------------------

    def test_v5d_a_done_card_is_two_words_and_the_seat(self):
        long_text = "Parser fixed and the PR is up, see run 20260915-0001 and key abc123"
        self.assertEqual(notify.main(["done", long_text]), 0)
        self.assertEqual(len(self.posts), 1, self.posts)
        payload = self.posts[0]
        self.assertEqual(payload["content"], "<@42>")
        self.assertEqual(payload["username"], "agentkit")
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "Done · seat")
        for absent in ("description", "fields", "footer", "url"):
            self.assertNotIn(absent, embed)
            self.assertNotIn(absent, json.dumps(payload))
        self.assertNotIn(long_text, json.dumps(payload))
        # the text is kept where it is useful: the outbox record, the log line,
        # the terminal notice and --dry-run -- never on Discord
        self.assertEqual(notify.last("seat")["text"], long_text)
        event = json.loads(next(notify.outbox().glob("*.json")).read_text())
        self.assertEqual((event["text"], event["message"].split(": ", 1)[1]), (long_text, long_text))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(notify.main(["done", long_text, "--dry-run"]), 0)
        self.assertIn(long_text, out.getvalue() + err.getvalue())
        self.assertEqual(len(self.posts), 1)   # a dry run posts nothing

    def test_v5d_a_needs_card_is_two_words_and_the_seat(self):
        long_text = "Which branch should this land on, and who owns the numbers below?"
        self.assertEqual(notify.main(["needs", long_text]), 0)
        self.assertEqual(len(self.posts), 1, self.posts)
        payload = self.posts[0]
        self.assertEqual(payload["content"], "<@42>")
        self.assertEqual(payload["username"], "agentkit")
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "Needs you · seat")
        for absent in ("description", "fields", "footer", "url"):
            self.assertNotIn(absent, embed)
        self.assertNotIn(long_text, json.dumps(payload))
        self.assertEqual(notify.last("seat")["text"], long_text)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(notify.main(["needs", long_text, "--dry-run"]), 0)
        self.assertIn(long_text, out.getvalue() + err.getvalue())

    def test_v5d_a_done_with_no_runs_going_posts_at_once(self):
        self.assertEqual(notify.main(["done", "Quick answer"]), 0)
        self.assertEqual(len(self.posts), 1, self.posts)
        self.assertEqual(self.posts[0]["embeds"][0]["title"], "Done · seat")
        events = [json.loads(path.read_text()) for path in notify.outbox().glob("*.json")]
        self.assertEqual([(event["status"], event["session"]) for event in events],
                         [("delivered", "seat")])

    # --- (rule 8) a run keeps its test origin --------------------------------

    def test_v5d_a_test_origin_run_speaks_to_its_sink_only(self):
        run_dir = config.RUNS / "20260915-0001-sink"
        run_dir.mkdir(parents=True, exist_ok=True)
        with patch.dict(os.environ, {notify.SINK_ENV: "dry-run"}):
            run.capture_launch(run_dir, {})
        self.assertEqual(run.read_state(run_dir)["notify_sink"], "dry-run")
        plain_dir = config.RUNS / "20260915-0002-owner"
        plain_dir.mkdir(parents=True, exist_ok=True)
        with patch.dict(os.environ, {notify.SINK_ENV: ""}):
            run.capture_launch(plain_dir, {})
        self.assertNotIn("notify_sink", run.read_state(plain_dir))
        # the capture is asserted; a going run would keep the word working below
        shutil.rmtree(plain_dir)
        # the suite is over and the marker is gone, and the launching seat with it
        state = run.read_state(run_dir)
        state.update(state="pass", verdict="PASS", finished_at=time.time(), reported=False)
        run.save_state(run_dir, state)
        with patch.dict(os.environ, {notify.SINK_ENV: ""}), \
                patch.object(orch, "find", return_value=None):
            run.announce(run.read_state(run_dir), run_dir, self.log.append)
        self.assertEqual(self.requests, [])          # the orphan notice went nowhere near Discord
        self.assertTrue(run.read_state(run_dir)["reported"])
        self.assertIn("went to the test sink", self.err.getvalue())
        interrupted = run.read_state(run_dir)
        interrupted.update(state="interrupted", interrupted_at=time.time(),
                           recovery_pending=True)
        run.save_state(run_dir, interrupted)
        with patch.dict(os.environ, {notify.SINK_ENV: ""}), \
                patch.object(orch, "find", return_value=None):
            run.notify_recovery(run_dir, run.read_state(run_dir))
        self.assertEqual(self.requests, [])
        self.assertEqual(run.read_state(run_dir)["recovery_notified"], "needs")

    def test_v5d_the_watchers_reap_path_obeys_the_runs_record(self):
        run_dir = config.RUNS / "20260915-0001-sink"
        run_dir.mkdir(parents=True, exist_ok=True)
        with patch.dict(os.environ, {notify.SINK_ENV: "dry-run"}):
            run.capture_launch(run_dir, {})
        # the loop died mid-run, long after any launch grace
        state = run.read_state(run_dir)
        state.update(state="running", pid=2 ** 30, started_at=time.time() - 7200)
        state.pop("process_identity", None)
        state.pop("launch_pending", None)
        run.save_state(run_dir, state)
        with patch.dict(os.environ, {notify.SINK_ENV: ""}), \
                patch.object(orch, "find", return_value=None):
            state = run.reap(run_dir, run.read_state(run_dir))
        self.assertEqual(state["state"], "interrupted")
        self.assertEqual(self.requests, [])          # the interruption notice stayed off Discord
        self.assertEqual(run.read_state(run_dir)["recovery_notified"], "needs")

    def test_v5d_a_run_without_the_record_is_the_owners(self):
        run_dir = config.RUNS / "20260915-0001-owner"
        run_dir.mkdir(parents=True, exist_ok=True)
        with patch.dict(os.environ, {notify.SINK_ENV: ""}):
            run.capture_launch(run_dir, {})
        state = run.read_state(run_dir)
        state.update(state="interrupted", interrupted_at=time.time(), recovery_pending=True)
        run.save_state(run_dir, state)
        with patch.dict(os.environ, {notify.SINK_ENV: ""}), \
                patch.object(orch, "find", return_value=None):
            run.notify_recovery(run_dir, run.read_state(run_dir))
        self.assertEqual(len(self.requests), 1)      # the owner hears it, as today
        self.assertTrue(self.requests[0][0].startswith(WEBHOOK.split("?")[0]),
                        self.requests[0][0])
        self.assertEqual(run.read_state(run_dir)["recovery_notified"], "needs")


if __name__ == "__main__":
    unittest.main()
