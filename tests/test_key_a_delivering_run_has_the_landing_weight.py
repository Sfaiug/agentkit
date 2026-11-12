"""A run delivering a green landing verdict has the landing check's CPU weight on its own unit,
and a run's again where it rejoins the line.

The delivery is the same landing as the line's check, which runs at the top weight; at a run's,
each delivery crawled beside a check and every member behind it waited (11 Nov 2026).
Black-box: the program `AK_BIN` names runs a task from outside through tests/fixtures/akbin.py
on the project and suite of tests/fixtures/akline.py, unsplit, with harnesses from fakeadapter.py
and the GitHub of fakegh.py.  A socket where a user manager listens, and a systemd-run that starts
each scope's command with a cgroup membership (AK_CGROUP_FILE) naming that scope, give the run a
unit of its own; systemctl records each argv and answers only set-property.
"""

import json
import os
from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.akbin import LOG, Manager
from fixtures.akline import READINGS, Line, rules
from fixtures.fakegh import GitHub

SERVICE = f"user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service"
# A scope's command runs as the manager would run it, in a cgroup of its own; a service the
# manager is refused, so that work starts plainly.
SYSTEMD_RUN = '''#!{python}
import os, pathlib, sys
args = sys.argv[1:]
if "--scope" not in args:
    sys.exit(1)
unit = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--unit="))
at = args.index("--") + 1 if "--" in args else next(
    n for n, arg in enumerate(args) if not arg.startswith("-"))
membership = pathlib.Path({memberships}, unit)
membership.write_text("0::/{service}/agentkit.slice/" + unit + ".scope\\n")
os.environ["AK_CGROUP_FILE"] = str(membership)
os.execvp(args[at], args[at:])
'''
# The target moves the first time a delivery asks for the check's weight: before it fetches.
MOVE = ('case " $* " in *" CPUWeight=10000 "*) [ -e {done} ] || {{ : >{done}; cd {clone} && '
        'echo moved >moved.txt && git add moved.txt && git commit -qm moved && '
        'git push -q origin HEAD:main; }} ;; esac\n')


def weight(unit, value):
    return ["--user", "set-property", "--runtime", f"{unit}.scope", f"CPUWeight={value}"]


class DeliveringRunHasTheLandingWeight(unittest.TestCase):
    def deliver(self, code=0, moved=False):
        """A task's run, from its start to its end, beside a manager that answers set-property
        with `code`, its target moving as its first delivery starts where `moved`; its record."""
        line = Line({"AGENTS.md": rules("sh suite.sh"), "t/ok.sh": "true\n"})
        self.addCleanup(line.close)
        self.home = home = line.home
        manager = Manager(home)
        self.addCleanup(manager.close)
        memberships = home.root / "memberships"
        memberships.mkdir()
        (memberships / "shell").write_text(f"0::/{SERVICE}/app.slice/acme.service\n")
        home.env.update(AK_HOST_READINGS=READINGS, AK_NOTIFY_SINK=None,
                        AK_CGROUP_FILE=str(memberships / "shell"))
        home.fake("busctl", "#!/bin/sh\nexit 1\n")     # nor does the manager move a process
        home.fake("systemd-run", SYSTEMD_RUN.format(
            python=sys.executable, memberships=repr(str(memberships)), service=SERVICE))
        move = ""
        if moved:
            clone = home.root / "elsewhere"
            self.assertEqual(home.run("git", "clone", "-q", line.rig.bare, clone).code, 0)
            move = MOVE.format(done=shlex.quote(str(home.root / "moved")),
                               clone=shlex.quote(str(clone)))
        home.fake("systemctl", LOG.format(python=shlex.quote(sys.executable),
                                          log=shlex.quote(str(home.log("systemctl"))))
                  + move + f'case " $* " in *" set-property "*) exit {code} ;; esac\nexit 1\n')
        GitHub(home).grant(line.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"])
        fakeadapter.install(home, claude="work", codex="pass")
        done = home.ak("run", str(taskfile.write(home, line.rig.path)), timeout=600)
        self.run_dir = taskfile.only_run(home)
        state = json.loads((self.run_dir / "run.json").read_text())
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(state.get("merged"), state)
        return state

    def asked(self, unit):
        """Each set-property asked of `unit`, oldest first."""
        return [argv for argv in self.home.calls("systemctl")
                if argv[:4] == ["--user", "set-property", "--runtime", f"{unit}.scope"]]

    def test_a_green_member_merges_at_the_checks_weight(self):
        unit = self.deliver()["scope"]
        self.assertTrue(unit.startswith("agentkit-run-"), unit)
        self.assertEqual(self.asked(unit), [weight(unit, 10000)])

    def test_a_member_whose_target_moved_rejoins_at_a_runs_weight(self):
        unit = self.deliver(moved=True)["scope"]
        self.assertEqual(self.asked(unit),
                         [weight(unit, 10000), weight(unit, 40), weight(unit, 10000)])

    def test_a_refusing_manager_costs_one_warn_line_and_the_run_merges(self):
        unit = self.deliver(code=1)["scope"]
        self.assertEqual(self.asked(unit), [weight(unit, 10000)])
        lines = (self.run_dir / "log.txt").read_text().splitlines()
        self.assertEqual(len([line for line in lines if "WARN" in line and "CPUWeight" in line]),
                         1, lines)


if __name__ == "__main__":
    unittest.main()
