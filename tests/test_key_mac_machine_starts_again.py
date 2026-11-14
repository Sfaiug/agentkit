"""On a Mac, ak's Linux machine starts again by itself when it stops or stops answering.

Lima's own LaunchDaemon starts the machine only when the Mac boots.  So the install also puts a
LaunchDaemon of ak's own, which checks the machine every minute as the account: one stopped
starts; one running, or Broken as Lima says while its host agent does not answer, that has not
answered `ssh -F <Lima's own ssh file for it> lima-ak true` for 10 minutes, whatever the account's
own ssh setup knows, is stopped by force and starts, once, even when that start fails, until it
answers again, is started anew or the Mac starts, each whatever the clock reads by then;
anything else changes nothing.  The time it last answered or started outlives
each check and an install that finds it running, silence counts only while the machine runs, so
never from before the Mac started, and with no answer on record, from the first check.  The
install says so in one line, a second changes nothing, and one after the daemon was booted out
loads it again.  Black-box on the Mac of fakes of tests/test_key_install_mac_linux_machine.py:
each check runs the daemon's program as launchd would, with only its environment, on a clock of
fakes (`date +%s` reads `<root>/now`, the Mac's boot time is `<root>/boot`, its boot's id
`<root>/session`) and an `ssh` that answers while the machine runs and is not hung, and the
config it reads, the one `-F` names or else the account's, with each file it includes, knows it.
"""

import json
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_key_install_mac_linux_machine import Mac

BOOT, DAY = 1_794_268_800, 24 * 3600     # 10 Nov 2026, at midnight
SSH = """#!{python}
import json, os, sys
from pathlib import Path
args, root = sys.argv[1:], Path({root!r})
with open(root / "logs/ssh.log", "a") as log:
    log.write(json.dumps(args) + "\\n")
def knows(config):
    lines = config.read_text().splitlines() if config.is_file() else []
    return "Host lima-ak" in lines or any(knows(Path(line.split(None, 1)[1]))
                                          for line in lines if line.startswith("Include "))
config = Path(args[args.index("-F") + 1] if "-F" in args else os.environ["HOME"] + "/.ssh/config")
machine = root / "machine"
up = machine.exists() and machine.read_text() == "Running" and not (root / "hung").exists()
sys.exit(0 if up and knows(config) and args[-2:] == ["lima-ak", "true"] else 255)
"""
DATE = '#!/bin/sh\n[ "$*" = +%s ] && exec cat {now}\nPATH=/usr/bin:/bin exec date "$@"\n'


class Watched(Mac):
    """A Mac of fakes with ak's machine on it."""

    def __init__(self):
        super().__init__()
        root = self.home.root
        self.home.fake("ssh", SSH.format(python=sys.executable, root=str(root)))
        self.home.fake("date", DATE.format(now=shlex.quote(str(root / "now"))))
        for name in ("boot", "session"):
            (root / name).write_text(str(BOOT))
        self.at(BOOT + 3600)

    def at(self, now):
        (self.home.root / "now").write_text(str(now))

    def started(self, at):
        """The Mac started at `at`, which names that boot, and Lima's daemon started the
        machine with it."""
        for name in ("boot", "session"):
            (self.home.root / name).write_text(str(at))
        (self.home.root / "machine").write_text("Running")
        (self.home.root / "hung").unlink(missing_ok=True)

    def hangs(self):
        (self.home.root / "hung").write_text("")

    def stops(self):
        """As `limactl stop`, a power-off inside or a dead host agent leaves it."""
        (self.home.root / "machine").write_text("Stopped")

    def breaks(self):
        """Its host agent runs but does not answer Lima."""
        (self.home.root / "machine").write_text("Broken")

    def answers(self):
        return subprocess.run([self.home.bin / "ssh", "-F", self.home.path / ".lima/ak/ssh.config",
                               "lima-ak", "true"]).returncode == 0

    def loaded(self):
        """The services launchd has loaded, as `<domain>/<label>`."""
        return json.loads((self.home.root / "launchd.json").read_text())

    def loads(self):
        """launchctl's calls that load or unload a service."""
        return [call for call in self.home.calls("launchctl")
                if call[0] in ("bootstrap", "bootout")]

    def daemons_of_ak(self):
        return [path for path in self.daemons.glob("*.plist")
                if not path.name.startswith("io.lima-vm.")]

    def check(self, at, fails=False):
        """Run the daemon's program once at `at`, as launchd runs it; the limactl calls it made
        but to list the machine.  It fails only where `fails` says so."""
        self.at(at)
        [plist] = self.daemons_of_ak()
        daemon = plistlib.loads(plist.read_bytes())
        before = len(self.lima())
        done = subprocess.run(daemon["ProgramArguments"], cwd="/", stdin=subprocess.DEVNULL,
                              env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                                   **daemon.get("EnvironmentVariables", {})},
                              capture_output=True, text=True, timeout=120)
        assert (done.returncode != 0) == fails, done.stdout + done.stderr
        return [call for call in self.lima()[before:] if call[0] != "list"]


