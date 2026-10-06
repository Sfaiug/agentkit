#!/usr/bin/env python3
"""ak's release kit: put the newest commit ak tested live on this host, and the previous
release back by itself when the new one fails its health check.

A project copies this file to deploy/release.py and runs it from a root systemd timer:

    release.py ROOT          one tick for the project installed at ROOT
    release.py ROOT --adopt  make ROOT/repo's checked-out commit the first release

One tick fetches main and takes the newest first-parent commit that descends from the live
release, carries ak's `Suite-Passed-Tree:` stamp for its own tree, and is no ancestor of a
commit that failed here: a failed release waits for a newer one. It builds that commit in its
own release directory with its own fresh virtualenv, runs the install and migrate commands,
switches the `current` link, makes the installed unit files exactly the release's, restarts
the units, and runs the health command until it passes or its time is up. A failure before
the switch changes nothing live. Any failure after it puts the previous release back: the
link, its unit files (units only the failed release brought are stopped and removed), its
units restarted, its health passed. Either way the tick exits 1, so the timer's OnFailure=
alert fires. A restore that fails, or a tick cut off mid-release, is finished by the next
tick. Main must keep containing the live release: a rewritten main is refused until someone
releases by hand.

ROOT holds repo/ (a clone of the project), releases/<sha>/, current -> releases/<sha>,
released ("<sha> <time>", the live release), previous (the release before it, kept for a
restore), attempt (a release under way), units (the unit files this kit installed) and
tick.lock; repo/ keeps a ref per failed commit under refs/release/failed/. Migrations run before the switch, so each
must keep the previous release working: a restore puts the code back, never the schema.

The project's deploy/release.toml, read from the commit being released:

    user = "app"                        # runs every project command (default: root)
    units = ["app.service"]             # restarted after a switch and after a restore
    health = "curl -fsS http://127.0.0.1:8100/healthz"
    health_seconds = 90                 # how long the health command may take to pass
    requirements = "requirements.txt"   # installed into the release's own .venv, if present
    python = "/usr/local/bin/python3.11"
    install = "npm ci && npm run build" # runs in every release, after the virtualenv
    migrate = ".venv/bin/python -m scripts.migrate"
    env_file = "/etc/app/app.env"       # KEY=VALUE lines for every project command
    unit_files = "deploy/systemd"       # *.service and *.timer, kept exactly as the release's
    keep = 5                            # release directories kept besides live and previous

Commands run from the release directory with `bash -c`, each in its own process group.
Python 3.11 standard library.
"""

import fcntl
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import sys
import tempfile
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


FAILED = "refs/release/failed/"     # a ref per failed commit keeps it, and its history, from gc


def failed_commits(repo):
    return git(repo, "for-each-ref", "--format=%(objectname)", FAILED).split()


def candidate(repo, live):
    """The newest stamped first-parent commit on main that descends from `live` and is no
    ancestor of a commit that failed here (a rewrite cannot reopen an older release)."""
    failed = failed_commits(repo)
    for sha in git(repo, "rev-list", "--first-parent", f"{live}..origin/main").split():
        if any(git_ok(repo, "merge-base", "--is-ancestor", sha, bad) for bad in failed):
            return None
        if git_ok(repo, "merge-base", "--is-ancestor", live, sha) and stamped(repo, sha):
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


def run(config, release, argv, seconds=COMMAND_SECONDS):
    """A project command in `release` as the project's user, in its own process group, all
    of which ends the moment the command does; its exit code and output."""
    user = config.get("user")
    if user and user != pwd.getpwuid(os.getuid()).pw_name:
        argv = ["runuser", "-u", user, "--", *argv]
    with tempfile.TemporaryFile() as out:
        try:
            child = subprocess.Popen(argv, cwd=release, env=environment(config), stdout=out,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     start_new_session=True)
        except (OSError, KeyError) as exc:
            return 1, why(exc)
        try:
            code = child.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            code = 124
        try:
            os.killpg(child.pid, signal.SIGKILL)   # whatever it left behind ends too
        except ProcessLookupError:
            pass
        child.wait()
        out.seek(0)
        text = out.read().decode("utf-8", "replace").strip()
    return code, f"killed after {seconds}s\n{text}" if code == 124 else text


def must(config, release, what, argv):
    code, out = run(config, release, argv)
    if code:
        tail = "\n".join(out.splitlines()[-20:])
        raise Failed(f"{what} failed (exit {code}): `{' '.join(argv)}`\n{tail}")


def chown(config, path):
    user = config.get("user")
    if user and os.getuid() == 0:
        subprocess.run(["chown", "-R", f"{user}:", str(path)], check=True, timeout=GIT_SECONDS)


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


def prepare(root, sha, migrate=True):
    """Everything a release needs before anything live changes: the checkout, its own
    virtualenv installed fresh from its requirements, its install and migrate commands."""
    release = build(root, sha)
    config = load(release)
    chown(config, release)
    requirements = config.get("requirements", "requirements.txt")
    if (release / requirements).is_file():
        python = config.get("python", "python3")
        must(config, release, "virtualenv", [python, "-m", "venv", ".venv"])
        must(config, release, "pip install",
             [".venv/bin/pip", "install", "-q", "-r", requirements])
    if config.get("install"):
        must(config, release, "install", ["bash", "-c", config["install"]])
    if migrate and config.get("migrate"):
        must(config, release, "migrate", ["bash", "-c", config["migrate"]])
    return config, release


