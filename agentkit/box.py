"""The worker's filesystem and process walls, built in one place.

Offline worker fixtures may patch command to yield (argv, env, {}), keeping
their process audit active outside the turn. The real walls are exercised by
tests/test_worker_box.py.
"""

import json
import os
from pathlib import Path
import pwd
import select
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from string import Template

# What a box never passes on: GitHub tokens, and the SSH agent's address.
TOKENS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "SSH_AUTH_SOCK")
PROCESSES = "box-processes.json"
# The supervisor runs from the text this module was loaded from: the file on disk can change
# under a running launcher, when a probe checks out another revision of ak's own checkout.
SUPERVISOR = None if __name__ == "__main__" else Path(__file__).read_text()


def _links(root):
    """Every link reachable from root, through linked directories too, each directory once.

    A closed directory on the way raises PermissionError: what it holds is unknown."""
    found, seen, pending = [], set(), [Path(root)]
    while pending:
        directory = pending.pop()
        try:
            real = directory.resolve(strict=True)
            entries = [] if real in seen else list(os.scandir(directory))
        except PermissionError:
            raise
        except (OSError, RuntimeError):
            # Missing, looping or not a directory: nothing readable through it.
            continue
        seen.add(real)
        for entry in entries:
            if entry.is_symlink():
                found.append(Path(entry.path))
            try:
                if entry.is_dir():
                    pending.append(Path(entry.path))
            except PermissionError:
                raise
            except OSError:
                continue
    return found


