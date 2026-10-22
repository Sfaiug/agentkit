"""`ak browser status`, `login` and `install`: whether the shared browser is usable, the way in
to sign a site in, and a setup that never runs where it must not.

A seat asks `status` before it reaches for the browser, so its exit code is the answer: 0 when
every part that is installed is up, or when nothing is (a Mac never had the stack), 1 when any
installed part is down, a unit, the shared MCP server or Chromium's DevTools port.  `login`
hands the owner the noVNC address and the password: the stored one, or a new one when only
x11vnc's own file is left, and then it restarts x11vnc and nothing else, since Chromium's
profile is the logins.  `install` in a throwaway HOME refuses before it touches the machine.
The stack is the host's, so each command runs in a box of its own (bubblewrap): a network with
nothing but loopback, where the test's browser answers on DevTools' port, and a directory of
the test's in place of /etc/systemd/system; systemctl and sudo are fakes answering for the
units the test installs.  Black-box: the program `AK_BIN` names runs from outside through
tests/fixtures/akbin.py, and this test fails against `/bin/false`.
"""

import ctypes.util
import json
import shlex
import shutil
import sys
import time
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import AK, LOG, REFUSE, Home

BOX = shutil.which("bwrap")
UNIT_DIR = Path("/etc/systemd/system")
UNITS = tuple(f"browser-bridge-{part}.service"
              for part in ("xvfb", "openbox", "chromium", "x11vnc", "novnc"))
MCP = "browser-bridge-mcp.service"
UP = dict.fromkeys((*UNITS, MCP), "active running")
NOVNC = "http://100.64.0.7:6080/vnc.html?autoconnect=1&resize=remote"
NOVNC_UNIT = ("[Service]\nExecStart=/usr/bin/websockify --web=/usr/share/novnc "
              "100.64.0.7:6080 127.0.0.1:5900\n")
SECRETS = ".agentkit/secrets"
PAGES = [{"id": "T1", "type": "page", "title": "Acme dashboard", "url": "https://acme.test/"},
         {"id": "T2", "type": "page", "title": "Beta docs", "url": "https://beta.test/docs"},
         {"id": "F1", "type": "iframe", "title": "Ad frame", "url": "https://ads.test/"}]
MUTATIONS = {"start", "stop", "restart", "reload", "enable", "disable", "daemon-reload"}

# systemctl as systemd answers it for the units the test put in `UNITS_FILE`, each
# "<active> <sub>"; any other is not found.  A restart of a unit it has is kept in the log.
SYSTEMCTL = """
import json, sys
args = sys.argv[1:]
with open(LOG, "a") as log:
    log.write(json.dumps(args) + "\\n")
units = json.load(open(UNITS_FILE))
verb, *names = [arg for arg in args if not arg.startswith("-")]
state = lambda name: (units.get(name) or "inactive dead").split()
if verb == "show":
    for name in names:
        print(f"Id={name}\\nLoadState={'loaded' if name in units else 'not-found'}\\n"
              f"ActiveState={state(name)[0]}\\nSubState={state(name)[1]}\\n")
elif verb == "is-active":
    print("\\n".join(state(name)[0] for name in names))
    sys.exit(0 if all(state(name)[0] == "active" for name in names) else 3)
elif verb != "restart" or not all(name in units for name in names):
    print(f"systemctl: {verb} not scripted in this test", file=sys.stderr)
    sys.exit(1)
"""
SUDO = '[ "$1" = -n ] && shift\n[ "$1" = systemctl ] && exec "$@"\n' \
       'echo "sudo: not scripted in this test" >&2\nexit 1\n'
# Chromium's DevTools port inside the box, with the tabs given open; then the program runs.
DEVTOOLS = """
import http.server, json, subprocess, sys, threading
pages = json.loads(sys.argv[1])
class DevTools(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"/json/version": {"Browser": "Chrome/140.0.7339.80"},
                           "/json/list": pages}.get(self.path)).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *_args):
        pass
if pages is not None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 9222), DevTools)
    threading.Thread(target=server.serve_forever, daemon=True).start()
sys.exit(subprocess.run(sys.argv[2:]).returncode)
"""


