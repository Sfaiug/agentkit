"""With memory fine, a Claude seat whose turn rested past its harness's prompt cache (an hour)
sleeps, done or only waiting on its runs; one rested less stays awake, and so does one retrying a
stalled turn, its owner's stalled run beside hiding none of it.  Asleep, one waiting on its runs reads `working`, and its run's ending wakes it and
is typed in after the resume.  A rest is aged by its recorded turn end, set back, never waited
out.  Black-box against `AK_BIN`, as tests/test_idle_seat_sleeps.py."""

import json
import re
import shlex
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home, boxable, owner
from fixtures.akseat import PANE, Seat
from fixtures.hookdrive import Hooks

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
FINE = {"mem_total_mb": 16000, "cpus": 8, "load": 0.1, "free_mb": 12000}
HOUR = 3600
# how long ago each seat's turn ended, whether a run of its own goes, and the API error its turn
# stopped on; every run started before the turn that launched it ended, so no rest is aged by it,
# and `waiting` has a line of its plan still open, which its turn ended on its runs to wait for
SEATS = {"done": (2 * HOUR, False, None), "waiting": (2 * HOUR, True, None),
         "fresh": (HOUR / 2, True, None),
         "stalled": (2 * HOUR, True, "API Error: 400 upstream connect error")}
AWAKE = ("fresh", "stalled")


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class IdleSeatHoldsNoMemory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file")
        del home.env["AK_MAX_RUNS"]       # its host gates on: memory is read as injected
        akconfig.write(home, ["opus"])
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        fake = fakeadapter.install(home, claude="pass")["claude"]
        home.write(".agentkit/state/plan-done.md", "- [x] Shipped it\n")
        hooks, cls.seats, cls.runs, now = Hooks(home), {}, {}, time.time()
        for name, (ago, runs, error) in SEATS.items():
            seat = cls.seats[name] = Seat(home, name, screen="claude-stall-pane.txt" if error
                                          else "claude-prompt-pane.txt", planned=name == "waiting")
            # its conversation, ending on the error as Claude Code records one
            said = [{"type": "user", "message": {"role": "user", "content": "hello"}}]
            said += [{"type": "assistant", "isApiErrorMessage": True, "message": {
                "role": "assistant", "content": [{"type": "text", "text": error}]}}] * bool(error)
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            home.write(f".claude/projects/{folder}/conv-{name}.jsonl",
                       "".join(json.dumps(entry) + "\n" for entry in said))
            # woken, the harness shows the seat's screen again and keeps what is typed in
            argv = [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]
            fake.answer("interactive", shlex.join(argv), given=(f"conv-{name}",))
            if runs:     # its loop a live process of the test's, so no tick takes it for dead
                loop = subprocess.Popen(["sleep", "600"])
                cls.addClassCleanup(loop.wait)
                cls.addClassCleanup(loop.kill)
                cls.runs[name] = home.write(f".agentkit/runs/20261028-0900-{name}/run.json", {
                    "run_id": f"20261028-0900-{name}", "title": f"fix {name}",
                    "launched_session": name, "state": "running", "step": "executor",
                    "started_at": now - ago - HOUR, **owner(loop.pid)})
            hooks.fire("UserPromptSubmit", {"prompt": "go"}, seat=name, pane=seat)
            hooks.fire("Stop", {"background_tasks": [], "transcript_path": "",
                                "last_assistant_message": "Done."}, seat=name, pane=seat,
                       finished=True)
            fact = home.path / f".agentkit/state/hook-{name}.json"
            home.write(fact, {**json.loads(fact.read_text()), "at": now - ago})
            if error:     # and since its turn ended, an older run of its own stalled: the owner's
                home.write(f".agentkit/runs/20261028-0800-{name}/run.json", {
                    "run_id": f"20261028-0800-{name}", "title": "an older fix",
                    "launched_session": name, "state": "stalled", "step": "executor",
                    "started_at": now - ago - 2 * HOUR, "finished_at": now - ago - HOUR})
        cls.tick()
        cls.awake = sorted(home.tmux("list-sessions", "-F", "#{session_name}").out.split())
        cls.words = {name: cls.why(name) for name in SEATS}

    @classmethod
    def tick(cls):
        done = cls.home.ak("watch", boxed=True, env={"AK_HOST_READINGS": json.dumps(FINE)})
        assert done.code == 0, done.out + done.err
        return done

    @classmethod
    def why(cls, name):
        """`ak orch why`'s word and its reason."""
        done = cls.home.ak("orch", "why", name)
        assert done.code == 0, done.err
        lines = done.out.splitlines()
        reason = next(line for line in lines if line.startswith("  reason:"))
        return lines[0].split(None, 1)[1], reason.split(":", 1)[1].strip()

    def test_rested_past_the_cache_it_sleeps_with_memory_fine(self):
        # `stalled` is `waiting` but for the error its turn stopped on, which the tick retries
        self.assertEqual(self.awake, sorted(AWAKE))
        for name in AWAKE:
            self.assertEqual(self.words[name][0], "working")

    def test_asleep_it_reads_as_awake_and_its_run_s_ending_wakes_it(self):
        self.assertFalse({"done", "waiting"} & set(self.awake))
        self.assertEqual(self.words["done"][0], "done")
        word, reason = self.words["waiting"]
        self.assertEqual(word, "working")
        self.assertIn("fix waiting", reason)
        run = self.runs["waiting"]
        self.home.write(run, {**json.loads(run.read_text()), "state": "fail", "verdict": "FAIL",
                              "finished_at": time.time()})
        self.tick()
        if not self.seats["waiting"].lines():
            self.tick()       # its harness was not yet at its prompt: the next tick types it
        line, = self.seats["waiting"].wait_lines(1)
        self.assertIn("20261028-0900-waiting", line)


if __name__ == "__main__":
    unittest.main()