def _git(args, env, cwd, **kwargs):
    """Ask ak's own Git: the first in a directory ak's own PATH names in full.

    Its answers decide what a box hides and what it opens for writing. The command's PATH, a
    relative entry and the current directory may each name the project's own `git`."""
    git = shutil.which("git", path=os.pathsep.join(filter(os.path.isabs, os.get_exec_path())))
    if git is None:
        from . import config
        raise config.Error("worker box needs git in a directory PATH names in full")
    return subprocess.run([git, *args], cwd=cwd,
                          env={**env, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"},
                          capture_output=True, text=True, timeout=10, **kwargs)


def _credentials(env, cwd, agent=None):
    # The turn reads a relative path in its environment from its own directory.
    base = Path(cwd or os.getcwd())
    homes = {base / (env.get("HOME") or Path.home()), Path(pwd.getpwuid(os.getuid()).pw_dir)}
    configs = {home / ".config" for home in homes}
    if env.get("XDG_CONFIG_HOME"):
        configs.add(base / env["XDG_CONFIG_HOME"])
    gh = {root / "gh" for root in configs}
    if env.get("GH_CONFIG_DIR"):
        gh.add(base / env["GH_CONFIG_DIR"])
    caches = {home / ".cache" for home in homes}
    if env.get("XDG_CACHE_HOME"):
        caches.add(base / env["XDG_CACHE_HOME"])
    places = {home / ".git-credential-cache" for home in homes}
    places.update(root / "git/credential" for root in caches)
    places.update(home / ".git-credentials" for home in homes)
    places.update(root / "git/credentials" for root in configs)
    places.update(root / "hosts.yml" for root in gh)
    # A worker reaches no server: only the orchestrator's own shell holds SSH keys and agent.
    for ssh in (home / ".ssh" for home in homes):
        places.add(ssh)
        # A key linked in from elsewhere stays readable at its target unless that is hidden too.
        places.update(_links(ssh))
    if agent:
        # The address is the caller's, so a relative one names a place in the caller's directory;
        # the box passes no address on, so nothing inside reads it any other way.
        places.add(Path(os.getcwd(), agent))
    # A named credential store is just as readable as the default one. Ask Git so
    # includes and repository-local settings use its own precedence and quoting.
    result = _git(["config", "--get-regexp", r"^credential(\..*)?\.helper$"], env, cwd)
    for line in result.stdout.splitlines():
        try:
            helper = line.split(None, 1)[1]
            words = shlex.split(helper)
        except (IndexError, ValueError):
            continue
        if not words or Path(words[0]).name not in (
                "store", "git-credential-store", "cache", "git-credential-cache"):
            continue
        flag = "--socket" if "cache" in words[0] else "--file"
        for i, word in enumerate(words[1:], 1):
            value = word[len(flag) + 1:] if word.startswith(flag + "=") else (
                words[i + 1] if word == flag and i + 1 < len(words) else None)
            if value:
                literal = f"'{value}'" in helper or f"'{flag}={value}'" in helper
                if not literal:
                    value = Template(value).safe_substitute(env)
                path = Path(value.replace("~/", str(env.get("HOME") or Path.home()) + "/", 1)
                            if value.startswith("~/") and not literal else value)
                places.add(base / path)
    return places


def _paths(names, env, cwd):
    values = {key: value for key, value in env.items() if value}
    values.setdefault("HOME", str(Path.home()))
    for name in names:
        if name.startswith("~/"):
            name = "$HOME/" + name[2:]
        try:
            path = Path(Template(name).substitute(values))
        except KeyError:
            continue
        yield path if path.is_absolute() else Path(cwd or os.getcwd()) / path


def _walls(cmd):
    """Make the whole filesystem read-only, keeping devices usable."""
    cmd.extend(["--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"])
    # A read-only bind disables devices too. Restore the nodes, leaving their
    # directories read-only so ordinary files cannot fill the host's /dev tmpfs.
    for device in Path("/dev").rglob("*"):
        # The box gets disk-backed shm; do not bind the host's transient files.
        if device.is_relative_to("/dev/shm"):
            continue
        # ptmx needs its devpts mount; binding one inode breaks terminal allocation.
        # Bubblewrap supplies that pair, whose terminals end with their descriptors.
        if device == Path("/dev/ptmx") or device.is_relative_to("/dev/pts"):
            continue
        if device.is_symlink():
            cmd.extend(["--symlink", os.readlink(device), str(device)])
        else:
            option = "--dev-bind" if device.is_char_device() or device.is_block_device() else "--ro-bind"
            cmd.extend([option, str(device), str(device)])
    cmd.extend(["--remount-ro", "/dev"])


def _writable(clean, cwd, out_dir, state, places, logins):
    """The command's own places: its workspace and Git storage, out dir and harness state."""
    writable = set()
    for path in [*_paths(state, clean, cwd), *map(Path, places)]:
        path = path.resolve()
        path.mkdir(parents=True, exist_ok=True)
        writable.add(path)
    # A sandbox HOME lends credential files as links. Their targets must also
    # allow an in-place token refresh; renaming over the link uses its state dir.
    for path in _paths(logins, clean, cwd):
        if path.is_symlink():
            target = path.resolve()
            if not target.exists():
                # A shared refresh lock can be lent before its first use. Create
                # only that file, keeping its parent read-only inside the turn.
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            writable.add(target)
    if cwd is not None:
        workspace = Path(cwd).resolve()
        writable.add(workspace)
        if (workspace / ".git").exists():
            git_env = {key: value for key, value in clean.items()
                       if key not in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE")}
            result = _git(["rev-parse", "--absolute-git-dir", "--git-common-dir"], git_env,
                          workspace, check=True)
            writable.update((workspace / path).resolve() for path in result.stdout.splitlines())
    if out_dir is not None:
        writable.add(Path(out_dir).resolve())
    return writable


def _sockets(own):
    """Where to cover every Unix socket bound on the host now, but those in the box's own places.

    A host service runs commands for whoever connects, outside the box. Abstract names have no
    file to cover, and a relative one names a place in a directory the list does not give."""
    found = set()
    for line in Path("/proc/net/unix").read_text().splitlines()[1:]:
        fields = line.split(None, 7)
        if len(fields) < 8 or not fields[7].startswith("/"):
            continue
        try:
            path = Path(fields[7]).resolve(strict=True)
            if not stat.S_ISSOCK(path.stat().st_mode):
                continue
        except (OSError, RuntimeError):
            # Gone, or a name no longer leading to a socket: nothing to connect to there.
            continue
        if any(parent in own for parent in path.parents):
            continue
        # Bubblewrap opens each directory on the way to a mount point: one closed to you is
        # covered whole.
        found.add(next((parent for parent in reversed(path.parents)
                        if not os.access(parent, os.R_OK)), path))
    return found


def _inside():
    """Is this inside a box? Its PID 1 is then the supervisor, reporting to its out dir."""
    try:
        argv = Path("/proc/1/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    return (argv[1:3] == [b"-I", b"-c"] and len(argv) > 4
            and argv[4].endswith(f"/{PROCESSES}".encode()))


@contextmanager
def command(argv, env, out_dir=None, *, cwd=None, state=(), places=(), logins=(), walls=True,
            drain=False):
    """Yield spawn arguments; wait for teardown, and with drain for the command's output EOF.

    `state` names a manifest's paths, expanded from the environment; `places` are literal
    directories the command may also write. With an out dir, /tmp, /var/tmp, /dev/shm and the
    runtime directory are the box's own, but inside a box /tmp is that box's. Without walls every
    other write stays as it is outside: a check runs a project's own suite, which writes where
    that project says, like a cache in HOME.
    """
    clean = {key: value for key, value in env.items() if key not in TOKENS}
    cmd = ["bwrap", "--unshare-user", "--unshare-pid", "--as-pid-1", "--die-with-parent",
           "--new-session"]
    if walls:
        _walls(cmd)
    else:
        cmd.extend(["--bind", "/", "/", "--dev-bind", "/dev", "/dev", "--proc", "/proc"])
    # Host services such as the tmux server and the user's service manager listen in the temporary
    # places and the runtime directory. With an out dir the box has its own, on disk there, and
    # reaches no other socket of the host's. A box inside a box keeps that box's /tmp, where a
    # suite keeps what the boxes its checks start use.
    writable = _writable(clean, cwd, out_dir, state, places, logins)
    temporary = ["/var/tmp", "/dev/shm", f"/run/user/{os.getuid()}"]
    if out_dir is not None and _inside():
        writable.add(Path("/tmp").resolve())
    else:
        temporary.append("/tmp")
    private = set() if out_dir is None else {
        path.resolve() for path in map(Path, temporary) if path.is_dir()}
    at = len(cmd)
    for path in sorted(writable):
        # A redundant file mount prevents atomic refresh within its writable parent.
        if any(parent in writable for parent in path.parents):
            continue
        cmd.extend(["--bind", str(path), str(path)])
    # Mount the real target too: a sandbox HOME often links the account's login.
    targets = set()
    try:
        for path in _credentials(clean, cwd, env.get("SSH_AUTH_SOCK")):
            try:
                targets.add(path.resolve(strict=True))
            except PermissionError:
                raise
            except (OSError, RuntimeError):
                # Missing, looping or under a file: nothing to hide there.
                continue
    except PermissionError as exc:
        # The command could open a closed directory it owns, so what it holds stays unknown.
        from . import config
        real = Path(os.path.realpath(exc.filename))
        closed = next(path for path in (*reversed(real.parents), real)
                      if path == real or not os.access(path, os.R_OK | os.X_OK))
        raise config.Error(f"{closed} is closed to you, so the worker box cannot see what it must "
                           f"hide there; run `chmod u+rx {shlex.quote(str(closed))}`") from None
    if out_dir is not None:
        targets.update(_sockets(writable | private))
    folders = {path for path in targets if path.is_dir()}
    for path in sorted(targets):
        # Inside a hidden folder it is gone already, and no mount point can be made there.
        if any(parent in folders for parent in path.parents):
            continue
        cmd.extend(["--tmpfs", str(path), "--remount-ro", str(path)] if path in folders else
                   ["--dev-bind", "/dev/null", str(path)])
    if out_dir is None:
        yield [*cmd, "--", *argv], clean, {}
        return
    report = Path(out_dir).resolve() / PROCESSES
    report.unlink(missing_ok=True)
    # PID 1 records children before exiting; its exit makes the kernel kill
    # every descendant, even one with a new session or an empty environment.
    argv = [sys.executable, "-I", "-c", SUPERVISOR, str(report),
            *(["--drain"] if drain else []), *argv]
    read, write = os.pipe()
    target = None
    lock = threading.Lock()

    def namespace():
        nonlocal write, target
        with lock:
            if write is not None:
                os.close(write)
                write = None
                with os.fdopen(read) as info:
                    target = _pidfd(info.read())
        return target

    def stop(proc, grace):
        target = namespace()
        deadline = time.monotonic() + grace
        if target is not None:
            fd, pid = target
            # The info pipe precedes exec. PID 1 ignores TERM until the supervisor
            # installs its handler, so an early interruption must wait for it.
            while proc.poll() is None and time.monotonic() < deadline:
                try:
                    status = Path(f"/proc/{pid}/status").read_text()
                    caught = next(line.split()[1] for line in status.splitlines()
                                  if line.startswith("SigCgt:"))
                    if int(caught, 16) & (1 << (signal.SIGTERM - 1)):
                        signal.pidfd_send_signal(fd, signal.SIGTERM)
                        break
                except (FileNotFoundError, ProcessLookupError):
                    break
                time.sleep(.01)
        try:
            proc.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()

    with tempfile.TemporaryDirectory(prefix=".box-", dir=Path(out_dir).resolve()) as scratch:
        mounts = []
        for destination in sorted(private):
            source = Path(scratch, *destination.parts[1:])
            source.mkdir(parents=True, exist_ok=True)
            mounts.extend(["--bind", str(source), str(destination)])
        # Short aliases allow Unix sockets even when out has a long run id. Bind
        # these first so a workspace or declared state under /tmp or /var/tmp still wins.
        cmd[at:at] = mounts
        clean["TMPDIR"] = "/var/tmp"
        try:
            yield [*cmd, "--info-fd", str(write), "--", *argv], clean, {
                "pass_fds": (write,), "stop": stop}
        finally:
            target = namespace()
            if target is not None:
                _wait(target[0])


def _pidfd(info):
    # A killed bwrap can exit before its PID 1 finishes killing descendants.
    # Its private info pipe names that process; a pidfd waits for the kernel's
    # teardown, not an environment sweep or a delay guessed to be long enough.
    try:
        info = json.loads(info)
        pid = info["child-pid"]
        fd = os.pidfd_open(pid)
    except (ValueError, KeyError, ProcessLookupError):
        return
    try:
        try:
            same = Path(f"/proc/{pid}/ns/pid").stat().st_ino == info["pid-namespace"]
        except FileNotFoundError:
            # The namespace link disappears before PID 1 finishes teardown.
            same = True
    except BaseException:
        os.close(fd)
        raise
    if not same:
        os.close(fd)
        return None
    return fd, pid


def _wait(fd):
    try:
        # Also cover bwrap dying before it armed its parent-death signal.
        try:
            signal.pidfd_send_signal(fd, signal.SIGKILL)
        except ProcessLookupError:
            pass
        poll = select.poll()
        poll.register(fd, select.POLLIN)
        poll.poll()
    finally:
        os.close(fd)


def check():
    """Refuse before a run is allocated, including hosts that cannot nest a box."""
    from . import config
    remedy = "sudo apt-get install -y bubblewrap"
    if not shutil.which("bwrap"):
        raise config.Error(f"worker box needs bubblewrap; run `{remedy}`")
    try:
        with command(["true"], os.environ) as (inner, env, _):
            with command(inner, env) as (outer, env, _):
                result = subprocess.run(outer, env=env, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return
        why = result.stderr.strip() or f"exit {result.returncode}"
    except subprocess.TimeoutExpired:
        # A host that cannot nest a box says so at once; a slow probe is load, and every
        # turn keeps its own silence and ceiling limits.
        return
    except (OSError, subprocess.SubprocessError) as exc:
        why = str(exc)
    for path, setting in (("/proc/sys/kernel/unprivileged_userns_clone",
                           "kernel.unprivileged_userns_clone=1"),
                          ("/proc/sys/kernel/apparmor_restrict_unprivileged_userns",
                           "kernel.apparmor_restrict_unprivileged_userns=0")):
        try:
            value = Path(path).read_text().strip()
        except OSError:
            continue
        if value == ("0" if "clone" in path else "1"):
            remedy = f"sudo sysctl -w {setting}"
            break
    raise config.Error(f"worker box cannot start: {why}; run `{remedy}`; "
                       "the host must allow nested unprivileged user and PID namespaces")


def _report(out_dir):
    try:
        return json.loads((Path(out_dir) / PROCESSES).read_text())
    except (OSError, ValueError):
        return {}


def returncode(out_dir, fallback):
    """Keep signal deaths distinct from explicit exits like 137 and 143."""
    return _report(out_dir).get("returncode", fallback)


def leftovers(out_dir):
    """Processes recorded inside this turn's PID namespace, before it was destroyed."""
    return _report(out_dir).get("processes", [])


def _supervise(report, argv, drain=False):
    try:
        proc = subprocess.Popen(argv, start_new_session=True, **(
            {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT} if drain else {}))
    except OSError as exc:
        # A command that never started proves no defect; keep the shell's launch codes.
        code = 127 if isinstance(exc, FileNotFoundError) else 126
        print(exc, file=sys.stderr)
        Path(report).write_text(json.dumps({"returncode": code, "processes": []}))
        return code

    def term(signum, _frame):
        # Outer bwrap cannot forward TERM; leave it alive while the harness saves
        # its session. The kernel still ends detached descendants with PID 1.
        try:
            os.killpg(proc.pid, signum)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, term)
    reader = None
    if drain:
        # Checks have always waited for children holding their output pipe. Keep
        # PID 1 alive until EOF so those children still face the silence watchdog.
        def forward():
            with proc.stdout:
                for chunk in iter(lambda: proc.stdout.read1(64 * 1024), b""):
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
        reader = threading.Thread(target=forward)
        reader.start()
    # PID 1 also inherits orphans. Reap them while waiting for the adapter, so a
    # long turn cannot accumulate zombies from double-forked commands.
    while True:
        pid, status = os.waitpid(-1, 0)
        if pid == proc.pid:
            code = proc.returncode = os.waitstatus_to_exitcode(status)
            break
    while reader is not None and reader.is_alive():
        # Whoever still holds the output may leave more orphans; reap them until EOF.
        reader.join(0.05)
        try:
            while os.waitpid(-1, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            pass
    left = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            state = (entry / "stat").read_text().rsplit(")", 1)[1].split()[0]
            if state in ("Z", "X"):
                continue
            command = (entry / "cmdline").read_bytes().decode(errors="replace").replace("\0", " ").strip()
        except FileNotFoundError:
            continue
        except OSError:
            command = "command unavailable"
        left.append([int(entry.name), command])
    Path(report).write_text(json.dumps({"returncode": code, "processes": left}))
    return 128 - code if code < 0 else code


if __name__ == "__main__":
    drain = sys.argv[2] == "--drain"
    sys.exit(_supervise(sys.argv[1], sys.argv[3:] if drain else sys.argv[2:], drain))
