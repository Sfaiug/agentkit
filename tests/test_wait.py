"""A seat that ended its turn on `ak wait <session>` is working while that session works.

The wait is the seat's own word, replaced only by its next one: `ak wait` writes it, a newer
`ak notify` or `ak wait` replaces it, and the ladder, the stop hook and the tick's end-of-turn
rule all ask `watch.waiting_on` whether it holds.  Offline: fake seats, fake tmux, fake run
receipts and a throwaway HOME; the hook runs as its harness runs it, JSON on stdin.
"""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, notify, orch, run, watch, worker

NOW = 1_800_000_000
SEAT, OTHER = "acme-api", "fix-api"
RECOMMENDATION = "Here is my recommendation. Let me know if I should continue."


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
        run.save_state(directory, {"run_id": name, "title": f"Task {name}", "state": "running",
                                   "launched_session": owner, "repo": self.repo,
                                   "started_at": NOW - 600, "finished_at": None, **extra})

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

    def test_a_refuses_an_unknown_session_itself_and_no_seat_and_records_nothing(self):
        code, out, err = self.wait("no-such-seat")
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err.count("\n"), 1, err)
        self.assertIn("no-such-seat", err)
        code, out, err = self.wait(SEAT)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err.count("\n"), 1, err)
        with patch.dict(os.environ):
            os.environ.pop(config.SESSION_ENV)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(watch.wait_main([OTHER]), 1)
        self.assertEqual((out.getvalue(), err.getvalue().count("\n")), ("", 1))
        self.assertNotIn("wait", watch.seat_read(SEAT))
        # ... and the one it takes prints one line, writes the seat's own field and sends
        # no card and no notice
        code, out, err = self.wait(OTHER)
        self.assertEqual((code, out.count("\n"), err), (0, 1, ""))
        self.assertEqual(watch.seat_read(SEAT)["wait"]["on"], OTHER)
        self.assertIsNone(notify.last(SEAT, include_seen=True))
        self.assertEqual(self.posts, [])

    def test_b_working_waiting_on_the_other_while_it_works(self):
        self.wait(OTHER)
        self.turn(OTHER, "UserPromptSubmit")
        self.assertEqual(self.decide(), ("working", f"waiting on {OTHER}"))
        # ... by a run of its own just the same, with its turn over
        self.turn(OTHER, "Stop")
        self.receipt("20260101-0900-schema", OTHER)
        self.assertEqual(self.decide(), ("working", f"waiting on {OTHER}"))
        # somebody else's run is not the other's work
        self.receipt("20260101-0900-schema", "someone-else")
        self.assertEqual(self.decide()[0], "needs you")

    def test_c_needs_you_once_the_other_stops(self):
        self.wait(OTHER)
        self.turn(OTHER, "UserPromptSubmit")
        self.assertEqual(self.decide()[0], "working")
        self.turn(OTHER, "Stop")
        self.assertEqual(self.decide(), ("needs you", "waiting for you"))
        # a seat nobody is in has no turn, whatever its record last showed
        self.turn(OTHER, "UserPromptSubmit")
        self.seats[OTHER]["exited"] = True
        self.assertEqual(self.decide(), ("needs you", "waiting for you"))
        # ... and so has one no listing holds at all, while a run of its own still counts
        self.seats[OTHER]["exited"] = False
        gone = self.seats.pop(OTHER)
        self.assertEqual(self.decide(), ("needs you", "waiting for you"))
        self.receipt("20260101-0800-absent", OTHER)
        self.assertEqual(self.decide(), ("working", f"waiting on {OTHER}"))
        run.save_state(config.RUNS / "20260101-0800-absent", {
            **run.read_state(config.RUNS / "20260101-0800-absent"), "state": "pass",
            "finished_at": NOW - 30})
        self.seats[OTHER] = gone
        # the wait itself is still the seat's word: nothing that looked ended it
        self.assertEqual(watch.seat_read(SEAT)["wait"]["on"], OTHER)
        # ... and a run of the other's parked on a login makes the other his, not working:
        # every rung above the other's runs counts, and so the wait on it is his too
        self.seats[OTHER]["exited"] = False
        self.turn(OTHER, "Stop")
        self.receipt("20260101-0900-schema", OTHER, state="waiting_login",
                     waiting_for="claude", finished_at=NOW - 300)
        self.assertEqual(self.decide(OTHER)[0], "needs you")
        self.assertEqual(self.decide(), ("needs you", "waiting for you"))

    def test_d_two_seats_waiting_on_each_other_are_both_his(self):
        self.wait(OTHER)
        self.wait(SEAT, seat=OTHER)
        self.assertEqual(self.decide(SEAT), ("needs you", "waiting for you"))
        self.assertEqual(self.decide(OTHER), ("needs you", "waiting for you"))
        # ... until one of them works by its own run: the other one reads that, and the
        # working one is never working by the wait that points back at it
        self.receipt("20260101-0900-schema", OTHER)
        self.assertEqual(self.decide(SEAT), ("working", f"waiting on {OTHER}"))
        self.assertEqual(self.decide(OTHER)[0], "working")
        self.assertIn("running", self.decide(OTHER)[1])

    def test_e_a_newer_notify_done_replaces_the_wait(self):
        self.wait(OTHER)
        self.turn(OTHER, "UserPromptSubmit")
        self.assertEqual(self.decide(), ("working", f"waiting on {OTHER}"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(notify.main(["done", "Shipped the parser"]), 0)
        self.assertEqual(self.decide(), ("done", "Shipped the parser"))
        # ... and a newer wait replaces the done in turn
        self.wait(OTHER)
        self.assertEqual(self.decide(), ("working", f"waiting on {OTHER}"))

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

    def test_f_the_stop_hook_lets_a_turn_ended_on_a_wait_stand_while_it_holds(self):
        # a recommendation with nothing to wait on is sent back
        self.assertIn('"block"', self.hook())
        self.wait(OTHER)
        self.assertIn('"block"', self.hook())      # the other is not working yet
        self.receipt("20260101-0900-schema", OTHER)
        self.assertEqual(self.hook(), "")
        self.receipt("20260101-0900-schema", OTHER, state="waiting_login",
                     waiting_for="claude", finished_at=NOW - 60)
        self.assertIn('"block"', self.hook())      # the other is his, not working
        self.receipt("20260101-0900-schema", OTHER, state="pass", finished_at=NOW - 30)
        self.assertIn('"block"', self.hook())

    def test_g_the_tick_leaves_a_turn_ended_on_a_wait_alone_while_it_holds(self):
        # A harness with no blocking hook: the tick holds the same rule off its screen,
        # a prompt that has stood past STALL_WAIT on words that are no question
        pane, now, logs = f"{RECOMMENDATION}\n\n⟩", watch.time.time(), []
        watch.seat_write(SEAT, state="at_prompt", turn_began=now - 900, stop_said_at=now - 3600)
        records = [(Path("/runs/theirs"), {"launched_session": OTHER, "state": "running"})]
        self.wait(OTHER)
        with patch.object(watch, "type_into", return_value=True) as typed, \
                patch.object(watch, "pane_text", return_value=pane):
            watch.stop_nudge(self.seats[SEAT], "muse", pane, None, records, False, logs.append)
            typed.assert_not_called()
            # ... and once the other's run is over, it is told to get on with it
            watch.stop_nudge(self.seats[SEAT], "muse", pane, None, [], False, logs.append)
            self.assertEqual(typed.call_count, 1, logs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