def machine(case):
    """A Home whose systemctl, sudo and desktop tools are the test's, with two unit
    directories to stand for the host's: `bare`, and `stack` holding the noVNC unit."""
    case.home = home = Home()
    case.addClassCleanup(home.close)
    python = shlex.quote(sys.executable)
    case.units_file = home.root / "units.json"
    home.fake("systemctl", f"#!{sys.executable}\nLOG = {str(home.log('systemctl'))!r}\n"
                           f"UNITS_FILE = {str(case.units_file)!r}\n" + SYSTEMCTL)
    home.fake("sudo", LOG.format(python=python, log=shlex.quote(str(home.log("sudo")))) + SUDO)
    for name in ("xdotool", "import", "apt-get", "npm", "dpkg-query"):
        home.fake(name, REFUSE.format(python=python, name=name,
                                      log=shlex.quote(str(home.log(name)))))
    case.bare, case.stack = home.root / "bare", home.root / "stack"
    case.bare.mkdir()
    case.stack.mkdir()
    (case.stack / "browser-bridge-novnc.service").write_text(NOVNC_UNIT)


def boxed(case, *args, units=None, installed=(), pages=None, env=None):
    """`ak browser ARGS` in its box: `units` stands for /etc/systemd/system, `installed` maps
    each unit systemd has to its state, and `pages` are the tabs of a browser that is up."""
    case.units_file.write_text(json.dumps(dict(installed)))
    return case.home.run(BOX, "--dev-bind", "/", "/", "--unshare-user", "--unshare-net",
                         "--die-with-parent", "--bind", str(units or case.stack), str(UNIT_DIR),
                         sys.executable, "-c", DEVTOOLS, json.dumps(pages), AK, "browser",
                         *args, env=env)


def said(out):
    """status's lines by the word each starts with, and its indented rows."""
    lines = out.splitlines()
    return ({line.split()[0]: line.split(None, 1)[1] for line in lines if line[:1].strip()},
            [line.strip() for line in lines if line.startswith("  ")])


def restarted(home):
    """Each unit systemctl was told to restart, oldest first."""
    words = [[arg for arg in call if not arg.startswith("-")] for call in home.calls("systemctl")]
    return [name for verb, *names in filter(None, words) if verb == "restart" for name in names]


