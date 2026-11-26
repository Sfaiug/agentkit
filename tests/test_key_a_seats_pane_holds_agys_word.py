"""A seat's pane holds agy's own state word (`idle` or `busy`) and render moment.

On a tmux server of its own (tests/fixtures/akbin.py, as akterm.py uses), real status renders
are piped to hooks/claude-status.sh inside a pane, and the pane's `@ak_agent_state` is read back
with tmux itself: `<moment> <word>`, the moment fixed-width so it orders as text.
"""

import json, os, random, re, shlex, shutil, subprocess, sys, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from fixtures.akbin import REAL_TMUX, SOCKET, Home
from fixtures.akterm import CONF

HOOK, CORE_TOOLS = ROOT / "hooks/claude-status.sh", ("bash", "cat", "jq", "tmux", "mkdir", "mktemp", "mv", "rm")
STAMP, LAUNCH = re.compile(r"\d{12}\.\d{6}"), "launch-one"   # the first launch's token, as orch.start sets one
LAUNCH_PANE = ("import json, sys; from pathlib import Path; from unittest.mock import patch\n"
               "sys.path.insert(0, sys.argv[1]); from agentkit import orch, statusbar; cmd = json.loads(sys.argv[4])\n"
               "with patch.object(orch, 'user_manager', return_value=False), patch.object(statusbar, 'dress'):\n"
               "    orch.start('acme', Path(sys.argv[3]), cmd, 'opus') if sys.argv[2] == 'start' "
               "else orch._start_harness('acme', 'opus', Path(sys.argv[3]), cmd, json.loads(sys.argv[5]))\n")
# Each file the test waits for is written under another name and renamed into place: a reader
# never takes one half-written.
RUNNER = r"""import json, os, subprocess, sys, time
from pathlib import Path
q = Path(sys.argv[1])
tmp = q / "ready.tmp"; tmp.write_text(json.dumps({"tmux": os.environ.get("TMUX", ""), "pane": os.environ.get("TMUX_PANE", "")})); tmp.replace(q / "ready")
while True:
    for req in sorted(q.glob("req-*.json")):
        s = json.loads(req.read_text()); req.unlink()
        env = {k: v for k, v in {**os.environ, **s.get("env", {})}.items() if k not in s.get("unset", ())}
        r, w = os.pipe()
        try: p = subprocess.run(s["argv"], input=s["payload"], text=True, capture_output=True, env=env, timeout=30, pass_fds=(w,))
        finally: os.close(w)
        with os.fdopen(r, "rb") as d: d.read()
        res = req.with_name(req.name.replace("req-", "res-", 1))
        tmp = res.with_suffix(".tmp"); tmp.write_text(json.dumps({"code": p.returncode, "out": p.stdout, "err": p.stderr})); tmp.replace(res)
    time.sleep(0.01)
"""


