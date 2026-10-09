"""Two seats in a temporary HOME, one seat's pane and tmux faked, and ak's own typed line to
drive the typing guards with: a wait on a run that has ended, which the tick's wait pass types
into the seat (`watch.wait_over`).  Offline: no real seat, transcript or state."""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from agentkit import config, harness, orch, record, watch  # noqa: E402

SENDER, SEAT = "fix-api", "acme-docs"
NOW = 1_000_000.0
RUN = "20260101-0900-acme-parser"
LINE = f"run {RUN} ended PASS, merged; your wait is over. Decide the next step."
PROMPT = (REPO / "tests/fixtures/claude-prompt-pane.txt").read_text(encoding="utf-8")


class Seats(unittest.TestCase):
    """Two seats in a temporary HOME, the receiving seat's pane and tmux faked."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-seats-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "AGENTKIT_SESSION": SENDER, "AGENTKIT_RUN": "",
            "AK_PARENT_RUN": "", "AK_RUN_LOG": "", "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
            "AK_NOTIFY_SINK": "dry-run"}))
        for name in ("HOME", "STATE", "RUNS", "WT", "WORK", "TMP", "SECRETS", "ENV", "CODE"):
            stack.enter_context(patch.object(config, name, self.root / ".agentkit" / name.lower()))
        self.cfg = config.load()
        config.ensure_dirs()
        for name in (SENDER, SEAT):
            config.save_session(self.cfg, name, "opus", ["astra"], {
                "cwd": str(self.root / name), "conversation": "thread",
                "id_source": harness.LAUNCHER})
        self.seat = {"name": SEAT, "created": 10, "legacy": False}
        self.free, self.typed = True, []
        stack.enter_context(patch.object(orch, "sessions", side_effect=lambda: [self.seat]))
        stack.enter_context(patch.object(orch, "find", side_effect=lambda name:
                                         self.seat if name == self.seat["name"] else None))
        stack.enter_context(patch.object(orch, "tmux_out", side_effect=self.tmux))
        stack.enter_context(patch.object(watch, "at_prompt", side_effect=lambda *_a, **_kw: self.free))
        self.pane = self.base = PROMPT
        self.empty = "❯ \n"      # the base pane's empty composer row
        stack.enter_context(patch.object(watch, "pane_text", side_effect=lambda *_a, **_kw: self.pane))
        stack.enter_context(patch.object(watch, "KEY_GAP", 0))
        stack.enter_context(patch.object(watch.time, "sleep"))
        stack.enter_context(patch.object(watch.time, "time", return_value=NOW))

    def tmux(self, *args, **_kw):
        self.assertEqual(args[args.index("-t") + 1], f"={self.seat['name']}:")
        if args[0] == "display-message" and args[-1].startswith("#{pane_tty}"):
            return 1, "no tty in this screen fixture"
        self.assertEqual(args[0], "send-keys")
        if "-l" in args:
            self.typed.append(args[-1])
            self.pane = self.base.replace(self.empty, "❯ " + args[-1] + "\n")
        elif args[-1] == "Enter":
            self.pane = self.base
        return 0, ""

    def wait_line(self, name=SEAT):
        """That seat waits on a run that has ended: the next wait pass types LINE into it."""
        directory = config.RUNS / RUN
        directory.mkdir(parents=True, exist_ok=True)
        record.save_state(directory, {"run_id": RUN, "title": "Task acme parser", "state": "pass",
                                      "verdict": "PASS", "merged": True, "launched_session": name,
                                      "started_at": NOW - 600, "finished_at": NOW - 60})
        watch.seat_write(name, wait={"on": RUN, "kind": "run", "at": NOW - 300})

    def tick(self):
        """The tick's wait pass."""
        watch.wait_over(self.cfg, lambda _: None)

    def told(self, name=SEAT):
        """Whether that seat's wait has been told its end: the line left the composer."""
        wait = watch.seat_read(name).get("wait")
        return bool(isinstance(wait, dict) and wait.get("told"))

    def receipts(self, name=SEAT):
        return list(harness.entries(config.seat_file("input", name)))

    def opened(self, created):
        """The seat named SEAT, opened at `created`: a new one where that differs."""
        config.save_session(self.cfg, SEAT, "opus", ["astra"], {
            "cwd": str(self.root / SEAT), "conversation": f"thread-{created}",
            "id_source": harness.LAUNCHER, "created": created})
        watch.seat_write(SEAT, stopped_at=None)