@unittest.skipUnless(BOX and UNIT_DIR.is_dir(), "no bubblewrap to hold the host's stack away")
class Status(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        machine(cls)

    def test_with_nothing_installed_it_says_how_to_install_and_is_no_failure(self):
        done = boxed(self, "status", units=self.bare)
        self.assertEqual(done.code, 0, done.out + done.err)
        lines, rows = said(done.out)
        self.assertEqual([row.split() for row in rows], [[unit, "absent"] for unit in UNITS])
        self.assertIn("`ak browser install`", lines["units"])
        self.assertRegex(lines["mcp"], r"^http://localhost:8931/mcp not active")
        self.assertRegex(lines["cdp"], r"^http://127\.0\.0\.1:9222 unreachable")
        self.assertNotIn("http", lines["novnc"])

    def test_a_running_stack_names_its_browser_each_open_tab_and_the_novnc_address(self):
        now = time.time()
        self.home.write(".agentkit/state/browser-tabs.json", {"T1": {
            "first_seen": now - 9000, "last_change": now - 7300, "url": PAGES[0]["url"],
            "title": PAGES[0]["title"]}})
        done = boxed(self, "status", installed=UP, pages=PAGES)
        self.assertEqual(done.code, 0, done.out + done.err)
        lines, rows = said(done.out)
        self.assertEqual([row.split() for row in rows[:5]],
                         [[unit, "active", "(running)"] for unit in UNITS])
        self.assertRegex(lines["mcp"], r"^http://localhost:8931/mcp active")
        self.assertEqual(lines["cdp"], "http://127.0.0.1:9222 reachable, Chrome/140.0.7339.80")
        self.assertRegex(lines["tabs"], r"^2 open \(cap 12; a tab idle 60 min is closed")
        self.assertEqual([row.split() for row in rows[5:]],
                         [["Acme", "dashboard", "https://acme.test/", "idle", "2h"],
                          ["Beta", "docs", "https://beta.test/docs", "idle", "0m"]])
        self.assertIn("DISPLAY=:99", lines["desktop"])
        self.assertNotIn("missing", lines["desktop"])
        self.assertEqual(lines["novnc"], NOVNC)

    def test_any_installed_part_that_is_down_exits_1(self):
        cases = {"a unit stopped": ({**UP, UNITS[2]: "inactive dead"}, PAGES),
                 "the MCP server stopped": ({**UP, MCP: "inactive dead"}, PAGES),
                 "Chromium's port unreachable": (UP, None)}
        out = {}
        for case, (installed, pages) in cases.items():
            with self.subTest(case):
                done = boxed(self, "status", installed=installed, pages=pages)
                self.assertEqual(done.code, 1, done.out + done.err)
                out[case] = done.out
        self.assertIn([UNITS[2], "inactive", "(dead)"],
                      [row.split() for row in said(out["a unit stopped"])[1]])

    def test_a_machine_without_systemd_reads_as_a_mac_and_is_no_failure(self):
        bare = self.home.root / "no-systemd"
        bare.mkdir()
        (bare / "python3").symlink_to(sys.executable)
        done = boxed(self, "status", units=self.bare, env={"PATH": str(bare)})
        self.assertEqual(done.code, 0, done.out + done.err)
        lines, rows = said(done.out)
        self.assertEqual(rows, [])
        for word in ("units", "mcp"):
            self.assertIn("no systemd on this machine", lines[word])
        self.assertIn("unreachable", lines["cdp"])
        self.assertIn("missing xdotool", lines["desktop"])


@unittest.skipUnless(BOX and UNIT_DIR.is_dir(), "no bubblewrap to hold the host's stack away")
class Login(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        machine(cls)

    def setUp(self):
        shutil.rmtree(self.home.path / SECRETS, ignore_errors=True)
        for name in ("systemctl", "sudo"):
            self.home.log(name).unlink(missing_ok=True)

    def logged_in(self, **kwargs):
        done = boxed(self, "login", **kwargs)
        self.assertEqual(done.code, 0, done.out + done.err)
        return dict(line.split(None, 1) for line in done.out.splitlines()
                    if line.split(None, 1)[0] in ("open", "password"))

    def test_the_stored_password_is_shown_with_the_address_and_nothing_restarts(self):
        for name in ("browser-bridge-vnc.txt", "browser-bridge-vnc"):
            with self.subTest(name):
                shutil.rmtree(self.home.path / SECRETS, ignore_errors=True)
                stored = self.home.write(f"{SECRETS}/{name}", "Kq7mW2xRt9Lp4ZaB\n")
                self.assertEqual(self.logged_in(installed=UP),
                                 {"open": NOVNC, "password": "Kq7mW2xRt9Lp4ZaB"})
                self.assertEqual(stored.read_text(), "Kq7mW2xRt9Lp4ZaB\n")
        self.assertEqual((restarted(self.home), self.home.calls("sudo")), ([], []))

    @unittest.skipUnless(ctypes.util.find_library("vncserver"),
                         "x11vnc's password file is written through libvncserver")
    def test_with_only_x11vnc_s_file_left_a_new_password_is_minted_and_only_x11vnc_restarts(
            self):
        old = self.home.write(f"{SECRETS}/browser-bridge-vnc.rfbauth", "\x01" * 8)
        shown = self.logged_in(installed=UP)
        new = self.home.path / SECRETS / "browser-bridge-vnc.txt"
        self.assertRegex(new.read_text(), r"^[A-Za-z0-9]{16}\n$")
        self.assertEqual(shown, {"open": NOVNC, "password": new.read_text().strip()})
        for path in (new, old):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600, path.name)
        self.assertNotEqual(old.read_bytes(), b"\x01" * 8)
        self.assertEqual(restarted(self.home), ["browser-bridge-x11vnc.service"])

    def test_with_no_novnc_address_it_refuses_and_mints_nothing(self):
        done = boxed(self, "login", units=self.bare)
        self.assertEqual((done.code, done.out), (2, ""), done.err)
        self.assertIn("`ak browser install`", done.err)
        self.assertFalse((self.home.path / SECRETS / "browser-bridge-vnc.txt").exists())


@unittest.skipUnless(BOX and UNIT_DIR.is_dir(), "no bubblewrap to hold the host's stack away")
class Install(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        machine(cls)

    def test_in_a_throwaway_home_it_refuses_before_touching_the_machine(self):
        done = boxed(self, "install", units=self.bare)
        self.assertEqual(done.code, 0, done.out + done.err)
        self.assertRegex(done.out, r"^setup +sandbox HOME cannot install system units\n$")
        for tool in ("sudo", "apt-get", "npm", "dpkg-query"):
            self.assertEqual(self.home.calls(tool), [], tool)
        self.assertFalse([call for call in self.home.calls("systemctl")
                          if MUTATIONS & set(call)])
        self.assertFalse((self.home.path / ".local/share/browser-bridge").exists())


if __name__ == "__main__":
    unittest.main()
