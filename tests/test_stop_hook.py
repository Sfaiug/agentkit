"""An orchestrator turn ends with a question, a done, or a run to wait on; else it goes back.

Offline and deterministic: hooks/orchestrator-stop.sh is run as its harness runs it -- the
hook's own JSON on stdin -- against fake transcripts and a throwaway HOME, and the tick that
holds the same rule where a harness has no hook to hold it in is called directly.  No harness,
no network and nothing of the owner's is touched.
"""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, notify, orch, watch

HOOK = REPO / "hooks/orchestrator-stop.sh"
SEAT_STATE = REPO / "hooks/seat-state.sh"
SEAT = "stop-seat"
REASON = ("You stopped without asking the user a question, declaring done with ak notify done, "
          "or waiting on a run. Continue: decide the next step and do it.")
RECOMMENDATION = "Here is my recommendation. Let me know if I should continue."
STOOD = 300     # longer than watch.STALL_WAIT: how long a tick lets a screen stand
# The screen a Muse seat opens on, captured: its update notice, its banner and an empty
# composer.  Nothing on it is an answer, and no turn has ended behind it.
BANNER = (REPO / "tests/fixtures/muse-prompt-pane.txt").read_text()
# A real Claude Code 2.1.280 Stop payload with a background command and a background agent in
# flight; tests/fixtures/README.md says how it was captured.
BACKGROUND = REPO / "tests/fixtures/claude-stop-background.json"


def launched(task):
    """The transcript lines of a tool call Claude Code ran in the background, as it writes them."""
    use = f"toolu_{task['id']}"
    tool = "Agent" if task["type"] == "subagent" else "Bash"
    result = ({"isAsync": True, "status": "async_launched", "agentId": task["id"]}
              if tool == "Agent" else {"stdout": "", "backgroundTaskId": task["id"]})
    call = {"type": "tool_use", "id": use, "name": tool,
            "input": {"description": task["description"], "run_in_background": True}}
    answer = {"type": "tool_result", "tool_use_id": use, "content": "running in the background"}
    return [{"type": "assistant", "isSidechain": False,
             "message": {"role": "assistant", "content": [call]}},
            {"type": "user", "isSidechain": False, "toolUseResult": result,
             "message": {"role": "user", "content": [answer]}}]


def reported(task):
    """The task notification that work settling starts the seat's next turn with."""
    return {"type": "user", "isSidechain": False, "message": {"role": "user", "content": (
        f"<task-notification>\n<task-id>{task['id']}</task-id>\n"
        f"<tool-use-id>toolu_{task['id']}</tool-use-id>\n<status>completed</status>\n"
        "</task-notification>")}}


