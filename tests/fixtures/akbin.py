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
"""

from collections import namedtuple
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

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

LOG = "#!/bin/sh\n{python} -c 'import json, sys; print(json.dumps(sys.argv[1:]))' \"$@\" >>{log}\n"
REFUSE = LOG + 'echo "{name}: not scripted in this test" >&2\nexit 1\n'
# A socket path could name any server on the machine, as could a socket name holding a slash
# (`-L ../../tmux-1000/agentkit` walks out of TMUX_TMPDIR), and TMUX or TMUX_PANE the caller's
# own.  Its flags are read as tmux's getopt reads them: bundled, a value attached or in the next
# word.
TMUX = LOG + """refuse() {{ echo "tmux: a test's tmux takes no socket path" >&2; exit 2; }}
value() {{ case $1$2 in L*/*) refuse ;; esac; }}
want=
for a do
  if [ -n "$want" ]; then value "$want" "$a"; want=; continue; fi
  case $a in --|-|[!-]*) break ;; esac
  flags=${{a#-}}
  while [ -n "$flags" ]; do
    flag=${{flags%"${{flags#?}}"}}; flags=${{flags#?}}
    case $flag in
      S) refuse ;;
      [cfLT]) if [ -n "$flags" ]; then value "$flag" "$flags"; else want=$flag; fi; break ;;
    esac
  done
done
unset TMUX TMUX_PANE
export TMUX_TMPDIR={tmpdir}
exec {real} "$@"
"""


class Home:
    """A throwaway HOME the program runs in; `close` (or leaving `with`) ends every process it
    left and removes it."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="akbin-")).resolve()
        self.path = self.root / "home"
        self.bin = self.root / "bin"
        # A socket's path must fit in 104 bytes, and TMPDIR may be deep inside a checkout.
        self.tmux_dir = Path(tempfile.mkdtemp(prefix="akt-", dir="/tmp")).resolve()
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
        servers = self.tmux_dir / f"tmux-{os.getuid()}"
        for socket in servers.iterdir() if servers.is_dir() else ():
            ask = [REAL_TMUX, "-S", str(socket)]
            pid = subprocess.run([*ask, "display-message", "-p", "#{pid}"], capture_output=True,
                                 text=True, timeout=30).stdout.strip()
            subprocess.run([*ask, "kill-server"], capture_output=True, timeout=30)
            _wait_gone(int(pid) if pid.isdigit() else None)
        # what the program detached from them: a stray still writing would put the Home back
        for pid in self._strays():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            _wait_gone(pid)
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.tmux_dir, ignore_errors=True)

    def _strays(self):
        """Processes still running in this Home: their environment names it as HOME."""
        mark = f"HOME={self.path}".encode()
        found = []
        for entry in Path("/proc").glob("[0-9]*"):
            try:
                if mark in (entry / "environ").read_bytes().split(b"\0"):
                    found.append(int(entry.name))
            except OSError:      # gone meanwhile, or not ours to read
                continue
        return found

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

    def ak(self, *args, **kwargs):
        """Run the program once; see `run`."""
        return self.run(AK, *args, **kwargs)

    def run(self, *argv, input=None, tty=False, env=None, cwd=None, timeout=120):
        """Run a command in this Home and wait for it.  `tty` puts a terminal on its stdin with
        `input` typed into it, as a person would.  A hang fails the test, naming the command,
        and leaves nothing of it running."""
        typist = terminal = None
        if tty:
            typist, terminal = os.openpty()
            os.write(typist, (input or "").encode())
            input = None
        try:
            proc = subprocess.Popen(argv, stdin=terminal if tty else subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    cwd=cwd or self.path, env=self._env(env),
                                    start_new_session=True)
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

    def spawn(self, *args, env=None, cwd=None):
        """Start the program and leave it running, its output in `home.log(...)`; `close` ends
        it."""
        name = f"spawn-{len(self._spawned) + 1}"
        with self.log(f"{name}.out").open("w") as out, self.log(f"{name}.err").open("w") as err:
            proc = subprocess.Popen([AK, *args], stdin=subprocess.DEVNULL, stdout=out, stderr=err,
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
