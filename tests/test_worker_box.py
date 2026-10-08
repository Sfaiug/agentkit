"""A turn cannot read GitHub credentials or leave even an unmarked, detached child."""

from contextlib import ExitStack
import fcntl
import ipaddress
import json
import os
import re
from pathlib import Path
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from fixtures.sandbox import account_home
from agentkit import box, config, run, worker


ADAPTER = r'''import json, os, signal, subprocess, sys, time
from pathlib import Path
if sys.argv[1] == "auth":
    print("fixture login")
    sys.exit(0)
root = Path(os.environ["BOX_FIXTURE"])
out = Path(sys.argv[6])
if os.environ.get("BOX_TERM"):
    def term(*_):
        (out / "session_id").write_text("fixture-session")
        if os.environ["BOX_TERM"] == "exit":
            sys.exit(0)
    signal.signal(signal.SIGTERM, term)
def read(path):
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""
seen = {"hosts": read(Path.home() / ".config/gh/hosts.yml"),
        "token": os.environ.get("GH_TOKEN"),
        "store": read(Path.home() / ".git-credentials")}
if os.environ.get("BOX_PATHS"):
    seen["paths"] = [read(Path(path)) for path in json.loads(os.environ["BOX_PATHS"])]
    seen["tokens"] = [os.environ.get(key) for key in (
        "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")]
    seen["pid1_token"] = b"GH_TOKEN=" in Path("/proc/1/environ").read_bytes()
if os.environ.get("BOX_AGENT"):
    import socket
    agent = socket.socket(socket.AF_UNIX)
    try:
        agent.connect(os.environ["BOX_AGENT"])
        seen["agent"] = True
    except OSError:
        seen["agent"] = False
    seen["agent_address"] = os.environ.get("SSH_AUTH_SOCK")
if os.environ.get("BOX_INSPECT"):
    (Path.home() / ".codex").mkdir(exist_ok=True)
    (Path.home() / ".codex/fixture").write_text("harness write")
    seen["home"] = str(Path.home())
    seen["cwd"] = os.getcwd()
    seen["uid"] = os.getuid()
    seen["provider"] = os.environ["FIXTURE_PROVIDER_TOKEN"]
if os.environ.get("BOX_NEST") == "1":
    os.environ["BOX_NEST"] = "0"
    sys.path.insert(0, os.environ["BOX_REPO"])
    from agentkit import config, worker
    config.adapter = lambda _harness: Path(sys.argv[0])
    cfg = json.loads((root / "cfg.json").read_text())
    logs = []
    code, text, _, killed, left = worker.turn(
        cfg, "w", "nested task", root, root / "nested", limit=10, log=logs.append)
    seen["nested"] = {"code": code, "seen": json.loads(text), "killed": killed,
                      "left": left, "logs": logs}
if os.environ.get("BOX_LEAK", "1") == "1":
    subprocess.Popen([sys.executable, str(root / "detached.py"), str(out)],
                     env={}, start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 5
    while not (out / "ready").exists():
        if time.monotonic() > deadline:
            raise RuntimeError("fixture child never started")
        time.sleep(.01)
(out / "final.md").write_text(json.dumps(seen))
(out / "events.jsonl").write_text("{}\n")
if os.environ.get("BOX_SIGNAL"):
    os.kill(os.getpid(), int(os.environ["BOX_SIGNAL"]))
if os.environ.get("BOX_HANG"):
    time.sleep(300)
sys.exit(int(os.environ.get("BOX_EXIT", "0")))
'''

DETACHED = r'''import fcntl, os, sys, time
from pathlib import Path
out = Path(sys.argv[1])
with (out / "alive.lock").open("w") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    (out / "ready").write_text("ready")
    deadline = time.monotonic() + 30
    while not (out / "stop").exists() and time.monotonic() < deadline:
        time.sleep(.01)
'''


SOCKETS = r'''import json, os, socket, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.environ["BOX_REPO"])
from agentkit import box
sys.path.insert(0, str(Path(os.environ["BOX_REPO"]) / "tests"))
from fixtures.sandbox import account_home
import atexit
if sys.argv[1] == "host":
    homes = account_home(os.environ["HOME"])
    homes.__enter__()
    atexit.register(homes.__exit__, None, None, None)
work, role, places = Path(os.environ["BOX_WORK"]), sys.argv[1], [Path(path) for path in sys.argv[2:]]


def listen(path):
    # A service's socket, with a file beside it. AF_UNIX names are short; the checkout's may not be.
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / "file").write_text("")
    os.chdir(path.parent)
    server = socket.socket(socket.AF_UNIX)
    server.bind(path.name)
    server.listen(8)
    return server


def reach(path):
    try:
        os.chdir(path.parent)
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(path.name)
        return True
    except OSError:
        return False


def boxed(role, home_overlay):
    out = Path(tempfile.mkdtemp(dir=work))
    argv = [sys.executable, __file__, role, *map(str, places)]
    with box.command(argv, dict(os.environ), out, cwd=work, home_overlay=home_overlay,
                     state=("/tmp/state", "/var/tmp/state")) as (cmd, env, spawn):
        spawn.pop("stop")
        result = subprocess.run(cmd, env=env, cwd=work, capture_output=True, text=True,
                                timeout=60, **spawn)
    return json.loads(result.stdout) if result.returncode == 0 else result.stderr


if role == "probe":
    seen = {str(path): [reach(path), (path.parent / "file").exists()] for path in places}
    own = Path(tempfile.mkdtemp(dir="/tmp"), "s")
    with listen(own):
        seen["own"] = reach(own)
    seen["state"] = []
    for place in map(Path, ("/tmp/state", "/var/tmp/state")):
        seen["state"].append((place / "kept").read_text())
        (place / "write").write_text("own")
    print(json.dumps(seen))
elif role == "host":
    work.mkdir(parents=True)
    if os.environ.get("BOX_RUNTIME_LINK"):
        Path(os.environ["BOX_RUNTIME_LINK"]).mkdir()
        Path(os.environ["XDG_RUNTIME_DIR"]).symlink_to(os.environ["BOX_RUNTIME_LINK"])
    listeners = list(map(listen, places))
    for place in map(Path, ("/tmp/state", "/var/tmp/state")):
        place.mkdir()
        (place / "kept").write_text("kept")
    seen = {}
    for name, home_overlay in (("worker", False), ("check", True)):
        seen[name] = boxed("probe", home_overlay)
        seen[f"{name} inside a box"] = boxed(name, home_overlay)
    seen["unboxed"] = json.loads(subprocess.run([sys.executable, __file__, "probe", *sys.argv[2:]],
                                                capture_output=True, text=True).stdout or "null")
    print(json.dumps(seen))
else:
    # What a parent box keeps in its own /tmp is the parent's alone.
    places.append(Path("/tmp/parent/s"))
    with listen(places[-1]):
        print(json.dumps(boxed("probe", role == "check")))
'''

