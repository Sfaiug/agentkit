"""v5m: the menu opens on the seats, and a worker is nobody's seat.

Two rules, both offline.  `ak orch`'s maintenance no longer hands the endings back to the
owner -- the orchestrator seat that launched a run reports it, and did already -- so opening a
seat marks nothing told; `announce` and `r` still do.  And nothing below the loop carries
$AGENTKIT_SESSION: the model calls and the done-when commands are seatless, so an `ak run` or
a smoke suite started from either belongs to no seat at all.

Fake adapters, scratch runs (no repository, so no branch, no PR and no merge), no tmux, no
network and no notification transport.
"""

from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, notify, orch, run, terminal, usage, watch

SEAT = "seat-v5m"          # the seat every one of these runs is launched from

# Every model call writes down the role it was given and the environment it was called with,
# which is the whole of what (c) asks.  `usage` answers unknown so that a nested `ak run` --
# which has none of this module's patches -- can still pick its models without a provider.
ADAPTER = '''import json, os, pathlib, sys
if sys.argv[1] == "usage":
    print(json.dumps({"meters": [], "error": "unknown: v5m fixture"}))
    sys.exit(0)
assert sys.argv[1] == "run", sys.argv
root = pathlib.Path(os.environ["V5M_FIXTURE"])
workspace, out = pathlib.Path(sys.argv[4]), pathlib.Path(sys.argv[6])
prompt = pathlib.Path(sys.argv[5]).read_text()
role = ("reviewer" if prompt.startswith("You are the reviewer")
        else "fixer" if prompt.startswith("You are the executor, continuing")
        else "executor")
with (root / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({"role": role, "model": sys.argv[2],
                         "session": os.environ.get("AGENTKIT_SESSION", "<absent>"),
                         "run_role": os.environ.get("AK_RUN_ROLE", "<absent>")}) + "\\n")
if role == "reviewer":
    verdicts = json.loads((root / "verdicts.json").read_text())
    seen = sum(1 for line in (root / "calls.jsonl").read_text().splitlines()
               if json.loads(line)["role"] == "reviewer")
    word = verdicts[seen - 1] if seen <= len(verdicts) else verdicts[-1]
    text = f"VERDICT: {word}\\n\\n## Findings\\n- deliverable.txt:1 - say it again - the task asks"
else:
    (workspace / "deliverable.txt").write_text(role + "\\n")
    text = f"## Summary\\nThe {role} wrote the deliverable."
(out / "final.md").write_text(text)
(out / "stderr.log").write_text("offline fixture")
'''