class KeptUp(unittest.TestCase):
    """One Mac, installed twice; each test of the check on a day of its own, an hour after the
    Mac started."""
    day = 0

    @classmethod
    def setUpClass(cls):
        cls.mac = mac = Watched()
        cls.addClassCleanup(mac.close)
        cls.first = mac.install().out.splitlines()
        [cls.plist] = mac.daemons_of_ak()
        cls.daemon = cls.plist.read_bytes()
        cls.service = "system/" + plistlib.loads(cls.daemon)["Label"]
        cls.loaded, cls.loads = mac.loaded(), mac.loads()
        cls.second = mac.install().out.splitlines()
        cls.loads_again = mac.loads()[len(cls.loads):]

    def setUp(self):
        KeptUp.day += 1
        self.now = BOOT + KeptUp.day * DAY
        self.mac.started(self.now - 3600)

    def holds(self, path, text):
        """The file at `path` in the account's home holds `text` until the test ends."""
        path = self.mac.home.path / path
        self.addCleanup(path.write_text, path.read_text())
        path.write_text(text)

    def minutes(self, first, last):
        """A check each minute from `first` to `last` minutes on: what each did to the machine."""
        return [[call[0] for call in self.mac.check(self.now + minute * 60)]
                for minute in range(first, last + 1)]

    def test_a_daemon_of_ak_s_own_checks_the_machine_every_minute_as_the_account(self):
        daemon = plistlib.loads(self.daemon)
        self.assertEqual(daemon["StartInterval"], 60)
        self.assertEqual(daemon["UserName"], "acme")
        self.assertIs(daemon["AbandonProcessGroup"], True)
        self.assertIn(self.service, self.loaded)

    def test_the_install_says_so_in_one_line(self):
        [line] = [line for line in self.first if "stops answering" in line]
        self.assertIn("starts again", line)

    def test_a_second_install_keeps_the_one_daemon_as_it_was(self):
        self.assertEqual(self.mac.daemons_of_ak(), [self.plist])
        self.assertEqual(self.plist.read_bytes(), self.daemon)
        self.assertEqual(self.loads_again, [])
        self.assertEqual([line for line in self.second if "stops answering" in line], [])

    def test_the_next_install_brings_back_a_machine_stopped_for_good(self):
        subprocess.run([self.mac.home.bin / "launchctl", "bootout", self.service], check=True)
        self.mac.stops()
        self.mac.at(self.now)
        self.mac.install()
        self.assertIn(self.service, self.mac.loaded())
        self.mac.hangs()
        self.assertEqual(self.minutes(1, 9), [[]] * 9)
        self.assertEqual(self.minutes(10, 10), [["stop", "start"]])

    def test_a_machine_not_running_starts(self):
        self.mac.stops()
        self.assertEqual(self.minutes(0, 0), [["start"]])
        self.assertTrue(self.mac.answers())

    def test_a_running_machine_that_answers_is_left_as_it_is(self):
        asked = len(self.mac.home.calls("ssh"))
        self.assertEqual(self.minutes(0, 0), [[]])
        self.assertEqual([call[-2:] for call in self.mac.home.calls("ssh")[asked:]],
                         [["lima-ak", "true"]])

    def test_a_machine_answering_through_lima_s_own_file_is_left_as_it_is(self):
        """Whatever the account's own ssh setup knows, as one that lost its Include."""
        self.holds(".ssh/config", "")
        self.assertEqual(self.minutes(0, 10), [[]] * 11)

    def test_one_not_answering_through_lima_s_own_file_stops_by_force_after_ten_minutes(self):
        """Whatever the account's own ssh setup reaches."""
        self.minutes(0, 0)
        self.holds(".ssh/config", "Host lima-ak\n")
        self.holds(".lima/ak/ssh.config", "")
        self.assertEqual(self.minutes(1, 10), [[]] * 9 + [["stop", "start"]])

    def test_nine_minutes_without_an_answer_change_nothing(self):
        self.minutes(0, 0)
        self.mac.hangs()
        self.assertEqual(self.minutes(1, 9), [[]] * 9)

    def test_ten_minutes_without_an_answer_stop_it_by_force_and_start_it(self):
        self.minutes(0, 0)
        self.mac.hangs()
        self.assertEqual(self.minutes(1, 9), [[]] * 9)
        stop, start = self.mac.check(self.now + 600)
        self.assertEqual((stop[0], start[0]), ("stop", "start"))
        self.assertTrue({"--force", "-f"} & set(stop), stop)
        self.assertTrue(self.mac.answers())

    def test_one_stopped_by_force_is_left_running_until_it_has_answered_again(self):
        """What fails may be the check's own way to the machine, and each stop ends every
        session in it: a restart that brought no answer is not tried again."""
        self.minutes(0, 0)
        self.mac.hangs()
        self.assertEqual(self.minutes(10, 10), [["stop", "start"]])
        self.mac.hangs()    # started, and still no answer
        self.assertEqual(self.minutes(11, 40), [[]] * 30)
        self.mac.started(self.now - 3600)    # it answers again
        self.assertEqual(self.minutes(41, 41), [[]])
        self.mac.hangs()
        self.assertEqual(self.minutes(42, 51), [[]] * 9 + [["stop", "start"]])

    def test_one_stopped_by_force_is_left_running_though_its_start_failed(self):
        """Lima's start fails with the machine left running when something it waits for in the
        machine never comes."""
        staged = self.mac.home.root / "limactl"
        self.addCleanup(shutil.copy, staged, self.mac.home.bin / "limactl")
        self.mac.home.fake("limactl",
                           f'#!/bin/sh\n{shlex.quote(str(staged))} "$@" && [ "$1" != start ]\n')
        self.minutes(0, 0)
        self.mac.hangs()
        self.assertEqual([call[0] for call in self.mac.check(self.now + 600, fails=True)],
                         ["stop", "start"])
        self.mac.hangs()
        self.assertEqual(self.minutes(11, 11), [[]])

    def test_one_stopped_by_force_is_left_running_when_the_clock_is_set(self):
        """Setting a Mac's clock moves its boot time with it."""
        self.minutes(0, 0)
        self.mac.hangs()
        self.assertEqual(self.minutes(10, 10), [["stop", "start"]])
        self.mac.hangs()
        (self.mac.home.root / "boot").write_text(str(self.now - 3660))
        self.assertEqual(self.minutes(11, 21), [[]] * 11)

    def test_a_stop_by_force_from_before_the_mac_started_does_not_count(self):
        self.minutes(0, 0)
        self.mac.hangs()
        self.assertEqual(self.minutes(10, 10), [["stop", "start"]])
        self.mac.started(self.now + 3600)    # before it answered again
        self.mac.hangs()
        self.assertEqual(self.minutes(69, 70), [[], ["stop", "start"]])
        self.mac.started(self.now + 4140)    # again, by a clock set back to before that stop
        self.mac.hangs()
        self.assertEqual(self.minutes(79, 80), [[], ["stop", "start"]])

    def test_the_answer_or_start_after_a_stop_by_force_counts_even_by_a_clock_set_back(self):
        self.minutes(0, 0)
        self.mac.hangs()
        self.assertEqual(self.minutes(10, 10), [["stop", "start"]])
        self.assertEqual(self.minutes(9, 9), [[]])    # it answers, the clock set back a minute
        self.mac.hangs()
        self.assertEqual(self.minutes(18, 19), [[], ["stop", "start"]])
        self.mac.stops()
        self.assertEqual(self.minutes(18, 18), [["start"]])    # the clock set back again
        self.mac.hangs()
        self.assertEqual(self.minutes(27, 28), [[], ["stop", "start"]])

    def test_the_ten_minutes_count_across_runs_from_the_last_answer(self):
        self.assertEqual(self.minutes(0, 0) + self.minutes(5, 5), [[], []])
        self.mac.hangs()
        self.assertEqual(self.minutes(14, 15), [[], ["stop", "start"]])

    def test_an_install_while_it_hangs_keeps_its_last_answer(self):
        self.minutes(0, 0)
        self.mac.hangs()
        self.mac.at(self.now + 540)
        self.mac.install()
        self.assertEqual(self.minutes(10, 10), [["stop", "start"]])

    def test_a_broken_machine_that_has_not_answered_for_ten_minutes_too(self):
        self.minutes(0, 0)
        self.mac.breaks()
        self.assertEqual(self.minutes(1, 9), [[]] * 9)
        self.assertEqual(self.minutes(10, 10), [["stop", "start"]])
        self.assertTrue(self.mac.answers())

    def test_silence_from_before_the_mac_started_does_not_count(self):
        self.minutes(0, 0)
        self.mac.started(self.now + 3600)    # off for an hour
        self.mac.hangs()
        self.assertEqual(self.minutes(61, 69), [[]] * 9)
        self.assertEqual(self.minutes(70, 70), [["stop", "start"]])

    def test_silence_before_a_check_found_it_stopped_does_not_count_whoever_starts_it(self):
        """Another start may come right after the check's look at its status."""
        self.minutes(0, 0)
        self.mac.hangs()
        self.mac.stops()
        root = self.mac.home.root
        self.mac.home.fake("limactl", f'#!/bin/sh\n{shlex.quote(str(root / "limactl"))} "$@" &&'
                                      f' printf Running >{shlex.quote(str(root / "machine"))}\n')
        self.assertEqual(self.minutes(9, 9), [[]])
        shutil.copy(root / "limactl", self.mac.home.bin / "limactl")
        self.assertEqual(self.minutes(10, 19), [[]] * 9 + [["stop", "start"]])

