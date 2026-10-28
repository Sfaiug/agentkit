"""While memory is tight the longest-idle Claude seat sleeps, one a tick, keeping its conversation,
ak's own desktop server beside it or not; a working, asking, attached, busy (another project's
desktop server too) or Codex seat never does.  An ending or opening wakes it, a failed wake keeping
the ending owed; it reads asleep (the key, run here).  Black-box against `AK_BIN`."""

import json
import os
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
from fixtures.akbin import REAL_TMUX, REPO, SOCKET, Home, boxable
from fixtures.akseat import PANE, Seat
from fixtures.hookdrive import Hooks
from test_key_sleeping_seat_reads_asleep import SleepingSeatReadsAsleep  # noqa: F401

PROXIES = ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
TIGHT, FINE = ({"mem_total_mb": 16000, "cpus": 8, "load": 0.1, "free_mb": n} for n in (100, 12000))
IDLE = ("oldest", "older", "desktop")      # in the order their turns ended
AWAKE = ("working", "asking", "attached", "busy", "lookalike")
PERMISSION = {"tool_name": "Bash", "tool_input": {"command": "make deploy"}}


@unittest.skipUnless(REAL_TMUX and boxable(), "no tmux, or no bwrap able to box a tick here")
class IdleSeatSleeps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        with socket.socket() as probe:     # a port nobody listens on: the tick reaches no board
            probe.bind(("127.0.0.1", 0))
            home.env.update(dict.fromkeys(PROXIES, f"http://127.0.0.1:{probe.getsockname()[1]}"),
                            GIT_ALLOW_PROTOCOL="file")
        del home.env["AK_MAX_RUNS"]       # its host gates on: memory is read as injected
        akconfig.write(home, ["opus", "astra"])
        home.write(".agentkit/state/gc.json", {"started_at": time.time()})
        cls.fake = fakeadapter.install(home, claude="pass", codex="pass")["claude"]
        # an idle Codex seat on a thread its launch's receipt proves its own
        cwd = str(Seat(home, "codex", model="astra", screen="codex-prompt-pane.txt",
                       record={"codex_launch": "1" * 32}).cwd)
        rollout = home.write(".codex/sessions/2026/10/23/rollout-conv-codex.jsonl", json.dumps(
            {"type": "session_meta", "payload": {"id": "conv-codex", "cwd": cwd}}) + "\n")
        home.write(f".agentkit/state/codex-launch-{'1' * 32}.json", {"launch": "1" * 32, "cwd": cwd,
                   "event": {"hook_event_name": "SessionStart", "source": "startup", "cwd": cwd,
                             "session_id": "conv-codex", "transcript_path": str(rollout)}})
        # its seats sit in the cgroup it runs in: run from a seat's own shell, that seat's scope
        # holds processes their trees never reach and every one reads busy (`sleep._busy`)
        hooks, cls.seats = Hooks(home), {}
        # a shell its harness started, as a background command is; ak's desktop server, on a pipe
        # nobody closes; or another project's server by the same name
        os.mkfifo(pipe := home.path / "desktop-in")
        lookalike = home.write("acme/tools/desktop-mcp.py", "import time\ntime.sleep(600)\n")
        work = {"busy": "sh -c 'sleep 600; :'",
                "desktop": shlex.join([sys.executable, str(REPO / "tools/desktop-mcp.py")])
                + " <>" + shlex.quote(str(pipe)),
                "lookalike": shlex.join([sys.executable, str(lookalike)])}
        for name in (*IDLE, *AWAKE):
            seat = cls.seats[name] = Seat(home, name, screen="claude-working-pane.txt"
                                          if name == "working" else "claude-prompt-pane.txt")
            # a conversation Claude filed under the workspace's path, which the seat resumes
            folder = re.sub(r"[^A-Za-z0-9]", "-", str(seat.cwd))
            home.write(f".claude/projects/{folder}/conv-{name}.jsonl",
                       '{"type":"user","message":{"role":"user","content":"hello"}}\n')
            # woken, the harness shows the seat's screen again and keeps what is typed in
            argv = [sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]
            cls.fake.answer("interactive", shlex.join(argv), given=(f"conv-{name}",))
            hooks.fire("UserPromptSubmit", {"prompt": "go"}, seat=name, pane=seat)
            if name != "working":
                hooks.fire("Stop", {"background_tasks": [], "transcript_path": "",
                                    "last_assistant_message": "Done."}, seat=name, pane=seat)
            if name in work:
                home.tmux("respawn-pane", "-k", "-t", seat.pane,
                          f"{work[name]} & exec {shlex.join(argv)}")
                seat._settle()
            time.sleep(1.1)     # each turn ended a second after the one before
        hooks.fire("PermissionRequest", PERMISSION, seat="asking", pane=cls.seats["asking"])
        cls.client = subprocess.Popen([REAL_TMUX, "-L", SOCKET, "-C", "attach", "-t", "=attached"],
                                      stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                      env=home._env(None))
        cls.addClassCleanup(cls.client.kill)
        cls.tick(FINE)
        cls.after_fine = cls.sessions()
        cls.tight = [cls.tick(TIGHT) for _ in range(4)]
        cls.slept = cls.sessions()
        cls.records = {name: json.loads(home.path.joinpath(
            f".agentkit/state/session-{name}.json").read_text()) for name in IDLE}

    @classmethod
    def tick(cls, memory):
        done = cls.home.ak("watch", boxed=True, env={"AK_HOST_READINGS": json.dumps(memory)})
        assert done.code == 0, done.out + done.err
        return done

    @classmethod
    def sessions(cls):
        return sorted(cls.home.tmux("list-sessions", "-F", "#{session_name}").out.split())

    def test_while_memory_is_tight_the_longest_idle_seat_sleeps_one_a_tick(self):
        self.assertEqual(self.after_fine, sorted((*IDLE, *AWAKE, "codex")))    # with memory fine
        slept = [re.findall(r"put (\S+) to sleep", done.out) for done in self.tight]
        self.assertEqual(slept, [["oldest"], ["older"], ["desktop"], []])
        self.assertEqual(self.slept, sorted((*AWAKE, "codex")))
        for name in IDLE:
            self.assertEqual(self.records[name]["conversation"], f"conv-{name}")

    def test_an_ending_wakes_its_seat_and_is_typed_in_after(self):
        # asleep three hours: a seat gone that long is no longer reopened for a run's ending
        now, record = time.time(), self.records["oldest"]
        self.home.write(".agentkit/state/session-oldest.json", {**record, "seen": now - 10800})
        run = self.home.write(".agentkit/runs/20261023-0900-fix-api/run.json", {
            "run_id": "20261023-0900-fix-api", "title": "fix the api", "launched_session": "oldest",
            "state": "fail", "verdict": "FAIL", "started_at": now - 600, "finished_at": now})
        gone = self.seats["oldest"].cwd.rename(self.home.path / "gone")   # its first wake fails
        self.tick(FINE)
        gone.rename(self.seats["oldest"].cwd)
        # two hours on, still owed: not history the tick passes over
        self.home.write(run, {**json.loads(run.read_text()), "finished_at": now - 7200})
        self.tick(FINE)
        if not self.seats["oldest"].lines():
            self.tick(FINE)       # its harness was not yet at its prompt: the next tick types it
        line, = self.seats["oldest"].wait_lines(1)    # kept only by a harness on conv-oldest
        self.assertIn("20261023-0900-fix-api", line)

    def test_opening_a_sleeping_seat_resumes_it(self):
        self.assertEqual(self.home.ak("orch", "older").code, 0)
        self.assertIn("older", self.sessions())
        self.assertEqual(sum("conv-older" in c["argv"] for c in self.fake.calls("interactive")), 1)


if __name__ == "__main__":
    unittest.main()
