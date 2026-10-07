"""The worker's filesystem, network and process walls, built in one place.

Offline worker fixtures may patch command to yield (argv, env, {}), keeping
their process audit active outside the turn. The real walls are exercised by
tests/test_worker_box.py.
"""

import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
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
TRANSIENT = tuple(map(Path, ("/run", "/tmp", "/var/tmp", "/dev/shm")))
OVERLAY_REMEDY = ("install bubblewrap with --tmp-overlay support and use a kernel that allows "
                  "overlayfs in unprivileged user namespaces")
# The supervisor runs from the text this module was loaded from: the file on disk can change
# under a running launcher, when a probe checks out another revision of ak's own checkout.
SUPERVISOR = None if __name__ == "__main__" else Path(__file__).read_text()


def _contents(root):
    """Every path under root, through linked directories too, each directory once.

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
            found.append(Path(entry.path))
            try:
                if entry.is_dir():
                    pending.append(Path(entry.path))
            except PermissionError:
                raise
            except OSError:
                continue
    return found


def _host_binary(name):
    return shutil.which(name, path=os.pathsep.join(filter(os.path.isabs, os.get_exec_path())))


def _git(args, env, cwd, **kwargs):
    """Ask ak's own Git: the first in a directory ak's own PATH names in full.

    Its answers decide what a box hides and what it opens for writing. The command's PATH, a
    relative entry and the current directory may each name the project's own `git`."""
    git = _host_binary("git")
    if git is None:
        from . import config
        raise config.Error("worker box needs git in a directory PATH names in full")
    return subprocess.run([git, *args], cwd=cwd,
                          env={**env, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"},
                          capture_output=True, text=True, timeout=10, **kwargs)


def _homes(env, cwd):
    base = Path(cwd or os.getcwd())
    return {base / (env.get("HOME") or Path.home()), Path(pwd.getpwuid(os.getuid()).pw_dir)}


def _credentials(env, cwd, agent=None):
    # The turn reads a relative path in its environment from its own directory.
    base = Path(cwd or os.getcwd())
    homes = _homes(env, cwd)
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
    places.update(home / ".ssh" for home in homes)
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
    # A masked folder's files and links must not gain another name in /run's copy.
    for path in tuple(places):
        places.update(_contents(path))
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


def _copy_run(source, destination, hidden):
    """Keep readable directories, links and files; let the kernel resolve their paths."""
    if source in hidden or any(parent in hidden for parent in source.parents):
        return
    # Bind mounts and hard links can give the same credential another path.
    hidden_ids = set()
    for path in hidden:
        try:
            info = path.stat()
        except OSError:
            continue
        hidden_ids.add((info.st_dev, info.st_ino))
    for directory, dirs, files, fd in os.fwalk(source):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) in hidden_ids:
            dirs.clear()
            continue
        directory = Path(directory)
        # An out dir in /run must not copy its own growing scratch back into itself.
        # Credentials must never gain a second path on disk, even if the launcher dies.
        dirs[:] = [name for name in dirs if directory / name != destination.parent
                   and directory / name not in hidden]
        files = [name for name in files if directory / name not in hidden]
        if directory == source:
            dirs[:] = [name for name in dirs if name != "user"]
            files = [name for name in files if name != "user"]
        target = destination / directory.relative_to(source)
        target.mkdir(parents=True, exist_ok=True)
        for name in dirs + files:
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if (info.st_dev, info.st_ino) in hidden_ids:
                    if name in dirs:
                        dirs.remove(name)
                    continue
                mode = info.st_mode
                link = os.readlink(name, dir_fd=fd) if stat.S_ISLNK(mode) else None
            except OSError:
                continue
            if stat.S_ISDIR(mode):
                (target / name).mkdir(exist_ok=True)
            elif link is not None:
                (target / name).symlink_to(link)
            elif stat.S_ISREG(mode):
                try:
                    # A service may replace an entry during the copy. Never follow its new
                    # link or block on its new FIFO; read only an opened regular file.
                    opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                except OSError:
                    continue
                with os.fdopen(opened, "rb") as readable:
                    info = os.fstat(opened)
                    if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) not in hidden_ids:
                        with (target / name).open("wb") as copied:
                            while True:
                                try:
                                    content = readable.read(shutil.COPY_BUFSIZE)
                                except OSError:
                                    (target / name).unlink()
                                    break
                                if not content:
                                    break
                                copied.write(content)