class RunningBefore(unittest.TestCase):
    """A Mac whose machine Lima started with it before ak's check came: the check has no answer
    on record, and the machine hangs as the install puts the check."""

    def test_its_ten_minutes_count_from_the_first_check(self):
        mac = Watched()
        self.addCleanup(mac.close)
        lima = mac.home.path / ".lima/ak"
        lima.mkdir(parents=True)
        (lima / "lima.yaml").write_text("")
        (lima / "ssh.config").write_text("Host lima-ak\n")
        shutil.copy(mac.home.root / "limactl", mac.home.bin / "limactl")
        mac.started(BOOT)
        mac.hangs()
        mac.install()
        self.assertNotIn("start", [call[0] for call in mac.lima()])
        calls = [[call[0] for call in mac.check(BOOT + 3600 + minute * 60)]
                 for minute in range(11)]
        self.assertEqual(calls, [[]] * 10 + [["stop", "start"]])

class ItsOwnStore(unittest.TestCase):
    """A Mac whose Lima keeps its machines where LIMA_HOME names, which launchd passes on to
    no daemon."""

    def test_its_check_watches_the_machine_in_the_store_the_install_used(self):
        mac = Watched()
        self.addCleanup(mac.close)
        mac.home.env["LIMA_HOME"] = str(mac.home.root / "store")
        mac.install()
        self.assertEqual(mac.check(BOOT + 3600), [])    # it answers through the store's ssh file
        mac.hangs()
        calls = [[call[0] for call in mac.check(BOOT + 3600 + minute * 60)]
                 for minute in range(1, 11)]
        self.assertEqual(calls, [[]] * 9 + [["stop", "start"]])

if __name__ == "__main__":
    unittest.main()
