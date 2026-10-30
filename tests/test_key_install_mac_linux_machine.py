"""On a Mac, a server install puts ak's server in a Linux machine of its own and makes the Mac
its client.

ak's worker box, landing gate and limits exist only on Linux.  So a Mac's server install (no
saved server elsewhere, or `--server`) sets up a Linux machine once, sized from the Mac with a
share left to macOS, with the account's name and /home/<name>, none of the Mac's folders and the
Mac's checkout at the same commit; runs the Linux server install in it, with a terminal when it
has one; starts it with the Mac; and records it as the Mac's server, reached over a local ssh
alias.  A second install finds it and changes nothing already right; a client stays a client.
Black-box: install.sh of the checkout `AK_BIN` names runs in an answer-key Home that is the
account's own (tests/fixtures/installer.py), on a Mac of fakes: `uname`, `sysctl`, `df`, `brew`,
`launchctl`, `fdesetup`, a `pmset` keeping its settings in `<root>/pmset.json`, a `sudo` that
runs only `pmset` and a `limactl` whose machine is a directory, `<root>/guest`.
"""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import LOG, Home

GIB = 1024 ** 3
# The machine is a directory: `shell` runs its command in the home there, but for ak's own
# install, which it only records, with whether it had a terminal; `create` and `autostart` leave
# the files Lima leaves.
LIMACTL = """#!{python}
import json, os, subprocess, sys
from pathlib import Path
args, root = sys.argv[1:], Path({root!r})
with open(root / "logs/limactl.log", "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["autostart", "--help"]:
    sys.exit(0)
if args[0] == "create":
    lima = Path(os.environ["HOME"], ".lima/ak")
    lima.mkdir(parents=True)
    (lima / "lima.yaml").write_text("")
    (lima / "ssh.config").write_text("Host lima-ak\\n")
elif args[:2] == ["autostart", "enable"]:
    Path(os.environ["AK_LAUNCH_DAEMONS"], "io.lima-vm.daemon.ak.plist").write_text("")
elif args[0] == "shell":
    assert args[1] == "--workdir" and args[3] == "ak", args
    home, command = root / "guest" / args[2].lstrip("/"), args[4:]
    home.mkdir(parents=True, exist_ok=True)
    if command[:2] == ["bash", "agentkit/install.sh"]:
        with open(root / "logs/inside.log", "a") as log:
            log.write(json.dumps({{"args": command[2:], "tty": os.isatty(0)}}) + "\\n")
        sys.exit(int(os.environ.get("INSIDE_EXIT", "0")))
    sys.exit(subprocess.call(command, cwd=home, env={{**os.environ, "HOME": str(home)}}))
"""
BREW = LOG + '[ "$*" != "install lima" ] || cp -- {limactl} {bin}/limactl\n'
SYSCTL = '#!/bin/sh\ncase "$2" in hw.ncpu) echo {cpus} ;; hw.memsize) echo {memory} ;; *) exit 1 ;; esac\n'
DF = ("#!/bin/sh\necho 'Filesystem 1024-blocks Used Available Capacity Mounted on'\n"
      "echo '/dev/disk3s5 976490576 1 {free} 1% /System/Volumes/Data'\n")
# Each power source's settings, as `pmset -g custom` prints them; only root changes them, with
# `-a` for every source, `-c` on power, `-b` on battery.
PMSET = """#!{python}
import json, os, sys
from pathlib import Path
args, path = sys.argv[1:], Path({root!r}, "pmset.json")
with open(path.with_name("logs") / "pmset.log", "a") as log:
    log.write(json.dumps(args) + "\\n")
sources = json.loads(path.read_text())
if args == ["-g", "custom"]:
    for source, settings in sources.items():
        print(source + ":")
        for name, value in settings.items():
            print(f" {{name:<20}} {{value}}")
    sys.exit(0)
if "SUDO_USER" not in os.environ:
    sys.exit("pmset: this command requires root")
for source in {{"-a": list(sources), "-c": ["AC Power"], "-b": ["Battery Power"]}}[args[0]]:
    sources[source].update((name, int(value)) for name, value in zip(args[1::2], args[2::2]))
path.write_text(json.dumps(sources))
"""
SUDO = LOG + '[ "$1" = pmset ] || {{ echo "sudo: not scripted in this test" >&2; exit 1; }}\n' \
    'SUDO_USER=acme exec "$@"\n'