def _own(scratch, clean, cwd, writable, hidden):
    """A copy of /run without services, and empty temporary and runtime directories."""
    own = {path.resolve() for path in TRANSIENT}
    for path in _paths(("$XDG_RUNTIME_DIR",), clean, cwd):
        if path.is_dir():
            real = path.resolve()
            # A writable workspace or state inside /tmp exposes its children again, so its
            # host runtime directory still needs a cover of its own.
            if not any(place == real or place in real.parents for place in own) or any(
                    place == real or place in real.parents for place in writable):
                own.add(real)
    # Bubblewrap's /dev has a shm directory even where the host's links into /run.
    own.add(Path("/dev/shm"))
    binds = {path: Path(scratch, str(i)) for i, path in enumerate(sorted(own))}
    for source in binds.values():
        source.mkdir(parents=True, exist_ok=True)
    run = Path("/run").resolve()
    _copy_run(run, binds[run], hidden)
    runtime = Path("user", str(os.getuid()))
    (binds[run] / runtime).mkdir(mode=0o700, parents=True)
    binds[run / runtime] = binds[run] / runtime
    clean["XDG_RUNTIME_DIR"] = str(Path("/run") / runtime)
    return binds


def _bind(own, writable, homes=()):
    """Mount HOME overlays, private and writable places, parents first so deeper mounts win."""
    clash = sorted(own.keys() & writable)
    if clash:
        from . import config
        raise config.Error(f"{clash[0]} is a place the box keeps empty and one it writes through "
                           "to; give each a directory of its own")
    overlays = set(homes) - own.keys() - writable
    mounts = {Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), line.split()[4]))
              for line in Path("/proc/self/mountinfo").read_text().splitlines()} if overlays else set()
    # Overlayfs refuses inherited child mounts. Leave those homes read-only rather than
    # rebuilding their contents: a box's arguments must not grow with directory entries.
    overlays = {path for path in overlays if not any(path in mount.parents for mount in mounts)}
    binds = {**{path: path for path in overlays}, **own, **{path: path for path in writable}}
    args = []
    for path in sorted(binds):
        # What the nearest mounted parent already shows needs no mount of its own, and a
        # redundant file mount prevents atomic refresh within its writable parent.
        parent = next((parent for parent in path.parents if parent in binds), None)
        if path in overlays:
            args.extend(["--overlay-src", str(path), "--tmp-overlay", str(path)])
        elif (parent is None or parent in overlays
              or binds[parent] / path.relative_to(parent) != binds[path]):
            args.extend(["--bind", str(binds[path]), str(path)])
    return args


