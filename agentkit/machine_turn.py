"""A model turn on a rented machine once config.toml says `turns_on_machines = true`, its results
back here when it ends. Hidden here: the machine, picked as agentkit/helper.py picks a suite's among
those that take turns, and the ssh to it; the parcel beside a suite's: the out dir, the checkout's
uncommitted paths, ak itself, a HOME of the turn's own, holding a copy of its login the adapter
lends and the conversation it resumes, and the harness program to run, which the machine fetches the
first time a turn names it (mac.sh's `fetch`), a new version here reaching it at its next turn; the
container tools/helper/turn.sh runs the turn in, at this host's paths; and what comes back: the out
dir, a bundle of the turn's commits, the last holding what it left uncommitted, which git applies
here, and the conversation it reported, at its place under this host's HOME.
"""

import fnmatch
import glob
import io
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import tempfile
import time

from . import config, gitcall, helper

AK = ("adapters", "agentkit", "bin", "tools")    # ak itself, read-only there, `bin` on PATH
# Seconds a lent login must last, else the turn runs here: a longer turn would end on an expired
# login and page the owner.
LENT_FOR = 3600


def _sessions(harness):
    """Where the harness keeps a conversation, `[worker] sessions`: globs under HOME with `{id}`."""
    return [place.removeprefix("~/") for place in
            config.manifest(harness).get("worker", {}).get("sessions", ())]


def _conversation(harness, session):
    """The globs under HOME of the conversation `session`: it is what they match and all under
    that. An id with a `/` names no file, so an id a turn reported reaches nowhere else."""
    if not session or "/" in session:
        return []
    return [place.replace("{id}", glob.escape(session)) for place in _sessions(harness)]


def call(entry, cmd, cwd, out_dir, env, places, session, watch):
    """(exit, killed, session) of the turn `cmd` of the model `entry` on a machine with room, or
    None: it runs here, as with the switch off, `places`, no program for it (`_program`), a
    checkout where a rebase or merge stopped (`_stopped`), no login to lend, no recipe, no room, a
    harness with no `sessions`, or a `session` to resume that this host does not hold, as here is
    where a later resume would look for it too. `watch(argv,
    **streams)` runs ssh as the worker's watchdog runs a turn, into the out dir's events.jsonl and
    stderr.log. A lost machine's turn fails, this host's files as they were, and leaves `session`,
    the conversation it was given: the id it streamed names one that is nowhere. One whose results
    came home leaves the conversation it reported, whatever its exit."""
    harness = entry["harness"]
    try:
        on = (config._read_toml(config.HOME / config.CONFIG_NAME) or {}).get("turns_on_machines")
        program = _program(harness) if on is True and not places and _sessions(harness) else None
    except config.Error:    # a config.toml mid-edit fails no turn: it runs here
        program = None
    if not program or _stopped(cwd):
        return None
    held = [name for place in _conversation(harness, session)
            for name in glob.glob(place, root_dir=env["HOME"])]
    if session and not held:
        return None
    cwd, out_dir = Path(cwd).absolute(), Path(out_dir).absolute()
    with tempfile.TemporaryDirectory() as home:
        lent = _lend(entry, cmd[0], env, home)
        if not lent:
            return None
        # 2048: twice this is 4 GiB, as on 30 Oct 2026 this host's runs peaked at a median of 768
        # MiB and p90 of 1868 MiB, test pieces included, with one at 5438 MiB.
        away = helper.start(2, 2048, cwd, lambda line: None, shlex.join(cmd), lambda tar: _parcel(
            tar, program, cwd, out_dir, env, home, lent, held))[0]
    if away is None:
        return None
    volumes = [f"home:{env['HOME']}", f"work:{cwd}", f"out:{out_dir}",
               *(f"ak/{name}:{config.REPO / name}:ro" for name in AK)]
    try:
        with (out_dir / "events.jsonl").open("ab") as events, \
                (out_dir / "stderr.log").open("ab") as err:
            code, _, killed = watch(helper._remote(
                away.alias, "turn", away.key, away.image, away.memory_mb, away.repo, *volumes,
                "--", cwd, config.REPO, away.branch, away.default, *cmd), stdout=events, stderr=err)
        if code == helper.FULL:    # its room went to another before it started: it runs here
            return None
        if not killed:    # the turn's own exit and conversation come home with its results
            code, session = code == 0 and _home(away, harness, cwd, out_dir, env["HOME"]) or (
                helper.LOST, session)
    finally:
        helper.finish(away)
    return code, killed, session


