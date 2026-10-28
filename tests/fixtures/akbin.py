"""Run an ak program from outside, the way a person, a model or a harness does.

The answer key's tests (tests/test_key_*.py) judge ak only by its exit code, what it prints and
what it writes, so one test holds whichever build `AK_BIN` names: this checkout's `bin/ak` when
unset, and a relative name is read from the checkout.  Nothing here imports agentkit.

`Home` is a throwaway HOME for the program, with the shipped `config.default.toml` as its config.
The program sees an environment built from nothing, never the caller's: no `AK_*`, `AGENTKIT_*`,
tmux or harness variable reaches it, so it is nobody's seat or run and can find no login, no user
systemd manager and no repository above its HOME; notifications go nowhere; and `home.bin` leads
PATH.  There a fake of each host tool in `REFUSED` logs its call and refuses it, so no test
reaches GitHub, the live host, the owner's units or a harness unless it puts a fake of its own
there with `home.fake`.  `tmux` is the real one, held to a socket directory of this Home's own:
judge it by its state through `home.tmux`, never by the commands ak sent it, which another build
may send another way.

    from fixtures.akbin import Home
    with Home() as home:
        done = home.ak("run", "-h")
        assert done.code == 0, done.err

`home.tick()` runs one `ak watch` in a box (`boxable()` says whether bubblewrap can build
one here) and waits out what it detached there, so nothing of it outlives the test.
A test whose ticks act on processes it started, which that box cannot see, ends with
`rerun_boxed()` before `unittest.main()`: the whole file then runs in one such box, `BOXED`.
"""

from collections import namedtuple
import functools
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
_NAMED = Path(os.environ.get("AK_BIN") or "bin/ak")
AK = str(_NAMED if _NAMED.is_absolute() else REPO / _NAMED)
SOCKET = "agentkit-test"    # the tmux server ak's seats are on in every Home
# Only the system's own directories: the caller's PATH may lead to ak's tmux shim or a harness.
SYSTEM = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin")
REAL_TMUX = shutil.which("tmux", path=os.pathsep.join(SYSTEM))

# GitHub, the live host, the owner's units and crontab, desktop notices, the network and each
# harness's own login.
REFUSED = ("gh", "ssh", "curl", "systemctl", "systemd-run", "loginctl", "journalctl", "crontab",
           "notify-send", "claude", "codex", "muse", "grok", "opencode", "agy")

Done = namedtuple("Done", "code out err")

# ak's collection sweeps /tmp: a /tmp of the box's own keeps the host's out of its reach.
_FILES = ("bwrap", "--dev-bind", "/", "/", "--tmpfs", "/tmp")
# A tick's box (`Home.tick`), where it runs this file's `_last`.
_BOX = (*_FILES, "--unshare-net", "--unshare-pid", "--proc", "/proc")


@functools.cache
def boxable():
    """Whether bubblewrap can build `home.tick()`'s box here."""
    return bool(shutil.which("bwrap")) and subprocess.run(
        [*_BOX, "--", "true"], capture_output=True, timeout=60).returncode == 0


def _binds(*paths):
    """What keeps those of `paths` under /tmp in the box, whose own /tmp hides the host's."""
    return [arg for path in sorted(map(str, paths), key=len)
            if Path(path).is_relative_to("/tmp") for arg in ("--bind", path, path)]


BOXED = "AKBIN_BOXED" in os.environ


def rerun_boxed():
    """Run this test file again in one box of `home.tick()`'s kind, every Home and ak of it
    inside, and exit with its status; inside one, or where bwrap cannot build one, return."""
    if BOXED or not boxable():
        return
    sys.exit(subprocess.call([*_BOX, *_binds(REPO, Path(AK).resolve().parent), "--setenv",
                              "AKBIN_BOXED", "1", "--", sys.executable,
                              os.path.abspath(sys.argv[0]), *sys.argv[1:]]))


def owner(pid):
    """The process identity `ak run` records for itself: the boot, and the process's start."""
    stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    btime = next(int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines()
                 if line.startswith("btime "))
    ticks = int(stat[19])
    return {"pid": pid, "process_identity": {
        "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(), "ticks": ticks,
        "started_at": btime + ticks / os.sysconf("SC_CLK_TCK")}}