class StopHook(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".stop-hook-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit/state"
        self.runs = self.home / ".agentkit/runs"
        self.state.mkdir(parents=True)
        self.runs.mkdir(parents=True)
        self.turn = time.time() - 60
        self.latch(self.turn)

    # --- the fixtures a turn is judged from ---------------------------------

    def latch(self, turn, blocks=None):
        """What hooks/seat-state.sh leaves behind on UserPromptSubmit: this turn's start."""
        record = {"session": SEAT, "turn": turn, "blocks": 0 if blocks is None else blocks}
        (self.state / f"stop-{SEAT}.json").write_text(json.dumps(record) + "\n")

    def transcript(self, said, sidechain=None, before=()):
        """A Claude Code transcript whose last assistant message is `said`, `before` above it."""
        path = self.home / "transcript.jsonl"
        lines = [{"type": "user", "message": {"role": "user", "content": "go"}}, *before,
                 {"type": "assistant", "isSidechain": False,
                  "message": {"role": "assistant", "content": [{"type": "text", "text": said}]}}]
        if sidechain is not None:
            lines.append({"type": "assistant", "isSidechain": True,
                          "message": {"role": "assistant",
                                      "content": [{"type": "text", "text": sidechain}]}})
        path.write_text("".join(json.dumps(line) + "\n" for line in lines))
        return path

    def notified(self, kind, when):
        (self.state / f"notify-{SEAT}.json").write_text(json.dumps(
            {"session": SEAT, "kind": kind, "text": "something", "time": when}) + "\n")

    def run_json(self, name, **fields):
        directory = self.runs / name
        directory.mkdir()
        (directory / "run.json").write_text(json.dumps(
            {"run_id": name, "launched_session": SEAT, **fields}) + "\n")

    # --- driving the hook the way the harness does --------------------------

    def stop(self, said=RECOMMENDATION, env=None, hook=HOOK, **payload):
        """One end-of-turn hook call; the answer is what the harness reads off stdout."""
        if said is not None and "transcript_path" not in payload:
            payload["transcript_path"] = str(self.transcript(said))
        payload.setdefault("hook_event_name", "Stop")
        payload.setdefault("session_id", "fake")
        environment = {"PATH": os.environ["PATH"], "HOME": str(self.home),
                       "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator"}
        environment.update(env or {})
        done = subprocess.run(["bash", str(hook)], input=json.dumps(payload), text=True,
                              capture_output=True, env=environment)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def blocked(self, output):
        self.assertTrue(output.strip(), "the hook allowed the stop")
        return json.loads(output)

    def read_as(self):
        """(state, event) a Claude seat's row reads off what its hooks have written down."""
        with patch.object(config, "STATE", self.state):
            return watch.hook_state("claude", watch.hook_facts(SEAT))[:2]

    # --- the three endings a turn is allowed --------------------------------

    def test_a_question_in_the_last_paragraph_allows_the_stop(self):
        self.assertEqual(self.stop("I found two options.\n\nWhich one do you want?"), "")
        # ... and one buried above the last paragraph is not the question the user was asked
        self.assertEqual(self.blocked(self.stop("Which one?\n\nI will go with the first."))
                         ["decision"], "block")

    def test_a_question_that_asks_only_leave_to_go_on_is_sent_back_on_claude(self):
        """"Here is my recommendation, let me know if I should continue", with the mark on it.

        On Claude Code, whose Stop hands over `background_tasks`.  A harness that does not has
        its questions judged as they always were: the last case here, and Codex's further down.
        The last sentence is taken whole, and only a bare request for leave is sent back.
        """
        for asked in ("Shall I continue?", "Should I proceed?", "Shall I go ahead?",
                      "Want me to continue?", "Let me know if I should continue?",
                      "OK to proceed?", "Would you like me to keep going?",
                      # whatever case and marks it wears, and whatever was said before it
                      "SHALL I CONTINUE?!", "**Shall I go on?**",
                      "- Parser fixed.\n- Tests pass.\nShall I go on?",
                      "The parser is fixed. Should we proceed?"):
            with self.subTest(asked=asked):
                self.latch(self.turn)
                self.assertEqual(self.blocked(self.stop(f"{RECOMMENDATION}\n\n{asked}",
                                                        background_tasks=[]))["reason"], REASON)
        # any other question is one the user has to answer: one that asks for something or
        # offers a choice before or after asking leave, beside it, or instead of it
        for asked in ("Can you send the missing schema; shall I continue once I have it?",
                      "Want me to fix the parser or review the deployment configuration?",
                      "Which schema should it read? Shall I continue?",
                      "Which schema should it read? Shall I continue with the parser meanwhile?",
                      "Shall I continue with docs/guide.md?", "Shall I continue or not?",
                      "Which of the two should I merge first?",
                      "Which database do you want me to use?",
                      "**Next step:** which schema should it read?",
                      "Should I proceed with SQLite or PostgreSQL?",
                      "Which one do you want, or shall I pick the first?"):
            with self.subTest(asked=asked):
                self.latch(self.turn)
                self.assertEqual(self.stop(f"{RECOMMENDATION}\n\n{asked}", background_tasks=[]),
                                 "")
        # ... and a harness with no background work to tell is judged as it always was
        self.latch(self.turn)
        self.assertEqual(self.stop(f"{RECOMMENDATION}\n\nShall I continue?"), "")

    def test_a_needs_or_done_recorded_this_turn_allows_the_stop(self):
        for kind in ("needs", "done"):
            with self.subTest(kind=kind):
                self.latch(self.turn)
                self.notified(kind, self.turn + 1)
                self.assertEqual(self.stop(), "")

    def test_a_notification_from_an_earlier_turn_does_not_allow_it(self):
        self.notified("done", self.turn - 600)
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)

    def test_a_run_launched_during_the_turn_allows_the_stop(self):
        self.run_json("finished", state="done", started_at=self.turn + 5,
                      finished_at=self.turn + 6)
        self.assertEqual(self.stop(), "")

    def test_an_unfinished_run_of_this_seat_allows_the_stop(self):
        for state in ("queued", "running", "waiting", "exhausted", "stalled"):
            with self.subTest(state=state):
                self.setUp()
                (self.state / f"session-{SEAT}.json").write_text("{}\n")
                self.run_json("old", state=state, started_at=self.turn - 9000,
                              finished_at=self.turn - 60)
                self.assertEqual(self.stop(), "")

    def test_another_seats_run_is_no_reason_to_stop(self):
        directory = self.runs / "theirs"
        directory.mkdir()
        (directory / "run.json").write_text(json.dumps(
            {"run_id": "theirs", "launched_session": "other-seat", "state": "running"}) + "\n")
        self.assertEqual(self.blocked(self.stop())["reason"], REASON)

    def test_a_stop_on_its_own_background_work_is_a_wait_until_that_work_reports(self):
        """ak-verification, 2026-09-23: six checkers going in the harness, and sent back twice.

        Claude Code hands its Stop hook the work it still has in flight -- the captured payload
        holds a background command and a background agent -- and a stop on that work stands
        without counting against the turn.  This hook writes it down as a `background` Stop,
        which is working, and hooks/seat-state.sh beside it leaves it be.  Once the work has
        reported back the list is empty, and the ending is judged as ever.
        """
        payload = json.loads(BACKGROUND.read_text())
        tasks = payload["background_tasks"]
        before = [line for task in tasks for line in launched(task)]
        payload["transcript_path"] = str(self.transcript(payload["last_assistant_message"],
                                                         before=before))
        self.assertEqual(self.stop(said=None, **payload), "")
        self.stop(said=None, hook=SEAT_STATE, **payload)
        self.assertEqual(self.read_as(), ("working", "Stop/background"))
        self.assertEqual(json.loads((self.state / f"stop-{SEAT}.json").read_text())["blocks"], 0)
        # ... and it reports back: the notifications start a turn, which ends on nothing
        payload.update(background_tasks=[], last_assistant_message=RECOMMENDATION,
                       transcript_path=str(self.transcript(RECOMMENDATION, before=before + [
                           reported(task) for task in tasks])))
        self.assertEqual(self.blocked(self.stop(said=None, **payload))["reason"], REASON)
        self.assertEqual(self.read_as(), ("working", "Stop/held"))

    # --- what happens to a turn that ended on none of them ------------------

    def test_a_plain_recommendation_is_blocked_with_the_rule_it_broke(self):
        decision = self.blocked(self.stop())
        self.assertEqual(decision, {"decision": "block", "reason": REASON})

    def test_a_stop_sent_back_is_the_turn_going_on_before_either_hook_and_after(self):
        """On Claude Code this hook writes the Stop down, and only once it has judged it.

        The two hooks run side by side and either can finish first, so what the row reads
        between them is the turn it was already in, never a Stop nobody has judged yet; the
        third stop of the turn stands, and reads as the seat at its prompt.
        """
        for order in ((SEAT_STATE, HOOK), (HOOK, SEAT_STATE)):
            with self.subTest(first=order[0].name):
                self.setUp()
                self.stop(said=None, hook=SEAT_STATE, hook_event_name="UserPromptSubmit")
                payload = {"transcript_path": str(self.transcript(RECOMMENDATION)),
                           "background_tasks": [], "stop_hook_active": False}
                for _ in range(2):
                    answers = []
                    for hook in order:
                        answers.append(self.stop(said=None, hook=hook, **payload))
                        self.assertEqual(self.read_as()[0], "working")
                    self.assertEqual(self.blocked("".join(answers))["reason"], REASON)
                    self.assertEqual(self.read_as(), ("working", "Stop/held"))
                    payload["stop_hook_active"] = True
                self.assertEqual([self.stop(said=None, hook=hook, **payload) for hook in order],
                                 ["", ""])
                self.assertEqual(self.read_as(), ("at_prompt", "Stop"))

    def test_the_third_stop_of_one_turn_is_allowed(self):
        self.assertEqual(self.blocked(self.stop())["decision"], "block")
        self.assertEqual(self.blocked(self.stop())["decision"], "block")
        self.assertEqual(self.stop(), "")
        self.assertEqual(json.loads((self.state / f"stop-{SEAT}.json").read_text())["blocks"], 2)

    def test_a_new_user_prompt_resets_the_counter(self):
        self.blocked(self.stop())
        self.blocked(self.stop())
        self.assertEqual(self.stop(), "")
        # the prompt hook the harness already runs is what starts the next turn
        subprocess.run(["bash", str(SEAT_STATE)], text=True,
                       input=json.dumps({"hook_event_name": "UserPromptSubmit"}),
                       env={"PATH": os.environ["PATH"], "HOME": str(self.home),
                            "AGENTKIT_SESSION": SEAT, "AK_RUN_ROLE": "orchestrator",
                            "IDLE_COMPACT_STATE": ""}, check=True)
        record = json.loads((self.state / f"stop-{SEAT}.json").read_text())
        self.assertEqual(record["blocks"], 0)
        self.assertGreater(record["turn"], self.turn)
        self.assertEqual(self.blocked(self.stop())["decision"], "block")

    # --- who this hook may never speak for ----------------------------------

    def test_a_worker_process_is_untouched(self):
        for env in ({"AK_RUN_ROLE": "worker"}, {"AGENTKIT_SESSION": ""}):
            with self.subTest(env=env):
                self.assertEqual(self.stop(env=env), "")
        self.assertEqual(json.loads((self.state / f"stop-{SEAT}.json").read_text())["blocks"], 0)

    # --- nothing to judge on is never a reason to block ---------------------

    def test_a_turn_with_no_start_written_down_is_left_alone(self):
        (self.state / f"stop-{SEAT}.json").unlink()
        self.assertEqual(self.stop(), "")

    def test_an_unreadable_transcript_is_left_alone(self):
        self.assertEqual(self.stop(said=None, transcript_path=str(self.home / "gone.jsonl")), "")
        self.assertEqual(self.stop(said=None), "")

    def test_a_payload_no_argument_list_would_carry_still_decides(self):
        """A turn that moved a lot of tool output is still a turn this has to judge."""
        said = RECOMMENDATION + "\n\n" + "detail. " * 20_000     # past Linux's 128 KB limit
        self.assertGreater(len(said), 128 * 1024)
        self.assertEqual(self.blocked(self.stop(said=None, last_assistant_message=said))
                         ["reason"], REASON)
        self.latch(self.turn)
        self.assertEqual(self.stop(said=None, last_assistant_message=said + "\n\nShall I?"), "")

    # --- the other shape the same hook is handed ----------------------------

    def test_codex_hands_the_message_itself_and_a_sidechain_is_not_it(self):
        self.assertEqual(self.stop(said=None, last_assistant_message="Shall I go on?"), "")
        self.assertEqual(self.blocked(self.stop(said=None, last_assistant_message="Done that."))
                         ["reason"], REASON)
        # a sub agent's question below this seat's own last word is not this seat's question
        payload = {"transcript_path": str(self.transcript(RECOMMENDATION, sidechain="Which?"))}
        self.assertEqual(self.blocked(self.stop(said=None, **payload))["reason"], REASON)


