"""A server install ends saying whether this machine stays on: ak's home, or a laptop ak runs on
only while it is awake.

ak works while its owner sleeps, so it needs one machine that stays on (owner, 24 Nov 2026).
After its summary, on stdout, a server install whose own machine is the one a person sits at
reads `tools/machine.sh` here: with `battery 0` it says this machine is ak's home and how to
start; with `battery 1` it says this machine is a laptop and, when `README.md` holds one line
with both `git clone` and `install.sh`, gives that line to paste on a machine that stays on and
the client install to run here after (with none or several, those lines are left out).  A Linux
machine that Lima runs (`/mnt/lima-cidata` exists) prints nothing: its Mac's installer prints
from the Mac's own `tools/machine.sh` answer, with nothing passed between the two installers.
A client install, the throwaway-HOME sandbox and `--prepare` print nothing.  Black-box: the real
install.sh of a copy of the checkout `AK_BIN` names (tests/fixtures/installer.py), with a fake
`tools/machine.sh` put in its place and `AK_LIMA_CIDATA` pointed at `<root>/lima-cidata`, runs
in an answer-key Home that is the account's own; and on the fake Mac of
tests/test_key_install_mac_linux_machine.py.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import installer
from fixtures.akbin import Home
from test_key_install_mac_linux_machine import MINI, Mac

LAPTOP_POWER = {"Battery Power": {"sleep": 1, "displaysleep": 2}, **MINI}
ANSWER = """#!/bin/sh
cat <<'EOF'
system Linux
cores 4
memory_mb 7951
free_mb 6020
load 0.4
processor x86_64
disk_free_mb 81920
battery {battery}
power 1
EOF
"""
HOME_LINES = (
    "This machine is ak's home. It has no battery, so ak takes it to stay on.\n"
    "Type ak, press n and say what you want.\n"
)
LAPTOP_HEAD = (
    "This machine is a laptop. ak needs one machine that stays on: it works while you\n"
    "sleep, and a laptop does not. ak runs here while this laptop is awake.\n"
)
FIRST_LINES = (HOME_LINES.splitlines()[0], LAPTOP_HEAD.splitlines()[0])


def laptop_lines(install_line):
    return (
        LAPTOP_HEAD
        + "For a machine that stays on (a rented VM, a PC, a Mac mini), paste there:\n"
        + f"  {install_line}\n"
        + "then here: ./install.sh --client <its ssh name>\n"
    )


def readme_install_line(readme):
    lines = [line for line in readme.read_text().splitlines()
             if "git clone" in line and "install.sh" in line]
    assert len(lines) == 1, lines
    return lines[0]


def account(case):
    """A Home that is the account's own until `case`'s tests are done, with `AK_LIMA_CIDATA` at
    `<root>/lima-cidata`, nonexistent until a test creates it."""
    home = Home()
    case.addClassCleanup(home.close)
    installer.prepare(home)
    installer.own_home(home)
    home.env["AK_LIMA_CIDATA"] = str(home.root / "lima-cidata")
    return home


@unittest.skipUnless(sys.platform.startswith("linux"), "a Linux host's install")
class SaysWhetherThisMachineStaysOn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = home = account(cls)
        cls.checkout = checkout = home.root / "checkout"
        cls.script = installer.copy(checkout)
        cls.readme = (checkout / "README.md").read_text()
        cls.install_line = readme_install_line(checkout / "README.md")
        cls.probe = checkout / "tools" / "machine.sh"

        cls.probe.write_text(ANSWER.format(battery=0))
        cls.plugged = cls.install(home, "--server")

        cls.lima_home = account(cls)
        (cls.lima_home.root / "lima-cidata").mkdir()
        cls.lima_plugged = cls.install(cls.lima_home, "--server")

        cls.probe.write_text(ANSWER.format(battery=1))
        cls.laptop = cls.install(home, "--server")
        cls.lima_laptop = cls.install(cls.lima_home, "--server")

        cls.client = cls.install(account(cls), "--client", "acme-box")

        sandbox = Home()
        cls.addClassCleanup(sandbox.close)
        installer.prepare(sandbox)
        sandbox.env["AK_LIMA_CIDATA"] = str(sandbox.root / "lima-cidata")
        cls.sandbox = cls.install(sandbox, "--server")

        cls.prepare = cls.install(home, "--prepare")

    @classmethod
    def install(cls, home, *args):
        return home.run("bash", str(cls.script), *args)

    def said_last(self, done, expected):
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertTrue(done.out.endswith(expected), done.out)
        self.assertIn("summary: server;", done.out[:-len(expected)])

    def said_neither(self, done, mode=None):
        self.assertEqual(done.code, 0, done.out + done.err)
        if mode is not None:
            self.assertIn(f"summary: {mode};", done.out)
        for line in FIRST_LINES:
            self.assertNotIn(line, done.out)
            self.assertNotIn(line, done.err)

    def test_no_battery_says_this_machine_is_ak_s_home(self):
        self.said_last(self.plugged, HOME_LINES)

    def test_battery_says_this_machine_is_a_laptop_with_the_readme_line(self):
        self.said_last(self.laptop, laptop_lines(self.install_line))

    def test_with_no_or_several_readme_lines_the_pasting_lines_are_left_out(self):
        cases = {
            "none": "# agentkit\n\ngit clone https://example.com/acme/agentkit\n./install.sh\n"
                    "git clone https://example.com/acme/agentkit && ~/agentkit/installXsh\n",
            "several": f"# agentkit\n\n{self.install_line}\n{self.install_line} --server\n",
        }
        self.probe.write_text(ANSWER.format(battery=1))
        self.addCleanup(lambda: (self.checkout / "README.md").write_text(self.readme))
        for name, text in cases.items():
            with self.subTest(name):
                (self.checkout / "README.md").write_text(text)
                done = self.install(self.home, "--server")
                self.said_last(done, LAPTOP_HEAD)
                self.assertNotIn("paste there:", done.out)
                self.assertNotIn("./install.sh --client", done.out)

    def test_a_lima_guest_prints_neither_first_line(self):
        self.said_neither(self.lima_plugged, "server")
        self.said_neither(self.lima_laptop, "server")

    def test_a_client_install_prints_neither_first_line(self):
        self.said_neither(self.client, "client of acme-box")

    def test_a_sandbox_home_prints_neither_first_line(self):
        self.said_neither(self.sandbox, "server")

    def test_prepare_prints_nothing(self):
        self.said_neither(self.prepare)
        self.assertEqual(self.prepare.out, "")
        self.assertEqual(self.prepare.err, "")


class AMac(unittest.TestCase):
    def test_a_mac_prints_from_its_own_machine_probe_with_nothing_passed_to_its_guest(self):
        line = readme_install_line(installer.CHECKOUT / "README.md")
        for kind, power, expected in (("mini", MINI, HOME_LINES),
                                      ("laptop", LAPTOP_POWER, laptop_lines(line))):
            with self.subTest(kind):
                mac = Mac(power=power)
                self.addCleanup(mac.close)
                # Even if the host running this test is a Lima guest, a Mac's own installer prints.
                cidata = mac.home.root / "lima-cidata"
                cidata.mkdir()
                mac.home.env["AK_LIMA_CIDATA"] = str(cidata)
                done = mac.install()
                self.assertTrue(done.out.endswith(expected), done.out)
                self.assertIn("summary: client of lima-ak;", done.out[:-len(expected)])
                self.assertEqual(mac.inside(), [{"args": ["--server"], "tty": False}])

    def test_a_mac_client_prints_neither_first_line(self):
        mac = Mac(power=LAPTOP_POWER)
        self.addCleanup(mac.close)
        done = mac.install("--client", "acme-box")
        for line in FIRST_LINES:
            self.assertNotIn(line, done.out)
            self.assertNotIn(line, done.err)


if __name__ == "__main__":
    unittest.main()