FDESETUP = '#!/bin/sh\n[ "$1" = isactive ] && echo {on} && {on}\n'
# A Mac mini as it ships: it sleeps once its display does and stays off after a power cut.
MINI = {"AC Power": {"Sleep On Power Button": 1, "autorestart": 0, "disksleep": 10, "sleep": 1,
                     "displaysleep": 10}}


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


class Mac:
    """A Mac of fakes in a Home that is the account's own, named acme."""

    def __init__(self, cpus=10, memory_gib=16, free_gib=500, power=MINI, filevault=False):
        self.home = home = Home()
        installer.prepare(home)
        installer.own_home(home)
        python = shlex.quote(sys.executable)
        staged = home.root / "limactl"
        staged.write_text(LIMACTL.format(python=sys.executable, root=str(home.root)))
        staged.chmod(0o755)
        home.fake("brew", BREW.format(python=python, log=shlex.quote(str(home.log("brew"))),
                                      limactl=shlex.quote(str(staged)),
                                      bin=shlex.quote(str(home.bin))))
        home.fake("uname", "#!/bin/sh\necho Darwin\n")
        home.fake("launchctl", "#!/bin/sh\nexit 0\n")
        home.fake("sysctl", SYSCTL.format(cpus=cpus, memory=memory_gib * GIB))
        home.fake("df", DF.format(free=free_gib * 1024 * 1024))
        home.fake("pmset", PMSET.format(python=sys.executable, root=str(home.root)))
        (home.root / "pmset.json").write_text(json.dumps(power))
        home.fake("sudo", SUDO.format(python=python, log=shlex.quote(str(home.log("sudo")))))
        home.fake("fdesetup", FDESETUP.format(on="true" if filevault else "false"))
        self.daemons = home.root / "LaunchDaemons"
        self.daemons.mkdir()
        home.env.update(USER="acme", AK_LAUNCH_DAEMONS=str(self.daemons))
        self.guest = home.root / "guest/home/acme"

    def install(self, *args, tty=False):
        done = installer.run(self.home, *args) if not tty else \
            self.home.run("bash", str(installer.INSTALL), *args, tty=True)
        assert done.code == 0, done.out + done.err
        return done

    def lima(self):
        return self.home.calls("limactl")

    def inside(self):
        return self.home.calls("inside")

    def power(self):
        return json.loads((self.home.root / "pmset.json").read_text())

    def server(self):
        path = self.home.path / ".agentkit/state/server"
        return path.read_text() if path.exists() else None

    def close(self):
        self.home.close()


