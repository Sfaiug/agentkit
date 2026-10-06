#!/usr/bin/env python3
"""ak's release kit: put the newest commit ak tested live on this host, and the previous
release back by itself when the new one fails its health check.

A project copies this file to deploy/release.py and runs it from a root systemd timer:

    release.py ROOT          one tick for the project installed at ROOT
    release.py ROOT --adopt  make ROOT/repo's checked-out commit the first release

One tick fetches main and takes the newest first-parent commit that descends from the live
release, carries ak's `Suite-Passed-Tree:` stamp for its own tree, and is no ancestor of a
commit that failed after its switch here: a failed release waits for a newer one. It builds that commit in its
own release directory with its own fresh virtualenv, runs the install and migrate commands,
saves the host's copies of the unit files the release ships, switches the `current` link,
stops and disables the units the live release ran that this one does not, installs the
release's unit files, enables and restarts this one's units, and runs the health command
until it passes within its time. A failure before the switch changes nothing live, and the next
tick tries again. A failure after it puts the live release back: the link, the saved unit
files exactly as they were, its units, its health; that commit is remembered as failed.
Either way the tick exits 1, so the timer's OnFailure= alert fires. A restore that fails, or
a tick cut off mid-release, is finished by the next tick, and every tick first prunes old
release directories. Main must keep containing the live release: a rewritten main is
refused until someone releases by hand.

ROOT holds repo/ (a clone of the project), releases/<sha>/, current -> releases/<sha>,
released ("<sha> <time> <previous sha>", the live release), attempt (a release under way),
units-before/ (the unit files an attempt replaced) and tick.lock; repo/ keeps a ref per
failed commit under refs/release/failed/. Everything root acts on is read from repo/, never
from a release directory the project's user can write, and every project command drops to
the project's user before it starts. Migrations run before the switch, so each must keep
the live release working: a restore puts the code back, never the schema.

The project's deploy/release.toml, read from the commit being released:

    user = "app"                        # runs every project command (default: root)
    units = ["app.service"]             # enabled and restarted while this release is live
    health = "curl -fsS http://127.0.0.1:8100/healthz"
    health_seconds = 90                 # how long the health command may take to pass
    requirements = "requirements.txt"   # installed into the release's own .venv, if present
    python = "/usr/local/bin/python3.11"
    install = "npm ci && npm run build" # runs in every release, after the virtualenv
    migrate = ".venv/bin/python -m scripts.migrate"
    env_file = "/etc/app/app.env"       # KEY=VALUE lines for every project command (no link)
    unit_files = "deploy/systemd"       # its *.service and *.timer files are installed
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
FAILED = "refs/release/failed/"     # a ref per failed commit keeps it, and its history, from gc


class Failed(Exception):
    """A tick that must end red, with the line that says why."""


def say(line):
    print(f"[release] {line}", flush=True)


def why(exc):
    return str(exc) if isinstance(exc, Failed) else f"{type(exc).__name__}: {exc}"


def git(repo, *args, raw=False):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=GIT_SECONDS)
    if done.returncode:
        raise Failed(f"git {' '.join(args)}: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout if raw else done.stdout.decode("utf-8", "replace").strip()


def git_ok(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=GIT_SECONDS).returncode == 0


def stamped(repo, sha):
    """Whether `sha` carries ak's one stamp naming its own tree."""
    tree = git(repo, "rev-parse", f"{sha}^{{tree}}")
    values = git(repo, "show", "-s", f"--format=%(trailers:key={STAMP},valueonly)", sha).split()
    return len(values) == 1 and values[0].lower() == tree


def candidate(repo, live):
    """The newest stamped first-parent commit on main that descends from `live` and is no
    ancestor of a commit that failed here (a rewrite cannot reopen an older release)."""
    failed = git(repo, "for-each-ref", "--format=%(objectname)", FAILED).split()
    for sha in git(repo, "rev-list", "--first-parent", f"{live}..origin/main").split():
        if any(git_ok(repo, "merge-base", "--is-ancestor", sha, bad) for bad in failed):
            return None
        if git_ok(repo, "merge-base", "--is-ancestor", live, sha) and stamped(repo, sha):
            return sha
    return None


def load(repo, sha):
    """`sha`'s deploy/release.toml, as committed."""
    try:
        config = tomllib.loads(git(repo, "show", f"{sha}:{CONFIG}"))
    except (Failed, tomllib.TOMLDecodeError) as exc:
        raise Failed(f"{CONFIG} unreadable in {sha[:12]}: {exc}") from exc
    config.setdefault("health_seconds", 90)
    config.setdefault("keep", 5)
    units = config.get("units")
    if (not units or not isinstance(units, list) or not all(isinstance(u, str) for u in units)
            or not isinstance(config.get("health"), str) or not config["health"]):
        raise Failed(f"{CONFIG} must name `units` and a `health` command")
    if not isinstance(config["health_seconds"], int) or config["health_seconds"] < 1:
        raise Failed(f"{CONFIG}: `health_seconds` must be a whole number of seconds, 1 or more")
    if not isinstance(config["keep"], int) or config["keep"] < 0:
        raise Failed(f"{CONFIG}: `keep` must be a whole number, 0 or more")
    return config