class Sandbox(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5m-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # the same layout the subprocesses derive from $HOME, so a nested run lands in the
        # very ~/.agentkit/runs this process reads
        home = self.root / ".agentkit"
        self.stack.enter_context(patch.object(config, "HOME", home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK"):
            self.stack.enter_context(patch.object(config, name, home / name.lower()))
        self.stack.enter_context(patch.object(config, "CODE", self.root / "code"))
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.adapters = self.root / "adapters"
        self.adapters.mkdir()
        # This fixture owns its top-level seat; the worker running the test is not its parent.
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "NO_COLOR": "1", "LANG": "C.UTF-8",
            config.SESSION_ENV: SEAT, config.RUN_DIR_ENV: "", config.UNATTENDED_ENV: "",
            "AK_RUN_ROLE": "", "AK_RUN_LOG": "",
            "AK_RUN_DEPTH": "0", "AK_PARENT_RUN": "",
            "IDLE_COMPACT_STATE": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AGENTKIT_DISCORD_USER_ID": "", "AGENTKIT_TMUX_SOCKET": "agentkit-test",
            "TMUX_TMPDIR": str(sockets), "PYTHONDONTWRITEBYTECODE": "1",
            config.ADAPTER_DIR_ENV: str(self.adapters), "V5M_FIXTURE": str(self.root)}))
        config.ensure_dirs()
        self.cfg = config.load()
        for harness in {m["harness"] for m in self.cfg["models"].values()}:
            path = self.adapters / f"{harness}.sh"
            path.write_text(f"#!{sys.executable}\n{ADAPTER}")
            path.chmod(0o755)
        # the seat lookup, without a tmux server: only SEAT is up
        self.live = {SEAT}
        self.stack.enter_context(patch.object(orch, "watching",
                                              side_effect=lambda name: name in self.live))
        self.stack.enter_context(patch.object(orch, "sessions",
                                              side_effect=lambda: [{"name": n} for n in self.live]))
        self.stack.enter_context(patch.object(terminal, "height", return_value=24))
        self.stack.enter_context(patch.object(usage, "collect", return_value={}))
        self.stack.enter_context(patch.object(usage, "pick_order", return_value=["opus", "astra"]))
        self.stack.enter_context(patch.object(run, "disk_pressure", return_value=False))
        self.stack.enter_context(patch.object(run.time, "sleep"))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))

    # --- fixtures ----------------------------------------------------------

    def receipt(self, name, title, owner=SEAT, state="pass", verdict="PASS", reported=False,
                **extra):
        """A finished scratch run on disk, as the loop leaves one."""
        directory = config.RUNS / name
        directory.mkdir()
        (directory / "log.txt").touch()
        run.save_state(directory, {
            "run_id": name, "title": title, "state": state, "verdict": verdict,
            "launched_session": owner, "reported": reported, "scratch": True,
            "executor": "opus", "reviewer": "astra", "merged": False,
            "review": {"executor": "opus", "reviewer": "astra", "returncode": 0,
                       "executor_provider": config.model(self.cfg, "opus")["provider"],
                       "reviewer_provider": config.model(self.cfg, "astra")["provider"],
                       "verdict": "PASS", "done_when": True},
            "started_at": time.time() - 60, "finished_at": time.time(), **extra})
        return directory

    def task(self, title, cmds, rounds=1):
        path = self.root / f"{run.slugify(title)}.md"
        path.write_text(f"---\nrepo: none\nrounds: {rounds}\n---\n# {title}\n\n"
                        "## Goal\nNothing: the fixture adapters do the work.\n\n"
                        "## Done when\n```bash\n" + "\n".join(cmds) + "\n```\n")
        return path

    def launch(self, task_path, verdicts=("PASS",)):
        """Run the whole loop in this process; returns (exit code, run dir, state)."""
        (self.root / "verdicts.json").write_text(json.dumps(list(verdicts)))
        with redirect_stdout(io.StringIO()):
            code = run.main([str(task_path), "--exec", "opus", "--review", "astra"])
        directories = run.run_dirs()
        self.assertEqual(len(directories), 1)
        state = run.read_state(directories[0])
        self.assertEqual(state["run_depth"], 0)
        self.assertEqual(state["parent_run"], "")
        return code, directories[0], state

    def calls(self):
        path = self.root / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def nested_run(self, title):
        """`ak run` started from a done-when, the way an executor's test suite starts one."""
        (self.root / "verdicts.json").write_text(json.dumps(["PASS"]))
        command = shlex.join([sys.executable, str(REPO / "bin" / "ak"), "run",
                              str(self.task(title, ["true"])),
                              "--exec", "opus", "--review", "astra"])
        before = set(run.run_dirs())
        ok, text = run.run_done_when([command], self.root,
                                     self.root / f"{run.slugify(title)}.log", set())
        self.assertTrue(ok, text)
        made = [d for d in run.run_dirs() if d not in before]
        self.assertEqual(len(made), 1, made)
        state = run.read_state(made[0])
        self.assertEqual(state["run_depth"], 1)
        self.assertEqual(state["parent_run"], "")
        return made[0], state

    def overview(self):
        """{name: project} as the menu's project overview draws it, without asking tmux."""
        seats = [{"name": SEAT, "path": str(config.CODE), "repo": None, "created": 9000}]
        with patch.object(watch, "live_state", return_value={"word": "idle", "since": 9000}):
            return {project["name"]: project for project in menu.projects(self.cfg, seats)}


