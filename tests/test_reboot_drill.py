"""A reboot drill: the first tick after a boot puts every seat and run back where it was.

Offline.  The host before the reboot is four seats and three runs in the sandbox's HOME; the
reboot is a new boot id, and no process any record names.  tmux, the process table and the user
manager are faked: tmux lists the seats that are up, a captured Claude pane is each one's screen
and its send-keys type into it; a pid lives while it is in `alive`; a unit started is its `ak
run` words and a new pid.  The tick is `watch.main` with only the passes that put seats and
runs back, and the cards', in its own order (`fixtures.tick`).  A relaunch is faked as the boot
tests fake it (`orch.resume`), and every page goes through `notify.post`, recorded here.
"""

from contextlib import redirect_stdout
import io
import itertools
import json
import os
import time
import unittest
from unittest.mock import patch

from fixtures.clock import Clock
from fixtures.sandbox import REPO, Sandbox
from fixtures.tick import only_passes
from agentkit import config, deliver, gate, host, land, notify, orch, watch
from agentkit import record as run_record

PROMPT = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text()
EMPTY = "❯\xa0\n"        # that pane's composer row, empty
QUESTION = "Which branch should fix-api land on?"
WORKING, SLOT = "20261017-2100-acme-parser", "20261017-2110-acme-docs"
LANDING = "20261017-2050-acme-api"
LINE = deliver.merge_lock_path("https://github.com/acme/fix-api", "origin/main").name
PASSES = ("the notification retry did not run", "the boot resume pass did not run",
          "the held-line Enter pass did not run", "the mid-turn continue pass did not run",
          "the dead-loop pass did not run", "the dead-job pass did not run",
          "the stall pass did not run", "the waiting-resume pass did not run",
          "the card transition pass did not run", "the seat revival pass did not run")