NETWORK = r"""import json, os, shutil, socket, struct, subprocess, sys, tempfile, threading
from contextlib import ExitStack
from pathlib import Path
root, role = Path(sys.argv[1]), sys.argv[2]
if role == "mount":
    subprocess.run(["mount", "--make-rprivate", "/"], check=True)
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    if sys.argv[4] == "online":
        subprocess.run(["ip", "link", "add", "internet", "type", "dummy"], check=True)
        # The host's own address is the last of its network in one case, and past its
        # preferred life in another.
        subprocess.run(["ip", "addr", "add", {"family254": "192.0.2.254/24", "familyrule": "192.0.2.1/32"}.get(
                            sys.argv[3], "192.0.2.1/24"), "dev", "internet",
                        *(("preferred_lft", "0") if sys.argv[3] == "familypast4" else ())], check=True)
        subprocess.run(["ip", "link", "set", "internet", "up"], check=True)
        # One case has no IPv4 way out, only the network next to it; another has its only
        # way out in a routing table of its own that a rule chooses, and IPv4 alone.
        if sys.argv[3] == "familyrule":
            subprocess.run(["ip", "route", "add", "default", "dev", "internet", "table", "100"], check=True)
            subprocess.run(["ip", "rule", "add", "lookup", "100", "priority", "100"], check=True)
        elif sys.argv[3] != "familyno4":
            subprocess.run(["ip", "route", "add", "default", "dev", "internet"], check=True)
        # The host's own address toward the internet is a box's own there, so what the
        # stand-in internet serves is at an address on a second network.
        for command in (("link", "add", "beyond", "type", "dummy"),
                        ("addr", "add", "198.51.100.1/32" if sys.argv[3] == "familyrule" else
                         "198.51.100.1/24", "dev", "beyond"),
                        ("link", "set", "beyond", "up")):
            subprocess.run(["ip", *command], check=True)
        if Path("/proc/sys/net/ipv6").exists() and sys.argv[3] != "familyrule":
            # The stand-in internet has IPv6 as well, with an address of the global kind
            # or, case by case, a private, a 6to4 or a Teredo one, and a network beyond
            # its first one.
            first = {"familyprivate": "fd42::1/64", "familyno4": "fd42::1/64",
                     "family6to4": "2002:c000:201::1/64",
                     "familyteredo": "2001:0:c000:201::1/64"}.get(sys.argv[3], "2001:db8::1/64")
            # One case's only address is past its preferred life, which the kernel knows
            # and libc asks it; another has a gai.conf of its own, which pairs the host's
            # address with one destination of the internet's and with no other.
            past = ("preferred_lft", "0") if sys.argv[3] in ("familydeprecated", "familygaipast") else ()
            if sys.argv[3].startswith("familygai") and Path("/etc/gai.conf").exists():
                # A third pairs the host's IPv4 address with one IPv4 destination alone.
                (root / "gai.conf").write_text(
                    "label ::1/128 0\nlabel ::/0 1\nlabel 2002::/16 2\nlabel ::/96 3\n"
                    "label ::ffff:0:0/96 4\nlabel fec0::/10 5\nlabel fc00::/7 6\n"
                    "label 2001:0::/32 7\nlabel 2001:db8::/64 99\nlabel 2001:db8:77::/48 99\n"
                    + ("label ::ffff:192.0.2.1/128 98\nlabel ::ffff:203.0.113.7/128 98\n"
                       if sys.argv[3] == "familygai4" else ""))
                subprocess.run(["mount", "--bind", str(root / "gai.conf"), "/etc/gai.conf"], check=True)
            # In one more the address is on a second interface as well, past its life there.
            if sys.argv[3] == "familytwice":
                subprocess.run(["ip", "link", "add", "twice", "type", "dummy"], check=True)
                subprocess.run(["ip", "addr", "add", "2001:db8::1/128", "dev", "twice", "nodad",
                                "preferred_lft", "0"], check=True)
            for command in (("addr", "add", first, "dev", "internet", "nodad", *past),
                            ("-6", "route", "add", "default", "dev", "internet"),
                            *([] if past else [("addr", "add", "fd42:1::1/64", "dev", "beyond", "nodad")])):
                subprocess.run(["ip", *command], check=True)
    Path("/proc/sys/net/ipv4/ip_unprivileged_port_start").write_text("0")
    # The fixture's own resolver, so the host's decides nothing here: one on the stand-in
    # internet, or for the resolver cases one that only this namespace's own network
    # reaches. 127.53 is 127.0.0.53 to libc; an address with a carriage return after it is
    # none to libc, and with no nameserver named it asks 127.0.0.1.
    resolver = root / "resolv.conf"
    address = {"dns": "127.0.0.53", "dns6": "::1", "dnsshort": "127.53", "dnscrlf": "192.0.2.1\r",
               "dnsnone": None}.get(sys.argv[3], "198.51.100.1")
    resolver.write_bytes(((f"nameserver {address}\n" if address else "")
                          + "search acme.test\noptions timeout:1 attempts:1\n").encode())
    subprocess.run(["mount", "--bind", str(resolver), "/etc/resolv.conf"], check=True)
    # The package's AppArmor profile uses an unconfined exec transition, forbidden
    # by an enclosing box's no_new_privs. This private copy tests pasta itself.
    bindir = root / "bin"
    (bindir / "real").mkdir(parents=True)
    pasta = Path(shutil.which("pasta"))
    for binary in (pasta, pasta.with_name("pasta.avx2")):
        if binary.exists():
            shutil.copyfile(binary, bindir / "real" / binary.name)
            (bindir / "real" / binary.name).chmod(0o755)
    # That profile also lets pasta start no program outside /bin and /usr/bin. The copy
    # keeps the rule, and ak runs here under a Python outside both, as from /usr/local/bin
    # or a virtual environment.
    (bindir / "pasta").write_text('''#!/bin/sh
for word in "$@"; do
    case "$word" in
    /bin/*|/usr/bin/*) ;;
    /*) if [ -f "$word" ] && [ -x "$word" ]; then
            echo "Failed to start command or shell: Permission denied" >&2
            exit 1
        fi ;;
    esac
done
exec "$(dirname "$0")/real/pasta" "$@"
''')
    (bindir / "pasta").chmod(0o755)
    os.environ["PATH"] = str(bindir) + os.pathsep + os.environ["PATH"]
    (root / "venv").mkdir()
    (root / "venv/python3").symlink_to(sys.executable)
    os.execvp("setpriv", ["setpriv", "--inh-caps=-all", "--ambient-caps=-all",
                         str(root / "venv/python3"), __file__, str(root), "host", *sys.argv[3:]])
sys.path.insert(0, os.environ["BOX_REPO"])
from agentkit import box
sys.path.insert(0, str(Path(os.environ["BOX_REPO"]) / "tests"))
from fixtures.sandbox import account_home


from test_worker_box import beside
if role == "host" and sys.argv[3].startswith("stop-"):
    from test_worker_box import stop_box
    with socket.socket() as internet:
        if sys.argv[4] == "online":
            internet.bind(("192.0.2.1", 12345))
            internet.listen()
        stop_box(root, already_gone=sys.argv[3] == "stop-gone", online=sys.argv[4] == "online")
    print(json.dumps("ok"))
    sys.exit(0)


# Loopback answers and there is no way out, whatever idle devices the kernel puts in a
# new network.
LOOPBACK_ONLY = '''import json, socket
def way(family, address):
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as asked:
            asked.connect((address, 9))
        return True
    except OSError:
        return False
print(json.dumps([way(socket.AF_INET, "127.0.0.1"), way(socket.AF_INET, "203.0.113.1"), way(socket.AF_INET6, "2001:db8:9::1")]))
'''


def boxed(source, overlay=False):
    out = Path(tempfile.mkdtemp(dir=root))
    with account_home(root), box.command([sys.executable, "-c", source], dict(os.environ),
                                        out, cwd=root, home_overlay=overlay) as (cmd, env, spawn):
        spawn.pop("stop")
        result = subprocess.run(cmd, env=env, cwd=root, capture_output=True, text=True,
                                timeout=30, **spawn)
    assert result.returncode == 0, result.stderr
    # The walls print nothing of their own into what a command prints, and the pasta that
    # ran beside the box is gone with it.
    assert result.stderr == "", result.stderr
    assert not beside(root), beside(root)
    return json.loads(result.stdout)


if role == "offline":
    assert boxed(LOOPBACK_ONLY) == [True, False, False]
    # The shell that brought this role here cannot carry such a name itself.
    os.environ["BASH_FUNC_acme%%"] = "() {  echo kept\n}"
    assert boxed('import json, os; print(json.dumps(os.environ.get("BASH_FUNC_acme%%")))') \
        == "() {  echo kept\n}"
    assert boxed('import json, socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); '
                 's.listen(); c = socket.create_connection(s.getsockname()); '
                 'print(json.dumps(True))') is True
    print(json.dumps("ok"))
    sys.exit(0)


def serve(server, stop, dns=False):
    server.settimeout(.1)
    while not stop.is_set():
        try:
            if dns:
                query, peer = server.recvfrom(4096)
                labels, at = [], 12
                while query[at]:
                    size = query[at]
                    labels.append(query[at + 1:at + 1 + size].decode())
                    at += size + 1
                # Each name has an address in each family: asked for one, that one is given.
                # The second name's IPv6 address is one the case's own address pairs with.
                kind = struct.unpack("!H", query[at + 1:at + 3])[0]
                paired = {"family6to4": "2002:c633:6401::9", "familyteredo": "2001:0:c633:6401::9",
                          "familygai": "2001:db8:77::9", "familygai4": "2001:db8:77::9",
                          "familygaipast": "2001:db8:77::9"}.get(
                              sys.argv[3], "2001:db8:9::9")
                found = ".".join(labels) in ("fixture.acme.test", "paired.acme.test")
                given = {1: socket.inet_aton("203.0.113.7"), 28: socket.inet_pton(
                    socket.AF_INET6, paired if labels[0] == "paired" else "2001:db8:9::9")}.get(kind)
                answer = b"" if given is None or not found else (
                    b"\xc0\x0c" + struct.pack("!HHIH", kind, 1, 60, len(given)) + given)
                server.sendto(query[:2] + struct.pack("!HHHHH", 0x8180 if found else 0x8183,
                                                    1, int(bool(answer)), 0, 0)
                              + query[12:] + answer, peer)
            else:
                client, _ = server.accept()
                with client:
                    client.sendall(b"acme")
        except socket.timeout:
            pass
        except OSError:
            break


probe = r'''import json, os, socket
from pathlib import Path
assert [os.getuid(), os.getgid()] == json.loads(os.environ["IDENTITY"])
Path("written").write_text("own")
def reaches(family, address):
    with socket.socket(family) as client:
        client.settimeout(2)
        try:
            client.connect(address)
            return client.recv(4) == b"acme"
        except OSError:
            return False
seen = [reaches(socket.AF_INET, (host, int(os.environ["PORT"])))
        for host in ("198.51.100.1", "192.0.2.1", "127.0.0.1", "192.0.2.0")]
seen.append(reaches(socket.AF_UNIX, "\0acme"))
seen.append(reaches(socket.AF_INET6, ("::1", int(os.environ["PORT"]))))
for host in filter(None, os.environ["IPV6"].split()):
    seen.append(reaches(socket.AF_INET6, (host, int(os.environ["PORT"]))))
print(json.dumps(seen))
'''
stop, threads = threading.Event(), []
try:
    with ExitStack() as stack:
        if sys.argv[3].startswith("dns"):
            family, address = {"dns6": (socket.AF_INET6, "::1"),
                               "dnscrlf": (socket.AF_INET, "127.0.0.1"),
                               "dnsnone": (socket.AF_INET, "127.0.0.1")}.get(
                                   sys.argv[3], (socket.AF_INET, "127.0.0.53"))
            server = stack.enter_context(socket.socket(family, socket.SOCK_DGRAM))
            server.bind((address, 53))
            thread = threading.Thread(target=serve, args=(server, stop, True))
            thread.start()
            threads.append(thread)
            assert socket.gethostbyname("fixture.acme.test") == "203.0.113.7"
            # The resolver file does not name this host's resolver plainly: the box is in
            # the host's network, as before, and resolves the name as the host does.
            here = os.readlink("/proc/self/ns/net")
            for overlay in (False, True):
                assert boxed('import json, os, socket; print(json.dumps([os.readlink("/proc/self/ns/net"), '
                             'socket.gethostbyname("fixture")]))', overlay) == [here, "203.0.113.7"]
        elif sys.argv[3].startswith("family"):
            if Path("/proc/sys/net/ipv6").exists() and (
                    not sys.argv[3].startswith("familygai") or Path("/etc/gai.conf").exists()):
                server = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
                server.bind(("198.51.100.1", 53))
                thread = threading.Thread(target=serve, args=(server, stop, True))
                thread.start()
                threads.append(thread)
                # Two names with an address in each family, served by a resolver this time.
                # Libc weighs for this host its ways out, the addresses the kernel would
                # send from and gai.conf, and a box in a network of its own lists each
                # name's two in the order the host lists them: its IPv6 address is the
                # host's, so every pairing is. Where libc would still list otherwise, or
                # the host has no way out in a family, the box is given the host's network.
                order = ('import json, os, socket; print(json.dumps([os.readlink("/proc/self/ns/net"), '
                         '*([found[0] for found in socket.getaddrinfo(name + ".acme.test", 80, '
                         'type=socket.SOCK_STREAM)] for name in ("fixture", "paired"))]))')
                net, here, paired = json.loads(subprocess.check_output(
                    [sys.executable, "-c", order], text=True, timeout=30))
                first = socket.AF_INET6 if sys.argv[3] in (
                    "family", "familyno4", "family254", "familypast4", "familytwice") else socket.AF_INET
                # With no IPv6 at all libc still lists the name's IPv6 address, last.
                assert here[0] == first and sorted(here) == [socket.AF_INET, socket.AF_INET6], here
                if sys.argv[3] in ("family6to4", "familyteredo", "familygai", "familygai4"):
                    assert paired[0] == socket.AF_INET6, paired
                if sys.argv[3] == "familygaipast":
                    # The labels pair this name's addresses, yet the address is past its life.
                    assert paired[0] == socket.AF_INET, paired
                for overlay in (False, True):
                    own, *there = boxed(order, overlay)
                    assert there == [here, paired], (there, here, paired)
                    assert (own == net) == (sys.argv[3] in (
                        "familyno4", "familydeprecated", "familygaipast", "familypast4",
                        "familytwice")), (own, net)
        else:
            # Where this host has IPv6, the stand-in internet answers over it too, at an
            # address on its second network; its own address toward the internet is the
            # box's own there, and nothing of the host's answers at it.
            ipv6 = ["2001:db8::1", "fd42:1::1"] if Path("/proc/sys/net/ipv6").exists() else []
            os.environ["IPV6"] = " ".join(ipv6)
            for family, address in ((socket.AF_INET, ("198.51.100.1", 12345)),
                                    (socket.AF_INET, ("192.0.2.1", None)),
                                    (socket.AF_INET, ("127.0.0.1", None)),
                                    (socket.AF_INET6, ("::1", None)),
                                    (socket.AF_UNIX, "\0acme"),
                                    *((socket.AF_INET6, (host, None)) for host in ipv6)):
                server = stack.enter_context(socket.socket(family))
                if family in (socket.AF_INET, socket.AF_INET6):
                    server.bind((address[0], address[1] if address[1] is not None else port))
                    port = server.getsockname()[1]
                else:
                    server.bind(address)
                server.listen(8)
                thread = threading.Thread(target=serve, args=(server, stop))
                thread.start()
                threads.append(thread)
            os.environ["PORT"] = str(port)
            os.environ["IDENTITY"] = json.dumps([os.getuid(), os.getgid()])
            seen = json.loads(subprocess.check_output([sys.executable, "-c", probe],
                                                     cwd=root, text=True, timeout=10))
            assert seen == [True, True, True, False, True, True, *[True for _ in ipv6]], seen
            for overlay in (False, True):
                seen = boxed(probe, overlay)
                # The internet answers; the host's own address there, its loopback, the
                # gateway's address and its abstract sockets do not.
                assert seen == [True, False, False, False, False, False,
                                *([False, True] if ipv6 else [])], seen
                assert (root / "written").stat().st_uid == os.getuid()
                assert (root / "written").stat().st_gid == os.getgid()
            # The command's variables arrive whole, one a shell cannot name among them.
            os.environ["BASH_FUNC_acme%%"] = "() {  echo kept\n}"
            assert boxed('import json, os; print(json.dumps(os.environ.get("BASH_FUNC_acme%%")))') \
                == "() {  echo kept\n}"
            # A stop reaches the command's own handler, which saves its cleanup first.
            from agentkit import worker
            out = Path(tempfile.mkdtemp(dir=root))
            source = ('import signal, sys, time; from pathlib import Path; '
                      'signal.signal(signal.SIGTERM, lambda *_: '
                      '(Path("closed").touch(), sys.exit(0))); '
                      'Path("ready").touch(); time.sleep(300)')
            with account_home(root), box.command([sys.executable, "-c", source], dict(os.environ),
                                                out, cwd=root) as (cmd, env, spawn):
                _, _, killed = worker.limited(cmd, None, env=env, cwd=root,
                                               abort=lambda: (root / "ready").exists(), **spawn)
            assert killed and (root / "closed").exists()
            assert box.leftovers(out) == []
            result = subprocess.run(
                ["unshare", "--user", "--map-current-user", "--net", "--keep-caps",
                 "sh", "-c", 'ip link set lo up && exec setpriv --inh-caps=-all --ambient-caps=-all "$@"',
                 "-", sys.executable, __file__, str(root), "offline"],
                capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
            assert json.loads(result.stdout) == "ok"
            unavailable = root / "unavailable"
            unavailable.mkdir()
            # A pasta that fails has already made a process for its command, and leaves it,
            # with nothing said or with part of the holder's line: the box starts with
            # loopback only, at once, and that process is ended.
            os.environ["PATH"] = str(unavailable) + os.pathsep + os.environ["PATH"]
            for said in ("", "printf rea\n"):
                (unavailable / "pasta").write_text(
                    f'#!/bin/sh\n{said}sleep 300 &\necho $! > {unavailable}/left\nexit 1\n')
                (unavailable / "pasta").chmod(0o755)
                assert boxed(LOOPBACK_ONLY) == [True, False, False]
                left = Path("/proc", (unavailable / "left").read_text().strip(), "stat")
                assert not left.exists() or left.read_text().rsplit(")", 1)[1].split()[0] == "Z"
        stop.set()
        for thread in threads:
            thread.join()
finally:
    stop.set()
    for thread in threads:
        thread.join()
print(json.dumps("ok"))
"""


