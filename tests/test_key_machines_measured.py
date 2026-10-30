"""ak measures every machine it may use, and `ak doctor` says what each one is.

Owner decision, 29 Oct 2026: this one, read here, and each `[machines.<ssh alias>]` and the
`suite_helper`, asked over ssh side by side, one that never answers holding the tick only for its
ssh timeout.  A battery is sometimes on at once, under a day of checks new, 95% of the last three
days' answered always on.  Black-box: `AK_BIN` runs `ak doctor`, and `ak watch` in the box of
`home.tick()` (tests/fixtures/akbin.py), which fails a tick leaving a process; ssh is a fake
running the probe on a Mac's tools' output, the clock tests/fixtures/clock.py's, days ahead.
"""

from pathlib import Path
import re
import shlex
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, REPO, Home, boxable

DAY = 86400
# Every `bin/ak` gives `machines` the test clock, as far ahead as the file it names says.
CLOCK = """
import sys, time
if sys.argv[:1] == [{ak!r}]:
    found = sys.path[:]
    sys.path[:0] = [{repo!r}, {tests!r}]
    from fixtures.clock import Clock
    from agentkit import machines
    sys.path[:] = found
    clock = machines.time = Clock(time.sleep)
    clock.time = lambda: time.time() + float(open({ahead!r}).read())
"""
# Of the test's files in ~/fakes: the alias goes in `asked`; one named in `away` is away, one in
# `hang` never answers, one in `garbled` answers bytes that are no text, and any other runs the
# command with the tools of machines/<alias> first.
SSH = """#!/bin/sh
while :; do case $1 in --) shift; break ;; -[bcDEeFIiJLlmOoPpQRSWw]) shift 2 ;; -*) shift ;;
  *) break ;; esac; done
echo "$1" >>{root}/asked
! grep -qx "$1" {root}/away || exit 255
! grep -qx "$1" {root}/hang || exec sleep 3600
! grep -qx "$1" {root}/garbled || {{ printf '\\377\\n'; exit 0; }}
PATH={root}/machines/$1:$PATH
shift
exec sh -c "$*"
"""
MAC = {"uname": "case $1 in -s) echo Darwin ;; -m) echo arm64 ;; esac",
       "sysctl": "case $2 in hw.ncpu) echo 10 ;; hw.memsize) echo 17179869184 ;;"
                 " vm.loadavg) echo '{ 2.41 2.10 1.90 }' ;; esac",
       "memory_pressure": "echo 'System-wide memory free percentage: 20%'",
       "df": "echo 'Filesystem 1024-blocks Used Available Capacity Mounted on'\n"
             "echo '/dev/disk3s5 971350180 700000000 220200960 77% /System/Volumes/Data'"}
LAPTOP = ("Now drawing from 'Battery Power'\n"
          " -InternalBattery-0 (id=6488163)\t82%; discharging; 5:12 remaining present: true")
MINI = "Now drawing from 'AC Power'"     # no battery
SAID = "macOS arm64 · 10 cores, load 2.4 · 16 GB, 3.2 GB free · 210 GB disk free"
NEVER = "never answered"