class RebootDrill(Sandbox):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_ROLE": "", "AGENTKIT_DISCORD_WEBHOOK": "", "AGENTKIT_DISCORD_USER_ID": "",
            "AGENTKIT_RUN": "", "AK_PARENT_RUN": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        self.boot, self.now = "before", time.time()
        self.live, self.composer, self.told, self.pages, self.units = [], {}, [], [], []
        self.alive, self.pids = set(), itertools.count(5_000_001)  # past any pid_max: none real
        self.stack.enter_context(patch.object(watch, "boot_id", side_effect=lambda: self.boot))
        self.stack.enter_context(patch.object(orch, "sessions", lambda: list(self.live)))
        self.stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        self.stack.enter_context(patch.object(host, "alive", lambda pid: pid in self.alive))
        self.stack.enter_context(patch.object(host, "process_identity", self.identity))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=False))
        self.stack.enter_context(patch.object(orch, "start_in_slice", side_effect=self.start))
        self.resume = self.stack.enter_context(patch.object(orch, "resume",
                                                            side_effect=self.reopened))
        self.stack.enter_context(patch.object(notify, "post", side_effect=self.page))
        self.stack.enter_context(patch.object(watch, "seat_model",
                                              return_value=("claude", "anthropic")))
        self.stack.enter_context(patch.object(watch, "time", Clock(lambda _seconds: None)))
        watch.save_state({**watch.load_state(), "boot_id": "before"})

    # --- the fakes ------------------------------------------------------------------------

    def tmux(self, *args, **_kw):
        name = args[args.index("-t") + 1].strip("=:") if "-t" in args else None
        if name not in {seat["name"] for seat in self.live}:
            return 1, f"can't find session: {name}"
        if args[0] == "capture-pane":
            return 0, PROMPT.replace(EMPTY, f"❯\xa0{self.composer.get(name, '')}\n")
        if args[0] == "send-keys" and "-l" in args:
            self.composer[name] = args[-1]
            return 0, ""
        if args[0] == "send-keys" and args[-1] == "Enter":
            if name in self.composer:
                self.told.append((name, self.composer.pop(name)))
            return 0, ""
        return 1, "not in this fake"

    def identity(self, pid):
        return {"boot": self.boot, "ticks": pid, "started_at": 0} if pid in self.alive else None

    def start(self, argv, *_a, **_kw):
        """The user manager starting a unit: its `ak run` words, and a pid that lives."""
        self.units.append(argv[argv.index("run") + 1:])
        pid = next(self.pids)
        self.alive.add(pid)
        return pid

    def page(self, payload, _files, _message, receipt=None):
        self.pages.append(payload["content"])
        if receipt is not None:
            receipt["status"] = "delivered"
        return 0

    def reopened(self, cfg, name, **_kw):
        self.live.append(self.listed(name))
        self.fact(name, "Notification", "idle_prompt", at=time.time())   # back at its prompt
        return "resumed"

    # --- the host before the reboot ------------------------------------------------------

    def listed(self, name):
        return {"name": name, "path": str(self.root), "created": 100, "attached": False,
                "exited": False, "legacy": False, "resumable": False}

    def fact(self, name, event, kind="", at=None):
        config.hook_facts_path(name).write_text(json.dumps(
            {"session": name, "event": event, "kind": kind,
             "at": self.now - 600 if at is None else at}))

    def seat(self, name, event, up=True):
        """A seat with its own conversation and its hook's last word before the host went
        down; tmux lists it while it is `up`."""
        config.save_session(self.cfg, name, "fable", ["astra"],
                            {"cwd": str(self.root), "created": 100,
                             "conversation": f"thread-{name}", "id_source": orch.LAUNCHER})
        self.fact(name, event)
        if up:
            self.live.append(self.listed(name))

    def receipt(self, name, pid, **fields):
        """A run of the mid-turn seat's, its loop at `pid` on the boot before."""
        directory = config.RUNS / name
        directory.mkdir()
        (directory / "log.txt").touch()
        run_record.save_state(directory, {
            "run_id": name, "title": name, "launched_session": "midturn", "executor": "opus",
            "reviewer": "astra", "rounds": 3, "round_summaries": [], "scratch": True,
            "base": None, "started_at": self.now - 3600, "pid": pid,
            "process_identity": {"boot": "before", "ticks": pid, "started_at": 0}, **fields})

    def before(self):
        self.seat("midturn", "UserPromptSubmit")
        self.seat("asking", "Stop")
        notify.shaped("needs", QUESTION, session="asking")
        self.seat("idle", "Stop")
        self.seat("closed", "PermissionRequest", up=False)
        notify.record("closed", "needs", "Ship it?")
        orch.mark_owner_closed("closed")
        work = config.WORK / "parser"
        work.mkdir(parents=True)
        self.receipt(WORKING, 4101, state="running", step="executor", worktree=str(work))
        self.receipt(SLOT, 4102, state="queued", slot_waiting=True, launch_pending=False,
                     queued_at=self.now - 1800)
        landing = config.WORK / "api"
        landing.mkdir()
        self.receipt(LANDING, 4103, state="waiting", verdict="PASS", worktree=str(landing),
                     waiting_on={"line": LINE, "joined": self.now - 900})

    def tick(self):
        """The reboot, then the first tick after it: no seat, process or unit outlives it,
        the lander the line's join started among them."""
        for went in (self.live, self.alive, self.units):
            went.clear()
        self.boot = "after"
        with only_passes(self.root, *PASSES) as reached, \
                patch.object(watch, "gh_json", return_value=(None, "offline")), \
                redirect_stdout(io.StringIO()) as said:
            self.assertEqual(watch.main([]), 0)
        self.assertLessEqual(set(PASSES), set(reached), "a pass the drill names is gone")
        return said.getvalue().splitlines()

    # --- the drill -----------------------------------------------------------------------

    def test_the_first_tick_after_a_reboot_puts_every_seat_and_run_back(self):
        self.before()
        self.assertEqual(len(self.pages), 1, "the owner was asked before the reboot")
        self.assertEqual(self.pages.pop(), "Needs you · asking")
        slot = gate.slot_order(run_record.read_state(config.RUNS / SLOT))
        said = self.tick()
        self.assertEqual([line for line in said if line.startswith("WARN")],
                         ["WARN GitHub is unavailable; PR checks skipped (offline)"])
        # 1. each run goes on once: the working run and the slot waiter by their own resume,
        # the lander's line by its lander, and nothing else is started
        self.assertEqual(sorted(self.units), sorted([["resume", WORKING], ["resume", SLOT],
                                                     ["--lander", LINE]]))
        state = {name: run_record.read_state(config.RUNS / name)
                 for name in (WORKING, SLOT, LANDING)}
        self.assertEqual(state[WORKING]["state"], "running")
        self.assertEqual((state[SLOT]["state"], state[SLOT]["slot_waiting"]), ("queued", True))
        self.assertEqual(gate.slot_order(state[SLOT]), slot, "the slot waiter lost its place")
        self.assertEqual(state[LANDING]["state"], "waiting")
        self.assertTrue(land.member(state[LANDING]))
        # 2. the seats that owe work come back and are told why; the rest stay closed
        self.assertEqual(sorted(call.args[1] for call in self.resume.call_args_list),
                         ["asking", "midturn"])
        self.assertEqual(sorted(self.told), [("asking", watch.ASKED_LINE),
                                             ("midturn", watch.MIDTURN_LINE)])
        self.assertEqual(watch.session_state("idle")["word"], "idle")
        self.assertTrue(watch.seat_read("closed")["closed_by_owner"])
        # 3. and nobody pages the owner
        self.assertEqual(self.pages, [])


if __name__ == "__main__":
    unittest.main()
