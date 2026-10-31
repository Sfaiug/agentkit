"""On ak's server the tick kills, through logind, a login of ak's user that ended a day ago and
still runs something, and says so in one line of its log.

Offline: loginctl, systemctl, the session cgroups, the process table and the clock are fixtures.
"""

import os
import subprocess
import time
import unittest
from unittest.mock import patch

from fixtures.clock import Clock
from fixtures.sandbox import Sandbox
from agentkit import config, gc, orch, watch

NOW = 30 * 86400
HOUR = 3600
UID = str(os.getuid())


class EndedLoginLeftoversStopped(Sandbox):
    def setUp(self):
        super().setUp()
        self.logins, self.commands, self.lines, self.gone = {}, [], [], []
        self.running = {4242: (1, ["opencode", "serve", "--service"]),
                        4343: (1, ["bash", "-c", "while sleep 60; do :; done"])}
        self.cgroups = self.root / "cgroup"
        self.stack.enter_context(patch.dict(os.environ, {
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0", "AK_CGROUP_ROOT": str(self.cgroups)}))
        for name in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG"):
            os.environ.pop(name, None)
        clock = Clock(time.sleep)
        clock.monotonic = lambda: NOW
        self.stack.enter_context(patch.object(gc, "time", clock))
        self.stack.enter_context(patch.object(orch, "user_manager", return_value=True))
        self.stack.enter_context(patch.object(orch, "processes",
                                              side_effect=lambda: dict(self.running)))
        self.stack.enter_context(patch.object(gc.subprocess, "run", side_effect=self.system))
        (config.STATE / "installed-at").write_text("1000\n")     # install.sh on a server

    def login(self, number, state, since, pids=(4242,), uid=UID, nested=()):
        group = f"/user.slice/user-{uid}.slice/session-{number}.scope"
        self.logins[number] = {"uid": uid, "Id": f"session-{number}.scope", "SubState": state,
                               "ControlGroup": group,
                               "StateChangeTimestampMonotonic": str((NOW - since) * 1_000_000)}
        scope = self.cgroups / group.lstrip("/")
        scope.mkdir(parents=True)
        (scope / "cgroup.procs").write_text("".join(f"{pid}\n" for pid in pids))
        (scope / "workload").mkdir()              # a child: the scope's own list leaves it out
        (scope / "workload/cgroup.procs").write_text("".join(f"{pid}\n" for pid in nested))
        (scope / "threads/cgroup.procs").mkdir(parents=True)   # unreadable, as a threaded child's

    def system(self, command, **_kw):
        self.commands.append(command)
        output = ""
        if command == ["loginctl", "list-sessions", "--no-legend"]:
            output = "".join(f"{number} {login['uid']} acme - pts/{number}\n"
                             for number, login in self.logins.items())
        elif command[:2] == ["systemctl", "show"]:
            shown = {login["Id"]: login for login in self.logins.values()}
            output = "\n\n".join(
                "\n".join(f"{key}={value}" for key, value in shown.get(unit, {
                    "Id": unit, "SubState": "dead", "ControlGroup": "",
                    "StateChangeTimestampMonotonic": "0"}).items() if key != "uid")
                for unit in command[2:] if unit.startswith("session-"))
        elif command[:2] == ["loginctl", "terminate-session"]:
            pass        # as logind, which began stopping the login when it ended, answers it
        elif command[:2] == ["loginctl", "kill-session"]:
            if "--signal=SIGKILL" in command:          # OpenCode's server catches TERM
                self.gone.append(command[-1])
                self.logins.pop(command[-1])
                self.running.clear()                   # the login's processes go with it
        else:
            self.fail(f"not a logind or systemd question: {command}")
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    def tick(self):
        step = next(step for what, step, _ in watch.local_passes({}, False, self.lines.append)
                    if what == "ended logins")
        step()

    def stopped(self):
        return self.gone

    def test_a_login_ended_a_day_ago_is_stopped_through_logind(self):
        self.login("34", "abandoned", 25 * HOUR, nested=(4343,))
        self.login("35", "abandoned", 2 * 86400, pids=())           # nothing left running
        self.login("36", "abandoned", 3 * 86400, uid=str(os.getuid() + 1))   # another user's
        self.tick()
        self.assertEqual(self.stopped(), ["34"])
        self.assertEqual(self.lines, ["stopped login 34, ended 1d ago, still running: opencode "
                                      "serve --service; bash -c while sleep 60; do :; done"])

    def test_a_login_logind_will_not_terminate_is_killed(self):
        self.login("34", "abandoned", 2 * 86400)
        self.tick()
        self.assertEqual((self.running, self.lines), ({}, [
            "stopped login 34, ended 2d ago, still running: opencode serve --service"]))

    def test_a_login_ended_an_hour_ago_is_kept(self):
        self.login("34", "abandoned", HOUR)
        self.tick()
        self.assertEqual((self.stopped(), self.lines), ([], []))

    def test_a_login_in_use_is_kept(self):
        self.login("34", "running", 3 * 86400)                     # logged in three days ago
        self.tick()
        self.assertEqual((self.stopped(), self.lines), ([], []))

    def test_a_client_host_stops_nothing(self):
        self.login("34", "abandoned", 3 * 86400)
        (config.STATE / "server").write_text("agentkit\n")      # install.sh --client
        self.tick()
        (config.STATE / "server").unlink()
        (config.STATE / "installed-at").unlink()                  # never installed here
        self.tick()
        self.assertEqual((self.commands, self.lines), ([], []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
