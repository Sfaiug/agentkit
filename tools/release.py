#!/usr/bin/env python3
"""ak's release kit: put the newest commit ak tested live on this host, and the previous
release back by itself when the new one fails its health check.

A project copies this file to deploy/release.py and runs it from a root systemd timer:

    release.py ROOT          one tick for the project installed at ROOT
    release.py ROOT --adopt  make ROOT/repo's checked-out commit the first release

One tick fetches main and takes the newest first-parent commit after the live release that
carries ak's `Suite-Passed-Tree:` stamp for its own tree, never reaching past a commit that
failed here: a failed release waits for a newer one. It builds that commit in its own
release directory, with a virtualenv installed fresh from its requirements file (and the
files that file includes) and kept per their hash; runs the install and migrate commands;
switches the `current` link; installs changed unit files; restarts the units; and runs the
health command until it passes or its time is up. A failure before the switch changes
nothing live. Any failure after it switches `current` back, puts the previous unit files
back, stops and removes units only the failed release added, and restarts. Either way the
tick exits 1, so the timer's OnFailure= alert fires. A tick cut off mid-release finishes
the restore on the next tick, which retries a restore that failed until the previous
release is healthy again. Main must keep containing the live release: a rewritten main is
refused until someone releases by hand.

ROOT holds repo/ (a clone of the project), releases/<sha>/, venvs/<hash>/, current ->
releases/<sha>, released ("<sha> <time>", the live release), attempt (a release under way),
failed and tick.lock. Migrations run before the switch, so each must keep the previous
release working: a restore puts the code back, never the schema.

The project's deploy/release.toml, read from the commit being released:

    user = "app"                        # runs every project command (default: root)
    units = ["app.service"]             # restarted after a switch and after a restore
    health = "curl -fsS http://127.0.0.1:8100/healthz"
    health_seconds = 90                 # how long the health command may take to pass
    requirements = "requirements.txt"   # the virtualenv's pip requirements (if the file exists)
    python = "/usr/local/bin/python3.11"
    install = "npm ci && npm run build" # runs in every release, after the virtualenv
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
GIT_SECONDS = 300
COMMAND_SECONDS = 1800
HEALTH_TRY_SECONDS = 20
SYSTEMCTL = os.environ.get("AK_RELEASE_SYSTEMCTL", "systemctl")
UNIT_DIR = Path(os.environ.get("AK_RELEASE_UNIT_DIR", "/etc/systemd/system"))


class Failed(Exception):
    """A tick that must end red, with the line that says why."""


def say(line):
    print(f"[release] {line}", flush=True)


def why(exc):
    return str(exc) if isinstance(exc, Failed) else f"{type(exc).__name__}: {exc}"


def git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=GIT_SECONDS)
    if done.returncode:
        raise Failed(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


def git_ok(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=GIT_SECONDS).returncode == 0


def stamped(repo, sha):
    """Whether `sha` carries ak's one stamp naming its own tree."""
    tree = git(repo, "rev-parse", f"{sha}^{{tree}}")
    values = git(repo, "show", "-s", f"--format=%(trailers:key={STAMP},valueonly)", sha).split()
    return len(values) == 1 and values[0].lower() == tree


def candidate(repo, live, failed):
    """The newest stamped first-parent commit after `live`, never past a failed one."""
    for sha in git(repo, "rev-list", "--first-parent", f"{live}..origin/main").split():
        if sha in failed:
            return None
        if stamped(repo, sha):
            return sha
    return None


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
    except (OSError, KeyError) as exc:
        return 1, why(exc)
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


def requirement_files(path, found=None):
    """`path` and every file it includes with -r or -c, in reading order."""
    found = [] if found is None else found
    if path in found or not path.is_file():
        return found
    found.append(path)
    for line in path.read_text().splitlines():
        line = line.strip()
        for flag in ("--requirement", "--constraint", "-r", "-c"):
            if line.startswith(flag):
                rest = line[len(flag):].lstrip(" =").strip()
                if rest:
                    requirement_files((path.parent / rest).resolve(), found)
                break
    return found


