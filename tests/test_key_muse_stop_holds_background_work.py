"""A Muse seat's Stop names the background work it still has in flight, as a Claude seat's does.

A seat's harness ending ends its background work with it.  So each Stop records what the seat
holds, the type of each piece (`holds`), and a seat holding work leaves an account with usage
left only once it is spent.  Muse's Stop payload lists none of it, so its adapter reads the
session's own log: a terminal, a sub-agent or a workflow it linked `background` and has not
logged the end of.  Its reminders are Muse's, not the seat's.

Black-box: the program `AK_BIN` names opens a Muse seat from a person's terminal
(tests/fixtures/akterm.py) on a fake muse that keeps the line it was started with, and each hook
is fired as Muse fires it.  The hook payloads and the session.jsonl records are copied, ids
invented, from a live Muse 1.4.12 seat on this host (`muse-spark-1.3`, 26 Oct 2026) that started
`sleep` as a background terminal and a sub-agent: its SessionStart and Stop payloads, and the
records its session.jsonl held when that Stop fired and once both had ended.  What a resumed
session logs of the work its killed process held is copied the same way from a Muse 1.4.13 seat
(`muse-wonder-full-1.0`, 27 Oct 2026) whose harness was ended under its terminal and sub-agent.
The tick meets usage readings the test writes, and no provider.
"""

import json
import os
import shlex
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig
from fixtures.akbin import REAL_TMUX, Home, boxable
from fixtures.akseat import FIXTURES, PANE
from fixtures.akterm import Terminal

SESSION = "01a17700-0000-7000-8000-00000000acme"
RUN = "01a17700-0000-7000-8000-0000000000a1"
SHELL, AGENT, REMINDER = (f"01a17700-0000-7000-8000-0000000000{n}" for n in ("b1", "b2", "b3"))
SAID = {"cwd": "/home/acme/code/fix-api", "model": "muse-spark-1.3", "model_provider": "meta",
        "permission_mode": "bypassPermissions", "session_id": SESSION, "transcript_path": None}
STARTED = {**SAID, "hook_event_name": "SessionStart", "source": "startup"}
STOPPED = {**SAID, "hook_event_name": "Stop", "stop_hook_active": False,
           "last_assistant_message": "Started both; ending turn.",
           "turn_id": "01a17700-0000-7000-8000-0000000000c1"}

MUSE = """#!/bin/sh
if [ "$1 $2 $3" = "schema generate-json-schema --out" ]; then
  exec echo '{{"hook_event": {{"enum": ["stop", "notification"]}}}}' >"$4/muse.schema.json"
fi
[ -t 0 ] || exit 1
{python} -c 'import json, sys; json.dump(sys.argv[2:], open(sys.argv[1], "w"))' {root}/argv.json "$@"
exec {python} {pane} {screen} {root}/typed
"""


def linked(task, kind, **display):
    """A task Muse started in the background: its stream linked, then its kind proposed."""
    stream = {"id": task, "kind": "task"}
    return [("runtime.session", {"event": {**({"display": display} if display else {}),
                                           "execution_mode": "background",
                                           "kind": "task_stream_linked", "task_id": task,
                                           "task_stream": stream},
                                 "kind": "run", "run_id": RUN}),
            ("runtime.session", {"event": {"kind": "proposed", "task_id": task, "task_kind": kind},
                                 "kind": "task", "run_id": RUN, "task_id": task})]


STARTED_WORK = [*linked(SHELL, "tool.bash", prompt_preview="sleep 75"),
                *linked(AGENT, "workflow.agent.native"),
                *linked(REMINDER, "reminder.agent.goal-reminder", label="goal-reminder reminder",
                        model="same-as-main", role="reminder")]
ENDED_WORK = [
    ("runtime.session", {"event": {"kind": "completed", "task_id": SHELL}, "kind": "task",
                         "run_id": RUN, "task_id": SHELL}),
    ("subagent.control.result_ready", {"kind": "subagent_control", "record": {
        "artifact_refs": [], "attempt_ref": {"task_id": AGENT,
                                             "task_stream": {"id": AGENT, "kind": "task"}},
        "error_kind": None, "evidence_refs": [], "final_message_chars": 2, "kind": "result_ready",
        "result_channel": "final_text", "result_not_quiescent_rejections": 0,
        "result_report_nudges": 0, "result_report_outcome": "reported",
        "result_validation_rejections": 0, "source_provider_item_ids": [],
        "subagent_id": "01a17700-0000-7000-8000-0000000000d1", "summary": "ok",
        "task_terminal_ref": {"sequence": 5, "task_id": AGENT, "task_stream": f"task/{AGENT}"},
        "text": "ok", "transcript_path": None}})]
LOST_WORK = [       # the resumed session's own account of what the dead process ran
    ("runtime.session", {"event": {"kind": "cancelled", "task_id": SHELL,
                                   "reason": "resume_reconcile:orphaned_by_process_loss"},
                         "kind": "task", "run_id": RUN, "task_id": SHELL}),
    ("subagent.control.recovery_available", {"kind": "subagent_control", "record": {
        "kind": "recovery_available",
        "lost_attempt_ref": {"task_id": AGENT, "task_stream": {"id": AGENT, "kind": "task"}},
        "parent_session_id": SESSION, "reason": "runtime_restarted_without_live_child_handle",
        "recovery_terminal_ref": {"sequence": 5, "task_id": AGENT,
                                  "task_stream": f"task/{AGENT}"},
        "subagent_id": "01a17700-0000-7000-8000-0000000000d1", "wake_policy": "do_not_wake"}})]


