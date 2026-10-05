#!/usr/bin/env python3
"""ak's release kit: put the newest commit ak tested live on this host, and the previous
release back by itself when the new one fails its health check.

A project copies this file to deploy/release.py and runs it from a root systemd timer:

    release.py ROOT          one tick for the project installed at ROOT
    release.py ROOT --adopt  make ROOT/repo's checked-out commit the first release

One tick fetches main and takes the newest first-parent commit that carries ak's
`Suite-Passed-Tree:` stamp for its own tree, is newer than the live release and has not
failed here. It builds that commit in its own release directory, with a virtualenv built
fresh from the requirements file and kept per its hash; migrates; installs changed unit
files; switches the `current` link; restarts the units; and runs the health command until
it passes or its time is up. A failure before the switch changes nothing live. A failure
after it switches `current` back, restores the previous unit files, restarts, and keeps the
commit in `failed`, so the next tick waits for a newer one.  Either way the tick exits 1,
so the timer's OnFailure= alert fires.

ROOT holds repo/ (a clone of the project on main), releases/<sha>/, venvs/<hash>/,
current -> releases/<sha>, released ("<sha> <time>", the live release), failed and
tick.lock.  Migrations run before the switch, so each must keep the previous release
working: a restore puts the code back, never the schema.

The project's deploy/release.toml, read from the commit being released:

    user = "app"                        # runs every project command (default: root)
    units = ["app.service"]             # restarted after a switch and after a restore
    health = "curl -fsS http://127.0.0.1:8100/healthz"
    health_seconds = 90                 # how long the health command may take to pass
    install = ".venv/bin/pip install -q -r requirements.txt"
    requirements = "requirements.txt"   # the file whose hash keys the virtualenv
    python = "/usr/local/bin/python3.11"
    migrate = ".venv/bin/python -m scripts.migrate"
    env_file = "/etc/app/app.env"       # KEY=VALUE lines for every project command
    unit_files = "deploy/systemd"       # *.service and *.timer installed when changed
    keep = 5                            # release directories kept

Commands run from the release directory with `bash -c`.  Python 3.11 standard library.
"""

import fcntl
import hashlib
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import time
import tomllib

STAMP = "Suite-Passed-Tree"
CONFIG = "deploy/release.toml"
WALK = 500          # first-parent commits searched for a stamp before giving up
GIT_SECONDS = 300
COMMAND_SECONDS = 1800
HEALTH_TRY_SECONDS = 20
SYSTEMCTL = os.environ.get("AK_RELEASE_SYSTEMCTL", "systemctl")
UNIT_DIR = Path(os.environ.get("AK_RELEASE_UNIT_DIR", "/etc/systemd/system"))


class Failed(Exception):
    """A tick that must end red, with the line that says why."""


def say(line):
    print(f"[release] {line}", flush=True)


def git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=GIT_SECONDS)
    if done.returncode:
        raise Failed(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


def stamped(repo, sha):
    """Whether `sha` carries ak's one stamp naming its own tree."""
    tree = git(repo, "rev-parse", f"{sha}^{{tree}}")
    values = git(repo, "show", "-s", f"--format=%(trailers:key={STAMP},valueonly)", sha).split()
    return len(values) == 1 and values[0].lower() == tree


def candidate(repo, live, failed):
    """The newest stamped first-parent commit on main newer than `live`, else None."""
    for sha in git(repo, "rev-list", "--first-parent", f"--max-count={WALK}",
                   "origin/main").split():
        if sha == live:
            return None
        if live and git_ok(repo, "merge-base", "--is-ancestor", sha, live):
            return None     # never release backward, also after main was rewritten
        if sha not in failed and stamped(repo, sha):
            return sha
    return None


def git_ok(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=GIT_SECONDS).returncode == 0


def load(release):
    try:
        with (release / CONFIG).open("rb") as fh:
            config = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise Failed(f"{CONFIG} unreadable: {exc}") from exc
    if not isinstance(config.get("units"), list) or not config.get("health"):
        raise Failed(f"{CONFIG} must name `units` and a `health` command")
    return config


def environment(config):
    user = config.get("user") or pwd.getpwuid(os.getuid()).pw_name
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
           "HOME": pwd.getpwnam(user).pw_dir}
    path = config.get("env_file")
    if path:
        for line in Path(path).read_text().splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name and not name.startswith("#"):
                env[name.removeprefix("export ").strip()] = value.strip().strip("'\"")
    return env


def run(config, release, command, seconds=COMMAND_SECONDS):
    """A project command in `release` as the project's user; its exit code and output."""
    argv = ["bash", "-c", command]
    user = config.get("user")
    if user and user != pwd.getpwuid(os.getuid()).pw_name:
        argv = ["runuser", "-u", user, "--", *argv]
    try:
        done = subprocess.run(argv, cwd=release, env=environment(config), capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, timeout=seconds)
    except subprocess.TimeoutExpired:
        return 124, f"killed after {seconds}s"
    return done.returncode, (done.stdout + done.stderr).strip()


def must(config, release, what, command):
    code, out = run(config, release, command)
    if code:
        tail = "\n".join(out.splitlines()[-20:])
        raise Failed(f"{what} failed (exit {code}): `{command}`\n{tail}")


def chown(config, path):
    user = config.get("user")
    if user and os.getuid() == 0:
        subprocess.run(["chown", "-R", f"{user}:", str(path)], check=True, timeout=GIT_SECONDS)