SHM = r'''import json, os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.environ["BOX_REPO"])
from agentkit import box
sys.path.insert(0, str(Path(os.environ["BOX_REPO"]) / "tests"))
from fixtures.sandbox import account_home
import atexit
if True:
    homes = account_home(os.environ["HOME"])
    homes.__enter__()
    atexit.register(homes.__exit__, None, None, None)
root = Path(sys.argv[1])
write = "from pathlib import Path; p = Path('/dev/shm/acme'); p.write_text('own'); print(p.read_text())"
seen = {}
for home_overlay in (False, True):
    out = Path(tempfile.mkdtemp(dir=root))
    with box.command([sys.executable, "-c", write], dict(os.environ), out, cwd=root,
                     home_overlay=home_overlay) as (cmd, env, spawn):
        spawn.pop("stop")
        result = subprocess.run(cmd, env=env, cwd=root, capture_output=True, text=True,
                                timeout=60, **spawn)
    seen["check" if home_overlay else "worker"] = result.stdout.strip() or result.stderr
seen["host"] = os.path.exists("/run/shm/acme")
print(json.dumps(seen))
'''


RUN_LINKS = r'''import os, shutil, socket, stat, subprocess, sys, tempfile
from pathlib import Path
root = Path(sys.argv[2])
if sys.argv[1] == "mount":
    # Only this namespace sees the stand-in /run and /etc; no host file is changed.
    etc = root / "etc"
    etc.mkdir()
    for name in ("passwd", "group", "nsswitch.conf", "hosts"):
        shutil.copyfile(Path("/etc", name), etc / name)
    (etc / "resolv.conf").symlink_to("/run/acme/first")
    subprocess.run(["mount", "--make-rprivate", "/"], check=True)
    subprocess.run(["mount", "-t", "tmpfs", "tmpfs", "/run"], check=True)
    resolver = Path("/run/acme/real")
    resolver.mkdir(parents=True)
    subprocess.run(["mount", "-t", "tmpfs", "tmpfs", str(resolver)], check=True)
    subprocess.run(["mount", "--bind", str(etc), "/etc"], check=True)
    device = Path("/run/device")
    device.touch()
    subprocess.run(["mount", "--bind", "/dev/null", str(device)], check=True)
    namespace = Path("/run/netns/acme")
    namespace.parent.mkdir()
    namespace.touch()
    subprocess.run(["mount", "--bind", "/proc/self/ns/uts", str(namespace)], check=True)
    os.execvp("setpriv", ["setpriv", "--inh-caps=-all", "--ambient-caps=-all",
                         sys.executable, __file__, "host", str(root)])
sys.path.insert(0, os.environ["BOX_REPO"])
from agentkit import box
sys.path.insert(0, str(Path(os.environ["BOX_REPO"]) / "tests"))
from fixtures.sandbox import account_home
import atexit
if sys.argv[1] == "host":
    homes = account_home(os.environ["HOME"])
    homes.__enter__()
    atexit.register(homes.__exit__, None, None, None)
paths = ["/etc/resolv.conf", "/run/acme/first", "/run/acme/linked/resolver",
         "/run/acme/real/deep/../resolver", "/run/acme/outside/resolver"]
runtime = Path("/run/user", str(os.getuid()))
if sys.argv[1] == "probe":
    assert [Path(path).read_text() for path in paths] == ["nameserver 192.0.2.1\n"] * len(paths)
    for name in ("socket", "late", "fifo"):
        assert not os.path.lexists("/run/acme/" + name), name
    assert not os.path.lexists("/run/device")
    assert not os.path.lexists("/run/netns/acme")
    assert not Path("/run/acme/closed/secret").exists()
    assert not Path("/run/acme/unreadable").exists()
    assert os.readlink("/run/acme/dangling") == "missing"
    assert os.readlink("/run/acme/socket-link") == "socket"
    assert not Path("/run/acme/socket-link").exists()
    assert Path("/run/acme/key").read_text() == ""
    assert not Path("/run/user/other").exists()
    assert os.environ["XDG_RUNTIME_DIR"] == str(runtime)
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
    assert list(runtime.iterdir()) == []
    (runtime / "write").write_text("own")
    if os.environ.get("BOX_EXTERNAL_RUNTIME"):
        assert list(Path("/run/runtime").iterdir()) == []
        Path("/run/runtime/write").write_text("own")
    print("ok")
else:
    run = Path("/run/acme")
    (run / "real/deep").mkdir(parents=True)
    (run / "real/resolver").write_text("nameserver 192.0.2.1\n")
    (run / "first").symlink_to("second")
    (run / "second").symlink_to("linked/deep/../resolver")
    (run / "linked").symlink_to("real")
    (root / "settings").mkdir()
    (root / "settings/resolver").symlink_to("/run/acme/first")
    (run / "outside").symlink_to(root / "settings")
    (run / "dangling").symlink_to("missing")
    (run / "socket-link").symlink_to("socket")
    (run / "key").write_text("fixture-key")
    (root / ".ssh").mkdir()
    (root / ".ssh/id_fixture").symlink_to(run / "key")
    os.mkfifo(run / "fifo")
    (run / "closed").mkdir()
    (run / "closed/secret").write_text("unreadable")
    (run / "closed").chmod(0)
    (run / "unreadable").write_text("unreadable")
    (run / "unreadable").chmod(0)
    (root / "runtime").mkdir()
    (root / "runtime/host").write_text("host")
    Path("/run/runtime").symlink_to(root / "runtime")
    runtime.mkdir(parents=True)
    (runtime / "host").write_text("host")
    Path("/run/user/other").mkdir()
    assert Path("/etc/resolv.conf").read_text() == "nameserver 192.0.2.1\n"
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(run / "socket"))
        server.listen(1)
        for home_overlay in (False, True):
            for host_runtime in ("/run/runtime", str(runtime), str(root / "missing"), None):
                env = dict(os.environ)
                env.pop("XDG_RUNTIME_DIR", None)
                if host_runtime is not None:
                    env["XDG_RUNTIME_DIR"] = host_runtime
                env["BOX_EXTERNAL_RUNTIME"] = "1" if host_runtime == "/run/runtime" else ""
                out = Path(tempfile.mkdtemp(dir=run if host_runtime is None else root))
                argv = [sys.executable, __file__, "probe", str(root)]
                with box.command(argv, env, out, cwd=root,
                                 home_overlay=home_overlay) as (cmd, env, spawn):
                    # Mounts and later writes must not bypass the snapshot or expose services.
                    (run / "real/resolver").write_text("nameserver 192.0.2.2\n")
                    with socket.socket(socket.AF_UNIX) as late:
                        late.bind(str(run / "late"))
                        late.listen(1)
                        spawn.pop("stop")
                        result = subprocess.run(cmd, env=env, cwd=root, capture_output=True,
                                                text=True, timeout=60, **spawn)
                    (run / "late").unlink()
                    (run / "real/resolver").write_text("nameserver 192.0.2.1\n")
                assert result.returncode == 0, (home_overlay, host_runtime, result.stderr)
                assert result.stdout.strip() == "ok", result.stdout
                assert (root / "runtime/host").read_text() == "host"
                assert (runtime / "host").read_text() == "host"
                assert not (root / "missing").exists()
    print("ok")
'''