class FreshMac(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mac = mac = Mac()
        cls.addClassCleanup(mac.close)
        mac.install(tty=True)
        cls.first = mac.lima()
        cls.ssh_config = (mac.home.path / ".ssh/config").read_text()
        cls.second = mac.install()

    def created(self):
        return [call for call in self.first if call[0] == "create"]

    def test_lima_is_installed_and_one_machine_created_from_debian_with_no_mac_folder(self):
        self.assertIn(["install", "lima"], self.mac.home.calls("brew"))
        [create] = self.created()
        self.assertEqual(create[-1], "template:debian")
        self.assertIn("--name=ak", create)
        self.assertIn("--mount-none", create)

    def test_it_has_the_account_s_name_and_home(self):
        [create] = self.created()
        user = create[create.index("--set") + 1]
        self.assertIn('.user.name = "acme"', user)
        self.assertIn('.user.home = "/home/acme"', user)

    def test_it_is_sized_from_the_mac_leaving_macos_its_share(self):
        [create] = self.created()
        # 10 cores keep 2, 16 GiB keep 4, 500 GiB free keep a quarter
        for flag in ("--cpus=8", "--memory=12", "--disk=375"):
            self.assertIn(flag, create)

    def test_it_is_up_and_starts_with_the_mac(self):
        self.assertIn(["start", "--tty=false", "ak"], self.first)
        self.assertIn(["autostart", "enable", "--condition=boot", "ak"], self.first)

    def test_it_holds_the_mac_s_checkout_at_the_same_commit(self):
        copy = str(self.mac.guest / "agentkit")
        self.assertEqual(git("-C", copy, "rev-parse", "HEAD"),
                         git("-C", str(installer.CHECKOUT), "rev-parse", "HEAD"))
        self.assertEqual(git("-C", copy, "remote", "get-url", "origin"),
                         git("-C", str(installer.CHECKOUT), "remote", "get-url", "origin"))

    def test_the_server_install_runs_inside_with_the_terminal_it_had(self):
        self.assertEqual(self.mac.inside(), [{"args": ["--server"], "tty": True},
                                             {"args": ["--server"], "tty": False}])

    def test_the_mac_is_its_client_over_the_machine_s_local_alias(self):
        self.assertEqual(self.mac.server(), "lima-ak\n")
        include = f"Include {self.mac.home.path}/.lima/ak/ssh.config"
        self.assertEqual(self.ssh_config.splitlines()[0], include)
        done = self.mac.home.ak("--dry-run")
        self.assertEqual(done.out, "would run ssh -t lima-ak ak --client\n", done.err)
        self.assertFalse((self.mac.home.path / ".agentkit/runs").exists())
        self.assertEqual(self.mac.home.calls("crontab"), [])

    def test_a_second_install_finds_the_machine_and_changes_nothing_already_right(self):
        again = self.mac.lima()[len(self.first):]
        self.assertEqual([call for call in again if call[0] in ("create", "autostart")
                          and call[1] != "--help"], [])
        self.assertNotIn(["sh", "-c"], [call[4:6] for call in again if call[0] == "shell"])
        self.assertEqual(self.mac.home.calls("brew").count(["install", "lima"]), 1)
        self.assertEqual((self.mac.home.path / ".ssh/config").read_text(), self.ssh_config)
        self.assertEqual(self.mac.server(), "lima-ak\n")


class SmallMac(unittest.TestCase):
    def test_a_small_mac_still_lends_the_machine_half(self):
        mac = Mac(cpus=4, memory_gib=8, free_gib=100)
        self.addCleanup(mac.close)
        mac.install("--server")
        [create] = [call for call in mac.lima() if call[0] == "create"]
        for flag in ("--cpus=2", "--memory=4", "--disk=50"):
            self.assertIn(flag, create)


class KeptMachine(unittest.TestCase):
    def test_a_version_it_swapped_in_stays_and_a_failed_server_install_records_no_server(self):
        mac = Mac()
        self.addCleanup(mac.close)
        version = mac.guest / "agentkit/.git"       # a worktree of ~/agentkit.git (versions.py)
        version.parent.mkdir(parents=True)
        version.write_text("gitdir: /home/acme/agentkit.git/worktrees/acme\n")
        mac.home.env["INSIDE_EXIT"] = "23"
        done = installer.run(mac.home)
        self.assertNotEqual(done.code, 0, done.out)
        self.assertEqual(version.read_text(), "gitdir: /home/acme/agentkit.git/worktrees/acme\n")
        self.assertIsNone(mac.server())


class Client(unittest.TestCase):
    def test_a_client_or_a_server_elsewhere_gets_no_machine(self):
        for args, record, alias in ((("--client",), None, "agentkit\n"),
                                    ((), "acme-box\n", "acme-box\n")):
            with self.subTest(args=args, record=record):
                mac = Mac()
                self.addCleanup(mac.close)
                if record:
                    mac.home.write(".agentkit/state/server", record)
                mac.install(*args)
                self.assertNotIn(["install", "lima"], mac.home.calls("brew"))
                self.assertEqual(mac.lima(), [])
                self.assertEqual(mac.inside(), [])
                self.assertEqual(mac.server(), alias)


if __name__ == "__main__":
    unittest.main()
