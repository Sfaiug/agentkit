"""A session is working, needs you or done; one function decides and every screen reads it.

One test per rung of `watch.session_state`'s ladder, in its order, plus the three surfaces
that have to agree with it: the menu's top line, `ak orch list` and the seat's own tmux bar.
Offline: fake seats, fake run receipts, the real renderers.
"""

from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from test_v4n import REPO, Sandbox
from agentkit import config, menu, notify, orch, run, terminal, watch, worker

NOW = 1_800_000_000
DAY = 86400
STOP = ("seat-state.sh", "orchestrator-stop.sh")    # what Claude Code runs on Stop, side by side


class ThreeStates(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        (config.CODE / "atoll" / ".git").mkdir(parents=True)
        self.repo = str(config.CODE / "atoll")
        self.seat = {"name": "atoll", "repo": self.repo, "path": self.repo,
                     "created": NOW - 5 * DAY, "attached": False, "exited": False,
                     "legacy": False, "resumable": False}
        config.save_session(self.cfg, "atoll", "fable", ["opus"],
                            {"repo": self.repo, "cwd": self.repo})
        self.options = {}
        self.pane = "$ "
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[self.seat]))
        self.stack.enter_context(patch.object(orch, "listing", return_value=[self.seat]))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(watch, "pane_text",
                                              side_effect=lambda *_a, **_k: self.pane))
        # The harness's `auth` verb, stubbed: what a login is doing is this test's to say,
        # and no real adapter may be asked about a real token here.
        self.token_ok = True
        self.stack.enter_context(patch.object(
            worker, "auth_ok",
            side_effect=lambda h, seat=False: (self.token_ok, f"{h}: stub")))

    def tmux(self, *args, **kwargs):
        if args[0] == "set-option":
            self.options[args[3]] = args[4]     # set-option -t <seat> <option> <value>
        return 0, ""

    def fact(self, event, kind="", text="", at=None):
        """What this seat's own lifecycle hook would have written."""
        config.hook_facts_path("atoll").write_text(json.dumps(
            {"session": "atoll", "event": event, "kind": kind, "text": text,
             "at": NOW if at is None else at}))

    def hooks(self, event, *scripts, **payload):
        """This seat's own hooks on one event, run as Claude Code runs them: JSON on stdin.

        Their HOME sees this sandbox's state and runs, so what they write down is what the
        row reads; what they print is what the harness would read back.
        """
        home = self.root / "hook-home"
        for name, target in (("state", config.STATE), ("runs", config.RUNS)):
            link = home / ".agentkit" / name
            link.parent.mkdir(parents=True, exist_ok=True)
            if not link.is_symlink():
                link.symlink_to(target)
        said = ""
        for script in scripts:
            done = subprocess.run(
                ["bash", str(REPO / "hooks" / script)], text=True, capture_output=True,
                input=json.dumps({"hook_event_name": event, "session_id": "fake", **payload}),
                env={"PATH": os.environ["PATH"], "HOME": str(home),
                     "AGENTKIT_SESSION": "atoll", "AK_RUN_ROLE": "orchestrator"})
            self.assertEqual(done.returncode, 0, done.stderr)
            said += done.stdout
        return said

    def transcript(self, said):
        """A Claude Code transcript whose last assistant message is `said`."""
        path = self.root / "transcript.jsonl"
        path.write_text("".join(json.dumps(line) + "\n" for line in (
            {"type": "user", "message": {"role": "user", "content": "go"}},
            {"type": "assistant", "isSidechain": False,
             "message": {"role": "assistant", "content": [{"type": "text", "text": said}]}})))
        return str(path)

    def receipt(self, name, owner="atoll", **extra):
        directory = config.RUNS / name
        directory.mkdir(parents=True, exist_ok=True)
        state = {"run_id": name, "title": f"Task {name}", "state": "pass", "verdict": "PASS",
                 "launched_session": owner, "reported": False, "repo": self.repo,
                 "executor": "opus", "reviewer": "astra", "rounds": 2, "round_summaries": [],
                 "finished_at": NOW - 1800, "started_at": NOW - 3600, **extra}
        run.save_state(directory, state)
        for path in list(directory.rglob("*")) + [directory]:
            try:
                os.utime(path, (NOW, NOW))
            except OSError:
                pass
        return directory

    def decide(self, gone=False, **kwargs):
        """Look at the seat the way a screen does, then decide from what was seen.

        `gone` is the seat nobody is in any more, which is the only seat an ending of its
        own is still his on: a live one was handed the ending by the run itself.
        """
        seat = {**self.seat, "exited": True} if gone else self.seat
        harness, live = watch.look_at(seat, cfg=self.cfg)
        return watch.session_state("atoll", NOW, session=seat, cfg=self.cfg,
                                   live=live, harness=harness, **kwargs)

    # --- the ladder, top rung first -----------------------------------------

    def test_a_expired_login_needs_you_before_anything_else(self):
        # Every lower rung is true at the same time: a going run, a turn in flight,
        # an ending nobody took up, a done notice. The login still wins.
        self.receipt("20260101-0900-going", state="running", finished_at=None)
        self.receipt("20260101-0800-broken", state="fail", verdict="FAIL")
        self.fact("UserPromptSubmit", at=NOW - 60)
        notify.record("atoll", "done", "Shipped it")
        state = watch.load_state()
        # what the last tick's `auth seat` verb answered about this seat's own login, which
        # is the whole of the rule -- never the pane, and never a worker's token
        state["auth_out"] = {"claude": {"ok": False, "why": "expired", "at": NOW - 900}}
        watch.save_state(state)
        found = self.decide()
        self.assertEqual(found["word"], "needs you")
        self.assertEqual(found["reason"], "claude login expired: open it and run /login")
        self.assertEqual(found["since"], NOW - 900)
        # ... and a run of this seat's parked on another harness's login is the same news.
        # That run being parked is the evidence; nothing asks a verb on its behalf, because
        # the pass that can answer is the one that unparks it.
        state["auth_out"] = {"claude": {"ok": True, "why": "", "at": NOW - 900}}
        watch.save_state(state)
        self.receipt("20260101-1000-parked", state="waiting_login", waiting_for="muse",
                     finished_at=NOW - 300)
        parked = self.decide()
        self.assertEqual(parked["word"], "needs you")
        self.assertIn("muse login expired", parked["reason"])
        self.assertEqual(parked["since"], NOW - 300)

    def test_b_a_going_run_is_working_and_names_it(self):
        # Two of its own runs, one parked on a provider window it resumes itself from;
        # both count, and the newest names the row.
        self.receipt("20260101-0900-first", state="running", finished_at=None,
                     started_at=NOW - 900, title="Rebuild the dashboard filters")
        self.receipt("20260101-1000-second", state="exhausted", finished_at=None,
                     started_at=NOW - 600, title="Parked on a window", quota_dry=True)
        # ... and an ending of its own, which a working seat never reads
        self.receipt("20260101-0100-broken", state="fail", verdict="FAIL")
        found = self.decide()
        self.assertEqual(found["word"], "working")
        self.assertEqual(found["reason"], "2 running · Parked on a window")
        self.assertEqual(found["since"], NOW - 900)
        # Somebody else's run is not this seat's business at all.
        self.receipt("20260101-1100-theirs", owner="other-seat", state="running",
                     finished_at=None, started_at=NOW - 300, title="Not mine")
        self.assertNotIn("Not mine", self.decide()["reason"])
        # `since` is when the word began, not when the fact behind it did: once the tick
        # has written it down, the older run ending leaves the seat working all along.
        watch.announce_state(self.seat, cfg=self.cfg)
        self.receipt("20260101-0900-first", state="pass", merged=True,
                     finished_at=NOW - 60, started_at=NOW - 900)
        found = self.decide()
        self.assertEqual(found["word"], "working")
        self.assertEqual(found["reason"], "1 running · Parked on a window")
        self.assertEqual(found["since"], NOW - 900)
        # ... and its tally counts the parked run the reason counts, so the row and
        # `ak orch list` can never disagree about how many are going.
        tallies = run.seat_tallies(state for _, state in menu.run_records())
        self.assertEqual(tallies["atoll"][0], 1)
        self.assertTrue(menu.tally(tallies["atoll"]).startswith("1 running"))

    def test_c_a_turn_in_flight_is_working_and_says_so_past_three_hours(self):
        self.fact("Stop", at=NOW - 7200)
        self.fact("UserPromptSubmit", at=NOW - 720)
        found = self.decide()
        self.assertEqual((found["word"], found["reason"], found["since"]),
                         ("working", "", NOW - 720))
        # Past three hours the word stands and the reason says how long it has run.
        self.fact("UserPromptSubmit", at=NOW - 4 * 3600)
        found = self.decide()
        self.assertEqual((found["word"], found["reason"]), ("working", "turn running 4h"))
        # The manifest reserves `working` to Claude's hooks, so its own fact stands even
        # while the TUI still draws the composer it drew when the last turn ended.
        self.fact("UserPromptSubmit", at=NOW - 720)
        self.pane = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()
        found = self.decide()
        self.assertEqual((found["word"], found["since"]), ("working", NOW - 720))
        # A harness that keeps `working` on its screen says so by its at-prompt rule
        # not matching: nothing readable on the pane is not a seat at its prompt.
        config.hook_facts_path("atoll").unlink()
        with patch.object(watch, "seat_model", return_value=("muse", "meta")):
            self.pane = ""
            self.assertEqual(self.decide()["word"], "working")

    def test_d_an_ending_is_its_orchestrators_business_never_his(self):
        # An ended run hands its ending back to the seat that launched it, so no reason
        # ever names a run or sends him to one. A gone seat names its own number.
        for name, extra in (
                ("20260101-0300-parser-edge-case",
                 {"state": "fail", "verdict": "FAIL", "finished_at": NOW - 3 * 3600}),
                ("20260101-0400-dashboard-filters",
                 {"state": "interrupted", "finished_at": None, "recovery_pending": True,
                  "interrupted_at": NOW - 2 * 3600}),
                ("20260101-0500-schema-rewrite",
                 {"state": "pass", "verdict": "PASS", "finished_at": NOW - 3600})):
            with self.subTest(run=name):
                for old in config.RUNS.iterdir():
                    run.save_state(old, {**run.read_state(old),
                                         "recovery_acknowledged_at": NOW})
                self.receipt(name, **extra)
                # the seat is still in its chair: the ending was handed back to it
                self.assertEqual(self.decide()["reason"], "waiting for you")
                found = self.decide(gone=True)
                self.assertEqual(found["word"], "needs you")
                self.assertRegex(found["reason"], r"^session closed: press \d+ to reopen$")
                self.assertNotIn("press r", found["reason"])
        # Days later the same: the ending never becomes his.
        for old in config.RUNS.iterdir():
            run.save_state(old, {**run.read_state(old), "recovery_acknowledged_at": NOW})
        self.receipt("20260101-0200-yesterdays-failure", state="fail", verdict="FAIL",
                     finished_at=NOW - 2 * DAY, started_at=NOW - 2 * DAY - 1800)
        found = self.decide(gone=True)
        self.assertEqual(found["word"], "needs you")
        self.assertRegex(found["reason"], r"^session closed: press \d+ to reopen$")
        self.assertNotIn("press r", found["reason"])

    def test_e_a_seat_nobody_is_in_says_which_number_reopens_it(self):
        for key in orch.CLOSED:
            with self.subTest(gone=key):
                seat = {**self.seat, key: True}
                found = watch.session_state("atoll", NOW, session=seat, cfg=self.cfg, number=3)
                self.assertEqual(found["word"], "needs you")
                self.assertEqual(found["reason"], "session closed: press 3 to reopen")
        # A harness that cannot prove which conversation it owned says so itself, and
        # that sentence is the rest of the reason: the number is about to start fresh.
        found = watch.session_state("atoll", NOW, cfg=self.cfg, number=3,
                                    session={**self.seat, "restart": "ownership unverified"})
        self.assertEqual(found["reason"],
                         "session closed: press 3 to reopen · ownership unverified")
        # An ending of its own never outranks it: the run is its orchestrator's business.
        self.receipt("20260101-0300-parser", state="fail", verdict="FAIL")
        found = watch.session_state("atoll", NOW, session={**self.seat, "exited": True},
                                    cfg=self.cfg, number=3)
        self.assertEqual(found["reason"], "session closed: press 3 to reopen")

    def test_f_a_done_notice_reads_done_with_its_first_line(self):
        notify.record("atoll", "done", "Merged #75\n\nThe loop pushes and merges now.")
        found = self.decide()
        self.assertEqual(found["word"], "done")
        self.assertEqual(found["reason"], "Merged #75")
        self.assertEqual(found["since"], notify.last("atoll")["time"])
        # Its own run going again outranks it: a done seat that started work is working.
        self.receipt("20260101-0900-next", state="running", finished_at=None,
                     started_at=NOW - 60, title="The next one")
        self.assertEqual(self.decide()["word"], "working")

    def test_g_at_its_prompt_with_nothing_running_is_needs_you(self):
        # Nothing recorded at all: it is his, and the reason says only that.
        self.assertEqual(self.decide(), {"word": "needs you", "reason": "waiting for you",
                                         "since": self.decide()["since"]})
        # A question it asked with `ak notify needs` is the reason.
        notify.record("atoll", "needs", "Which of the two schemas should it read?")
        found = self.decide()
        self.assertEqual((found["word"], found["reason"]),
                         ("needs you", "Which of the two schemas should it read?"))
        # ... and so is a question only its own ask hook reported.
        config.notify_path("atoll").unlink()
        self.fact("Notification", kind="permission_prompt",
                  text="Claude needs your permission to use Bash")
        self.pane = "streaming an answer"
        found = self.decide()
        self.assertEqual((found["word"], found["reason"]),
                         ("needs you", "Claude needs your permission to use Bash"))

    # --- and the screens that read it ---------------------------------------

    def test_h_the_menu_top_line_counts_only_needs_you(self):
        seats = []
        for name, kind in (("atoll", "needs"), ("parser", "working"), ("herdr", "done")):
            seats.append({**self.seat, "name": name})
            config.save_session(self.cfg, name, "fable", ["opus"],
                                {"repo": self.repo, "cwd": self.repo})
        self.receipt("20260101-0900-parser-work", owner="parser", state="running",
                     finished_at=None, started_at=NOW - 600, title="Parser work")
        notify.record("herdr", "done", "Shipped")
        with patch.object(orch, "listing", return_value=seats), \
                patch.object(menu.time, "time", return_value=NOW), \
                patch.object(terminal, "width", return_value=100), \
                patch.object(terminal, "height", return_value=40), \
                redirect_stdout(io.StringIO()) as out:
            menu.draw(self.cfg, seats)
        screen = out.getvalue()
        self.assertIn("your projects · 1 needs you", screen)
        # One needing seat, whatever the other two are, and the count says it once.
        self.assertEqual(len(re.findall(r"needs? you", screen)), 2)   # the line and the row
        self.assertIn("● working", screen)
        self.assertIn("✓ done", screen)

    def test_i_orch_list_prints_no_word_that_no_longer_exists(self):
        self.receipt("20260101-0900-going", state="running", finished_at=None,
                     started_at=NOW - 600, title="Going")
        seats = [self.seat, {**self.seat, "name": "ghost", "exited": True}]
        config.save_session(self.cfg, "ghost", "fable", ["opus"],
                            {"repo": self.repo, "cwd": self.repo})
        with patch.object(orch, "listing", return_value=seats), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(orch.cmd_list([]), 0)
        with patch.object(orch, "listing", return_value=seats), \
                redirect_stdout(io.StringIO()) as why:
            self.assertEqual(orch.cmd_list(["--why"]), 0)
        for screen in (out.getvalue(), why.getvalue()):
            for word in ("idle", "asking", "draft unsent", "stuck", "exited", "resumable",
                         "starts fresh", "legacy", "needs login", "unfinished",
                         "needs a look"):
                self.assertNotIn(word, screen, word)
            self.assertIn("working", screen)
        # `--why` keeps its evidence lines under the one word.
        self.assertIn("authority:", why.getvalue())
        self.assertIn("reason:", why.getvalue())

    def test_j_the_tmux_bar_carries_one_of_the_three_words(self):
        self.assertNotIn(orch.STATE_OPTION, self.options)   # a read never writes one
        for setup, word in ((lambda: self.receipt("20260101-0900-going", state="running",
                                                  finished_at=None, started_at=NOW - 60),
                             "working"),
                            (lambda: notify.record("atoll", "done", "Shipped"), "done"),
                            (lambda: notify.record("atoll", "needs", "Which schema?"),
                             "needs you")):
            with self.subTest(word=word):
                for old in config.RUNS.iterdir():
                    run.save_state(old, {**run.read_state(old), "state": "pass",
                                         "merged": True, "finished_at": NOW - 60})
                setup()
                self.assertEqual(self.decide()["word"], word)
                # a screen that draws a row publishes it; deciding alone writes nothing
                self.assertEqual(watch.announce_state(self.seat, cfg=self.cfg)["word"], word)
                self.assertEqual(self.options[orch.STATE_OPTION], word)
                self.assertIn(self.options[orch.STATE_OPTION], terminal.STATES)
                # tmux lost the option -- a failed set, or the seat given the name again:
                # the next screen says it again rather than waiting for the word to change.
                self.options.pop(orch.STATE_OPTION)
                watch.announce_state(self.seat, cfg=self.cfg)
                self.assertEqual(self.options[orch.STATE_OPTION], word)

    def test_k_one_function_decides_and_the_table_holds_three_words(self):
        self.assertEqual(list(terminal.STATES), ["working", "needs you", "done"])
        self.assertEqual(watch.WORDS, ("working", "needs you", "done"))
        for word, (mark, colour) in terminal.STATES.items():
            self.assertEqual(terminal.state_text(word), f"{mark} {word}")
            self.assertEqual(terminal.state_colour(word), colour)
        # Every screen's reading of a seat comes back through the one function.
        self.receipt("20260101-0900-going", state="running", finished_at=None,
                     started_at=NOW - 60, title="Going")
        self.assertEqual(menu.state(self.seat), "working")
        self.assertEqual(orch.state_word(self.seat, self.cfg), "working")
        self.assertEqual(menu.row(self.cfg, 1, self.seat)[3], "working")
        source = (REPO / "agentkit/menu.py").read_text()
        self.assertEqual(source.count("def session_state"), 0)
        self.assertEqual((REPO / "agentkit/watch.py").read_text().count("def session_state"), 1)

    def test_l_deciding_looks_at_nothing_and_writes_nothing(self):
        # The decision is a function of the facts handed to it: no capture, no record, no
        # option, no notice -- and none through a lookup either, which is what the bare
        # `session_state(name, now)` call below pins: the reconciling listing rewrites the
        # records it reads. `look_at` looks and `announce_state` remembers and publishes.
        self.receipt("20260101-0900-going", state="running", finished_at=None,
                     started_at=NOW - 60, title="Going")
        before = {path: path.read_bytes() for directory in (config.RUNS, config.STATE)
                  for path in directory.rglob("*") if path.is_file()}
        with patch.object(watch, "seat_write", side_effect=AssertionError("a read wrote")), \
                patch.object(config, "update_session",
                             side_effect=AssertionError("a read rewrote a record")), \
                patch.object(watch, "pane_text", side_effect=AssertionError("a read looked")):
            found = watch.session_state("atoll", NOW, session=self.seat, cfg=self.cfg)
            self.assertEqual(found["word"], "working")
            # ... and with nothing handed to it at all: the seat and its number are looked
            # up the reading way, so neither reconciles a record nor migrates a project.
            with patch.object(orch, "listing", wraps=orch.listing) as listed:
                bare = watch.session_state("atoll", NOW)
            self.assertEqual(bare["word"], "working")
            for call in listed.call_args_list:
                self.assertEqual(call.kwargs.get("reconcile", call.args and call.args[0]), False)
        self.assertNotIn(orch.STATE_OPTION, self.options)
        after = {path: path.read_bytes() for directory in (config.RUNS, config.STATE)
                 for path in directory.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        # Whoever draws a row is what writes the word down and publishes it.
        watch.announce_state(self.seat, cfg=self.cfg)
        self.assertEqual(watch.seat_read("atoll")["word"], "working")
        self.assertEqual(watch.seat_read("atoll")["word_since"], NOW - 60)

    def test_n_a_word_that_changes_starts_counting_again(self):
        # `since` is the beginning of this run of this word. A seat working for an hour,
        # blocked on a login ten minutes ago and unblocked now has been working since now:
        # the run it is on is older than the word, and the word is what the row says.
        self.receipt("20260101-0900-going", state="running", finished_at=None,
                     started_at=NOW - 3600, title="Going")
        self.assertEqual(self.decide()["since"], NOW - 3600)       # first sight: its evidence
        watch.announce_state(self.seat, cfg=self.cfg)
        state = watch.load_state()
        state["auth_out"] = {"claude": {"ok": False, "why": "expired", "at": NOW - 600}}
        watch.save_state(state)
        with patch.object(watch.time, "time", return_value=NOW - 600):
            blocked = watch.announce_state(self.seat, cfg=self.cfg)
        self.assertEqual((blocked["word"], blocked["since"]), ("needs you", NOW - 600))
        watch.save_state({**watch.load_state(), "auth_out": {}})
        with patch.object(watch.time, "time", return_value=NOW):
            freed = watch.announce_state(self.seat, cfg=self.cfg)
        self.assertEqual((freed["word"], freed["since"]), ("working", NOW))
        # A seat nobody is in any more starts counting from the change too, never nowhere.
        self.receipt("20260101-0900-going", state="pass", merged=True,
                     finished_at=NOW - 30, started_at=NOW - 3600)
        with patch.object(watch.time, "time", return_value=NOW + 60):
            closed = watch.announce_state({**self.seat, "exited": True}, cfg=self.cfg,
                                          number=1)
        self.assertEqual((closed["word"], closed["since"]), ("needs you", NOW + 60))
        # ... and a screen between two ticks is what recorded each of those beginnings.
        self.assertEqual(watch.seat_read("atoll")["word_since"], NOW + 60)

    def test_o_the_tick_publishes_last_and_for_a_seat_with_no_screen(self):
        # The bar carries what the pass concluded, not what it began with: a login this
        # tick found is on the bar when it ends, and a seat whose capture came back blank
        # is published all the same -- its harness is gone, which is the whole answer.
        # The pane is the trigger; the `auth` verb is what decides.
        self.pane = "Login expired \u00b7 Please run /login\n"
        self.token_ok = False
        logs = []
        with patch.object(notify, "shaped", return_value=0), \
                patch.object(watch, "type_into", return_value=True), \
                patch.object(notify, "progress", return_value=False):
            watch.health(self.cfg, watch.load_state(), False, logs.append)
        self.assertEqual(self.options[orch.STATE_OPTION], "needs you")
        self.assertIs(watch.load_state()["auth_out"]["claude"]["ok"], False)
        self.assertEqual(self.decide()["reason"],
                         "claude login expired: open it and run /login")
        self.token_ok = True
        # A blank capture on a closed seat still publishes: the tick is the only screen it
        # has, and `session closed: press 1 to reopen` is what its bar has to say.
        self.options.clear()
        self.pane = ""
        watch.forget("atoll")        # the login was fixed, the way opening the seat does it
        watch.save_state({**watch.load_state(), "auth_out": {}})
        self.assertNotIn("atoll", watch.load_state()["stalls"])
        closed = [{**self.seat, "exited": True}]
        with patch.object(orch, "sessions", return_value=closed), \
                patch.object(orch, "listing", return_value=closed), \
                patch.object(notify, "progress", return_value=False):
            watch.health(self.cfg, watch.load_state(), False, logs.append)
        self.assertEqual(self.options[orch.STATE_OPTION], "needs you")
        self.assertEqual(watch.seat_read("atoll")["reason"],
                         "session closed: press 1 to reopen")

    def test_p_no_row_ever_says_press_r(self):
        # Replaced, ownerless, superseded or his: no ending ever reaches a reason now.
        # A gone seat names its own number; `ak run status` is where runs are looked up.
        old = NOW - 2 * DAY
        self.receipt("20260101-0100-superseded", state="fail", verdict="FAIL",
                     title="Same title", finished_at=old, started_at=old - 1800)
        self.receipt("20260101-0200-replacement", state="pass", merged=True,
                     title="Same title", finished_at=NOW - 3600, started_at=NOW - 5400)
        self.receipt("20260101-0300-ownerless", owner=None, state="error",
                     finished_at=old, started_at=old - 1800)
        self.receipt("20260101-0400-his", state="fail", verdict="FAIL",
                     finished_at=old, started_at=old - 1800)
        for gone in (False, True):
            found = self.decide(gone=gone)
            self.assertNotIn("press r", found["reason"])
            self.assertNotRegex(found["reason"], r"run \S+ (failed|interrupted|not merged)")
        self.assertRegex(self.decide(gone=True)["reason"],
                         r"^session closed: press \d+ to reopen$")

    def test_q_a_stop_on_its_own_background_work_is_working_until_it_reports_back(self):
        # ak-verification, 2026-09-23: six checkers started in its harness, and `needs you` for
        # ten minutes.  Claude Code lists that work in the Stop payload, and the composer it
        # draws while it waits on it is no answer to anything.
        self.pane = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()
        payload = json.loads((REPO / "tests/fixtures/claude-stop-background.json").read_text())
        payload["transcript_path"] = self.transcript(payload.pop("last_assistant_message"))
        self.hooks("UserPromptSubmit", "seat-state.sh")
        self.assertEqual(self.hooks("Stop", *STOP, **payload), "")
        self.assertEqual(self.decide()["word"], "working")
        # a minute on, Claude says its prompt is idle, background work or not: it is not idle
        self.hooks("Notification", "seat-state.sh", notification_type="idle_prompt",
                   message="Claude is waiting for your input")
        self.assertEqual(self.decide()["word"], "working")
        # ... until it reports back: the notification starts a turn, which asks him something
        self.hooks("UserPromptSubmit", "seat-state.sh")
        payload.update(background_tasks=[],
                       transcript_path=self.transcript("Which of the two schemas should it read?"))
        self.assertEqual(self.hooks("Stop", *STOP, **payload), "")
        self.assertEqual(self.decide()["word"], "needs you")

    def test_r_a_stop_the_stop_hook_sent_back_is_working_and_the_third_is_his(self):
        self.hooks("UserPromptSubmit", "seat-state.sh")
        stop = {"transcript_path": self.transcript("Here is my recommendation. Let me know if "
                                                   "I should continue."), "background_tasks": []}
        # the two run side by side, either first: between them the row is the turn it was in
        for order in (STOP, STOP[::-1]):
            said = ""
            for script in order:
                said += self.hooks("Stop", script, **stop)
                self.assertEqual(self.decide()["word"], "working")
            self.assertIn('"block"', said)
            stop["stop_hook_active"] = True
        # the third stop of the turn stands: a seat that cannot go on is his again
        self.assertEqual(self.hooks("Stop", *STOP, **stop), "")
        self.assertEqual(self.decide()["word"], "needs you")

    def test_s_asking_leave_to_go_on_asks_him_nothing_and_the_seat_works_on(self):
        self.hooks("UserPromptSubmit", "seat-state.sh")
        leave = self.transcript("The parser is fixed.\n\nShall I continue?")
        self.assertIn('"block"', self.hooks("Stop", *STOP, transcript_path=leave,
                                            background_tasks=[]))
        self.assertEqual(self.decide()["word"], "working")
        # a choice only he can make still ends the turn, and is his
        asked = self.transcript("The parser is fixed.\n\nShould I proceed with SQLite or "
                                "PostgreSQL?")
        self.assertEqual(self.hooks("Stop", *STOP, transcript_path=asked, background_tasks=[],
                                    stop_hook_active=True), "")
        self.assertEqual(self.decide()["word"], "needs you")

    def test_m_the_tick_asks_about_this_pass_screen_and_never_the_last_ones(self):
        # A run of its own answers the ladder at its second rung, before any screen is
        # read. The hourly gates still have to be looking at the pane this pass captured:
        # asking about a seat that has been at its own prompt since is the bug this pins.
        self.receipt("20260101-0900-going", state="running", finished_at=None,
                     started_at=NOW - 600, title="Going")
        watch.seat_write("atoll", state="working", began=NOW - 7200)   # what a past pass saw
        self.pane = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()
        logs, state, now = [], watch.load_state(), time.time()
        state["stalls"]["atoll"] = {"since": now - watch.GIVE_UP - 1, "pane": self.pane,
                                    "changed_at": now - watch.GIVE_UP - 1,
                                    "stall_line": "",
                                    "stall_at": now - watch.GIVE_UP - 1}
        with patch.object(watch, "stalled_on", return_value="API Error"), \
                patch.object(watch, "stuck_on", return_value=True), \
                patch.object(watch, "type_into", return_value=True), \
                patch.object(notify, "progress", return_value=False), \
                patch.object(notify, "shaped", return_value=0) as card:
            watch.health(self.cfg, state, False, logs.append)
        card.assert_not_called()
        self.assertIn("sitting at its own prompt", " ".join(logs))
        self.assertEqual(watch.seat_read("atoll")["state"], "at_prompt")
        # ... and the word is still the running run's, written down by the same pass
        self.assertEqual(watch.seat_read("atoll")["word"], "working")

    def reboot_fixture(self, facts):
        """Seats with proven conversations, their hooks' last word, and a boot that changed."""
        for name, (event, kind) in facts.items():
            config.save_session(self.cfg, name, "fable", ["opus"],
                                {"repo": self.repo, "cwd": self.repo, "id_source": orch.LAUNCHER,
                                 "conversation": f"thread-{name}"})
            config.hook_facts_path(name).write_text(json.dumps(
                {"session": name, "event": event, "kind": kind, "at": NOW - 600}))
        watch.save_state({**watch.load_state(), "boot_id": "before"})
        live = []

        def reopened(cfg, name, **_kwargs):
            live.append({**self.seat, "name": name})
            # back at its prompt, which Claude's hook reports once it has sat there a minute
            config.hook_facts_path(name).write_text(json.dumps(
                {"session": name, "event": "Notification", "kind": "idle_prompt", "at": NOW - 1}))
            return "fresh" if name == "fresh" else "resumed"
        return live, reopened

    def prompted(self, name, at):
        """What hooks/seat-state.sh leaves for a prompt that went into that seat."""
        config.stop_path(name).write_text(json.dumps({"session": name, "turn": at, "blocks": 0}))

    def test_q_a_seat_the_host_ended_mid_turn_comes_back_working(self):
        # The host went down while the seat was in a turn: its hook's last word is a prompt
        # with no Stop after it, or its screen read the turn going again after a question it
        # asked was answered.  The first tick after the reboot reopens it on its own
        # conversation and tells it to continue that turn, the way a run's mid-turn resume
        # does; a seat that had finished its turn, or comes back fresh, is told nothing.
        live, reopened = self.reboot_fixture({
            "atoll": ("UserPromptSubmit", ""), "asked": ("Notification", "permission_prompt"),
            "idle": ("Stop", ""), "fresh": ("UserPromptSubmit", "")})
        watch.seat_write("asked", state="working", hooked="asking", hooked_at=NOW - 600)
        typed = []

        def send_line(session, text, log, landing=lambda: None):
            typed.append((session["name"], text))
            config.hook_facts_path(session["name"]).write_text(json.dumps(   # as it lands
                {"session": session["name"], "event": "UserPromptSubmit", "at": NOW}))
            self.prompted(session["name"], NOW)
            return True

        self.assertEqual(self.decide()["word"], "working")         # in its turn when it went
        with patch.object(watch, "boot_id", return_value="after"), \
                patch.object(orch, "sessions", side_effect=lambda: list(live)), \
                patch.object(orch, "resume", side_effect=reopened) as resume, \
                patch.object(watch, "_send_line", side_effect=send_line), \
                patch.object(watch.time, "sleep"):
            # the tick's own order: reopen, then tell
            watch.resume_after_boot(self.cfg, log=lambda _line: None)
            watch.continue_turns(self.cfg, lambda _line: None)
        self.assertEqual(sorted(call.args[1] for call in resume.call_args_list),
                         ["asked", "atoll", "fresh", "idle"])
        self.assertEqual(sorted(typed), [("asked", watch.MIDTURN_LINE),
                                         ("atoll", watch.MIDTURN_LINE)])
        self.assertIn("Continue that turn", watch.MIDTURN_LINE)
        self.assertEqual(self.decide()["word"], "working")
        # ... where, left alone at its prompt, it would have read needs you
        config.hook_facts_path("atoll").write_text(json.dumps(
            {"session": "atoll", "event": "Notification", "kind": "idle_prompt", "at": NOW}))
        self.assertEqual(self.decide()["word"], "needs you")

    def test_r_only_the_tick_types_the_line_and_only_until_it_lands(self):
        # A menu that reopens the seats only marks them: the tick types, and ticks never
        # overlap, so one mark is one line.  The mark is struck once the line lands, so a
        # send that failed -- or a tick killed in its warmup -- is tried by the next tick.
        live, reopened = self.reboot_fixture({"atoll": ("UserPromptSubmit", "")})
        landed, typed, logs = [False, True], [], []

        def send_line(session, text, log, landing=lambda: None):
            typed.append(session["name"])
            return landed.pop(0) if landed else False

        with patch.object(watch, "boot_id", return_value="after"), \
                patch.object(orch, "sessions", side_effect=lambda: list(live)), \
                patch.object(orch, "resume", side_effect=reopened) as resume, \
                patch.object(watch, "_send_line", side_effect=send_line), \
                patch.object(watch.time, "sleep"):
            watch.resume_after_boot(self.cfg, log=logs.append)
            self.assertEqual((typed, watch.seat_read("atoll")["midturn"]["boot"]), ([], "after"))
            watch.continue_turns(self.cfg, logs.append)
            self.assertEqual(watch.seat_read("atoll")["midturn"]["tries"], 1)
            watch.continue_turns(self.cfg, logs.append)
            self.assertEqual((typed, resume.call_count), (["atoll", "atoll"], 1))
            self.assertIsNone(watch.seat_read("atoll")["midturn"])
            # A seat prompted since it came back needs no line -- he took it up, and that
            # turn may still be going or already done -- nor does a mark another boot left.
            for boot, turn, event in (("after", NOW - 200, "UserPromptSubmit"),
                                      ("after", NOW - 200, "Stop"),
                                      ("before", NOW - 600, "UserPromptSubmit")):
                watch.seat_write("atoll", midturn={"boot": boot, "at": NOW - 300, "name": "atoll"})
                self.prompted("atoll", turn)
                self.fact(event, at=NOW - 100)
                watch.continue_turns(self.cfg, logs.append)
                self.assertIsNone(watch.seat_read("atoll")["midturn"])
            self.assertEqual(len(typed), 2)
            # ... and a line that never lands is given up after its tries, and said so.
            self.prompted("atoll", NOW - 600)
            self.fact("Notification", kind="idle_prompt", at=NOW - 100)
            watch.seat_write("atoll", midturn={"boot": "after", "at": NOW - 300, "name": "atoll",
                                               "tries": watch.MIDTURN_TRIES - 1})
            watch.continue_turns(self.cfg, logs.append)
        self.assertEqual(len(typed), 3)
        self.assertIsNone(watch.seat_read("atoll")["midturn"])
        self.assertIn(f"did not land in {watch.MIDTURN_TRIES} tries", logs[-1])

    def test_s_a_turn_the_owner_took_up_is_never_told_to_continue_whatever_its_name(self):
        # Read under the send's own lock, not before the warmup: a turn the owner took up while
        # the tick waited, for the warmup or for that lock, needs no line.  A seat renamed since
        # its reopen loses its mark, whenever it was renamed: its harness stamps prompts under
        # the name it was started with, not the one its stop file is read under now.
        live, reopened = self.reboot_fixture({"atoll": ("UserPromptSubmit", "")})
        typed, meanwhile, waiting, locking = [], [], [], notify.session_lock

        def rename(old, new):
            config.rename_session(old, new)
            live[0] = {**live[0], "name": new}

        def then(queue):
            while queue:
                queue.pop(0)()

        @contextmanager
        def session_lock(name):
            then(waiting)
            with locking(name) as held:
                yield held

        with patch.object(watch, "boot_id", return_value="after"), \
                patch.object(orch, "sessions", side_effect=lambda: list(live)), \
                patch.object(orch, "resume", side_effect=reopened), \
                patch.object(watch, "_send_line", side_effect=lambda s, *_a: typed.append(s)), \
                patch.object(notify, "session_lock", side_effect=session_lock), \
                patch.object(watch.time, "sleep", side_effect=lambda _s: then(meanwhile)):
            watch.resume_after_boot(self.cfg, log=lambda _line: None)
            meanwhile += [lambda: self.prompted("atoll", NOW - 50),
                          lambda: self.fact("Stop", at=NOW - 40)]
            watch.continue_turns(self.cfg, lambda _line: None)
            self.assertEqual((typed, watch.seat_read("atoll")["midturn"]), ([], None))
            # renamed before the tick, the owner's prompt stamped under its first name
            watch.seat_write("atoll", midturn={"boot": "after", "at": NOW - 45, "name": "atoll"})
            rename("atoll", "vega")
            self.prompted("atoll", NOW - 30)
            watch.continue_turns(self.cfg, lambda _line: None)
            self.assertEqual((typed, watch.seat_read("vega")["midturn"]), ([], None))
            # prompted, then renamed, while the tick waited
            watch.seat_write("vega", midturn={"boot": "after", "at": NOW - 20, "name": "vega"})
            meanwhile += [lambda: self.prompted("vega", NOW - 10), lambda: rename("vega", "rigel")]
            watch.continue_turns(self.cfg, lambda _line: None)
            self.assertEqual((typed, watch.seat_read("rigel")["midturn"]), ([], None))
            # prompted, or renamed, while the send waited for its lock
            watch.seat_write("rigel", midturn={"boot": "after", "at": NOW - 5, "name": "rigel"})
            waiting.append(lambda: self.prompted("rigel", NOW - 4))
            watch.continue_turns(self.cfg, lambda _line: None)
            self.assertEqual((typed, watch.seat_read("rigel")["midturn"]), ([], None))
            watch.seat_write("rigel", midturn={"boot": "after", "at": NOW - 3, "name": "rigel"})
            waiting.append(lambda: rename("rigel", "orion"))
            watch.continue_turns(self.cfg, lambda _line: None)
            self.assertEqual((typed, watch.seat_read("orion")["midturn"]), ([], None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