class MenuOpensOnTheSeats(Sandbox):
    def test_v5m_maintenance_reports_no_ending_and_leaves_reported_alone(self):
        first = self.receipt("run-1-owned", "First ending of a live seat")
        second = self.receipt("run-2-owned", "Second ending of a live seat",
                              state="fail", verdict="FAIL")
        told = self.receipt("run-3-told", "An ending already handed back", reported=True)
        messages = []
        with patch.object(orch, "stamp"), \
                patch.object(orch, "sweep"), patch.object(run, "schedule_gc"):
            orch.maintenance(messages.append)
        # nothing at all: no receipt line, and no warning while producing none
        self.assertEqual(messages, [])
        self.assertFalse(run.read_state(first)["reported"])
        self.assertFalse(run.read_state(second)["reported"])
        self.assertTrue(run.read_state(told)["reported"])

    def test_v5m_maintenance_still_reaps_a_dead_loop_and_wakes_only_its_own_seat(self):
        """Reporting went; the reconciliation it carried did not."""
        dead = self.receipt("run-6-dead", "A loop whose process is gone",
                            state="running", verdict=None, finished_at=None, pid=99999999)
        nobody = self.receipt("run-7-nobody", "A dead loop no seat launched", owner=None,
                              state="running", verdict=None, finished_at=None, pid=99999999)
        messages = []
        with patch.object(orch, "stamp"), \
                patch.object(orch, "sweep"), patch.object(run, "schedule_gc"), \
                patch.object(orch, "find", return_value=None), \
                patch.object(notify, "shaped", return_value=0) as shaped, \
                redirect_stdout(io.StringIO()):
            orch.maintenance(messages.append)
        self.assertEqual(messages, [])
        for directory in (dead, nobody):
            state = run.read_state(directory)
            self.assertEqual(state["state"], "interrupted", state)
            self.assertTrue(run.needs_recovery(state), state)
        # v5ay: the seat that launched one is there, so the ending is its to act on and the
        # owner is asked nothing; a seat mid-turn leaves it pending for the tick to deliver
        self.assertTrue(run.read_state(dead)["handback_pending"])
        self.assertNotIn("recovery_notified", run.read_state(dead))
        self.assertEqual(shaped.call_count, 0)
        self.assertNotIn("recovery_notified", run.read_state(nobody))
        # ... and once its seat is gone, the needs card is what it always was
        self.live.discard(SEAT)
        with patch.object(notify, "shaped", return_value=0) as gone, \
                redirect_stdout(io.StringIO()):
            run.notify_recovery(dead, run.read_state(dead))
        self.assertEqual(run.read_state(dead)["recovery_notified"], "needs")
        self.assertEqual(gone.call_count, 1)
        self.assertEqual(gone.call_args.kwargs["session"], SEAT)

    def test_v5m_announce_marks_an_ending_told_and_the_menu_marks_none(self):
        orphan = self.receipt("run-4-orphan", "An ending of a gone seat", owner="gone-seat")
        listed = self.receipt("run-5-listed", "Another ending of a gone seat", owner="gone-seat")
        with patch.object(notify, "shaped", return_value=0) as shaped:
            run.announce(run.read_state(orphan), orphan, lambda _: None)
        self.assertEqual(shaped.call_args.kwargs["session"], "gone-seat")
        self.assertTrue(run.read_state(orphan)["reported"])
        self.assertFalse(run.read_state(listed)["reported"])
        with redirect_stdout(io.StringIO()):
            menu.draw(self.cfg, [])
        self.assertFalse(run.read_state(listed)["reported"])
        with redirect_stdout(io.StringIO()):
            run.cmd_status([listed.name])
        self.assertTrue(run.read_state(listed).get("recovery_acknowledged_at"))