# What git keeps in a checkout's own git directory while a rebase, merge or cherry-pick waits on
# its conflicts: no parcel carries it, so a machine's fresh clone has nothing to go on with.
STOPPED = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD")


def _stopped(cwd):
    """Is a rebase, merge or cherry-pick stopped in the checkout at `cwd`?"""
    code, out = gitcall.git_out(cwd, "rev-parse", *(arg for name in STOPPED
                                                     for arg in ("--git-path", name)))
    return code == 0 and any(Path(cwd, path).exists() for path in out.splitlines())


def _program(harness):
    """(`<harness>/<version>/<program>`, {`uname -m`: URL}) of the program a machine needs for this
    harness's turn: the URLs its toml's `[fetch]` names, with `{version}` the version `ak update`
    reads here. None: it names none, or that version cannot be read."""
    from . import update    # here, not at the top: update reaches this module through the worker
    where = config.manifest(harness).get("fetch")
    entry = next((entry for entry in update.harnesses() if entry["name"] == harness), None)
    identity = where and entry and update.version(entry)
    if not identity:
        return None
    version = update.VERSION.search(identity).group(0)
    return (f"{harness}/{version}/{config.harness_program(harness)}",
            {machine: url.replace(update.VERSION_KEY, version) for machine, url in where.items()})


def _lend(entry, adapter, env, home):
    """The paths under `home` of the login the adapter lent there for the account `env` names, none
    where it lends none lasting LENT_FOR. The account is `lend`'s alone: the machine's adapter runs
    with none, reading the copy where the usual login lives."""
    try:
        done = config.run_adapter([adapter, "lend", home], 60,
                                  env={**env, **config.provider_env([entry["provider"]])})
        if done.returncode or float(done.stdout or "inf") < time.time() + LENT_FOR:
            return []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return [str(path.relative_to(home)) for path in Path(home).rglob("*") if path.is_file()]


def _parcel(tar, program, cwd, out_dir, env, home, lent, held):
    """Adds the turn's own to its parcel: turn.sh, the out dir, ak, the uncommitted paths (`paths`
    lists them all, `dirty/` holds those the checkout has), info/exclude, the HOME's .gitconfig,
    the login lent from `home` (`lent` lists its paths, which `turn` removes), `held`, the
    conversation it resumes, the program (`harness`, and `fetch/` where each kind of machine gets
    it) and the environment, never the loop's whole one."""
    from .worker import RUN_MARKER    # here, not at the top: the worker calls this module
    def put(name, text):
        info = tarfile.TarInfo(name)
        info.size = len(text.encode())
        tar.addfile(info, io.BytesIO(text.encode()))
    tar.add(helper.TOOLS / "turn.sh", "turn.sh")
    tar.add(out_dir, "out")
    for name in AK:
        tar.add(config.REPO / name, f"ak/{name}",
                filter=lambda member: None if "__pycache__" in member.name else member)
    paths = gitcall.dirty_paths(cwd)
    put("paths", "".join(f"{path}\0" for path in paths))
    for path in paths:
        if os.path.lexists(cwd / path):
            tar.add(cwd / path, f"dirty/{path}", recursive=False)
    exclude = cwd / gitcall.git(cwd, "rev-parse", "--git-path", "info/exclude")
    if exclude.is_file():
        tar.add(exclude, "exclude")
    who = [gitcall.git_out(cwd, "config", f"user.{key}")[1] for key in ("name", "email")]
    put("home/.gitconfig", "[user]\n\tname = {}\n\temail = {}\n".format(*who))
    put("lent", "".join(f"{path}\0" for path in lent))
    for path in lent:
        tar.add(Path(home, path), f"home/{path}")
    for name in held:
        tar.add(Path(env["HOME"], name), f"home/{name}")
    put("harness", program[0])
    for machine, url in program[1].items():
        put(f"fetch/{machine}", url)
    put("env", "".join(f"{key}={value}\0" for key, value in {**env, "TMPDIR": "/var/tmp"}.items()
                       if key.startswith(("AK_", "BASH_"))
                       or key in (RUN_MARKER, "HOME", "LANG", "SHELL", "TMPDIR")))


