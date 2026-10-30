"""Every `ak` command marks what it starts, and nothing meant to outlive it carries the mark.

`bin/ak` sets `owner.MARK` just before it runs a command: this process's pid namespace, pid and
start, the command and the seat, inherited by all it starts.  `--help` and an unknown command
set none and read nothing.  A unit, a tmux server, a seat's pane, the warm server, each detached
start and a sign-in are started unmarked; the menu's install keeps the mark.

Offline: a command's body is a stand-in, the unit's work, the seat's harness, tmux and the
adapter are the test's own small programs, and every detached start is caught at `Popen`.
"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.sandbox import REPO, Sandbox  # noqa: E402
from agentkit import config, gc, menu, orch, owner, update, warm, watch  # noqa: E402

MARKED = "4026531836 4242 777 watch acme"
# `ak usage` through bin/ak, its body a stand-in reporting what it runs under
PROBE = r"""
import json, os, runpy, subprocess, sys
repo = sys.argv[1]
sys.path.insert(0, repo)
from agentkit import owner, usage
opened, seen = [], {}
sys.addaudithook(lambda event, values: event == "open" and not seen
                 and isinstance(values[0], (str, bytes, os.PathLike))
                 and os.fsdecode(values[0]).startswith("/proc/")
                 and opened.append(os.fsdecode(values[0])))
def body(argv):
    with open("/proc/self/stat") as stat:
        seen["start"] = int(stat.read().rsplit(")", 1)[1].split()[19])
    seen.update(pid=os.getpid(), mark=os.environ.get(owner.MARK),
                namespace=os.stat("/proc/self/ns/pid").st_ino, child=subprocess.run(
                    [sys.executable, "-c", f"import os; print(os.environ[{owner.MARK!r}])"],
                    capture_output=True, text=True).stdout.removesuffix("\n"))
    return 0
usage.main = body
sys.argv = [os.path.join(repo, "bin", "ak"), *sys.argv[2:]]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit as exc:
    code = exc.code
print(json.dumps({"code": code, "seen": seen, "opened": opened,
                  "mark": os.environ.get(owner.MARK)}))