class NothingBelowTheLoopHasASeat(Sandbox):
    def test_v5m_every_model_call_is_made_without_the_seats_name(self):
        # FAIL then PASS, so the round-2 fixer is called as well as the executor and reviewer
        code, _, state = self.launch(self.task("Seatless workers", ["true"], rounds=2),
                                     verdicts=("FAIL", "PASS"))
        self.assertEqual(code, 0, state)
        self.assertEqual([call["role"] for call in self.calls()],
                         ["executor", "reviewer", "fixer", "reviewer"])
        for call in self.calls():
            self.assertEqual(call["session"], "<absent>", call)
            self.assertEqual(call["run_role"], "worker", call)

    def test_v5m_done_when_commands_run_without_the_seat_the_loop_keeps(self):
        seen = self.root / "donewhen.txt"
        code, _, state = self.launch(self.task(
            "Seatless done-when",
            ['printf \'%s\\n\' "${AGENTKIT_SESSION:-none}" >>"$V5M_FIXTURE/donewhen.txt"']))
        self.assertEqual(code, 0, state)
        self.assertEqual(seen.read_text().split(), ["none"])
        # ... while the loop itself still knows whose run this is
        self.assertEqual(config.current_session(), SEAT)
        self.assertEqual(state["launched_session"], SEAT)
        self.assertEqual(run.launched_session(state), SEAT)

    def test_v5m_a_nested_run_from_a_done_when_is_launched_from_no_seat(self):
        """No seat, no terminal, no menu: a run below a run is machinery."""
        self.assertEqual(config.current_session(), SEAT)   # a seat is there to be inherited
        directory, state = self.nested_run("Nested fixture run")
        self.assertEqual(state["state"], "pass")
        self.assertIsNone(state["launched_session"])
        self.assertIsNone(run.launched_session(state))
        self.assertTrue(state["unattended"])
        # never reported and never typed into a seat: the loop had nobody to hand it back to
        self.assertFalse(state["reported"])
        self.assertNotIn("recovery_notified", state)
        # nothing is printed or sent when a seat opens
        messages = []
        with patch.object(orch, "stamp"), \
                patch.object(orch, "sweep"), patch.object(run, "schedule_gc"), \
                patch.object(notify, "shaped", side_effect=AssertionError("notified")):
            orch.maintenance(messages.append)
        self.assertEqual(messages, [])
        # and it is in no view of the menu, nor in any seat's tally
        self.assertEqual(menu.run_records(), [])
        self.assertFalse(hasattr(menu, "runs_listing"))
        self.assertEqual([group["runs"] for group in self.overview().values()], [[]])
        self.assertEqual(run.seat_tallies([s for _, s in menu.run_records()]), {})
        groups = self.overview()
        self.assertEqual(groups["no project"]["rows"][0][1], SEAT)
        self.assertEqual(groups["no project"]["rows"][0][-1], menu.tally(None))
        # `ak run status` still has it, as it has the smoke suite's own runs
        self.assertIn(directory, run.run_dirs())

    def test_v5m_a_run_launched_by_hand_stays_in_records_but_makes_no_row(self):
        """The seatless run that is not machinery: nobody owns it, the terminal does."""
        with patch.dict(os.environ, {config.SESSION_ENV: ""}):
            self.assertIsNone(config.current_session())
            self.assertFalse(config.unattended())
            directory, state = self.launch(self.task("Launched by hand", ["true"]))[1:]
        self.assertIsNone(state["launched_session"])
        self.assertFalse(state["unattended"])
        self.assertEqual([d for d, _ in menu.run_records()], [directory])
        self.assertNotIn("scratch", self.overview())
        self.assertEqual([group["runs"] for group in self.overview().values()], [[]])

    def test_v5m_a_smoke_suites_nested_run_never_reaches_the_menu(self):
        """The case that filled the owner's screen: `unattended` keeps it off every view."""
        directory, state = self.nested_run("Smoke make hello pass")
        self.assertIsNone(state["launched_session"])
        self.assertIn("smoke-", directory.name)
        self.assertEqual(menu.run_records(), [])
        self.assertFalse(hasattr(menu, "runs_listing"))
        self.assertEqual([group["runs"] for group in self.overview().values()], [[]])
        with redirect_stdout(io.StringIO()):
            menu.draw(self.cfg, [])
        self.assertFalse(run.read_state(directory)["reported"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