def _home(away, harness, cwd, out_dir, home):
    """(the turn's exit, the conversation it reported) once all its results came home before any
    applied, else None: its commits, HEAD moved to its last, the checkout made its left commit and
    the index HEAD, so what it left uncommitted stays so; then the out dir, but the events and
    stderr streamed here already; last the conversation it reported, each file whole, which is all
    of its HOME that comes home: from the folders `sessions` start from, so its caches do not
    travel."""
    from .turns import session_of    # here, not at the top: the worker calls this module
    try:
        folders = {os.path.dirname(re.split(r"[*?[{]", place)[0]) for place in _sessions(harness)}
        reply = helper._remote(away.alias, "collect", away.key, *folders, timeout=600)
        if reply.returncode:
            return None
        # Its regular files by relative name alone, each part a name: nothing it sends reaches
        # past the out dir, nor lands elsewhere than the name a glob matched.
        with tarfile.open(fileobj=io.BytesIO(reply.stdout)) as tar:
            files = {member.name: tar.extractfile(member).read() for member in tar
                     if member.isfile() and {"", ".", ".."}.isdisjoint(member.name.split("/"))}
        code = int(files.pop("code"))
        with tempfile.TemporaryDirectory() as back:
            bundle = Path(back, "back.bundle")
            bundle.write_bytes(files.pop("back.bundle"))
            left = gitcall.git(cwd, "bundle", "list-heads", bundle, "refs/ak/left").split()[0]
            gitcall.git(cwd, "bundle", "unbundle", bundle)
            index = {"GIT_INDEX_FILE": f"{back}/index"}
            gitcall.git(cwd, "read-tree", "HEAD", env=index)
            gitcall.git(cwd, "add", "-A", env=index)
            gitcall.git(cwd, "update-ref", "HEAD", f"{left}^")
            gitcall.git(cwd, "read-tree", "--reset", "-u", left, env=index)
            gitcall.git(cwd, "read-tree", "HEAD")
        for name, data in files.items():
            if name.startswith("out/") and name not in ("out/events.jsonl", "out/stderr.log"):
                (out_dir / name[4:]).parent.mkdir(parents=True, exist_ok=True)
                (out_dir / name[4:]).write_bytes(data)
        session = session_of(out_dir)
        globs = [place.split("/") for place in _conversation(harness, session)]
        real = Path(home).resolve()
        for name, data in files.items():
            parts = name.split("/")[1:]
            path = real.joinpath(*parts)
            # Through no link on its way, one a turn run here could leave to lead out of HOME.
            if name.startswith("home/") and path.parent.resolve() == path.parent and any(
                    len(parts) >= len(place) and all(map(fnmatch.fnmatchcase, parts, place))
                    for place in globs):
                path.parent.mkdir(parents=True, exist_ok=True)
                # 0600, and a name no glob matches: a reader sees the old file or the whole new one.
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".", delete=False) as part:
                    part.write(data)
                Path(part.name).replace(path)
    except (OSError, subprocess.SubprocessError, tarfile.TarError, IndexError, KeyError,
            ValueError, config.Error):
        return None
    return code, session
