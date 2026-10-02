"""The worker's filesystem and process walls, built in one place."""

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
from contextlib import contextmanager
from string import Template

TOKENS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
PROCESSES = "box-processes.json"


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
    # A named credential store is just as readable as the default one. Ask Git so
    # includes and repository-local settings use its own precedence and quoting.
    result = subprocess.run(["git", "config", "--get-regexp", r"^credential(\..*)?\.helper$"],
                            cwd=cwd, env=env, capture_output=True, text=True, timeout=10)
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


@contextmanager
def command(argv, env, out_dir=None, *, cwd=None):
    """Yield (command, environment, spawn options); wait for teardown on every exit."""
    clean = {key: value for key, value in env.items() if key not in TOKENS}
    cmd = ["bwrap", "--unshare-user", "--unshare-pid", "--as-pid-1", "--die-with-parent",
           "--new-session", "--bind", "/", "/", "--dev-bind", "/dev", "/dev", "--proc", "/proc"]
    directories, files = _credentials(clean, cwd)
    for paths, option in ((directories, "--tmpfs"), (files, "--dev-bind")):
        # Mount the real target too: a sandbox HOME often links the account's login.
        targets = {path.resolve() for path in paths if path.exists()}
        for path in sorted(targets):
            cmd.extend([option, str(path)] if option == "--tmpfs" else
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
    try:
        yield [*cmd, "--info-fd", str(write), "--", *argv], clean, {"pass_fds": (write,)}
    finally:
        os.close(write)
        with os.fdopen(read) as info:
            _wait(info.read())


def _wait(info):
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
        if same:
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


def leftovers(out_dir):
    """Processes recorded inside this turn's PID namespace, before it was destroyed."""
    try:
        return json.loads((Path(out_dir) / PROCESSES).read_text())
    except (OSError, ValueError):
        return []


def _supervise(report, argv):
    proc = subprocess.Popen(argv)
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
    Path(report).write_text(json.dumps(left))
    return 128 - code if code < 0 else code


if __name__ == "__main__":
    sys.exit(_supervise(sys.argv[1], sys.argv[2:]))