def until(test, what, bound=60):
    deadline = time.monotonic() + bound
    while not test():
        if time.monotonic() > deadline:
            raise AssertionError(f"never {what}")
        time.sleep(0.05)


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class MuseStopHoldsBackgroundWork(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        q = shlex.quote
        home.fake("muse", MUSE.format(python=q(sys.executable), root=q(str(home.root)),
                                      pane=q(str(PANE)),
                                      screen=q(str(FIXTURES / "muse-prompt-pane.txt"))))
        for login in (".config", ".muse-second"):      # each account's, where Muse keeps it
            home.write(f"{login}/muse/auth.json",
                       {"providers": {"meta": {"user_email": "acme@example.com"}}})
        akconfig.write(home, ["spark"], providers={"meta": {"accounts": ["default", "second"]}})
        cls.terminal = Terminal(home, "orch", "acme", "--model", "spark", "--workers", "spark")
        argv = home.root / "argv.json"
        until(lambda: argv.exists() and argv.read_text().endswith("]"), "saw the Muse seat open")
        cls.argv = json.loads(argv.read_text())
        cls.fire(STARTED)

    @classmethod
    def fire(cls, payload):
        """Run each command the launch gave Muse for the event, as Muse runs one."""
        event = payload["hook_event_name"]
        for flag, value in zip(cls.argv, cls.argv[1:]):
            if flag == "-c" and value.startswith(f"hooks.{event}="):
                for group in json.loads(value.partition("=")[2]):
                    for hook in group["hooks"]:
                        done = cls.home.run("sh", "-c", hook["command"], input=json.dumps(payload))
                        assert done.code == 0, done.err

    def stop(self, records):
        """The seat's turn ends with its session's log holding `records`: its Stop as ak
        writes it down."""
        log = self.home.path / f".local/share/muse/sessions/2026/10/26/{SESSION}/session.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("".join(json.dumps({
            "schema_version": 1, "id": f"01a17700-0000-7000-8000-{n:012x}",
            "stream": {"kind": "session", "id": SESSION}, "sequence": n,
            "recorded_at": 1793045448161675 + n, "record_type": "event",
            "durability": "durable", "causation_id": None, "payload_type": kind,
            "payload_schema_version": 1, "payload": payload}) + "\n"
            for n, (kind, payload) in enumerate(records, 1)))
        self.fire(STOPPED)
        return json.loads((self.home.path / ".agentkit/state/hook-acme.json").read_text())

    def tick(self, used=97):
        """One tick with the seat's account `used`% into its 5h window and the other at 10%, its
        terminal untouched for ten minutes: the account it is on after."""
        now = time.time()

        def reading(used):
            return {"provider": "meta", "resets": 0, "meters": [
                {"name": "session", "used": used, "window_secs": 18000, "resets_at": now + 10800},
                {"name": "weekly_all", "used": 30, "window_secs": 604800,
                 "resets_at": now + 3 * 86400}]}
        self.home.write(".agentkit/state/usage.json", {
            "fetched_at": now, "reset_checked_at": now, "providers": {"meta": {
                **reading(used), "accounts": {"default": reading(used), "second": reading(10)}}}})
        tty = self.home.tmux("display-message", "-p", "-t", "=acme:", "#{pane_tty}").out.strip()
        os.utime(tty, (now - 600, now - 600))
        done = self.home.ak("watch", boxed=True)
        self.assertEqual(done.code, 0, done.out + done.err)
        record = json.loads((self.home.path / ".agentkit/state/session-acme.json").read_text())
        return record.get("account") or "default"

    def test_1_a_stop_holding_a_terminal_and_a_sub_agent_names_both(self):
        held = self.stop(STARTED_WORK)
        self.assertEqual((held["event"], held["kind"], held["holds"]),
                         ("Stop", "background", ["shell", "subagent"]))
        listed = self.home.ak("orch", "list")      # a wait: what it waits on works on
        self.assertEqual(listed.code, 0, listed.err)
        self.assertIn("working", next(row for row in listed.out.splitlines() if "acme" in row))

    def test_2_a_stop_whose_work_has_all_ended_holds_nothing(self):
        held = self.stop(STARTED_WORK + ENDED_WORK)
        self.assertEqual((held["event"], held["kind"]), ("Stop", ""))
        self.assertNotIn("holds", held)

    def test_2b_work_its_killed_process_held_is_not_held_once_resumed(self):
        held = self.stop(STARTED_WORK + LOST_WORK)
        self.assertEqual((held["event"], held["kind"]), ("Stop", ""))
        self.assertNotIn("holds", held)

    @unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
    def test_3_a_seat_holding_a_terminal_stays_on_an_account_with_usage_left(self):
        held = self.stop(STARTED_WORK[:2])      # a terminal is no wait, but still held
        self.assertEqual((held["kind"], held["holds"]), ("", ["shell"]))
        self.assertEqual(self.tick(), "default")
        self.stop(STARTED_WORK + ENDED_WORK)
        self.assertEqual(self.tick(), "second")


if __name__ == "__main__":
    unittest.main()
