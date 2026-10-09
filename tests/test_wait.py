"""A seat that ended its turn on `ak wait <pull request or run>` is working until that is over.

The wait is the seat's own word, replaced only by its next one: `ak wait` writes it, a newer
`ak notify` or `ak wait` replaces it, and the ladder, the stop hook and the tick's end-of-turn
rule all ask `watch.waiting_on` whether it holds.  The tick's wait pass (`watch.wait_over`) is
the one reader of the fact: it marks the wait over the moment the run ends or the pull request
merges or closes, and types one line into the seat at its next quiet prompt, naming that fact
and nothing else.  A wait never names a session.  Offline: fake seats, fake tmux, fake
captures, fake run receipts, a faked `gh` and a throwaway HOME; the hook runs as its harness
runs it, JSON on stdin.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from fixtures.sandbox import REPO, Sandbox
from agentkit import config, menu, notify, orch, run, watch, worker
from agentkit import record

NOW = 1_800_000_000
SEAT, OTHER = "acme-api", "fix-api"
THEIRS = "20260101-0900-schema"
PR = "https://github.com/acme/api/pull/12"
RECOMMENDATION = "Here is my recommendation. Let me know if I should continue."
PROMPT = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()
ENDED = f"run {THEIRS} ended PASS, merged; your wait is over. Decide the next step."


class Wait(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "AK_RUN_ROLE": "orchestrator",
            notify.SINK_ENV: "dry-run", "AGENTKIT_DISCORD_WEBHOOK": "",
            config.SESSION_ENV: SEAT}))
        (config.CODE / "acme" / ".git").mkdir(parents=True)
        self.repo = str(config.CODE / "acme")
        self.seats = {}
        for name in (SEAT, OTHER):
            self.seats[name] = {"name": name, "repo": self.repo, "path": self.repo,
                                "created": NOW - 86400, "attached": False, "exited": False,
                                "legacy": False, "resumable": False}
            config.save_session(self.cfg, name, "fable", ["opus"],
                                {"repo": self.repo, "cwd": self.repo})
        listed = lambda *_a, **_k: list(self.seats.values())
        self.stack.enter_context(patch.object(orch, "sessions", side_effect=listed))
        self.stack.enter_context(patch.object(orch, "listing", side_effect=listed))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(0, "")))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(watch, "pane_text", return_value="$ "))
        self.stack.enter_context(patch.object(worker, "auth_ok",
                                              side_effect=lambda h, seat=False: (True, h)))
        # GitHub, faked: what `gh pr view` answers about the one pull request; None is no answer
        self.gh = {"state": "OPEN", "number": 12, "mergeCommit": None}
        self.stack.enter_context(patch.object(watch, "gh_json", side_effect=lambda *_a, **_k: (
            (self.gh, "") if self.gh is not None else (None, "gh: no route to GitHub"))))
        # Discord, faked: the title of every card it took, which `ak wait` never sends
        self.posts = []

        def post(payload, files, message, receipt):
            self.posts.append(payload["embeds"][0]["title"])
            receipt.update(status="delivered", message_id=str(len(self.posts)), webhook="sink")
        self.stack.enter_context(patch.object(notify, "post", side_effect=post))
        self.stack.enter_context(patch.object(notify, "close_needs", return_value=[]))

    def turn(self, name, event):
        """What that seat's own lifecycle hook writes, then a screen looking at it."""
        config.hook_facts_path(name).write_text(json.dumps(
            {"session": name, "event": event, "kind": "", "text": "", "at": NOW - 60}))
        watch.look_at(self.seats[name], cfg=self.cfg)

    def receipt(self, name, owner, **extra):
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        record.save_state(directory, {"run_id": name, "title": f"Task {name}", "state": "running",
                                   "launched_session": owner, "repo": self.repo,
                                   "started_at": NOW - 600, "finished_at": None, **extra})

    def ended(self, name=THEIRS):
        record.save_state(config.RUNS / name, {
            **record.read_state(config.RUNS / name), "state": "pass", "verdict": "PASS",
            "merged": True, "finished_at": NOW - 30})

    def wait(self, on, seat=SEAT):
        """`ak wait <on>` in that seat: (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {config.SESSION_ENV: seat}), \
                redirect_stdout(out), redirect_stderr(err):
            code = watch.wait_main([on])
        return code, out.getvalue(), err.getvalue()

    def decide(self, name=SEAT):
        harness, live = watch.look_at(self.seats[name], cfg=self.cfg)
        found = watch.session_state(name, NOW, session=self.seats[name], cfg=self.cfg,
                                    live=live, harness=harness)
        return found["word"], found["reason"]

    def tick(self):
        """The tick's wait pass, every seat's screen showing the Claude prompt, a typed line in
        its composer until its Enter: the lines the fake tmux was given, in order."""
        sent, screen, self.logs = [], [PROMPT], []

        def tmux(*args, socket=None, client=False, **_kw):
            if args[0] == "send-keys" and "-l" in args:
                sent.append(args[-1])
                screen[0] = PROMPT.replace("❯ \n", f"❯ {args[-1]}\n")
            elif args[0] == "send-keys":
                screen[0] = PROMPT
            return 0, ""
        with patch.object(orch, "tmux_out", side_effect=tmux), \
                patch.object(watch, "pane_text", side_effect=lambda *_a: screen[0]), \
                patch.object(watch.time, "sleep", lambda _s: None):
            watch.wait_over(self.cfg, self.logs.append)
        return sent

    def test_a_refuses_a_session_a_missing_run_and_no_seat_and_records_nothing(self):
        for on in (OTHER, "no-such-run", "../runs", SEAT):
            with self.subTest(on=on):
                code, out, err = self.wait(on)
                self.assertEqual((code, out), (1, ""))
                self.assertEqual(err.count("\n"), 1, err)
                self.assertIn("never on a session", err)
        self.assertNotIn("wait", watch.seat_read(SEAT))
        with patch.dict(os.environ):
            os.environ.pop(config.SESSION_ENV)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(watch.wait_main([PR]), 1)
        self.assertEqual((out.getvalue(), err.getvalue().count("\n")), ("", 1))
        # ... and the ones it takes print one line, write the seat's own field and send
        # no card and no notice: a run of anybody's, or a pull request
        self.receipt(THEIRS, OTHER)
        code, out, err = self.wait(THEIRS)
        self.assertEqual((code, out.count("\n"), err), (0, 1, ""))
        self.assertEqual(watch.seat_read(SEAT)["wait"]["on"], THEIRS)
        self.assertEqual(watch.seat_read(SEAT)["wait"]["kind"], "run")
        code, out, err = self.wait(PR)
        self.assertEqual((code, out.count("\n"), err), (0, 1, ""))
        self.assertEqual(watch.seat_read(SEAT)["wait"], {**watch.seat_read(SEAT)["wait"],
                                                         "on": PR, "kind": "pr"})
        self.assertIsNone(notify.last(SEAT, include_seen=True))
        self.assertEqual(self.posts, [])

    def test_b_working_while_the_run_it_names_is_not_over(self):
        self.receipt(THEIRS, OTHER)
        self.wait(THEIRS)
        self.assertEqual(self.decide(), ("working", f"waiting on {THEIRS}"))
        # whoever launched it: a run is a run
        self.receipt(THEIRS, "someone-else")
        self.assertEqual(self.decide(), ("working", f"waiting on {THEIRS}"))
        # ... and one parked on a login is not over either: the tick leaves the wait alone
        self.receipt(THEIRS, OTHER, state="waiting_login", waiting_for="claude",
                     finished_at=NOW - 300)
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.decide(), ("working", f"waiting on {THEIRS}"))
        self.assertEqual(watch.waiting_on(SEAT)["on"], THEIRS)

    def test_c_over_once_the_run_ends_and_the_line_is_typed_once(self):
        self.receipt(THEIRS, OTHER)
        self.wait(THEIRS)
        self.assertEqual(self.tick(), [])       # going: nothing to tell yet
        self.ended()
        self.assertEqual(self.tick(), [ENDED])
        wait = watch.seat_read(SEAT)["wait"]
        self.assertEqual((wait["on"], wait["over"]), (THEIRS, f"run {THEIRS} ended PASS, merged"))
        self.assertTrue(wait["told"])
        self.assertEqual(self.tick(), [])       # once
        self.assertIsNone(watch.waiting_on(SEAT))
        self.assertEqual(self.decide(), ("needs you", "waiting for you"))
        self.assertIsNone(notify.last(SEAT, include_seen=True))   # told, not notified
        # a run that is gone altogether is over too
        self.receipt("20260101-0800-gone", OTHER)
        self.wait("20260101-0800-gone")
        for path in sorted((config.RUNS / "20260101-0800-gone").rglob("*"), reverse=True):
            path.unlink()
        (config.RUNS / "20260101-0800-gone").rmdir()
        self.assertEqual(self.tick(), ["run 20260101-0800-gone is gone; your wait is over. "
                                       "Decide the next step."])

    def test_d_a_pull_request_holds_while_open_and_ends_merged_or_closed(self):
        self.wait(PR)
        self.assertEqual(self.decide(), ("working", f"waiting on {PR}"))
        self.assertEqual(self.tick(), [])
        self.gh = {"state": "MERGED", "number": 12, "mergeCommit": {"oid": "abcdef1234567890"}}
        self.assertEqual(self.tick(), ["PR #12 merged as abcdef123456; your wait is over. "
                                       "Decide the next step."])
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.decide(), ("needs you", "waiting for you"))
        self.wait(PR)
        self.gh = {"state": "CLOSED", "number": 12, "mergeCommit": None}
        self.assertEqual(self.tick(), ["PR #12 closed without merging; your wait is over. "
                                       "Decide the next step."])
        # GitHub not answering leaves the wait as it is, and says so in the log
        self.wait(PR)
        self.gh = None
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.decide(), ("working", f"waiting on {PR}"))
        self.assertTrue(any(line.startswith(f"WARN {SEAT}: its wait on {PR} cannot be read")
                            for line in self.logs), self.logs)

    def test_e_a_newer_notify_done_replaces_the_wait(self):
        self.receipt(THEIRS, OTHER)
        self.wait(THEIRS)
        self.assertEqual(self.decide(), ("working", f"waiting on {THEIRS}"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(notify.main(["done", "Shipped the parser"]), 0)
        self.assertEqual(self.decide(), ("done", "Shipped the parser"))
        self.assertIsNone(watch.seat_read(SEAT).get("wait"))
        self.ended()
        self.assertEqual(self.tick(), [])       # a replaced wait is told nothing
        # ... and a newer wait replaces the done in turn
        self.receipt("20260101-1000-other", OTHER)
        self.wait("20260101-1000-other")
        self.assertEqual(self.decide(), ("working", "waiting on 20260101-1000-other"))

    def hook(self, said=RECOMMENDATION):
        """hooks/orchestrator-stop.sh on this seat's Stop, as Claude Code runs it."""
        home, sockets = self.root / "hook-home", self.root / "sockets"
        sockets.mkdir(mode=0o700, exist_ok=True)
        for name, target in (("state", config.STATE), ("runs", config.RUNS)):
            link = home / ".agentkit" / name
            link.parent.mkdir(parents=True, exist_ok=True)
            if not link.is_symlink():
                link.symlink_to(target)
        (config.STATE / f"stop-{SEAT}.json").write_text(json.dumps(
            {"session": SEAT, "turn": NOW - 60, "blocks": 0}) + "\n")
        transcript = self.root / "transcript.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "isSidechain": False, "message": {
            "role": "assistant", "content": [{"type": "text", "text": said}]}}) + "\n")
        done = subprocess.run(
            ["bash", str(REPO / "hooks/orchestrator-stop.sh")], text=True, capture_output=True,
            input=json.dumps({"hook_event_name": "Stop", "session_id": "fake",
                              "transcript_path": str(transcript)}),
            env={"PATH": os.environ["PATH"], "HOME": str(home), "AGENTKIT_SESSION": SEAT,
                 "AK_RUN_ROLE": "orchestrator", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
                 "TMUX_TMPDIR": str(sockets)})   # no tmux server this test did not make
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_f_the_stop_hook_lets_a_turn_ended_on_a_wait_stand_until_the_tick_ends_it(self):
        # a recommendation with nothing to wait on is sent back
        self.assertIn('"block"', self.hook())
        self.receipt(THEIRS, OTHER)
        self.wait(THEIRS)
        self.assertEqual(self.hook(), "")
        self.ended()
        self.assertEqual(self.hook(), "")       # the hook reads the tick's mark, never the fact
        self.assertEqual(self.tick(), [ENDED])
        self.assertIn('"block"', self.hook())
        # ... and so for a pull request
        self.wait(PR)
        self.assertEqual(self.hook(), "")
        self.gh = {"state": "MERGED", "number": 12, "mergeCommit": None}
        self.assertEqual(self.tick(), ["PR #12 merged; your wait is over. Decide the next step."])
        self.assertIn('"block"', self.hook())

    def test_g_the_tick_leaves_a_turn_ended_on_a_wait_alone_while_it_holds(self):
        # A harness with no blocking hook: the tick holds the same rule off its screen,
        # a prompt that has stood past STALL_WAIT on words that are no question
        pane, now, logs = f"{RECOMMENDATION}\n\n⟩", watch.time.time(), []
        watch.seat_write(SEAT, state="at_prompt", turn_began=now - 900, stop_said_at=now - 3600)
        self.receipt(THEIRS, OTHER)
        self.wait(THEIRS)
        with patch.object(watch, "type_into", return_value=True) as typed, \
                patch.object(watch, "pane_text", return_value=pane):
            watch.stop_nudge(self.seats[SEAT], "muse", pane, None, menu.run_records(), False,
                             logs.append)
            typed.assert_not_called()
            # ... nor once the run is over: the wait pass tells it that, and why, first
            self.ended()
            watch.stop_nudge(self.seats[SEAT], "muse", pane, None, menu.run_records(), False,
                             logs.append)
            typed.assert_not_called()
            # ... and once it has been told, it is told to get on with it
            watch.wait_mark(SEAT, watch.seat_read(SEAT)["wait"], over="run ended", told=now)
            watch.stop_nudge(self.seats[SEAT], "muse", pane, None, menu.run_records(), False,
                             logs.append)
            self.assertEqual(typed.call_count, 1, logs)

    def test_h_nothing_is_typed_mid_turn_and_the_line_comes_at_the_next_quiet_prompt(self):
        self.receipt(THEIRS, OTHER)
        self.wait(THEIRS)
        self.ended()
        self.turn(SEAT, "UserPromptSubmit")     # the waiting seat is in a turn of its own
        self.assertEqual(self.tick(), [])
        wait = watch.seat_read(SEAT)["wait"]
        self.assertTrue(wait["over"])           # the fact is written the moment it is seen
        self.assertNotIn("told", wait)          # ... the line waits for the quiet prompt
        self.assertIsNone(watch.waiting_on(SEAT))
        self.assertEqual(self.tick(), [])
        self.turn(SEAT, "Stop")
        self.assertEqual(self.tick(), [ENDED])
        self.assertTrue(watch.seat_read(SEAT)["wait"]["told"])

    def test_i_once_told_only_a_new_wait_is_a_new_wait(self):
        self.receipt(THEIRS, OTHER)
        self.wait(THEIRS)
        self.ended()
        self.assertEqual(self.tick(), [ENDED])
        self.receipt(THEIRS, OTHER)             # the same run going again changes nothing
        self.assertIsNone(watch.waiting_on(SEAT))
        self.assertEqual(self.decide(), ("needs you", "waiting for you"))
        self.assertEqual(self.tick(), [])
        self.wait(THEIRS)                        # a new wait, told in its turn
        self.assertEqual(self.decide(), ("working", f"waiting on {THEIRS}"))
        self.assertEqual(self.tick(), [])
        self.ended()
        self.assertEqual(self.tick(), [ENDED])
        self.assertEqual(self.tick(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