def venv(root, config, release):
    """Link release/.venv to the virtualenv its requirements file keys, building it fresh."""
    requirements = release / config.get("requirements", "requirements.txt")
    if not requirements.is_file():
        return
    python = config.get("python", "python3")
    key = hashlib.sha256(python.encode() + b"\0" + requirements.read_bytes()).hexdigest()[:16]
    target = root / "venvs" / key
    if not (target / ".complete").is_file():
        shutil.rmtree(target, ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        made = subprocess.run([python, "-m", "venv", str(target)], capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, timeout=GIT_SECONDS)
        if made.returncode:
            raise Failed(f"{python} -m venv failed: {(made.stdout + made.stderr).strip()[-300:]}")
        chown(config, target)
        (release / ".venv").symlink_to(target)
        must(config, release, "install", config.get("install", ""))
        (target / ".complete").write_text(f"{time.time()}\n")
    elif not (release / ".venv").exists():
        (release / ".venv").symlink_to(target)


def build(root, sha):
    """releases/<sha>, checked out fresh from repo/."""
    release = root / "releases" / sha
    if release.exists():
        git_ok(root / "repo", "worktree", "remove", "--force", str(release))
        shutil.rmtree(release, ignore_errors=True)
    git(root / "repo", "worktree", "prune")
    release.parent.mkdir(parents=True, exist_ok=True)
    git(root / "repo", "worktree", "add", "--detach", "--force", str(release), sha)
    return release


def install_units(config, release):
    """Copy the release's changed unit files into place; True when systemd must reload."""
    folder = config.get("unit_files")
    if not folder:
        return False
    changed = False
    for unit in sorted((release / folder).glob("*")):
        if unit.suffix not in (".service", ".timer"):
            continue
        target = UNIT_DIR / unit.name
        if not target.is_file() or target.read_bytes() != unit.read_bytes():
            shutil.copyfile(unit, target)
            target.chmod(0o644)
            changed = True
    return changed


def systemctl(*args):
    done = subprocess.run([SYSTEMCTL, *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=GIT_SECONDS)
    if done.returncode:
        raise Failed(f"systemctl {' '.join(args)}: {(done.stdout + done.stderr).strip()}")


def switch(root, sha):
    link = root / "current.new"
    link.unlink(missing_ok=True)
    link.symlink_to(Path("releases") / sha)
    link.replace(root / "current")


def start(config, release):
    """Units on `release`'s files, restarted, then its health command until it passes."""
    if install_units(config, release):
        systemctl("daemon-reload")
    systemctl("restart", *config["units"])
    deadline = time.monotonic() + int(config.get("health_seconds", 90))
    while True:
        code, out = run(config, release, config["health"], HEALTH_TRY_SECONDS)
        if code == 0:
            return ""
        if time.monotonic() >= deadline:
            return f"health failed (exit {code}): `{config['health']}`: {out[-300:]}"
        time.sleep(2)


def write(path, text):
    fresh = path.with_name(path.name + ".new")
    fresh.write_text(text)
    fresh.replace(path)


def live(root):
    try:
        return (root / "released").read_text().split()[0]
    except (OSError, IndexError):
        return None


def prune(root, keep, *held):
    releases = sorted((p for p in (root / "releases").iterdir() if p.is_dir()),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    for release in releases[keep:]:
        if release.name not in held:
            git_ok(root / "repo", "worktree", "remove", "--force", str(release))
            shutil.rmtree(release, ignore_errors=True)
    used = {os.path.realpath(p / ".venv") for p in (root / "releases").iterdir()
            if (p / ".venv").is_symlink()}
    for folder in (root / "venvs").glob("*"):
        if str(folder.resolve()) not in used:
            shutil.rmtree(folder, ignore_errors=True)


def tick(root):
    repo = root / "repo"
    git(repo, "fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main")
    previous = live(root)
    failed = set((root / "failed").read_text().split()) if (root / "failed").is_file() else set()
    sha = candidate(repo, previous, failed)
    if sha is None:
        return 0
    say(f"releasing {sha[:12]} over {previous[:12] if previous else 'nothing'}")
    release = build(root, sha)
    try:
        config = load(release)
        chown(config, release)
        venv(root, config, release)
        if config.get("migrate"):
            must(config, release, "migrate", config["migrate"])
    except Failed as exc:
        write(root / "failed", "\n".join(sorted(failed | {sha})) + "\n")
        raise Failed(f"{sha[:12]} not released, nothing live changed: {exc}") from exc
    switch(root, sha)
    try:
        failure = start(config, release)
    except Failed as exc:
        failure = str(exc)
    if not failure:
        write(root / "released", f"{sha} {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")
        prune(root, int(config.get("keep", 5)), sha, previous or "")
        say(f"live: {sha[:12]}")
        return 0
    write(root / "failed", "\n".join(sorted(failed | {sha})) + "\n")
    if not previous:
        raise Failed(f"{sha[:12]} failed and there is no earlier release to restore: {failure}")
    back = root / "releases" / previous
    switch(root, previous)
    restored = start(load(back), back)
    if restored:
        raise Failed(f"{sha[:12]} failed ({failure}); restoring {previous[:12]} failed too: {restored}")
    raise Failed(f"{sha[:12]} failed and {previous[:12]} is back live: {failure}")


def adopt(root):
    """Make repo/'s checked-out commit the first release, without restarting anything."""
    sha = git(root / "repo", "rev-parse", "HEAD")
    release = build(root, sha)
    config = load(release)
    chown(config, release)
    venv(root, config, release)
    switch(root, sha)
    write(root / "released", f"{sha} {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")
    say(f"adopted {sha[:12]}; point the units at {root / 'current'}")
    return 0


def main(argv):
    if len(argv) not in (2, 3) or (len(argv) == 3 and argv[2] != "--adopt"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    root = Path(argv[1]).resolve()
    with (root / "tick.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            return adopt(root) if len(argv) == 3 else tick(root)
        except Failed as exc:
            say(str(exc))
            return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