RUN_CREDENTIALS = r'''import os, subprocess, sys, tempfile
from pathlib import Path
root = Path(sys.argv[2])
if sys.argv[1] == "mount":
    subprocess.run(["mount", "--make-rprivate", "/"], check=True)
    subprocess.run(["mount", "-t", "tmpfs", "tmpfs", "/run"], check=True)
    keys = Path("/run/agenix/keys")
    keys.mkdir(parents=True)
    for source, alias in ((Path("/run/agenix/id_acme"), Path("/run/mounted-key")),
                          (keys, Path("/run/mounted-keys")),
                          (root / ".ssh/id_local", Path("/run/mounted-local-key")),
                          (root / ".cache/git/credential/key", Path("/run/mounted-cache-key"))):
        if source.is_dir():
            alias.mkdir()
        else:
            source.parent.mkdir(parents=True, exist_ok=True)
            source.touch()
            alias.touch()
        subprocess.run(["mount", "--bind", str(source), str(alias)], check=True)
    os.execvp("setpriv", ["setpriv", "--inh-caps=-all", "--ambient-caps=-all",
                         sys.executable, __file__, "host", str(root)])
sys.path.insert(0, os.environ["BOX_REPO"])
from agentkit import box
sys.path.insert(0, str(Path(os.environ["BOX_REPO"]) / "tests"))
from fixtures.sandbox import account_home
import atexit
if sys.argv[1] == "host":
    homes = account_home(os.environ["HOME"])
    homes.__enter__()
    atexit.register(homes.__exit__, None, None, None)
secrets = ("fixture-key", "fixture-folder-key", "fixture-git-store", "fixture-gh-login",
           "fixture-local-key", "fixture-cache-key")

def check_backing(out):
    for scratch in Path(out).glob(".box-*"):
        for path in scratch.rglob("*"):
            if not path.is_symlink() and path.is_file():
                assert path.read_text() not in secrets, ("credential copied to disk", str(path))

if sys.argv[1] == "probe":
    assert Path("/run/agenix/id_acme").read_text() == ""
    assert list(Path("/run/agenix/keys").iterdir()) == []
    assert Path("/run/agenix/git-store").read_text() == ""
    assert Path("/run/agenix/hosts.yml").read_text() == ""
    assert Path("/run/agenix/ordinary").read_text() == "public"
    assert Path("/run/public-hardlink").read_text() == "public"
    for alias in ("mounted-key", "mounted-keys", "mounted-local-key", "mounted-cache-key",
                  "hardlinked-key", "hardlinked-folder-key"):
        assert not os.path.lexists("/run/" + alias), alias
    check_backing(sys.argv[3])
    print("ok")
else:
    run = Path("/run/agenix")
    (run / "keys").mkdir(parents=True, exist_ok=True)
    for name, value in zip(("id_acme", "keys/id_other", "git-store", "hosts.yml"), secrets):
        (run / name).write_text(value)
    (run / "ordinary").write_text("public")
    (root / ".ssh/id_local").write_text(secrets[-2])
    (root / ".cache/git/credential/key").write_text(secrets[-1])
    (root / ".ssh/id_acme").symlink_to(run / "id_acme")
    (root / ".ssh/keys").symlink_to(run / "keys")
    Path("/run/hardlinked-key").hardlink_to(run / "id_acme")
    Path("/run/hardlinked-folder-key").hardlink_to(run / "keys/id_other")
    Path("/run/public-hardlink").hardlink_to(run / "ordinary")
    for login, target in ((root / ".git-credentials", run / "git-store"),
                          (root / ".config/gh/hosts.yml", run / "hosts.yml")):
        login.unlink()
        login.symlink_to(target)
    for home_overlay in (False, True):
        a, b = (Path(tempfile.mkdtemp(dir=root)) for _ in "ab")
        with box.command(["true"], dict(os.environ), a, cwd=root, home_overlay=home_overlay):
            argv = [sys.executable, __file__, "probe", str(root), str(a)]
            with box.command(argv, dict(os.environ), b, cwd=root,
                             home_overlay=home_overlay) as (cmd, env, spawn):
                spawn.pop("stop")
                result = subprocess.run(cmd, env=env, cwd=root, capture_output=True,
                                        text=True, timeout=60, **spawn)
            assert (result.returncode, result.stdout.strip()) == (0, "ok"), result.stderr
            check_backing(a)
    print("ok")
'''


def beside(root):
    """The pasta a network fixture copied into `root`, wherever it still runs."""
    found = []
    for entry in Path("/proc").iterdir():
        try:
            if entry.name.isdigit() and str(root / "bin").encode() in (entry / "cmdline").read_bytes():
                found.append(entry.name)
        except OSError:
            pass
    return found