def venv(root, config, release):
    """Link release/.venv to the virtualenv its requirements key, installing it fresh once."""
    requirements = release / config.get("requirements", "requirements.txt")
    files = requirement_files(requirements.resolve())
    if not files:
        return
    python = config.get("python", "python3")
    key = hashlib.sha256(python.encode())
    for path in files:
        key.update(b"\0" + os.path.relpath(path, release.resolve()).encode() + b"\0"
                   + path.read_bytes())
    target = root / "venvs" / key.hexdigest()[:16]
    if not (target / ".complete").is_file():
        shutil.rmtree(target, ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        made = subprocess.run([python, "-m", "venv", str(target)], capture_output=True,
                              text=True, stdin=subprocess.DEVNULL, timeout=GIT_SECONDS)
        if made.returncode:
            raise Failed(f"{python} -m venv failed: {(made.stdout + made.stderr).strip()[-300:]}")
        chown(config, target)
        (release / ".venv").symlink_to(target)
        must(config, release, "pip install",
             f".venv/bin/pip install -q -r {requirements.relative_to(release)}")
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


def prepare(root, sha):
    """Everything a release needs before anything live changes."""
    release = build(root, sha)
    config = load(release)
    chown(config, release)
    venv(root, config, release)
    if config.get("install"):
        must(config, release, "install", config["install"])
    if config.get("migrate"):
        must(config, release, "migrate", config["migrate"])
    return config, release


def unit_names(config, release):
    folder = config.get("unit_files")
    if not folder or not (release / folder).is_dir():
        return {}
    return {unit.name: unit for unit in sorted((release / folder).iterdir())
            if unit.suffix in (".service", ".timer")}


def install_units(config, release):
    """Copy the release's changed unit files into place; True when systemd must reload."""
    changed = False
    for name, unit in unit_names(config, release).items():
        target = UNIT_DIR / name
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


def start(config, release, reload=False):
    """'' once `release`'s units run on its unit files and its health passes, else why not."""
    try:
        if install_units(config, release) or reload:
            systemctl("daemon-reload")
        systemctl("restart", *config["units"])
    except Exception as exc:  # noqa: BLE001 - any host error is a failed start
        return why(exc)
    deadline = time.monotonic() + int(config.get("health_seconds", 90))
    while True:
        code, out = run(config, release, config["health"], HEALTH_TRY_SECONDS)
        if code == 0:
            return ""
        if time.monotonic() >= deadline:
            return f"health failed (exit {code}): `{config['health']}`: {out[-300:]}"
        time.sleep(2)


def restore(root, sha, previous):
    """Put `previous` back live in place of `sha`; '' once it is healthy, else why not."""
    try:
        switch(root, previous)
        back = root / "releases" / previous
        before = load(back)
        failed = root / "releases" / sha
        try:
            added = set(unit_names(load(failed), failed)) - set(unit_names(before, back))
        except Failed:
            added = set()
        for name in sorted(added):
            subprocess.run([SYSTEMCTL, "disable", "--now", name], capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=GIT_SECONDS)
            (UNIT_DIR / name).unlink(missing_ok=True)
        return start(before, back, reload=bool(added))
    except Exception as exc:  # noqa: BLE001 - the next tick tries again
        return why(exc)


def write(path, text):
    fresh = path.with_name(path.name + ".new")
    fresh.write_text(text)
    fresh.replace(path)


def read_words(path):
    try:
        return path.read_text().split()
    except OSError:
        return []


def live(root):
    words = read_words(root / "released")
    return words[0] if words else None


def finish_attempt(root, sha, previous, failure):
    """A release that did not become live: restore `previous`, then remember `sha` failed."""
    if live(root) == sha:
        (root / "attempt").unlink(missing_ok=True)      # it had finished before a cut-off
        return 0
    problem = restore(root, sha, previous)
    if problem:
        raise Failed(f"{sha[:12]} failed ({failure}); restoring {previous[:12]} failed too, "
                     f"the next tick tries again: {problem}")
    failed = set(read_words(root / "failed")) | {sha}
    write(root / "failed", "\n".join(sorted(failed)) + "\n")
    (root / "attempt").unlink(missing_ok=True)
    raise Failed(f"{sha[:12]} failed and {previous[:12]} is back live: {failure}")


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
    pending = read_words(root / "attempt")
    if len(pending) == 2:
        return finish_attempt(root, *pending, "the tick releasing it was cut off")
    repo = root / "repo"
    previous = live(root)
    if previous is None:
        raise Failed(f"no live release is recorded in {root}: run `release.py {root} --adopt`")
    git(repo, "fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main")
    if not git_ok(repo, "merge-base", "--is-ancestor", previous, "origin/main"):
        raise Failed(f"main no longer contains the live release {previous[:12]}: it was "
                     "rewritten, so release by hand")
    failed = set(read_words(root / "failed"))
    sha = candidate(repo, previous, failed)
    if sha is None:
        return 0
    say(f"releasing {sha[:12]} over {previous[:12]}")
    try:
        config, release = prepare(root, sha)
    except Exception as exc:  # noqa: BLE001 - nothing live changed yet
        write(root / "failed", "\n".join(sorted(failed | {sha})) + "\n")
        raise Failed(f"{sha[:12]} not released, nothing live changed: {why(exc)}") from exc
    write(root / "attempt", f"{sha} {previous}\n")
    try:
        switch(root, sha)
        failure = start(config, release)
    except Exception as exc:  # noqa: BLE001 - the switch itself failed
        failure = why(exc)
    if failure:
        return finish_attempt(root, sha, previous, failure)
    write(root / "released", f"{sha} {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")
    (root / "attempt").unlink(missing_ok=True)
    try:
        prune(root, int(config.get("keep", 5)), sha, previous)
    except OSError as exc:
        say(f"live: {sha[:12]}; pruning old releases failed: {exc}")
        return 0
    say(f"live: {sha[:12]}")
    return 0


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