@unittest.skipUnless(boxable(), "no bwrap able to box a tick here")
class MachinesMeasured(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = Home()
        cls.addClassCleanup(home.close)
        config = home.path / ".agentkit" / "config.toml"
        config.write_text('suite_helper = "helper"\n' + config.read_text() + "\n[audit]\n"
                          "on = false\n\n[machines.mac]\n\n[machines.mini]\n\n[machines.stuck]\n")
        home.fake("ssh", SSH.format(root=shlex.quote(str(home.path / "fakes"))))
        for alias, power in (("mac", LAPTOP), ("mini", MINI), ("helper", MINI)):
            for name, body in {**MAC, "pmset": f"cat <<'EOF'\n{power}\nEOF"}.items():
                home.write(f"fakes/machines/{alias}/{name}", f"#!/bin/sh\n{body}\n").chmod(0o755)
        home.write("fakes/sitecustomize.py", CLOCK.format(
            ak=AK, repo=str(Path(AK).resolve().parents[1]), tests=str(REPO / "tests"),
            ahead=str(home.path / "fakes" / "ahead")))
        cls.env = {"PYTHONPATH": str(home.path / "fakes")}
        cls.ticks = [cls.tick(0, away="helper", hang="stuck"), cls.tick(2 * DAY, garbled="stuck"),
                     cls.tick(3.5 * DAY, away="mini", garbled="stuck")]

    @classmethod
    def tick(cls, ahead, away="", hang="", garbled=""):
        """One tick `ahead` seconds on: the aliases ssh was given, the minutes it ran in as
        doctor writes them, and doctor's line of each machine by name."""
        for name, text in (("ahead", str(ahead)), ("away", away), ("hang", hang),
                           ("garbled", garbled), ("asked", "")):
            cls.home.write(f"fakes/{name}", text)
        start = time.time() + ahead
        done = cls.home.tick(env=cls.env)
        assert done.code == 0, done.out + done.err
        ran = {time.strftime("%-d %b %H:%M", time.gmtime(at))
               for at in (start, time.time() + ahead)}
        doctor = cls.home.ak("doctor", env=cls.env)
        assert doctor.code == 0, doctor.out + doctor.err
        return (sorted((cls.home.path / "fakes" / "asked").read_text().split()), ran,
                dict(re.findall(r"^machine  ([^:]+): (.*)$", doctor.out, re.M)))

    def test_each_tick_asks_every_other_machine_once_and_reads_this_one_here(self):
        for asked, _, lines in self.ticks:
            self.assertEqual(asked, ["helper", "mac", "mini", "stuck"])
            self.assertEqual(sorted(lines), ["helper", "mac", "mini", "stuck", "this one"])
            self.assertRegex(lines["this one"], r"^(new|sometimes on|always on) · Linux \S+ · "
                             r"\d+ cores, load [\d.]+ · [\d.]+ GB, [\d.]+ GB free · "
                             r"[\d.]+ GB disk free")

    def test_each_machine_is_what_its_checks_say(self):
        expected = (
            # a battery is sometimes on at once; under a day of checks is new, answers or not,
            # and one that hangs holds no tick
            {"mac": f"sometimes on · {SAID} · on battery", "mini": f"new · {SAID}",
             "helper": f"new · {NEVER}", "stuck": f"new · {NEVER}"},
            # every check answered for a day is always on; one of two, or none, sometimes on,
            # and an answer that is no text is one machine's miss
            {"mini": f"always on · {SAID}", "helper": f"sometimes on · {SAID}",
             "stuck": f"sometimes on · {NEVER}"},
            # only the last three days count: helper's miss at the first tick is gone
            {"mac": f"sometimes on · {SAID} · on battery", "mini": f"sometimes on · {SAID}",
             "helper": f"always on · {SAID}"})
        for n, ((_, _, lines), machines) in enumerate(zip(self.ticks, expected)):
            for name, line in machines.items():
                with self.subTest(tick=n, machine=name):
                    self.assertEqual(lines[name].split(" · last answered ")[0], line)

    def test_doctor_says_when_each_last_answered(self):
        (_, first, lines), (_, second, _), (_, _, last) = self.ticks
        self.assertIn(lines["mac"].rsplit("last answered ", 1)[1], {at[-5:] for at in first})
        self.assertIn(last["mini"].rsplit("last answered ", 1)[1], second)

    def test_machines_are_the_owner_s_in_a_config_naming_no_models(self):
        with Home() as home:
            home.write(".agentkit/config.toml", 'suite_helper = "helper"\n\n[machines.acme]\n')
            done = home.ak("doctor")
        self.assertEqual(done.code, 0, done.err)
        self.assertIn("machine  acme: new · never answered", done.out.splitlines())
        self.assertIn("machine  helper: new · never answered", done.out.splitlines())


if __name__ == "__main__":
    unittest.main()