def environment(config):
    user = config.get("user") or pwd.getpwuid(os.getuid()).pw_name
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
           "HOME": pwd.getpwnam(user).pw_dir}
    path = config.get("env_file")
    if path:
        with open(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        for line in lines:
            name, sep, value = line.strip().partition("=")
            if sep and name and not name.startswith("#"):
                env[name.removeprefix("export ").strip()] = value.strip().strip("'\"")
    return env


def run(config, release, argv, seconds=COMMAND_SECONDS):
    """A project command in `release` as the project's user, in its own process group, all
    of which ends the moment the command does; its exit code and output. The child drops to
    the user before it executes anything, so the project's environment never reaches root."""
    drop = {}
    user = config.get("user")
    with tempfile.TemporaryFile() as out:
        try:
            if user and user != pwd.getpwuid(os.getuid()).pw_name:
                entry = pwd.getpwnam(user)
                drop = {"user": entry.pw_uid, "group": entry.pw_gid,
                        "extra_groups": os.getgrouplist(user, entry.pw_gid)}
            child = subprocess.Popen(argv, cwd=release, env=environment(config), stdout=out,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     start_new_session=True, **drop)
        except (OSError, KeyError) as exc:
            return 1, why(exc)
        # The leader stays unreaped until its group is killed, so its id names no other group.
        deadline = time.monotonic() + seconds
        late = False
        while os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
            if time.monotonic() >= deadline:
                late = True
                break
            time.sleep(0.05)
        try:
            os.killpg(child.pid, signal.SIGKILL)   # whatever it left behind ends too
        except ProcessLookupError:
            pass
        code = child.wait()
        out.seek(0)
        text = out.read().decode("utf-8", "replace").strip()
    return (124, f"killed after {seconds:.1f}s\n{text}") if late else (code, text)


def must(config, release, what, argv):
    code, out = run(config, release, argv)
    if code:
        tail = "\n".join(out.splitlines()[-20:])
        raise Failed(f"{what} failed (exit {code}): `{' '.join(argv)}`\n{tail}")


def chown(config, path):
    user = config.get("user")
    if user and os.getuid() == 0:
        subprocess.run(["chown", "-R", f"{user}:", str(path)], check=True, timeout=GIT_SECONDS)


def remove(root, release):
    shutil.rmtree(release, ignore_errors=True)
    git(root / "repo", "worktree", "prune")


def prepare(root, sha, migrate=True):
    """Everything a release needs before anything live changes: releases/<sha> checked out
    fresh, its own virtualenv installed from its requirements, its install and migrate."""
    config = load(root / "repo", sha)
    release = root / "releases" / sha
    remove(root, release)
    release.parent.mkdir(parents=True, exist_ok=True)
    git(root / "repo", "worktree", "add", "--detach", "--force", str(release), sha)
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


def unit_files(repo, config, sha):
    """`sha`'s unit files by name, as committed."""
    folder = config.get("unit_files")
    if not folder:
        return {}
    files = {}
    for entry in git(repo, "ls-tree", "-z", sha, "--", f"{folder.rstrip('/')}/").split("\0"):
        meta, _, path = entry.partition("\t")
        if not path:
            continue
        mode, kind, blob = meta.split()
        name = path.rpartition("/")[2]
        if kind == "blob" and mode != "120000" and name.endswith((".service", ".timer")):
            files[name] = git(repo, "cat-file", "blob", blob, raw=True)
    return files


def systemctl(*args):
    done = subprocess.run([SYSTEMCTL, *args], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=GIT_SECONDS)
    if done.returncode:
        raise Failed(f"systemctl {' '.join(args)}: {(done.stdout + done.stderr).strip()}")
    return done.stdout


def retire(name):
    """Stop `name` and keep it from starting at boot, unless systemd says it is neither
    running nor enabled (never installed, or retired already)."""
    shown = systemctl("show", "-p", "ActiveState", "-p", "UnitFileState", name)
    state = dict(line.partition("=")[::2] for line in shown.splitlines())
    if (state.get("ActiveState") in ("inactive", "failed")
            and not state.get("UnitFileState", "enabled").startswith("enabled")):
        return
    systemctl("disable", "--now", name)


def replace_unit(name, copy):
    """Put a unit file in place whole: a link there is replaced, never written through."""
    fresh = UNIT_DIR / f".{name}.release"
    fresh.unlink(missing_ok=True)
    copy(fresh)
    fresh.replace(UNIT_DIR / name)


def save_units(root, names):
    """The host's unit files `names` as they are, in units-before/ until the next attempt, so
    a restore puts back exactly what was there."""
    saved = root / "units-before"
    shutil.rmtree(saved, ignore_errors=True)
    saved.mkdir()
    for name in names:
        if os.path.lexists(UNIT_DIR / name):
            shutil.copy2(UNIT_DIR / name, saved / name, follow_symlinks=False)
    write(saved / "names", "".join(f"{name}\n" for name in names))     # written last: complete


def place_units(files):
    for name, text in files.items():
        def copy(fresh, text=text):
            fresh.write_bytes(text)
            fresh.chmod(0o644)
        replace_unit(name, copy)


def put_back_units(root):
    """The unit files the attempt replaced, back as they were; one that was not there goes."""
    saved = root / "units-before"
    for name in read_words(saved / "names"):
        if os.path.lexists(saved / name):
            replace_unit(name, lambda fresh, name=name: shutil.copy2(
                saved / name, fresh, follow_symlinks=False))
        else:
            (UNIT_DIR / name).unlink(missing_ok=True)


def start(root, sha, before, put_units):
    """`sha`'s units running on its link: the units `before` (the config it replaces) ran and
    it does not retired while their files are still there, then `put_units()` and a reload,
    its own units enabled and restarted, its health passed within its time."""
    config = load(root / "repo", sha)
    for name in sorted(set(before["units"]) - set(config["units"])):
        retire(name)
    put_units()
    systemctl("daemon-reload")
    systemctl("enable", *config["units"])
    systemctl("restart", *config["units"])
    deadline = time.monotonic() + config["health_seconds"]
    while True:
        code, out = run(config, root / "releases" / sha, ["bash", "-c", config["health"]],
                        min(HEALTH_TRY_SECONDS, deadline - time.monotonic()))
        if code == 0 and time.monotonic() <= deadline:
            return
        if time.monotonic() + 2 >= deadline:
            result = f"exit {code}" if code else f"passed after its {config['health_seconds']}s"
            raise Failed(f"health failed ({result}): `{config['health']}`: {out[-300:]}")
        time.sleep(2)


def switch(root, sha):
    link = root / "current.new"
    link.unlink(missing_ok=True)
    link.symlink_to(Path("releases") / sha)
    link.replace(root / "current")


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


def finish_attempt(root, failure):
    """An attempt that did not finish. Done when its release went live; dropped when its
    switch never happened; else the live release is restored and the attempt's commit
    remembered as failed."""
    words = read_words(root / "attempt")
    sha, previous, restoring = words[0], words[1], words[2:] == ["restoring"]
    if live(root) == sha:
        (root / "attempt").unlink()     # it had finished before a cut-off
        return 0
    if not restoring and os.readlink(root / "current") != f"releases/{sha}":
        (root / "attempt").unlink()     # the next tick tries it again
        raise Failed(f"{sha[:12]} not released, nothing live changed: {failure}")
    write(root / "attempt", f"{sha} {previous} restoring\n")
    try:
        switch(root, previous)
        start(root, previous, load(root / "repo", sha), lambda: put_back_units(root))
    except Exception as exc:  # noqa: BLE001 - the next tick tries again
        raise Failed(f"{sha[:12]} failed ({failure}); restoring {previous[:12]} failed too, "
                     f"the next tick tries again: {why(exc)}") from exc
    git(root / "repo", "update-ref", FAILED + sha, sha)
    (root / "attempt").unlink()
    raise Failed(f"{sha[:12]} failed and {previous[:12]} is back live: {failure}")


def prune(root):
    """Keep the newest `keep` release directories besides the live and previous ones."""
    words = read_words(root / "released")
    held = {words[0], *words[2:3]}
    keep = load(root / "repo", words[0])["keep"]
    older = sorted((p for p in (root / "releases").iterdir() if p.is_dir() and p.name not in held),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for release in older[keep:]:
        remove(root, release)


def tick(root):
    if (root / "attempt").exists():
        return finish_attempt(root, "the tick releasing it was cut off")
    repo = root / "repo"
    previous = live(root)
    if previous is None:
        raise Failed(f"no live release is recorded in {root}: run `release.py {root} --adopt`")
    prune(root)
    git(repo, "fetch", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main")
    if not git_ok(repo, "merge-base", "--is-ancestor", previous, "origin/main"):
        raise Failed(f"main no longer contains the live release {previous[:12]}: it was "
                     "rewritten, so release by hand")
    sha = candidate(repo, previous)
    if sha is None:
        return 0
    say(f"releasing {sha[:12]} over {previous[:12]}")
    try:
        config, _ = prepare(root, sha)
        files = unit_files(repo, config, sha)
    except Exception as exc:  # noqa: BLE001 - nothing live changed: the next tick tries again
        raise Failed(f"{sha[:12]} not released, nothing live changed: {why(exc)}") from exc
    write(root / "attempt", f"{sha} {previous}\n")
    try:
        save_units(root, sorted(files))
        switch(root, sha)
        start(root, sha, load(repo, previous), lambda: place_units(files))
        write(root / "released", f"{sha} {time.strftime('%Y-%m-%dT%H:%M:%S%z')} {previous}\n")
    except Exception as exc:  # noqa: BLE001 - finish_attempt restores whatever changed
        return finish_attempt(root, why(exc))
    (root / "attempt").unlink()
    say(f"live: {sha[:12]}")
    return 0


def adopt(root):
    """Make repo/'s checked-out commit the first release, built as any release is, without
    migrating or restarting anything."""
    if live(root):
        raise Failed(f"{root} is adopted already: {live(root)[:12]} is live")
    sha = git(root / "repo", "rev-parse", "HEAD")
    prepare(root, sha, migrate=False)
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