@contextmanager
def _network(cmd, env, out_dir=None, info=None):
    # With no usable route, pasta has no outside to connect to. Bubblewrap still
    # supplies a private network namespace with its own working loopback.
    routes = any(line.split()[0] != "lo" and int(line.split()[3], 16) & 0x201 == 1
                 for line in Path("/proc/net/route").read_text().splitlines()[1:])
    ipv6 = Path("/proc/net/ipv6_route")
    routes6 = ipv6.exists() and any(
        line.split()[-1] != "lo" and int(line.split()[8], 16) & 0x201 == 1
        for line in ipv6.read_text().splitlines())
    if info is not None:
        # Pasta closes extra descriptors. Open the witness after it starts;
        # the box's private /tmp hides this file from the command.
        cmd = ["sh", "-c", 'exec 3>"$1"; shift; exec "$@"', "box", info, *cmd]
    if not (routes or routes6):
        yield [*cmd, "--unshare-net"]
        return
    unshare, pasta, setpriv = map(_host_binary, ("unshare", "pasta", "setpriv"))
    if not all((unshare, pasta, setpriv)):
        yield [*cmd, "--unshare-net"]
        return
    # Keep the account's numbers in pasta's user namespace. Its default maps the
    # account to root; bwrap must also receive no ambient capabilities.
    # A different address inside keeps host listeners on its LAN address reachable.
    # Loopback supplies both IP families, including a resolver's only family.
    prefix = [unshare, "--user", "--map-current-user", "--keep-caps", pasta,
              "--netns-only", "--config-net", "--no-map-gw", "--quiet",
              "--interface", "lo", "--ns-ifname", "tap0",
              "--address", "10.0.2.15", "--netmask", "24", "--gateway", "10.0.2.2",
              "--address", "fd00::15", "--gateway", "fe80::1",
              "-t", "none", "-u", "none", "-T", "none", "-U", "none"]
    resolver = Path("/etc/resolv.conf")
    content = resolver.read_text() if resolver.exists() else ""
    hosts = {}

    def forward(match):
        try:
            address = ipaddress.ip_address(match[2])
        except ValueError:
            return match[0]
        if not address.is_loopback:
            return match[0]
        hosts.setdefault(address.version, str(address).split("%")[0])
        return match[1] + ("10.0.2.3" if address.version == 4 else "fd00::3")

    content = re.sub(r"(?m)^([^\S\n]*nameserver[ \t]+)(\S+)", forward, content)
    for version, address in hosts.items():
        prefix.extend(["--dns-forward", "10.0.2.3" if version == 4 else "fd00::3",
                       "--dns-host", address])
    prefix.extend([setpriv, "--inh-caps=-all", "--ambient-caps=-all"])
    # In an enclosing box, the host's pasta may be unable to start a command
    # (for example an AppArmor exec transition under no_new_privs).
    with subprocess.Popen([*prefix, "/usr/bin/true"], env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as probe:
        try:
            ready = probe.wait(timeout=10) == 0
        except subprocess.TimeoutExpired:
            probe.terminate()
            try:
                probe.wait(timeout=10)
            except subprocess.TimeoutExpired:
                probe.kill()
                probe.wait()
            ready = False
    if not ready:
        yield [*cmd, "--unshare-net"]
        return
    if not hosts:
        yield [*prefix, *cmd]
        return
    with tempfile.NamedTemporaryFile(mode="w", prefix=".box-dns-", dir=out_dir) as dns:
        dns.write(content)
        dns.flush()
        yield [*prefix, *cmd, "--ro-bind", dns.name, str(resolver.resolve())]


@contextmanager
def command(argv, env, out_dir=None, *, cwd=None, state=(), places=(), logins=(),
            home_overlay=False, drain=False):
    """Yield spawn arguments; wait for teardown, and with drain for the command's output EOF.

    `state` names a manifest's paths, expanded from the environment; `places` are literal
    directories the command may also write. With an out dir, /run is copied without services
    or /run/user, and temporary and runtime directories are the box's own, empty. Everything
    else is read-only; `home_overlay` gives checks throwaway writes in the account's home and
    HOME without child mounts, beneath the writable places and credential masks.
    """
    clean = {key: value for key, value in env.items() if key not in TOKENS}
    cmd = ["bwrap", "--unshare-user", "--unshare-pid", "--as-pid-1", "--die-with-parent",
           "--new-session"]
    _walls(cmd)
    at = len(cmd)
    if out_dir is not None:
        for path in TRANSIENT:
            if not path.is_dir():
                from . import config
                raise config.Error(f"worker box needs {path}: the host directory is missing")
    writable = _writable(clean, cwd, out_dir, state, places, logins)
    # Mount the real target too: a sandbox HOME often links the account's login.
    targets = set()
    try:
        homes = {path.resolve() for path in _homes(clean, cwd)} if home_overlay else set()
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
    folders = {path for path in targets if path.is_dir()}
    for path in sorted(targets):
        # Inside a hidden folder it is gone already, and no mount point can be made there.
        if any(parent in folders for parent in path.parents):
            continue
        cmd.extend(["--tmpfs", str(path), "--remount-ro", str(path)] if path in folders else
                   ["--dev-bind", "/dev/null", str(path)])
    if out_dir is None:
        cmd[at:at] = _bind({}, writable, homes)
        with _network(cmd, clean) as connected:
            yield [*connected, "--", *argv], clean, {}
        return
    report = Path(out_dir).resolve() / PROCESSES
    report.unlink(missing_ok=True)
    # PID 1 records children before exiting; its exit makes the kernel kill
    # every descendant, even one with a new session or an empty environment.
    argv = [sys.executable, "-I", "-c", SUPERVISOR, str(report),
            *(["--drain"] if drain else []), *argv]
    target = None
    lock = threading.Lock()

    def namespace():
        nonlocal target
        with lock:
            if target is None:
                info.seek(0)
                target = _pidfd(info.read())
        return target

    def stop(proc, grace):
        target = namespace()
        deadline = time.monotonic() + grace
        if target is not None:
            fd, pid = target
            # The witness precedes exec. PID 1 ignores TERM until the supervisor
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
        elif proc.poll() is None:
            # Before bwrap publishes its witness, pasta's TERM handler destroys
            # its nascent namespace. KILL would leave that child waiting for it.
            proc.terminate()
        try:
            proc.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()

    with tempfile.TemporaryDirectory(prefix=".box-", dir=Path(out_dir).resolve()) as scratch, \
            tempfile.NamedTemporaryFile(mode="r+", prefix=".box-pid-") as info:
        try:
            # Short aliases allow Unix sockets even when out has a long run id.
            cmd[at:at] = _bind(_own(scratch, clean, cwd, writable, targets), writable, homes)
            clean["TMPDIR"] = "/var/tmp"
            with _network(cmd, clean, out_dir, info.name) as connected:
                yield [*connected, "--info-fd", "3", "--", *argv], clean, {"stop": stop}
        finally:
            target = namespace()
            if target is not None:
                _wait(target[0])


def _pidfd(info):
    # A killed bwrap can exit before its PID 1 finishes killing descendants.
    # Its private witness names that process; a pidfd waits for the kernel's
    # teardown, not an environment sweep or a delay guessed to be long enough.
    try:
        info = json.loads(info)
        pid = info["child-pid"]
        # Pasta also makes a PID namespace, so bwrap's child number may be local
        # to it. Find PID 1 by the namespace inode before opening its host pidfd.
        for entry in [Path(f"/proc/{pid}"), *Path("/proc").iterdir()]:
            if not entry.name.isdigit():
                continue
            try:
                if (entry / "ns/pid").stat().st_ino != info["pid-namespace"]:
                    continue
                status = (entry / "status").read_text().splitlines()
                if next(line.split()[-1] for line in status if line.startswith("NSpid:")) == "1":
                    pid = int(entry.name)
                    break
            except (FileNotFoundError, PermissionError):
                continue
        else:
            return
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
    if not shutil.which("pasta"):
        raise config.Error("worker box needs pasta; run `sudo apt-get install -y passt`")
    try:
        # The nested probe needs only loopback, like an offline check.
        inner = ["bwrap", "--unshare-user", "--unshare-pid", "--unshare-net",
                 "--ro-bind", "/", "/", "--", "true"]
        with command(inner, os.environ) as (outer, env, _):
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
                       "the host must allow nested unprivileged user, network and PID namespaces")


def _report(out_dir):
    try:
        return json.loads((Path(out_dir) / PROCESSES).read_text())
    except (OSError, ValueError):
        return {}


def launch_error(out_dir, env):
    """Name missing overlay support only when a plain box starts and an isolated overlay fails."""
    message = "check box cannot start"
    probe = ["bwrap", "--unshare-user", "--unshare-pid", "--ro-bind", "/", "/"]
    noop = ["--", sys.executable, "-I", "-c", "pass"]
    try:
        plain = subprocess.run([*probe, *noop], env=env, capture_output=True,
                               text=True, timeout=10)
        if plain.returncode == 0:
            with tempfile.TemporaryDirectory(dir=out_dir) as home:
                overlay = subprocess.run([*probe, "--overlay-src", home, "--tmp-overlay", home,
                                          *noop], env=env, capture_output=True,
                                         text=True, timeout=10)
            if overlay.returncode != 0:
                message += f": HOME overlays unavailable: {overlay.stderr.strip()}; {OVERLAY_REMEDY}"
    except (OSError, subprocess.SubprocessError):
        # The launcher's own diagnostic already names an ordinary mount or namespace failure.
        pass
    return f"\n{message}\n"


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