LOG = "#!/bin/sh\n{python} -c 'import json, sys; print(json.dumps(sys.argv[1:]))' \"$@\" >>{log}\n"
REFUSE = LOG + 'echo "{name}: not scripted in this test" >&2\nexit 1\n'
# A socket path could name any server on the machine, as could a socket name holding a slash
# (`-L ../../tmux-1000/agentkit` walks out of TMUX_TMPDIR), and TMUX or TMUX_PANE the caller's
# own.  The one path let through is the Home's own server's, as tmux gives it to a seat's pane
# (in TMUX, up to its first comma), matched as a string: no spelling of a path is judged by where
# it leads.  Its flags are read as tmux's getopt reads them: bundled, a value attached or in the
# next word.
TMUX = LOG + """refuse() {{ echo "tmux: a test's tmux takes no socket path but its own" >&2; exit 2; }}
value() {{
  case $1 in
    L) case $2 in */*) refuse ;; esac ;;
    S) [ "$2" = {own} ] || refuse ;;
  esac
}}
want=
for a do
  if [ -n "$want" ]; then value "$want" "$a"; want=; continue; fi
  case $a in --|-|[!-]*) break ;; esac
  flags=${{a#-}}
  while [ -n "$flags" ]; do
    flag=${{flags%"${{flags#?}}"}}; flags=${{flags#?}}
    case $flag in
      [cfLST]) if [ -n "$flags" ]; then value "$flag" "$flags"; else want=$flag; fi; break ;;
    esac
  done
done
case ${{TMUX-}} in {own},*) ;; *) unset TMUX TMUX_PANE ;; esac
export TMUX_TMPDIR={tmpdir}
exec {real} "$@"
"""


