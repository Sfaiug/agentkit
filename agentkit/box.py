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
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from string import Template

TOKENS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
PROCESSES = "box-processes.json"


def _links(root):
    """Every link reachable from root, through linked directories too, each directory once."""
    found, seen, pending = [], set(), [Path(root)]
    while pending:
        directory = pending.pop()
        if directory.resolve() in seen:
            continue
        seen.add(directory.resolve())
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                found.append(Path(entry.path))
            if entry.is_dir():
                pending.append(Path(entry.path))
    return found


def _credentials(env, cwd):
    homes = {Path(env.get("HOME") or Path.home()), Path(pwd.getpwuid(os.getuid()).pw_dir)}
    configs = {home / ".config" for home in homes}
    if env.get("XDG_CONFIG_HOME"):
        configs.add(Path(env["XDG_CONFIG_HOME"]))
    gh = {root / "gh" for root in configs}
    if env.get("GH_CONFIG_DIR"):
        gh.add(Path(env["GH_CONFIG_DIR"]))
    caches = {home / ".cache" for home in homes}
    if env.get("XDG_CACHE_HOME"):
        caches.add(Path(env["XDG_CACHE_HOME"]))
    directories = {home / ".git-credential-cache" for home in homes}
    directories.update(root / "git/credential" for root in caches)
    files = {home / ".git-credentials" for home in homes}
    files.update(root / "git/credentials" for root in configs)
    files.update(root / "hosts.yml" for root in gh)
    # A worker reaches no server: only the orchestrator's own shell holds SSH keys and agent.
    for ssh in (home / ".ssh" for home in homes):
        directories.add(ssh)
        # A key linked in from elsewhere stays readable at its target unless that is hidden too.
        for link in _links(ssh):
            (directories if link.is_dir() else files).add(link)
    if env.get("SSH_AUTH_SOCK"):
        files.add(Path(env["SSH_AUTH_SOCK"]))
    # A named credential store is just as readable as the default one. Ask Git so
    # includes and repository-local settings use its own precedence and quoting.
    result = subprocess.run(["git", "config", "--get-regexp", r"^credential(\..*)?\.helper$"],
                            cwd=cwd, env={**env, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"},
                            capture_output=True, text=True, timeout=10)
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
                files.add(path if path.is_absolute() else Path(cwd or os.getcwd()) / path)
    return directories, files


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


@contextmanager
def command(argv, env, out_dir=None, *, cwd=None, state=(), places=(), logins=()):
    """Yield (command, environment, spawn options); wait for teardown on every exit.

    `state` names a manifest's paths, expanded from the environment; `places` are literal
    directories the command may also write.
    """
    clean = {key: value for key, value in env.items() if key not in TOKENS}
    cmd = ["bwrap", "--unshare-user", "--unshare-pid", "--as-pid-1", "--die-with-parent",
           "--new-session", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"]
    # A read-only bind disables devices too. Restore the nodes, leaving their
    # directories read-only so ordinary files cannot fill the host's /dev tmpfs.
    for device in Path("/dev").rglob("*"):
        # The turn gets disk-backed shm below; do not bind the host's transient files.
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
    scratch_at = len(cmd)
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
            git_env.update(GIT_TERMINAL_PROMPT="0", GH_PROMPT_DISABLED="1")
            result = subprocess.run(["git", "rev-parse", "--absolute-git-dir", "--git-common-dir"],
                                    cwd=workspace, env=git_env, capture_output=True, text=True,
                                    check=True, timeout=10)
            writable.update((workspace / path).resolve() for path in result.stdout.splitlines())
    if out_dir is not None:
        output = Path(out_dir).resolve()
        writable.add(output)
    for path in sorted(writable):
        # A redundant file mount prevents atomic refresh within its writable parent.
        if any(parent in writable for parent in path.parents):
            continue
        cmd.extend(["--bind", str(path), str(path)])
    directories, files = _credentials(clean, cwd)
    hidden = {path.resolve() for path in directories if path.exists()}
    for paths, option in ((directories, "--tmpfs"), (files, "--dev-bind")):
        # Mount the real target too: a sandbox HOME often links the account's login.
        targets = {path.resolve() for path in paths if path.exists()}
        for path in sorted(targets):
            # Inside a hidden directory it is gone already, and no mount point can be made there.
            if any(parent in hidden for parent in path.parents):
                continue
            cmd.extend([option, str(path), "--remount-ro", str(path)] if option == "--tmpfs" else
                       [option, "/dev/null", str(path)])
    if out_dir is None:
        yield [*cmd, "--", *argv], clean, {}
        return
    report = Path(out_dir).resolve() / PROCESSES
    report.unlink(missing_ok=True)
    # PID 1 records children before exiting; its exit makes the kernel kill
    # every descendant, even one with a new session or an empty environment.
    argv = [sys.executable, str(Path(__file__).resolve()), str(report), *argv]
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

    with tempfile.TemporaryDirectory(prefix=".box-", dir=output) as scratch:
        mounts = []
        for name, destination in (("tmp", "/var/tmp"), ("shm", "/dev/shm")):
            source = Path(scratch) / name
            source.mkdir()
            mounts.extend(["--bind", str(source), destination])
        # Short aliases allow Unix sockets even when out has a long run id. Bind
        # these first so a workspace or declared state under /var/tmp still wins.
        cmd[scratch_at:scratch_at] = mounts
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


def _supervise(report, argv):
    proc = subprocess.Popen(argv, start_new_session=True)

    def term(signum, _frame):
        # Outer bwrap cannot forward TERM; leave it alive while the harness saves
        # its session. The kernel still ends detached descendants with PID 1.
        try:
            os.killpg(proc.pid, signum)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, term)
    # PID 1 also inherits orphans. Reap them while waiting for the adapter, so a
    # long turn cannot accumulate zombies from double-forked commands.
    while True:
        pid, status = os.waitpid(-1, 0)
        if pid == proc.pid:
            code = proc.returncode = os.waitstatus_to_exitcode(status)
            break
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
    sys.exit(_supervise(sys.argv[1], sys.argv[2:]))