def stop_box(root, *, already_gone, online):
    # Stdin holds bwrap mid-build and its status on stderr says it has named the box's
    # first process, the same with pasta beside the box as without: bwrap is the launcher
    # either way. Last, no stop at all: the context ends its own box as it closes.
    moments = ("named",) if already_gone else ("early", "named")
    up = "import time; print('up', flush=True); time.sleep(600)"
    for moment in moments if already_gone else (*moments, "unstopped"):
        out = Path(tempfile.mkdtemp(dir=root))
        proc = None
        try:
            with account_home(root), box.command([sys.executable, "-c", up], dict(os.environ), out,
                                                cwd=root, drain=True) as (cmd, env, spawn):
                stop = spawn.pop("stop")
                assert ("--unshare-net" not in cmd) == online, cmd
                if moment == "named":
                    at = cmd.index("--info-fd")
                    cmd[at:at] = ["--block-fd", "0", "--json-status-fd", "2"]
                proc = subprocess.Popen(cmd, env=env, cwd=root, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        start_new_session=True, **spawn)
                said = {"named": (proc.stderr, b'"child-pid"'), "unstopped": (proc.stdout, b"up")}
                if moment in said:
                    pipe, word = said[moment]
                    seen, deadline = b"", time.monotonic() + 30
                    while word not in seen:
                        assert select.select([pipe], [], [], max(
                            0, deadline - time.monotonic()))[0], f"the box never got to {moment}"
                        chunk = os.read(pipe.fileno(), 4096)
                        assert chunk, seen
                        seen += chunk
                if already_gone:
                    proc.kill()
                    proc.wait()
                if moment != "unstopped":
                    stop(proc, 0)
            # Whatever still ran would hold these open; the pasta beside the box is gone too.
            proc.communicate(timeout=30)
            assert not beside(root), beside(root)
        finally:
            # What a failing proof leaves ends with this fixture's PID namespace.
            if proc is not None:
                proc.kill()
                proc.wait(timeout=30)
                for pipe in (proc.stdin, proc.stdout, proc.stderr):
                    pipe.close()