class Home:
    """A throwaway HOME the program runs in; `close` (or leaving `with`), or else the death of
    the process that made it, ends every process it left and removes it."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="akbin-")).resolve()
        self.path = self.root / "home"
        self.bin = self.root / "bin"
        # A socket's path must fit in 104 bytes, and TMPDIR may be deep inside a checkout.
        self.tmux_dir = Path(tempfile.mkdtemp(prefix="akt-", dir="/tmp")).resolve()
        # The Home's lifeline: only this process holds the pipe on the reaper's stdin, not even
        # a process it forks, so the reaper reads its end once this process dies, however it
        # died, and does `close`'s work.  A shell waits, holding this file open, and Python runs
        # it only then, though the checkout be gone by then.  It holds neither of this process's
        # outputs, which a runner reads to their end, and no group of this process kills it.
        with open(__file__, "rb") as script:
            self._reaper = subprocess.Popen(
                ["/bin/sh", "-c", 'read _ || exec "$@"', "sh", sys.executable, "-I",
                 f"/dev/fd/{script.fileno()}", "reap", self.root, self.tmux_dir],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, pass_fds=[script.fileno()])
        os.register_at_fork(after_in_child=self._reaper.stdin.close)
        self._spawned = []
        for directory in (self.path / ".agentkit" / "state", self.bin, self.root / "tmp",
                          self.root / "run", self.root / "logs"):
            directory.mkdir(parents=True)
        self.root.joinpath("run").chmod(0o700)
        shutil.copy(REPO / "config.default.toml", self.path / ".agentkit" / "config.toml")
        self.write(".gitconfig", "[user]\n\tname = acme\n\temail = acme@example.com\n"
                                 "[init]\n\tdefaultBranch = main\n")
        python = shlex.quote(sys.executable)
        for name in REFUSED:
            self.fake(name, REFUSE.format(python=python, name=name,
                                          log=shlex.quote(str(self.log(name)))))
        self.fake("tmux", TMUX.format(python=python, log=shlex.quote(str(self.log("tmux"))),
                                      tmpdir=shlex.quote(str(self.tmux_dir)),
                                      own=shlex.quote(str(self.tmux_dir / f"tmux-{os.getuid()}"
                                                          / SOCKET)),
                                      real=shlex.quote(REAL_TMUX)) if REAL_TMUX else
                  REFUSE.format(python=python, name="tmux",
                                log=shlex.quote(str(self.log("tmux")))))
        self.env = {
            "HOME": str(self.path),
            "PATH": os.pathsep.join([str(self.bin), str(Path(sys.executable).parent), *SYSTEM]),
            "USER": os.environ.get("USER", "acme"), "LOGNAME": os.environ.get("LOGNAME", "acme"),
            "SHELL": "/bin/sh", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
            "TERM": "dumb", "NO_COLOR": "1", "TMPDIR": str(self.root / "tmp"),
            "TMUX_TMPDIR": str(self.tmux_dir), "AGENTKIT_TMUX_SOCKET": SOCKET,
            # an empty runtime directory: no user systemd manager or session bus to find
            "XDG_RUNTIME_DIR": str(self.root / "run"),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
            "GIT_CEILING_DIRECTORIES": str(self.root),
            "AK_NOTIFY_SINK": "dry-run",
            # nobody's nested run, and no slot gate parking a launch behind the host's load
            "AK_RUN_DEPTH": "0", "AK_MAX_RUNS": "0",
        }

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self):
        for proc in self._spawned:
            _end(proc)
        _clear(self.root, self.tmux_dir)
        _end(self._reaper)      # last: a close cut short leaves the rest to it

    def log(self, name):
        return self.root / "logs" / f"{name}.log"

    def fake(self, name, script):
        """Put an executable `name` first on the program's PATH."""
        path = self.bin / name
        path.write_text(script)
        path.chmod(0o755)
        return path

    def calls(self, name):
        """Each argv a logging fake was called with, oldest first."""
        try:
            return [json.loads(line) for line in self.log(name).read_text().splitlines()]
        except FileNotFoundError:
            return []

    def write(self, relative, data, *, ago=None):
        """Write a file under HOME, a dict or list as JSON; `ago` seconds back-dates it."""
        path = self.path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data if isinstance(data, str) else json.dumps(data, indent=1))
        if ago is not None:
            stamp = time.time() - ago
            os.utime(path, (stamp, stamp))
        return path

    def tree(self):
        """Every file and directory under HOME, with each file's bytes: what a command left."""
        return {str(path.relative_to(self.path)): path.read_bytes() if path.is_file() else None
                for path in sorted(self.path.rglob("*"))}

    def ak(self, *args, boxed=False, **kwargs):
        """Run the program once; see `run`.  `boxed` gives it the /tmp of `box`."""
        return self.run(*(self.box() if boxed else ()), AK, *args, **kwargs)

    def run(self, *argv, input=None, tty=False, env=None, cwd=None, timeout=120, keep=()):
        """Run a command in this Home and wait for it.  `tty` puts a terminal on its stdin with
        `input` typed into it, as a person would.  `keep` are descriptors it, and whatever it
        starts, inherits.  A hang fails the test, naming the command, and leaves nothing of it
        running."""
        typist = terminal = None
        if tty:
            typist, terminal = os.openpty()
            os.write(typist, (input or "").encode())
            input = None
        try:
            proc = subprocess.Popen(argv, stdin=terminal if tty else subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    cwd=cwd or self.path, env=self._env(env),
                                    start_new_session=True, pass_fds=keep)
            try:
                out, err = proc.communicate(input, timeout=timeout)
            except subprocess.TimeoutExpired:
                _end(proc)
                raise AssertionError(f"still running after {timeout} s: "
                                     f"{shlex.join(argv)}") from None
        finally:
            for fd in (typist, terminal):
                if fd is not None:
                    os.close(fd)
        return Done(proc.returncode, out, err)

    def tick(self, env=None):
        """One `ak watch`, boxed: a tick asks the public boards and the shared browser on
        loopback, so it gets a loopback of its own, where only a sink on the host's is relayed
        (tests/fixtures/sink.py), and its collection sweeps /tmp, so it gets one holding only
        this Home and the program."""
        sink = urlsplit(self._env(env).get("AK_NOTIFY_SINK", ""))
        port = sink.port if sink.hostname == "127.0.0.1" else None
        way = self.tmux_dir / "sink.sock"     # a socket's path must fit in 104 bytes
        listener = socket.create_server(str(way), family=socket.AF_UNIX)
        relay = _relay(listener, socket.AF_INET, ("127.0.0.1", port))
        try:
            return self.run(*self.box(_BOX), sys.executable, "-I", Path(__file__).resolve(),
                            "tick", str(port or ""), str(way), AK, "watch", env=env)
        finally:
            listener.shutdown(socket.SHUT_RDWR)     # wakes its `accept`, as `close` would not
            listener.close()
            relay.join()
            way.unlink()

    def box(self, box=_FILES):
        """bwrap's words putting a command in `box`, by default one whose /tmp holds only this
        Home and the program, on the host's network and processes so pages reach the test's
        sink and what it starts can outlive it; `boxable()` says whether bwrap can here."""
        return [*box, *_binds(*{self.root, self.tmux_dir, REPO, Path(AK).resolve().parent}), "--"]

    def spawn(self, *args, env=None, cwd=None, boxed=False):
        """Start the program and leave it running, its output in `home.log(...)`; `close` ends
        it.  `boxed` gives it the /tmp of `box`."""
        name = f"spawn-{len(self._spawned) + 1}"
        with self.log(f"{name}.out").open("w") as out, self.log(f"{name}.err").open("w") as err:
            proc = subprocess.Popen([*(self.box() if boxed else ()), AK, *args],
                                    stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    cwd=cwd or self.path, env=self._env(env),
                                    start_new_session=True)
        self._spawned.append(proc)
        return proc

    def tmux(self, *args, server=SOCKET):
        """Ask one of this Home's tmux servers, ak's unless named, as the test and not as ak."""
        proc = subprocess.run([REAL_TMUX, "-L", server, *args], capture_output=True, text=True,
                              env=self._env(None), timeout=30)
        return Done(proc.returncode, proc.stdout, proc.stderr)

    def _env(self, extra):
        """This Home's environment with `extra` over it; a None value removes the variable."""
        merged = {**self.env, **(extra or {})}
        return {key: value for key, value in merged.items() if value is not None}