def _wait_file(path, bound=15):
    deadline = time.monotonic() + bound
    while not path.exists():
        if time.monotonic() > deadline: raise AssertionError(f"{path} did not appear within {bound}s")
        time.sleep(0.01)
    return json.loads(path.read_text())


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class SeatPaneHoldsAgysWord(unittest.TestCase):
    def setUp(self):
        self.home, self.seq = Home(), 0; self.addCleanup(self.home.close)
        self.state, self.queue = self.home.path / ".agentkit/state", self.home.root / "queue"
        self.queue.mkdir(); (self.home.root / "pane.conf").write_text(CONF)
        done = self.home.tmux("-f", str(self.home.root / "pane.conf"), "new-session", "-d", "-s", "acme",
                              "-e", "AGENTKIT_SESSION=acme", "-e", f"AGENTKIT_TMUX_SOCKET={SOCKET}", "-e", f"AGENTKIT_PANE_LAUNCH={LAUNCH}",
                              "-P", "-F", "#{pane_id}", shlex.join([sys.executable, "-c", RUNNER, str(self.queue)]),
                              ";", "set-option", "-p", "-t", "=acme:", "@ak_pane_launch", LAUNCH)
        self.assertEqual(done.code, 0, done.err)
        self.pane, self.info = done.out.strip(), _wait_file(self.queue / "ready")

    def word(self, pane=None):
        """The pane's `@ak_agent_state`, None where it holds none."""
        done = self.home.tmux("show-options", "-pqv", "-t", pane or self.pane, "@ak_agent_state")
        self.assertEqual(done.code, 0, done.err)
        return done.out.strip() or None

    def _tools(self, name, names, **scripts):
        d = self.home.root / name; d.mkdir()
        for tool in names:
            found = shutil.which(tool, path=self.home.env["PATH"])
            if found: (d / tool).symlink_to(found)
        for tool, body in scripts.items():
            p = d / tool; p.write_text(f"#!/bin/sh\n{body}\n"); p.chmod(0o755)
        return d

    def _pane_env(self, path=None, **extra):
        return {**self.home.env, **({"PATH": path} if path else {}), "AGENTKIT_SESSION": "acme", "TMUX": self.info["tmux"],
                "TMUX_PANE": self.pane, "AGENTKIT_PANE_LAUNCH": LAUNCH, **extra}

    def pipe_in_pane(self, payload, *, moment=None, env=None, unset=()):
        text, run_env = (payload if isinstance(payload, str) else json.dumps(payload)), dict(env or {})
        self.seq += 1; argv = [str(HOOK)]
        if moment is not None:
            run_env["PATH"] = str(self._tools(f"tools-{self.seq}", CORE_TOOLS, perl=f"printf '%s' {shlex.quote(moment)}"))
            argv = ["bash", "-c", 'unset EPOCHREALTIME; . "$0"', str(HOOK)]
        req, res = self.queue / f"req-{self.seq:04d}.json", self.queue / f"res-{self.seq:04d}.json"
        tmp = req.with_suffix(".tmp"); tmp.write_text(json.dumps({"argv": argv, "payload": text, "env": run_env, "unset": list(unset)})); tmp.replace(req)
        reply = _wait_file(res); self.assertEqual(reply["code"], 0, reply["err"])
        return reply["out"]

    def test_renders_in_a_pane_keep_idle_or_busy(self):
        self.assertIsNone(self.word())
        meta, previous = {"session_id": "conv-acme", "model": {"id": "Gemini 4 Argon (Low)", "effort": "low"}}, ""
        for payload, expected in (({"agent_state": "authenticating"}, "busy"), ({**meta, "agent_state": "idle"}, "idle"),
                                  ({**meta, "agent_state": "working"}, "busy"), ({**meta, "agent_state": "idle"}, "idle"),
                                  ({**meta, "agent_state": "working"}, "busy"), ({**meta, "agent_state": "idle"}, "idle")):
            raw = json.dumps(payload)
            self.assertEqual(self.pipe_in_pane(raw), raw)
            moment, word = (self.word() or " ").split(" ")
            self.assertEqual(word, expected, payload); self.assertRegex(moment, STAMP); self.assertGreaterEqual(moment, previous); previous = moment

    def test_ordering_and_ignored_inputs(self):
        for payload, conv in (('{}\n{"session_id":"conv-acme","model":{"id":"argon","effort":"low"}}\n', "conv-acme"),
                              ('{"session_id":"conv-two","model":{"id":"argon","effort":"low"}}\n{broken\n', "conv-two")):
            self.assertEqual(self.pipe_in_pane(payload), payload); self.assertIsNone(self.word())
            self.assertEqual(json.loads((self.state / f"model-{conv}.json").read_text()), {"model": "argon", "effort": "low"})
        self.assertEqual(sorted(p.name for p in self.state.glob("model-*.json")), ["model-conv-acme.json", "model-conv-two.json"])
        for bad in (None, 1, True, [], {}):
            self.pipe_in_pane({"agent_state": bad}); self.assertIsNone(self.word(), bad)
        self.assertEqual(self.pipe_in_pane("not json"), "not json")
        self.pipe_in_pane({"agent_state": "working"}, env={"AK_RUN_ROLE": "worker"}); self.pipe_in_pane({"agent_state": "working"}, unset=("TMUX", "TMUX_PANE"))
        self.assertIsNone(self.word())
        self.pipe_in_pane({"agent_state": "working"}, moment="1000.500000"); self.assertEqual(self.word(), "000000001000.500000 busy")
        for moment in ("999.900000", "1000.500000"):
            self.pipe_in_pane({"agent_state": "idle"}, moment=moment); self.assertEqual(self.word(), "000000001000.500000 busy", moment)
        self.pipe_in_pane({"agent_state": "idle"}, moment="1000.500001"); self.assertEqual(self.word(), "000000001000.500001 idle")

    def test_a_respawn_clears_the_word_and_late_renders_of_an_earlier_launch_or_server_write_nothing(self):
        self.pipe_in_pane({"agent_state": "working"}, moment="2000.000000"); self.assertEqual(self.word(), "000000002000.000000 busy")
        gate = self.home.root / "respawn-gate"
        tools = self._tools("delayed-tmux", ("bash", "cat", "jq", "sh", "sleep"), tmux=f'while [ ! -e {shlex.quote(str(gate))} ]; do sleep 0.02; done\nexec {shlex.quote(REAL_TMUX)} "$@"')
        end, held = os.pipe()
        try:
            old = subprocess.run([str(HOOK)], input='{"agent_state":"working"}', text=True, capture_output=True, timeout=30, pass_fds=(held,), env=self._pane_env(str(tools)))
            self.assertEqual(old.returncode, 0, old.stderr)
            os.close(held); held = None; (self.queue / "ready").unlink()
            res = self.home.run(sys.executable, "-c", LAUNCH_PANE, str(ROOT), "respawn", str(self.home.path),
                                json.dumps([sys.executable, "-c", RUNNER, str(self.queue)]), json.dumps({"name": "acme", "pane": self.pane, "legacy": False}))
            self.assertEqual(res.code, 0, res.err)
            self.assertIsNone(self.word()); gate.write_text("go\n")
            with os.fdopen(end, "rb") as drained: drained.read()
            end = None; self.assertIsNone(self.word()); _wait_file(self.queue / "ready")
            self.pipe_in_pane({"agent_state": "idle"}, moment="1000.000000"); self.assertEqual(self.word(), "000000001000.000000 idle")
        finally:
            if held is not None: os.close(held)
            gate.write_text("go\n")
            if end is not None: os.close(end)
        stale = self.info["tmux"]; self.assertEqual(self.home.tmux("kill-server").code, 0)
        res = self.home.run(sys.executable, "-c", LAUNCH_PANE, str(ROOT), "start", str(self.home.path), json.dumps(["sleep", "60"]))
        self.assertEqual(res.code, 0, res.err)
        pane, pid, launch = self.home.tmux("display-message", "-p", "-t", "=acme:", "#{pane_id} #{pid} #{@ak_pane_launch}").out.split()
        # The reborn pane's own token, so only the server's pid tells the stale render from its own.
        for tmux, written in ((stale, False), (f"{stale.split(',')[0]},{pid},0", True)):
            r, w = os.pipe()
            try: subprocess.run([str(HOOK)], input='{"agent_state":"working"}', text=True, stdout=subprocess.DEVNULL, check=True, pass_fds=(w,),
                                env=self._pane_env(TMUX=tmux, TMUX_PANE=pane, AGENTKIT_PANE_LAUNCH=launch))
            finally: os.close(w)
            with os.fdopen(r, "rb") as drained: drained.read()
            kept = self.word(pane)
            if written: self.assertRegex(kept or "", rf"^{STAMP.pattern} busy$")
            else: self.assertIsNone(kept)

    def test_a_socket_path_holding_a_comma_keeps_the_word(self):
        made = self.home.tmux("-f", "/dev/null", "new-session", "-d", "-P", "-F", "#{socket_path},#{pid},0 #{pane_id}", "sleep 60", server="acme,two")
        self.assertEqual(made.code, 0, made.err); tmux, pane = made.out.split()
        # The Home's tmux takes no socket path but its own server's.
        tools = self._tools("comma-tmux", ("cat", "jq"), tmux=f'exec {shlex.quote(REAL_TMUX)} "$@"')
        r, w = os.pipe()
        try: subprocess.run([str(HOOK)], input='{"agent_state":"idle"}', text=True, stdout=subprocess.DEVNULL, check=True, pass_fds=(w,),
                            env=self._pane_env(str(tools), TMUX=tmux, TMUX_PANE=pane, AGENTKIT_PANE_LAUNCH=""))
        finally: os.close(w)
        with os.fdopen(r, "rb") as drained: drained.read()
        kept = self.home.tmux("show-options", "-pqv", "-t", pane, "@ak_agent_state", server="acme,two").out.strip()
        self.assertRegex(kept, rf"^{STAMP.pattern} idle$")

    def test_tmux_call_does_not_delay_stdout_and_concurrent_renders_keep_latest(self):
        gate, payload = self.home.root / "tmux-gate", json.dumps({"agent_state": "working"})
        slow = self._tools("slow-tmux", ("bash", "cat", "jq", "sh", "sleep"), tmux=f"while [ ! -e {shlex.quote(str(gate))} ]; do sleep 0.05; done")
        end, held = os.pipe()
        try:
            done = subprocess.run(["sh", "-c", f"{shlex.quote(str(HOOK))} | {{ cat; }}"], input=payload, text=True, capture_output=True, timeout=30, pass_fds=(held,), env=self._pane_env(str(slow)))
            self.assertEqual((done.returncode, done.stdout), (0, payload), done.stderr)
        finally:
            os.close(held); gate.write_text("go\n")
            with os.fdopen(end, "rb") as drained: drained.read()
        stamps = [(f"{5000 + i // 10}.{i % 10:06d}", "idle" if i % 2 == 0 else "working") for i in range(1, 31)]; random.shuffle(stamps)
        base, procs, pipes = self._tools("race-base", CORE_TOOLS), [], []
        try:
            for idx, (moment, state) in enumerate(stamps):
                tdir = self._tools(f"race-{idx}", (), perl=f"printf '%s' {shlex.quote(moment)}")
                r, w = os.pipe(); pipes.append(r)
                proc = subprocess.Popen(["bash", "-c", 'unset EPOCHREALTIME; . "$0"', str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, pass_fds=(w,), env=self._pane_env(f"{tdir}:{base}"))
                os.close(w); proc.stdin.write(json.dumps({"agent_state": state})); proc.stdin.close(); procs.append(proc)
            for proc in procs: self.assertEqual(proc.wait(timeout=30), 0, proc.stderr.read()); proc.stderr.close()
            for r in pipes:
                with os.fdopen(r, "rb") as drained: drained.read()
        finally:
            for proc in procs:
                if proc.poll() is None: proc.kill()
        self.assertEqual(self.word(), "000000005003.000000 idle")


if __name__ == "__main__":
    unittest.main()