class WorkerBox(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-worker-box-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.out = self.root / "out"
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(account_home(self.root))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "BOX_FIXTURE": str(self.root), "GH_TOKEN": "fixture-token",
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0"}))
        for key in ("AGENTKIT_RUN", "AK_PARENT_RUN", "AK_RUN_LOG", "GH_CONFIG_DIR",
                    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "BOX_LEAK", "BOX_NEST", "BOX_HANG",
                    "BOX_EXIT", "BOX_INSPECT", "BOX_PATHS", "BOX_SIGNAL", "BOX_TERM", "BOX_AGENT",
                    "SSH_AUTH_SOCK"):
            os.environ.pop(key, None)
        self.stack.enter_context(patch.object(config, "RUNS", self.root / "runs"))
        # The only real child is our fixture. No marker sweep may inspect the hosting run.
        self.stack.enter_context(patch.object(worker, "marked_pids", return_value=[]))
        gh = self.root / ".config/gh"
        gh.mkdir(parents=True)
        (gh / "hosts.yml").write_text("fixture-login")
        (self.root / ".git-credentials").write_text("fixture-store")
        adapter = self.root / "adapter.py"
        adapter.write_text(f"#!{sys.executable}\n{ADAPTER}")
        adapter.chmod(0o755)
        (self.root / "detached.py").write_text(DETACHED)
        self.stack.enter_context(patch.object(config, "adapter", return_value=adapter))
        self.cfg = {"models": {"w": {"harness": "fixture", "model": "fixture", "effort": "low",
                                    "provider": "fixture"}}, "providers": {"fixture": {}}}
        (self.root / "cfg.json").write_text(json.dumps(self.cfg))
        self.logs = []
        self.addCleanup(self.stop_child)

    def alive(self, out=None):
        with ((out or self.out) / "alive.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False

    def stop_child(self):
        for lock in self.root.rglob("alive.lock"):
            out = lock.parent
            (out / "stop").touch()
            deadline = time.monotonic() + 5
            while self.alive(out) and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertFalse(self.alive(out), "fixture child did not stop")

    def turn(self, limit=10):
        return worker.turn(self.cfg, "w", "fixture task", self.root, self.out,
                           limit=limit, log=self.logs.append)

    def test_credentials_and_unmarked_detached_child(self):
        code, text, _, killed, left = self.turn()
        self.assertEqual((code, killed), (0, False))
        self.assertEqual({**json.loads(text), "alive": self.alive(), "left": left,
                          "reported": any("detached.py" in line for line in self.logs)},
                         {"hosts": "", "token": None, "store": "", "alive": False,
                          "left": True, "reported": True})
        self.assertEqual((self.root / ".config/gh/hosts.yml").read_text(), "fixture-login")
        self.assertEqual((self.root / ".git-credentials").read_text(), "fixture-store")

    def test_paths_symlinks_and_all_token_variables(self):
        login, store = self.root / "login", self.root / "store"
        login.write_text("fixture-login")
        store.write_text("fixture-store")
        hosts = self.root / ".config/gh/hosts.yml"
        hosts.unlink()
        hosts.symlink_to(login)
        default = self.root / ".git-credentials"
        default.unlink()
        default.symlink_to(store)
        xdg, gh = self.root / "xdg", self.root / "gh"
        literal = self.root / "literal-$HOME"
        for path in (xdg / "gh/hosts.yml", xdg / "git/credentials", gh / "hosts.yml",
                     self.root / "named-store", self.root / "env-store", literal):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture-secret")
        (self.root / ".gitconfig").write_text(
            '[credential]\n\thelper = store --file "~/named-store"\n'
            '\thelper = store --file "$HOME/env-store"\n'
            f"\thelper = store --file '{literal}'\n")
        paths = [login, store, xdg / "gh/hosts.yml", xdg / "git/credentials", gh / "hosts.yml",
                 self.root / "named-store", self.root / "env-store", literal,
                 Path("/proc/1/root") / str(hosts).lstrip("/")]
        with patch.dict(os.environ, {
                "XDG_CONFIG_HOME": str(xdg), "GH_CONFIG_DIR": str(gh),
                "BOX_PATHS": json.dumps([str(path) for path in paths]),
                "GITHUB_TOKEN": "fixture-github", "GH_ENTERPRISE_TOKEN": "fixture-enterprise",
                "GITHUB_ENTERPRISE_TOKEN": "fixture-github-enterprise"}):
            code, text, _, killed, _ = self.turn()
        self.assertEqual((code, killed), (0, False))
        seen = json.loads(text)
        self.assertEqual(seen["paths"], [""] * len(paths))
        self.assertEqual(seen["tokens"], [None] * 4)
        self.assertFalse(seen["pid1_token"])
        self.assertEqual(login.read_text(), "fixture-login")
        self.assertEqual(store.read_text(), "fixture-store")

    def test_ssh_keys_and_agent_are_out_of_reach(self):
        key = self.root / ".ssh/id_fixture"
        key.parent.mkdir()
        key.write_text("fixture-key")
        # AF_UNIX paths are short; the checkout path may not be.
        short = tempfile.TemporaryDirectory(prefix="ak-agent-")
        self.addCleanup(short.cleanup)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        sock = Path(short.name) / "agent"
        listener.bind(str(sock))
        listener.listen(1)
        with patch.dict(os.environ, {"SSH_AUTH_SOCK": str(sock), "BOX_AGENT": str(sock),
                                     "BOX_PATHS": json.dumps([str(key)])}):
            code, text, _, killed, _ = self.turn()
        self.assertEqual((code, killed), (0, False))
        seen = json.loads(text)
        self.assertEqual((seen["paths"], seen["agent"], seen["agent_address"]), ([""], False, None))
        self.assertEqual(key.read_text(), "fixture-key")

    def test_a_relative_agent_address_never_reaches_the_turn(self):
        # A relative address is the caller's: it names this socket in the caller's directory.
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        name = f".ak-test-agent-{os.getpid()}"
        listener.bind(name)
        self.addCleanup(os.unlink, name)
        listener.listen(1)
        with patch.dict(os.environ, {"SSH_AUTH_SOCK": name, "BOX_AGENT": name}):
            code, text, _, killed, _ = self.turn()
        self.assertEqual((code, killed), (0, False))
        seen = json.loads(text)
        self.assertEqual((seen["agent"], seen["agent_address"]), (False, None))

    def test_an_agent_socket_inside_a_hidden_directory_still_starts(self):
        for place in (".ssh/agent", ".git-credential-cache/agent", ".cache/git/credential/agent"):
            with self.subTest(place=place):
                sock = self.root / place
                sock.parent.mkdir(parents=True, exist_ok=True)
                sock.write_text("")
                with patch.dict(os.environ, {"SSH_AUTH_SOCK": str(sock)}):
                    code, _, _, killed, _ = self.turn()
                self.assertEqual((code, killed), (0, False), self.logs)
                self.stop_child()

    def test_unusable_ssh_paths_still_start(self):
        ssh = self.root / ".ssh"
        cases = {"a link to itself": lambda: (ssh.mkdir(), (ssh / "self").symlink_to("self")),
                 "two links to each other": lambda: (
                     ssh.mkdir(), (ssh / "a").symlink_to("b"), (ssh / "b").symlink_to("a")),
                 "a looping .ssh": lambda: ssh.symlink_to(".ssh"),
                 "a file named .ssh": lambda: ssh.write_text("fixture")}
        for name, make in cases.items():
            with self.subTest(case=name):
                make()
                code, _, _, killed, _ = self.turn()
                self.assertEqual((code, killed), (0, False), self.logs)
                self.stop_child()
                if ssh.is_symlink() or ssh.is_file():
                    ssh.unlink()
                else:
                    shutil.rmtree(ssh)

    def test_keys_linked_into_ssh_stay_out_of_reach(self):
        vault, keys = self.root / "vault", self.root / "keydir"
        vault.mkdir()
        keys.mkdir()
        (vault / "id_linked").write_text("fixture-key")
        (keys / "id_dir").write_text("fixture-key")
        # Links inside a linked directory, and a loop that must not trap the walk.
        outside = self.root / "outside"
        (outside / "keydir").mkdir(parents=True)
        (outside / "id_file").write_text("fixture-key")
        (outside / "keydir/id_dir").write_text("fixture-key")
        (keys / "id_file").symlink_to(outside / "id_file")
        (keys / "keydir").symlink_to(outside / "keydir")
        (keys / "loop").symlink_to(keys)
        ssh = self.root / ".ssh"
        ssh.mkdir()
        (ssh / "id_linked").symlink_to("../vault/id_linked")
        (ssh / "keys").symlink_to(keys)
        paths = [vault / "id_linked", keys / "id_dir", outside / "id_file", outside / "keydir/id_dir"]
        with patch.dict(os.environ, {"BOX_PATHS": json.dumps([str(path) for path in paths])}):
            code, text, _, killed, _ = self.turn()
        self.assertEqual((code, killed), (0, False))
        self.assertEqual(json.loads(text)["paths"], [""] * len(paths))
        self.assertEqual([path.read_text() for path in paths], ["fixture-key"] * len(paths))

    def network_fixture(self, mode, *, online=True):
        work = self.root / (mode if online else mode + "-offline")
        work.mkdir()
        script = work / "network.py"
        script.write_text(NETWORK)
        result = subprocess.run(
            # A PID namespace of the fixture's own: whatever a failing proof leaves running
            # ends with it, also when this launcher is ended for its time limit, and no
            # number of another process's is ever signalled.
            ["unshare", "--user", "--map-current-user", "--net", "--mount", "--pid", "--fork",
             "--kill-child", "--mount-proc", "--keep-caps",
             sys.executable, str(script), str(work), "mount", mode, "online" if online else "offline"],
            env={**os.environ, "BOX_REPO": str(REPO), "HOME": str(work)}, capture_output=True, text=True,
            timeout=120)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, '"ok"'), result.stderr)

    def test_a_box_reaches_no_host_port(self):
        self.network_fixture("ports")

    def test_a_box_puts_the_families_of_a_name_in_the_order_its_host_does(self):
        for mode in ("family", "familyprivate", "familyno4", "family6to4", "familyteredo",
                     "familydeprecated", "familygai", "familygai4", "familygaipast",
                     "familypast4", "family254", "familytwice", "familyrule"):
            with self.subTest(mode=mode):
                self.network_fixture(mode)

    def test_a_box_keeps_the_hosts_network_where_resolv_conf_is_not_plain(self):
        for mode in ("dns", "dns6", "dnsshort", "dnscrlf", "dnsnone"):
            with self.subTest(mode=mode):
                self.network_fixture(mode)

    def test_a_hosts_addresses_must_be_weighed_as_a_boxs_would(self):
        four, six = ipaddress.ip_address("192.0.2.1"), ipaddress.ip_address("2001:db8::1")

        def address(local, index, flags=0x80):
            return struct.pack("=BBBBI", 0, 64, flags, 0, index) + struct.pack(
                "=HH", 4 + len(local.packed), 1) + local.packed

        def kernel(addresses, links=((2, 1), (3, 1))):
            # What the kernel answers: the addresses of the family asked for, or every
            # interface with its type.
            def answers(request, family=0):
                if request == 18:
                    return [struct.pack("=BBHI", 0, 0, kind, index) for index, kind in links]
                return [entry for version, entry in addresses if (version == 4) == (family == socket.AF_INET)]
            return patch.object(box, "_kernel", answers)

        plain = [(4, address(four, 2)), (6, address(six, 2))]
        for name, answers, alike in (
                ("both on one interface", kernel(plain), True),
                ("on two native interfaces", kernel([plain[0], (6, address(six, 3))]), True),
                ("one of the two under a tunnel", kernel([plain[0], (6, address(six, 3))],
                                                         links=((2, 768), (3, 1))), False),
                ("both under tunnels", kernel([plain[0], (6, address(six, 3))],
                                              links=((2, 768), (3, 776))), True),
                ("past its preferred life", kernel([plain[0], (6, address(six, 2, 0x20))]), False),
                ("not yet confirmed", kernel([(4, address(four, 2, 0x04)), plain[1]]), False),
                ("on a second interface as well", kernel([*plain, (6, address(six, 3, 0x20))]), False),
                ("unknown to the kernel", kernel([plain[0]]), False)):
            with self.subTest(name), answers:
                self.assertIs(box._alike({four, six}), alike)
        with patch.object(box, "_kernel", side_effect=OSError("refused")):
            self.assertIs(box._alike({four, six}), False)

    def test_only_plainly_named_resolvers_give_a_box_a_network_of_its_own(self):
        plain = (b"nameserver 192.0.2.1\n", b"nameserver 192.0.2.1", b"nameserver\t192.0.2.1\n",
                 b"# nameserver 127.0.0.1\n; nameserver ::1\nnameserver 192.0.2.1\n"
                 b"nameserver 2001:db8::1\nsearch acme.test\n")
        # No nameserver; one only the host's own network reaches as written; a line that is
        # not the word, blanks and one address, whatever a libc makes of it.
        other = (b"", b"search acme.test\n", b"nameserver 127.0.0.53\n", b"nameserver ::1\n",
                 b"nameserver 0.0.0.0\n", b"nameserver ::\n", b"nameserver fe80::1\n",
                 b"nameserver ::ffff:192.0.2.1\n", b"nameserver 224.0.0.251\n",
                 b"nameserver 192.0.2.1\nnameserver 127.0.0.1\n",
                 b"nameserver 127.53\n", b"nameserver 192.0.2.01\n", b"nameserver fe80::1%eth0\n",
                 b"nameserver 192.0.2.1\r\n", b" nameserver 192.0.2.1\n", b"nameserver 192.0.2.1;\n",
                 b"nameserver #192.0.2.1\n", b"nameserver 192.0.2.1 # acme\n",
                 b"nameserver 192.0.2.1\x00\n", b"nameserver \xff\xfe\n")
        # The box's own addresses there: the two it shares with the host.
        own = set(map(ipaddress.ip_address, ("192.0.2.15", "2001:db8::15")))
        for resolver, is_plain in (*((text, True) for text in plain), *((text, False) for text in other),
                                   (b"nameserver 192.0.2.15\n", False),
                                   (b"nameserver 2001:db8::15\n", False)):
            with self.subTest(resolver=resolver):
                self.assertIs(box._plain(resolver, own), is_plain)
        # A resolver in a family the box has no address in is out of its reach.
        four = {ipaddress.ip_address("192.0.2.15")}
        self.assertIs(box._plain(b"nameserver 192.0.2.1\n", four), True)
        self.assertIs(box._plain(b"nameserver 192.0.2.1\nnameserver 2001:db8::1\n", four), False)

    def test_a_box_reaches_no_host_socket(self):
        # Host services run commands for whoever connects, outside the box: a tmux server in
        # /tmp, the user's service manager in its runtime directory, the system bus in /run.
        # Worker and check boxes, even nested, reach none of them and keep /run's readable
        # file beside its socket; they reach sockets made in their own /tmp.
        # The host runtime directory is linked from /run to a directory outside
        # the box's temporary places, or is in a workspace in /tmp, which stays writable.
        script = self.root / "sockets.py"
        script.write_text(SOCKETS)
        for work, runtime, link in ((self.root / "work", Path("/run/runtime"), self.root / "runtime"),
                                    (Path("/tmp/ws"), Path("/tmp/ws/runtime"), ""),
                                    (Path("/var/tmp/ws"), Path("/var/tmp/ws/runtime"), "")):
            with self.subTest(runtime=str(runtime)):
                places = ["/tmp/host/s", "/var/tmp/host/s", str(runtime / "s"), "/run/acme/s"]
                # Fresh /tmp, /var and /run of the test's own stand for the host's, even inside a
                # box.
                host = ["bwrap", "--unshare-user", "--unshare-pid", "--die-with-parent",
                        "--bind", "/", "/", "--dev-bind", "/dev", "/dev", "--proc", "/proc",
                        "--tmpfs", "/tmp", "--tmpfs", "/var", "--tmpfs", "/run"]
                result = subprocess.run(
                    [*host, "--", sys.executable, str(script), "host", *places],
                    env={**os.environ, "BOX_REPO": str(REPO), "BOX_WORK": str(work),
                         "XDG_RUNTIME_DIR": str(runtime), "BOX_RUNTIME_LINK": str(link)},
                    capture_output=True, text=True, timeout=300)
                self.assertEqual(result.returncode, 0, result.stderr)
                hidden = {**dict.fromkeys(places, [False, False]), "/run/acme/s": [False, True],
                          "own": True, "state": ["kept", "kept"]}
                nested = {**hidden, "/tmp/parent/s": [False, False]}
                self.assertEqual(json.loads(result.stdout), {
                    "unboxed": {**dict.fromkeys(places, [True, True]), "own": True,
                                "state": ["kept", "kept"]},
                    "worker": hidden, "worker inside a box": nested,
                    "check": hidden, "check inside a box": nested})

    def test_a_box_binds_only_the_devices_its_account_has_access_to(self):
        opens = os.access

        def zero_is_closed(path, mode, **how):
            return Path(path) != Path("/dev/zero") and opens(path, mode, **how)

        with patch.object(box.os, "access", zero_is_closed), \
                box.command(["true"], dict(os.environ)) as (cmd, _, _):
            bound = {tuple(cmd[at + 1:at + 3]) for at, arg in enumerate(cmd) if arg == "--dev-bind"}
        # What the box binds itself, on top of the standard nodes bubblewrap's own /dev holds.
        self.assertIn(("/dev/null", "/dev/null"), bound)
        self.assertNotIn(("/dev/zero", "/dev/zero"), bound)
        # That /dev already holds the standard links too; the host's are not copied.
        self.assertFalse([cmd[at + 2] for at, arg in enumerate(cmd)
                          if arg == "--symlink" and cmd[at + 2].startswith("/dev/")])

    def test_shared_memory_is_the_boxs_own_where_the_host_links_it_into_run(self):
        # Older hosts link /dev/shm to /run/shm. Bubblewrap's /dev has a directory there;
        # every box writes its own shared memory.
        devices = [arg for name in ("null", "zero", "full", "random", "urandom", "tty")
                   for arg in ("--dev-bind", f"/dev/{name}", f"/dev/{name}")]
        host = ["bwrap", "--unshare-user", "--unshare-pid", "--die-with-parent", "--bind", "/", "/",
                "--tmpfs", "/dev", *devices, "--proc", "/proc", "--tmpfs", "/tmp",
                "--tmpfs", "/run", "--dir", "/run/shm", "--symlink", "/run/shm", "/dev/shm"]
        result = subprocess.run([*host, "--", sys.executable, "-c", SHM, str(self.root)],
                                env={**os.environ, "BOX_REPO": str(REPO)}, capture_output=True,
                                text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {"worker": "own", "check": "own", "host": False})

    def test_a_box_resolves_names_through_any_run_links(self):
        script = self.root / "run-links.py"
        script.write_text(RUN_LINKS)
        result = subprocess.run(
            ["unshare", "--user", "--map-current-user", "--mount", "--keep-caps",
             sys.executable, str(script), "mount", str(self.root)],
            env={**os.environ, "BOX_REPO": str(REPO)}, capture_output=True, text=True,
            timeout=300)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "ok"), result.stderr)

    def test_run_credentials_never_reach_the_backing_copy_or_another_box(self):
        script = self.root / "run-credentials.py"
        script.write_text(RUN_CREDENTIALS)
        result = subprocess.run(
            ["unshare", "--user", "--map-current-user", "--mount", "--keep-caps",
             sys.executable, str(script), "mount", str(self.root)],
            env={**os.environ, "BOX_REPO": str(REPO)}, capture_output=True, text=True,
            timeout=120)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "ok"), result.stderr)

    def test_a_failed_run_read_discards_partial_bytes_but_write_errors_still_fail(self):
        source, destination = self.root / "run", self.root / "copy"
        source.mkdir()
        destination.mkdir()
        (source / "file").write_text("ordinary")
        fdopen = os.fdopen

        class FailingRead:
            def __init__(self, fd, mode):
                self.stream = fdopen(fd, mode)

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.stream.close()

            def read(self, length):
                if self.stream.tell():
                    raise OSError("source read failed")
                return self.stream.read(2)

        with patch.object(box.os, "fdopen", FailingRead):
            box._copy_run(source, destination, set())
        self.assertFalse((destination / "file").exists())
        with patch.object(Path, "open", side_effect=OSError("destination write failed")), \
                self.assertRaisesRegex(OSError, "destination write failed"):
            box._copy_run(source, destination, set())
        box._copy_run(source, destination, set())
        self.assertEqual((destination / "file").read_text(), "ordinary")

    def test_a_runtime_directory_that_is_the_workspace_refuses_the_box(self):
        # The box keeps its runtime directory empty and writes through to its workspace: one
        # directory cannot be both.
        self.out.mkdir()
        for home_overlay in (False, True):
            with self.subTest(home_overlay=home_overlay), \
                    patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root)}), \
                    self.assertRaisesRegex(config.Error, "keeps empty and one it writes"):
                with box.command(["true"], dict(os.environ), self.out, cwd=self.root,
                                 home_overlay=home_overlay):
                    pass

    def test_a_missing_temporary_place_refuses_before_creating_any_host_directory(self):
        is_dir = Path.is_dir
        for missing in map(Path, ("/tmp", "/var/tmp", "/dev/shm", "/run")):
            for home_overlay in (False, True):
                with self.subTest(missing=str(missing), home_overlay=home_overlay), \
                        patch.object(Path, "is_dir", lambda path: path != missing and is_dir(path)), \
                        patch.object(box, "_writable", side_effect=AssertionError("host write")), \
                        self.assertRaisesRegex(config.Error, f"{missing}:.*missing"):
                    with box.command(["true"], dict(os.environ), self.out, cwd=self.root,
                                     state=(str(missing / "state"),), home_overlay=home_overlay):
                        pass

    def test_a_relative_home_hides_the_keys_where_the_turn_reads_them(self):
        # The turn resolves HOME=home in its own directory, not in the launcher's.
        key = self.root / "home/.ssh/id_fixture"
        key.parent.mkdir(parents=True)
        key.write_text("fixture-key")
        read = ("from pathlib import Path; key = Path.home() / '.ssh/id_fixture'; "
                "print(key.read_text() if key.exists() else '')")
        for home_overlay in (False, True):
            with self.subTest(home_overlay=home_overlay), patch.dict(os.environ, {"HOME": "home"}):
                with box.command([sys.executable, "-c", read], dict(os.environ), cwd=self.root,
                                 home_overlay=home_overlay) as (cmd, env, _):
                    result = subprocess.run(cmd, env=env, cwd=self.root, capture_output=True,
                                            text=True, timeout=10)
                self.assertEqual((result.returncode, result.stdout.strip()), (0, ""), result.stderr)
        self.assertEqual(key.read_text(), "fixture-key")

    def test_a_closed_directory_on_the_way_to_a_key_refuses_the_box(self):
        # The command could open a closed directory it owns, so what it holds counts as there.
        def listed_not_entered(case):
            (case / "home/.ssh").mkdir(parents=True)
            (case / "home/.ssh/id_linked").symlink_to(case / "id_outside")
            return {"HOME": str(case / "home")}, case / "home/.ssh", 0o111

        def linked_directory(case):
            (case / "home/.ssh").mkdir(parents=True)
            (case / "keydir").mkdir()
            (case / "keydir/id_linked").symlink_to(case / "id_outside")
            (case / "home/.ssh/keys").symlink_to(case / "keydir")
            return {"HOME": str(case / "home")}, case / "keydir", 0o111

        def linked_key(case):
            (case / "home/.ssh").mkdir(parents=True)
            (case / "vault").mkdir()
            (case / "vault/id_fixture").write_text("fixture-key")
            (case / "home/.ssh/id_fixture").symlink_to(case / "vault/id_fixture")
            return {"HOME": str(case / "home")}, case / "vault", 0

        def home(case):
            (case / "home/.ssh").mkdir(parents=True)
            return {"HOME": str(case / "home")}, case / "home", 0

        def agent(case):
            (case / "vault").mkdir()
            return {"SSH_AUTH_SOCK": str(case / "vault/agent")}, case / "vault", 0

        for make in (listed_not_entered, linked_directory, linked_key, home, agent):
            case = self.root / make.__name__
            case.mkdir()
            (case / "id_outside").write_text("fixture-key")
            env, closed, mode = make(case)
            closed.chmod(mode)
            self.addCleanup(closed.chmod, 0o700)
            for home_overlay in (False, True):
                with self.subTest(case=make.__name__, home_overlay=home_overlay), patch.dict(os.environ, env), \
                        self.assertRaisesRegex(config.Error, f"{re.escape(str(closed))}.* is closed to "
                                               f"you.*chmod u\\+rx"):
                    with box.command(["true"], dict(os.environ), cwd=self.root, home_overlay=home_overlay):
                        pass

    def test_the_credential_query_sees_no_token(self):
        # A git first on PATH answers the box's question about credential stores.
        bindir, seen, git = self.root / "bin", self.root / "seen.json", shutil.which("git")
        bindir.mkdir()
        (bindir / "git").write_text(
            f"#!{sys.executable}\nimport json, os, sys\n"
            f"open({str(seen)!r}, 'w').write(json.dumps([os.environ.get(k) for k in {box.TOKENS!r}]))\n"
            f"os.execv({git!r}, [{git!r}, *sys.argv[1:]])\n")
        (bindir / "git").chmod(0o755)
        with patch.dict(os.environ, {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
                                     "GITHUB_TOKEN": "fixture-github", "SSH_AUTH_SOCK": "agent"}):
            with box.command(["true"], dict(os.environ), cwd=self.root):
                pass
        self.assertEqual(json.loads(seen.read_text()), [None] * len(box.TOKENS))

    def test_the_commands_own_git_is_never_asked(self):
        # ak stands in the workspace, and PATH names `bin` and the current directory: the
        # project's own. Git's answers decide what the box hides and opens, so ak's own Git
        # gives them, reading configuration wherever it lives: here inside ~/.ssh.
        ssh, store, asked = self.root / ".ssh", self.root / "named-store", self.root / "asked"
        ssh.mkdir()
        store.write_text("fixture-store")
        (ssh / "git.inc").write_text(f"[credential]\n\thelper = store --file {store}\n")
        (self.root / ".gitconfig").write_text(f"[include]\n\tpath = {ssh / 'git.inc'}\n")
        bindir, git = self.root / "bin", shutil.which("git")
        subprocess.run([git, "init", "-q", str(self.root)], check=True)
        bindir.mkdir()
        (bindir / "git").write_text(
            f"#!{sys.executable}\nimport os, sys\nopen({str(asked)!r}, 'w')\n"
            f"os.execv({git!r}, [{git!r}, *sys.argv[1:]])\n")
        (bindir / "git").chmod(0o755)
        (self.root / "git").symlink_to(bindir / "git")
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.root)
        read = f"print(open({str(store)!r}).read())"
        relative = f"bin{os.pathsep}{os.pathsep}"
        with patch.dict(os.environ, {"PATH": relative + os.environ["PATH"]}):
            # Both box modes ask only ak's own Git.
            for home_overlay in (False, True):
                with self.subTest(home_overlay=home_overlay):
                    with box.command([sys.executable, "-c", read], dict(os.environ), cwd=self.root,
                                     home_overlay=home_overlay) as (cmd, env, _):
                        result = subprocess.run(cmd, env=env, cwd=self.root, capture_output=True,
                                                text=True, timeout=10)
                    self.assertEqual((result.returncode, result.stdout.strip()), (0, ""),
                                     result.stderr)
        # With no Git of ak's own the box refuses; it asks neither of the project's.
        with patch.dict(os.environ, {"PATH": relative + str(ssh)}), \
                self.assertRaisesRegex(config.Error, "needs git"):
            with box.command(["true"], dict(os.environ), cwd=self.root):
                pass
        self.assertFalse(asked.exists())

    def test_files_writes_identity_environment_and_exit_status_stay_the_same(self):
        with patch.dict(os.environ, {"BOX_LEAK": "0", "BOX_INSPECT": "1", "BOX_EXIT": "7",
                                     "FIXTURE_PROVIDER_TOKEN": "fixture-provider"}):
            code, text, _, killed, left = self.turn()
        self.assertEqual((code, killed, left), (7, False, False))
        seen = json.loads(text)
        self.assertEqual((seen["home"], seen["cwd"], seen["uid"], seen["provider"]),
                         (str(self.root), os.getcwd(), os.getuid(), "fixture-provider"))
        self.assertEqual((self.root / ".codex/fixture").read_text(), "harness write")

    def test_turns_can_run_inside_a_turn(self):
        with patch.dict(os.environ, {"BOX_NEST": "1", "BOX_REPO": str(REPO)}):
            code, text, _, killed, left = self.turn()
        nested = json.loads(text)["nested"]
        self.assertEqual((code, killed, left), (0, False, True))
        self.assertEqual((nested["code"], nested["killed"], nested["left"]), (0, False, True))
        self.assertEqual(nested["seen"], {"hosts": "", "token": None, "store": ""})
        self.assertTrue(any("detached.py" in line for line in nested["logs"]))
        self.assertFalse(self.alive(self.root / "nested"))
        self.assertFalse(self.alive())

    def test_signal_deaths_keep_their_status_without_reinterpreting_exit_codes(self):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=sig), patch.dict(os.environ, {
                    "BOX_LEAK": "0", "BOX_SIGNAL": str(sig)}):
                code, _, _, killed, left = self.turn()
                self.assertEqual((code, killed, left), (-sig, False, False))
                self.assertEqual(run.killed_word(code), f"killed ({sig.name})")
        for status in (137, 143):
            with self.subTest(exit=status), patch.dict(os.environ, {
                    "BOX_LEAK": "0", "BOX_EXIT": str(status)}):
                code, _, _, killed, left = self.turn()
                self.assertEqual((code, killed, left), (status, False, False))
                self.assertIsNone(run.killed_word(code))

    def test_commands_that_cannot_start_keep_shell_exit_codes(self):
        program = self.root / "unavailable"
        for mode, expected in ((None, 127), (0o644, 126), (0o755, 126)):
            with self.subTest(mode=mode):
                if mode is not None:
                    program.write_text("invalid executable\n")
                    program.chmod(mode)
                with patch.object(config, "adapter", return_value=program):
                    code, _, _, killed, left = self.turn()
                self.assertEqual((code, killed, left), (expected, False, False))
                self.assertEqual(box.returncode(self.out, -1), expected)
                diagnostic = (self.out / "stderr.log").read_text()
                self.assertIn(str(program), diagnostic)
                self.assertNotIn("Traceback", diagnostic)

                activity = self.root / "check.log"
                with activity.open("w+b") as output:
                    code, _, killed = worker.boxed(
                        [str(program)], 10, env=dict(os.environ), cwd=self.root,
                        activity=activity, output=output, stderr=subprocess.STDOUT)
                    output.seek(0)
                    diagnostic = output.read().decode()
                self.assertEqual((code, killed), (expected, False))
                self.assertIn(str(program), diagnostic)
                self.assertNotIn("Traceback", diagnostic)

    def test_silence_kills_unmarked_detached_children_too(self):
        with patch.dict(os.environ, {"BOX_HANG": "1", "BOX_TERM": "exit"}):
            code, _, session, killed, _ = self.turn(limit=2)
        self.assertEqual((code, session, killed), (worker.TIMEOUT, "fixture-session", True))
        self.assertTrue((self.out / "ready").exists())
        self.assertFalse(self.alive())

    def test_abort_and_interrupt_allow_harness_cleanup(self):
        with patch.dict(os.environ, {"BOX_HANG": "1", "BOX_TERM": "exit", "BOX_LEAK": "0"}):
            with self.subTest(stop="abort"), patch.object(worker, "auth_scanner", return_value=(
                    lambda out: "fixture login expired" if (out / "events.jsonl").exists() else None)):
                with self.assertRaises(worker.LoginExpired) as expired:
                    self.turn()
                self.assertEqual(expired.exception.session, "fixture-session")

            self.out = self.root / "interrupt"
            original = worker.subprocess.Popen.communicate
            interrupted = False

            def interrupt(proc, *args, **kwargs):
                nonlocal interrupted
                # The turn's own box is the one whose first process bwrap is to name: ak
                # also starts short ones of its own, to ask libc a question.
                if "--info-fd" in proc.args and not interrupted:
                    deadline = time.monotonic() + 5
                    while not (self.out / "events.jsonl").exists():
                        if time.monotonic() > deadline:
                            raise RuntimeError("fixture adapter never started")
                        time.sleep(.01)
                    interrupted = True
                    raise KeyboardInterrupt
                return original(proc, *args, **kwargs)

            with self.subTest(stop="interrupt"), \
                    patch.object(worker.subprocess.Popen, "communicate", interrupt), \
                    self.assertRaises(KeyboardInterrupt):
                self.turn()
            self.assertEqual((self.out / "session_id").read_text(), "fixture-session")

    def test_term_resistant_turn_is_still_forcibly_destroyed(self):
        with patch.dict(os.environ, {"BOX_HANG": "1", "BOX_TERM": "ignore"}), \
                patch.object(worker, "KILL_GRACE", .2):
            code, _, session, killed, _ = self.turn(limit=2)
        self.assertEqual((code, session, killed), (worker.TIMEOUT, "fixture-session", True))
        self.assertFalse(self.alive())

    def test_a_box_stopped_while_it_is_still_being_built_leaves_nothing_running(self):
        for online in (False, True):
            with self.subTest(online=online):
                self.network_fixture("stop-building", online=online)

    def test_a_box_whose_launcher_is_already_gone_is_ended_by_its_stop(self):
        for online in (False, True):
            with self.subTest(online=online):
                self.network_fixture("stop-gone", online=online)

    def test_launch_refuses_before_allocating_without_box_tools(self):
        which = shutil.which
        for binary, package in (("bwrap", "bubblewrap"), ("pasta", "passt")):
            with self.subTest(binary=binary), \
                    patch.object(box.shutil, "which", side_effect=lambda name, **kw:
                                 None if name == binary else which(name, **kw)), \
                    patch.object(config, "ensure_dirs", side_effect=AssertionError("allocated run")), \
                    self.assertRaisesRegex(config.Error, f"sudo apt-get install -y {package}"):
                run.main([str(self.root / "task.md")])

    def test_job_resume_refuses_before_starting_without_bubblewrap(self):
        receipt = self.root / "jobs" / "job-acme"
        receipt.mkdir(parents=True)
        run.jobs.save_job(receipt, {
            "job_id": "job-acme", "tasks": [{"name": "fix-api", "state": "queued"}]})
        with patch.dict(os.environ, {config.RUN_DIR_ENV: "", config.JOB_DIR_ENV: ""}), \
                patch.object(config, "JOBS", receipt.parent), \
                patch.object(config, "load", return_value={}), \
                patch.object(box.shutil, "which", return_value=None), \
                patch.object(run.jobs, "run_job_loop", return_value=0) as loop, \
                patch.object(run.jobs, "spawn_job_bg", return_value=0) as spawn:
            for tail in ([], ["--bg"]):
                with self.subTest(tail=tail), \
                        self.assertRaisesRegex(config.Error, "sudo apt-get install -y bubblewrap"):
                    run.cmd_resume([receipt.name, *tail])
            loop.assert_not_called()
            spawn.assert_not_called()

    def test_namespace_refusal_names_the_fix(self):
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        bwrap = fake_bin / "bwrap"
        bwrap.write_text("#!/bin/sh\necho 'fixture: namespaces denied' >&2\nexit 1\n")
        bwrap.chmod(0o755)
        original = Path.read_text

        def read(path, **kwargs):
            if str(path) == "/proc/sys/kernel/unprivileged_userns_clone":
                return "0"
            return original(path, **kwargs)

        with patch.dict(os.environ, {"PATH": f"{fake_bin}:{os.environ['PATH']}"}), \
                patch.object(Path, "read_text", read), \
                patch.object(config, "ensure_dirs", side_effect=AssertionError("allocated run")), \
                self.assertRaisesRegex(config.Error, "sudo sysctl -w kernel.unprivileged_userns_clone=1"):
            run.main([str(self.root / "task.md")])

    def test_a_slow_probe_on_a_busy_host_is_no_refusal(self):
        # bubblewrap works here; under landing load its probe can outlast the wait.
        slow = box.subprocess.TimeoutExpired("bwrap", 10)
        with patch.object(box.subprocess, "run", side_effect=slow):
            self.assertIsNone(box.check())


if __name__ == "__main__":
    unittest.main(verbosity=2)