def unit_files(config, release):
    folder = config.get("unit_files")
    if not folder or not (release / folder).is_dir():
        return {}
    return {unit.name: unit for unit in sorted((release / folder).iterdir())
            if unit.suffix in (".service", ".timer") and unit.is_file()}


def systemctl(*args):
    done = subprocess.run([SYSTEMCTL, *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=GIT_SECONDS)
    if done.returncode:
        raise Failed(f"systemctl {' '.join(args)}: {(done.stdout + done.stderr).strip()}")


def place_units(root, config, release):
    """Make the unit files this kit installed exactly `release`'s, then reload systemd.

    Each file is replaced as a whole, so a link in its place is replaced, never written
    through; one this kit installed that `release` lacks is stopped and removed.
    """
    wanted = unit_files(config, release)
    owned = set(read_words(root / "units"))
    # Own every name before placing any, so a placement cut short is still undone.
    write(root / "units", "".join(f"{name}\n" for name in sorted(owned | set(wanted))))
    for name, unit in wanted.items():
        fresh = UNIT_DIR / f".{name}.release"
        shutil.copyfile(unit, fresh)
        fresh.chmod(0o644)
        fresh.replace(UNIT_DIR / name)
    for name in sorted(owned - set(wanted)):
        systemctl("disable", "--now", name)
        (UNIT_DIR / name).unlink(missing_ok=True)
    write(root / "units", "".join(f"{name}\n" for name in sorted(wanted)))
    systemctl("daemon-reload")


def start(root, config, release, before=None):
    """`release`'s units on its unit files, restarted, then its health until it passes; units
    only `before` named (a config with no file behind them here) are stopped first."""
    place_units(root, config, release)
    for name in sorted(set((before or {}).get("units", ())) - set(config["units"])
                       - set(unit_files(config, release))):
        systemctl("stop", name)
    systemctl("restart", *config["units"])
    deadline = time.monotonic() + int(config.get("health_seconds", 90))
    while True:
        code, out = run(config, release, ["bash", "-c", config["health"]], HEALTH_TRY_SECONDS)
        if code == 0:
            return
        if time.monotonic() >= deadline:
            raise Failed(f"health failed (exit {code}): `{config['health']}`: {out[-300:]}")
        time.sleep(2)


def switch(root, sha):
    link = root / "current.new"
    link.unlink(missing_ok=True)
    link.symlink_to(Path("releases") / sha)
    link.replace(root / "current")


def restore(root, sha, previous):
    """Put `previous` back live in place of `sha`; '' once it is healthy, else why not."""
    try:
        switch(root, previous)
        back = root / "releases" / previous
        try:
            failed = load(root / "releases" / sha)
        except Failed:
            failed = None
        start(root, load(back), back, before=failed)
        return ""
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


def remember_failed(root, sha):
    git(root / "repo", "update-ref", FAILED + sha, sha)


def finish_attempt(root, sha, previous, failure):
    """A release that did not become live: restore `previous`, then remember `sha` failed."""
    if live(root) == sha:
        (root / "attempt").unlink(missing_ok=True)      # it had finished before a cut-off
        return 0
    problem = restore(root, sha, previous)
    if problem:
        raise Failed(f"{sha[:12]} failed ({failure}); restoring {previous[:12]} failed too, "
                     f"the next tick tries again: {problem}")
    remember_failed(root, sha)
    (root / "attempt").unlink(missing_ok=True)
    prune(root)
    raise Failed(f"{sha[:12]} failed and {previous[:12]} is back live: {failure}")


def prune(root):
    """Keep the newest release directories, never the live, previous or attempted one."""
    held = set(read_words(root / "attempt")) | set(read_words(root / "previous")) | {live(root)}
    try:
        keep = int(load(root / "current").get("keep", 5))
    except Failed:
        keep = 5
    releases = sorted((p for p in (root / "releases").iterdir() if p.is_dir()),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    for release in releases[keep:]:
        if release.name not in held:
            git_ok(root / "repo", "worktree", "remove", "--force", str(release))
            shutil.rmtree(release, ignore_errors=True)


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
    sha = candidate(repo, previous)
    if sha is None:
        return 0
    say(f"releasing {sha[:12]} over {previous[:12]}")
    try:
        config, release = prepare(root, sha)
    except Exception as exc:  # noqa: BLE001 - nothing live changed yet
        remember_failed(root, sha)
        prune(root)
        raise Failed(f"{sha[:12]} not released, nothing live changed: {why(exc)}") from exc
    write(root / "attempt", f"{sha} {previous}\n")
    try:
        switch(root, sha)
        start(root, config, release, before=load(root / "releases" / previous))
        write(root / "previous", f"{previous}\n")
        write(root / "released", f"{sha} {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")
    except Exception as exc:  # noqa: BLE001 - any failure after the switch restores
        return finish_attempt(root, sha, previous, why(exc))
    (root / "attempt").unlink(missing_ok=True)
    prune(root)
    say(f"live: {sha[:12]}")
    return 0


def adopt(root):
    """Make repo/'s checked-out commit the first release, built as any release is, without
    migrating or restarting anything."""
    if live(root):
        raise Failed(f"{root} is adopted already: {live(root)[:12]} is live")
    sha = git(root / "repo", "rev-parse", "HEAD")
    config, release = prepare(root, sha, migrate=False)
    switch(root, sha)
    write(root / "units", "".join(f"{name}\n" for name in unit_files(config, release)))
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