"""
SAYS = [sys.executable, "-c", f"import os; print(os.environ.get({owner.MARK!r}, 'unmarked'), "
        "os.environ.get('AGENTKIT_RUN'))"]


class AkMarksWhatItStarts(Sandbox):
    def setUp(self):
        super().setUp()
        self.adapters, self.said = self.root / "adapters", self.root / "said"
        self.adapters.mkdir()
        (self.adapters / "relay.sh").write_text(
            f'#!/bin/sh\necho "$1 ${{{owner.MARK}-unmarked}}" >> "{self.said}"\n')
        (self.adapters / "relay.sh").chmod(0o755)
        self.stack.enter_context(patch.dict(os.environ, {
            owner.MARK: MARKED, "TERM": "xterm-256color",
            config.ADAPTER_DIR_ENV: str(self.adapters)}))

    def ak(self, *args, session=None):
        env = {key: value for key, value in os.environ.items()
               if key not in (owner.MARK, config.SESSION_ENV)}
        env.update({config.SESSION_ENV: session} if session else {})
        done = subprocess.run([sys.executable, "-c", PROBE, str(REPO), *args], env=env,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout.splitlines()[-1])

    def test_a_command_runs_under_a_mark_naming_its_own_ak(self):
        for session in ("acme", None):
            with self.subTest(session=session):
                said = self.ak("usage", session=session)
                seen = said["seen"]
                self.assertEqual(seen["mark"], f"{seen['namespace']} {seen['pid']} "
                                               f"{seen['start']} usage {session or ''}")
                self.assertEqual(seen["child"], seen["mark"])     # what it starts inherits it

    def test_help_and_an_unknown_command_set_none_and_read_nothing(self):
        for args, code in ((["usage", "--help"], 0), (["--help"], 0), (["bogus"], 2)):
            with self.subTest(args=args):
                said = self.ak(*args)
                self.assertEqual((said["code"], said["mark"], said["opened"], said["seen"]),
                                 (code, None, [], {}))

    def test_a_unit_starts_unmarked_and_keeps_its_run_s_marker(self):
        out = self.root / "unit.out"
        with patch.object(orch, "user_manager", return_value=False):
            _, proc, _ = orch._start_in_slice(SAYS, "agentkit-test-unit",
                                              {**os.environ, "AGENTKIT_RUN": "/runs/fix-api"},
                                              out, lambda _: None, "agentkit-test.slice")
        proc.wait(timeout=60)
        self.assertEqual(out.read_text().split(), ["unmarked", "/runs/fix-api"])

    def test_no_tmux_command_hands_a_server_the_mark(self):
        tmux, seen = self.root / "fake-bin" / "tmux", self.root / "tmux.seen"
        tmux.parent.mkdir()
        tmux.write_text(f'#!/bin/sh\necho "${{{owner.MARK}-unmarked}}" >> "{seen}"\n')
        tmux.chmod(0o755)
        with patch.dict(os.environ, {"PATH": str(tmux.parent)}):     # no real tmux to reach
            orch.tmux_out("new-session", "-d", "-s", "acme")
            orch.tmux_out("switch-client", "-t", "acme", client=True)
        self.assertEqual(seen.read_text().split(), ["unmarked", "unmarked"])

    def test_a_seat_s_pane_drops_a_mark_its_server_holds(self):
        with patch.object(orch, "user_manager", return_value=False):
            command, _ = orch.seat_command("acme", SAYS)
        self.assertIsNone(orch.seat_env("acme", "agentkit-test")[owner.MARK])   # -r: later panes
        ran = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
        self.assertEqual(ran.stdout.split()[:1], ["unmarked"], ran.stderr)

    def test_the_warm_server_starts_unmarked(self):
        with patch.object(warm.os, "posix_spawn") as spawn:
            warm._start(str(REPO))
        env = spawn.call_args.args[2]
        self.assertIn("PATH", env)
        self.assertNotIn(owner.MARK, env)

    def test_each_detached_start_is_unmarked(self):
        started = []

        def popen(argv, **kw):
            started.append(kw.get("env"))
            return SimpleNamespace(pid=0)
        starts = {
            "gc.schedule_gc": lambda: gc.schedule_gc(print),
            "update.start": lambda: update.start("claude"),
            "menu.update_first": menu.update_first,
            "menu.stop_behind": lambda: menu.stop_behind("acme", True),
            "watch.start_look": lambda: watch.start_look("acme"),
            "orch.stop_scope": lambda: orch.stop_scope("agentkit-run-fix-api", wait=False),
        }
        with patch.object(subprocess, "Popen", popen), \
                patch.object(update, "agentkit_dir", return_value=config.REPO), \
                patch.object(orch, "user_manager", return_value=True), \
                patch.object(orch.host, "cgroup_contains", return_value=False), \
                patch.dict(os.environ, {"TMUX": "/tmp/tmux-1/default,1,0", "TMUX_PANE": "%1"}):
            for name, start in starts.items():
                with self.subTest(start=name):
                    del started[:]
                    start()
                    self.assertEqual(len(started), 1)
                    self.assertIsNotNone(started[0])      # None would hand on this one's own
                    self.assertNotIn(owner.MARK, started[0])

    def verbs(self, *verbs):
        keyboard = Mock()
        with patch.object(menu, "pause"), redirect_stdout(io.StringIO()), \
                patch.object(menu.worker, "auth_ok", return_value=(True, "ok")):
            failed = menu._adapter_verbs(keyboard, "relay", verbs, "Zeta", provider="zeta")
        self.assertEqual(keyboard.method_calls, [call.give(), call.take()])   # the keys back
        return failed

    def test_a_sign_in_is_unmarked_and_the_install_keeps_the_mark(self):
        self.assertEqual(self.verbs("install", "login"), "")
        self.assertEqual(self.verbs("login again"), "")
        self.assertEqual(self.said.read_text().splitlines(),
                         [f"install {MARKED}", "login unmarked", "login unmarked"])

    def test_a_malformed_manifest_fails_that_step_and_gives_the_keys_back(self):
        (self.adapters / "relay.toml").write_text("[launch\n")
        for verb in ("install", "login"):
            with self.subTest(verb=verb):
                self.assertEqual(self.verbs(verb),
                                 f"relay {verb} did not finish; Zeta is not added")
        self.assertFalse(self.said.exists())


if __name__ == "__main__":
    unittest.main()