class StopNudge(unittest.TestCase):
    """The same rule where no hook can hold it: `ak watch` reads it off the seat's screen.

    Through `watch.health`, the way cron reaches it, because what a tick hands the rule --
    a whole captured pane, and only when the seat is neither stalled nor stuck -- is half of
    what the rule reads.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".stop-nudge-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "AK_RUN_ROLE": "orchestrator",
            "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": ""}))
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(redirect_stderr(io.StringIO()))
        config.ensure_dirs()
        self.now = 100000.0
        self.stack.enter_context(patch.object(watch.time, "time", lambda: self.now))
        self.harness, self.records = "muse", []
        self.stack.enter_context(patch.object(orch, "sessions", lambda: [{"name": SEAT}]))
        self.stack.enter_context(patch.object(orch, "records", return_value={}))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              lambda *_: (self.harness, "meta")))
        self.stack.enter_context(patch.object(menu, "run_records", lambda: list(self.records)))
        self.stack.enter_context(patch.object(notify, "progress", return_value=None))
        self.pane = BANNER
        self.stack.enter_context(patch.object(watch, "pane_text", lambda _: self.pane))
        self.typed = self.stack.enter_context(
            patch.object(watch, "type_into", return_value=True))
        self.data, self.logs = watch.load_state(), []
        self.tick()     # the seat is opened, and something looks at the screen it opened on

    def showing(self, said, footer=""):
        """A Muse pane: what the seat last said, a blank line, then its composer and footer."""
        return f"{said}\n\n⟩\n{footer}" if footer else f"{said}\n\n⟩"

    def working(self, said):
        """The same, mid-turn: Muse draws its interrupt hint where the composer would be."""
        return f"{said}\n\nesc to interrupt"

    def drafting(self, said):
        """The same, with the user part way through a line they have not sent."""
        return f"{said}\n\n⟩ and now about the parser"

    def draw(self, pane):
        """What a menu draw does to a seat: classify it, and write down what it found."""
        self.now += STOOD
        self.pane = pane
        watch.live_state({"name": SEAT}, self.harness, pane=pane)

    def tick(self, seconds=STOOD, dry=False):
        """One `ak watch` pass, a stood prompt later; cron's own reach into the rule."""
        self.now += seconds
        watch.health({}, self.data, dry, self.logs.append)

    def stopped(self, said, footer=""):
        """The seat ends a turn on that, and the ticks that find it run.

        Two of them, because the words a seat stopped on have to stand for STALL_WAIT before
        anything is typed at them: the first look is what they stand from, and the second is
        when they have.
        """
        self.pane = self.showing(said, footer)
        self.tick()
        self.tick()

    # --- the rule, as a tick reaches it -------------------------------------

    def test_a_prompt_with_no_question_no_done_and_no_run_is_typed_into_once(self):
        self.stopped(RECOMMENDATION)
        self.tick()
        self.assertEqual([call.args[1] for call in self.typed.call_args_list], ["continue"])
        # ... and again once the seat has said something else and stopped on that
        self.stopped("Still just a recommendation.")
        self.assertEqual(self.typed.call_count, 2)

    def test_a_question_a_done_or_an_unfinished_run_holds_it_back(self):
        runs = [(Path("/runs/one"), {"launched_session": SEAT, "state": "running"})]
        for label, prepare in (
                ("a question", lambda: setattr(self, "pane", self.showing("Shall I merge it?"))),
                ("a done", lambda: notify.record(SEAT, "done", "shipped")),
                ("a run", lambda: self.records.extend(runs))):
            with self.subTest(case=label):
                self.setUp()
                self.pane = self.showing(RECOMMENDATION)
                prepare()
                self.tick()
                self.tick()
                self.typed.assert_not_called()

    def test_a_question_over_two_lines_is_one_and_a_decision_under_one_is_not(self):
        """pane_tail keeps no blank line, so the rule reads the pane and not its tail."""
        self.stopped("Which branch do you want?\nmain or release.")
        self.typed.assert_not_called()
        # the same words with the seat's own answer under them are not a question for the user
        self.stopped("Which one?\n\nI will go with the first.")
        self.assertEqual(self.typed.call_count, 1)

    # --- a turn nobody watched running is still a turn ----------------------

    def test_a_first_turn_that_ended_between_ticks_is_enforced(self):
        """Nothing here has to catch a seat working: the output is the evidence it did."""
        self.stopped(RECOMMENDATION)
        self.assertEqual(self.typed.call_count, 1)

    def test_a_short_turn_between_two_looks_is_a_turn_and_an_episode_of_its_own(self):
        """No tick and no draw falls inside either turn; the words they left behind mark them."""
        self.stopped(RECOMMENDATION)
        self.assertEqual(self.typed.call_count, 1)
        first = watch.seat_read(SEAT)["turn_began"]
        self.stopped("A second recommendation.")
        self.assertGreater(watch.seat_read(SEAT)["turn_began"], first)
        self.assertEqual(self.typed.call_count, 2)

    def test_a_seat_at_the_screen_its_harness_opened_on_is_never_typed_into(self):
        """A banner and an update notice are not an answer, and no turn ended behind them."""
        for _ in range(8):                          # however long it is left standing there
            self.tick()
        self.typed.assert_not_called()
        self.assertIsNone(watch.seat_read(SEAT).get("turn_began"))
        self.stopped(RECOMMENDATION)                # ... and the first real turn is enforced
        self.assertEqual(self.typed.call_count, 1)

    def test_a_done_from_a_turn_the_user_has_already_replied_to_does_not_exempt(self):
        notify.record(SEAT, "done", "shipped")
        self.stopped("The job is finished.")
        self.typed.assert_not_called()          # the turn that said it is the one on screen
        self.stopped(RECOMMENDATION)            # a turn later, under the same done
        self.assertEqual(self.typed.call_count, 1)

    def test_a_done_expires_when_a_turn_begins_after_it_however_that_turn_was_seen(self):
        """A turn beginning after a done is the user's reply, and answers it.

        The menu draws a row far oftener than cron ticks, so the turn that answers a done is
        commonly one no tick ever sees running.  live_state stamps it for whoever looked, and
        the words repeating is no reason to hold a done that has been answered.
        """
        notify.record(SEAT, "done", "shipped")
        self.stopped("The job is finished.")
        self.typed.assert_not_called()          # the turn that said it is the one on screen
        self.draw(self.working("The job is finished."))     # a menu draw, between ticks
        self.stopped("The job is finished.")    # ... and it stops on the same words again
        self.assertEqual(self.typed.call_count, 1)

    def test_a_done_never_seen_by_a_tick_does_not_exempt_the_job_after_it(self):
        """Job A's done, job B's recommendation, and not one tick between them.

        Every look at A belongs to the menu, so nothing binds the done at A's prompt and the
        first tick to reach the rule is looking at B.  The turn B began is what answers it.
        """
        self.draw(self.working("Halfway through job A."))
        notify.record(SEAT, "done", "shipped")      # A finishes and says so
        self.draw(self.showing("Job A is finished."))            # a menu draw, not a tick
        self.draw(self.working("Starting job B."))               # ... and another
        self.stopped(RECOMMENDATION)                # the first tick sees only B, stopped
        self.assertEqual(self.typed.call_count, 1)

    def test_a_done_recorded_under_a_turn_a_menu_draw_saw_start_still_holds(self):
        """The other way round: the turn began, then the done.  It is that turn's own."""
        self.draw(self.working("Halfway through the job."))
        notify.record(SEAT, "done", "shipped")
        self.stopped("The job is finished.")
        self.typed.assert_not_called()

    # --- what the user does in the composer is their business ---------------

    def test_a_draft_typed_and_cleared_neither_answers_a_done_nor_reopens_an_episode(self):
        """Editing a line and thinking better of it begins no turn and ends none."""
        self.draw(self.working("Halfway through the job."))
        notify.record(SEAT, "done", "shipped")  # recorded under the turn that just started
        self.stopped("The job is finished.")
        self.typed.assert_not_called()
        for state in (self.drafting("The job is finished."),     # they start typing
                      self.showing("The job is finished.")):     # ... and clear it again
            self.draw(state)
        self.stopped("The job is finished.")
        self.typed.assert_not_called()          # the done it finished on still stands

    def test_a_draft_typed_and_cleared_does_not_earn_a_second_keystroke(self):
        self.stopped(RECOMMENDATION)
        self.assertEqual(self.typed.call_count, 1)
        began = watch.seat_read(SEAT)["turn_began"]
        for state in (self.drafting(RECOMMENDATION), self.showing(RECOMMENDATION)):
            self.draw(state)
        # the words start standing again, but no turn ended: the episode is the same one
        self.assertEqual(watch.seat_read(SEAT)["turn_began"], began)
        self.stopped(RECOMMENDATION)
        self.assertEqual(self.typed.call_count, 1)

    def test_output_moving_under_one_long_turn_never_ages_that_turn_s_done(self):
        """Mid-turn output is not a turn ending: only what it stopped on dates the done."""
        for said in ("Reading the tests.", "Rewriting the parser."):
            self.pane = self.working(said)      # ticks land inside one long turn
            self.tick()
        notify.record(SEAT, "done", "shipped")  # ... which says it is done and keeps talking
        for said in ("Running the suite.", "Writing the summary."):
            self.pane = self.working(said)
            self.tick()
        self.stopped("All of it is done.")
        self.typed.assert_not_called()

    def test_a_missed_turn_clears_the_episode_the_last_nudge_belonged_to(self):
        self.stopped(RECOMMENDATION)
        self.assertEqual(self.typed.call_count, 1)
        self.stopped("Working on it.\n\nHere is another recommendation.")
        self.assertEqual(self.typed.call_count, 2)

    def test_the_episode_is_the_output_and_not_the_pane_holding_it(self):
        self.stopped(RECOMMENDATION)
        self.assertEqual(self.typed.call_count, 1)
        # the same words under a footer that repainted are the same episode
        self.stopped(RECOMMENDATION, footer="muse-spark-1.3-contributor · high · ~ · YOLO")
        self.assertEqual(self.typed.call_count, 1)

    def test_work_a_menu_draw_saw_ends_the_episode_even_on_the_same_words(self):
        """The episode is this prompt as well as its words, and a draw starts prompts too."""
        self.stopped(RECOMMENDATION)
        self.assertEqual(self.typed.call_count, 1)
        # no tick falls inside the turn; the menu draws while it runs, as every screen does
        self.draw(self.working(RECOMMENDATION))
        self.assertEqual(watch.seat_read(SEAT)["state"], "working")
        self.stopped(RECOMMENDATION)            # ... and it stops on the same words again
        self.assertEqual(self.typed.call_count, 2)

    def test_a_turn_that_ended_on_the_same_words_still_has_to_stand(self):
        """Coming back to the prompt starts the words standing again, identical or not.

        Otherwise the moment they are read as the old ones they are read as old enough, and
        the keystroke lands on a turn that has only just ended.
        """
        self.stopped(RECOMMENDATION)
        self.assertEqual(self.typed.call_count, 1)
        self.draw(self.working(RECOMMENDATION))     # a turn, seen only by a menu draw
        self.pane = self.showing(RECOMMENDATION)    # ... ending on the very same words
        self.tick(seconds=1)
        self.assertEqual(self.typed.call_count, 1)  # they have stood for a second
        self.tick(seconds=watch.STALL_WAIT)
        self.assertEqual(self.typed.call_count, 2)

    # --- and what the rule may never do -------------------------------------

    def test_a_seat_that_is_visibly_mid_turn_is_never_typed_into(self):
        """Working, asking or drafting, on this harness's own captured screens.

        However long any of them stands: a turn that has not ended has not broken the rule,
        and the keystroke would land in the middle of it.
        """
        for kind, state in (("working", "working"), ("dialog", "asking"), ("draft", "draft")):
            with self.subTest(kind=kind):
                self.setUp()
                opened = watch.seat_read(SEAT)["stop_said"]
                self.pane = (REPO / f"tests/fixtures/muse-{kind}-pane.txt").read_text()
                for _ in range(4):
                    self.tick()
                self.assertEqual(watch.seat_read(SEAT)["state"], state)
                # nothing it shows mid-turn is words it has stopped on
                self.assertEqual(watch.seat_read(SEAT)["stop_said"], opened)
                self.typed.assert_not_called()

    def test_a_composer_the_user_is_typing_into_is_never_appended_to(self):
        """The decision is made on this pass's capture; the seat is read again before typing."""
        for moved in (f"{RECOMMENDATION}\n\n⟩ merge it for me",   # a draft, half typed
                      self.working(RECOMMENDATION)):                # already working again
            with self.subTest(moved=moved):
                self.setUp()
                self.pane = self.showing(RECOMMENDATION)
                self.tick()                  # the prompt this pass's decision stands from
                reads = []

                def capture(_, moved=moved):
                    reads.append(None)       # the pass's own capture, then the seat since
                    return self.pane if len(reads) == 1 else moved

                with patch.object(watch, "pane_text", capture):
                    self.tick()
                self.typed.assert_not_called()

    def test_a_prompt_that_has_not_stood_is_left_alone(self):
        self.pane = self.showing(RECOMMENDATION)
        self.tick(seconds=1)
        self.tick(seconds=watch.STALL_WAIT - 2)
        self.typed.assert_not_called()
        self.tick(seconds=2)
        self.assertEqual(self.typed.call_count, 1)

    def test_a_harness_that_decides_in_its_own_hook_is_never_typed_into(self):
        for harness in ("claude", "codex"):
            with self.subTest(harness=harness):
                self.setUp()
                self.harness = harness
                self.assertFalse(watch.stop_enforced(harness))
                self.stopped(RECOMMENDATION)
                self.typed.assert_not_called()

    def test_a_failed_pass_over_the_runs_is_no_reason_to_type(self):
        with patch.object(menu, "run_records", side_effect=OSError("no runs")):
            self.stopped(RECOMMENDATION)
        self.typed.assert_not_called()

    def test_a_dry_run_says_what_it_would_type_and_neither_types_nor_writes(self):
        notify.record(SEAT, "done", "shipped")  # the one leg that would write on its own
        self.pane = self.showing(RECOMMENDATION)
        self.tick()
        before = watch.seat_read(SEAT)
        self.tick(dry=True)
        self.tick(dry=True)
        self.typed.assert_not_called()
        self.assertEqual(watch.seat_read(SEAT), before)
        self.assertNotIn("would resume", " ".join(self.logs))   # the done still holds it
        notify.clear(SEAT)
        self.tick(dry=True)
        self.typed.assert_not_called()
        self.assertIn("would resume", " ".join(self.logs))
        self.assertEqual(watch.seat_read(SEAT), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