def _clear(root, tmux_dir):
    """End the tmux servers the Home at `root` started, and its strays, and remove it."""
    servers = Path(tmux_dir, f"tmux-{os.getuid()}")
    for socket in servers.iterdir() if servers.is_dir() else ():
        ask = [REAL_TMUX, "-S", str(socket)]
        pid = subprocess.run([*ask, "display-message", "-p", "#{pid}"], capture_output=True,
                             text=True, timeout=30).stdout.strip()
        subprocess.run([*ask, "kill-server"], capture_output=True, timeout=30)
        _wait_gone(int(pid) if pid.isdigit() else None)
    # what the program detached from them: a stray still writing would put the Home back
    for pid in _strays(Path(root, "home")):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _wait_gone(pid)
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(tmux_dir, ignore_errors=True)


def _strays(home):
    """Processes still running in a Home: their environment names `home` as HOME."""
    mark = f"HOME={home}".encode()
    found = []
    for entry in Path("/proc").glob("[0-9]*"):
        try:
            if mark in (entry / "environ").read_bytes().split(b"\0"):
                found.append(int(entry.name))
        except OSError:      # gone meanwhile, or not ours to read
            continue
    return found


def _wait_gone(pid, bound=30):
    """Wait for a process that is not this one's child to end; a tmux server goes a moment after
    it is told to."""
    deadline = time.monotonic() + bound
    while pid and time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)


def _end(proc):
    """Kill a process's whole session and collect it, without waiting on its pipes: a process
    it detached may hold them open long after."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait()
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        if pipe:
            pipe.close()


def _relay(listener, family, address):
    """Carry each connection `listener` takes to `address`, both ways, until it ends; the
    thread returned takes them until `listener` is shut down."""
    def pipe(source, sink):
        try:
            while data := source.recv(65536):
                sink.sendall(data)
            sink.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    def serve():
        while True:
            try:
                near, far = listener.accept()[0], socket.socket(family)
                far.connect(address)
            except OSError:     # the tick is over
                return
            for ends in ((near, far), (far, near)):
                threading.Thread(target=pipe, args=ends, daemon=True).start()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


def _last(port, way, *program):
    """A tick's last breath in its box: the sink's port carried in from the socket at `way`, and
    what the program detached waited out before the box goes."""
    if port:
        _relay(socket.create_server(("127.0.0.1", int(port))), socket.AF_UNIX, way)
    code = subprocess.call(program)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if not [p for p in os.listdir("/proc") if p.isdigit() and int(p) not in (1, os.getpid())]:
            sys.exit(code)
        time.sleep(0.1)
    sys.exit("the tick left processes running")


if __name__ == "__main__":
    {"tick": _last, "reap": _clear}[sys.argv[1]](*sys.argv[2:])
