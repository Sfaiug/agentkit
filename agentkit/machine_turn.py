"""A model turn on a rented machine once config.toml says `machine_turns = true`, its results back
here when it ends. Hidden here: the machine, picked as agentkit/helper.py picks a suite's among
those that take turns, and the ssh to it; the parcel beside a suite's: the out dir, the checkout's
uncommitted paths, ak itself and a HOME of the turn's own, holding the conversation it resumes; the
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

from . import config, gitcall, helper

AK = ("adapters", "agentkit", "bin", "tools")    # ak itself, read-only there, `bin` on PATH
LOST = helper.LOST    # a turn's exit when its results did not come home


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


def call(harness, cmd, cwd, out_dir, env, places, session, watch):
    """(exit, killed) of the turn `cmd` on a machine with room, or None: it runs here, as with the
    switch off, `places`, no recipe, no room, a harness with no `sessions`, or a `session` to resume
    that this host does not hold, as here is where a later resume would look for it too.
    `watch(argv, **streams)` runs ssh as the worker's watchdog runs a turn, into the out dir's
    events.jsonl and stderr.log. A lost machine's turn fails, this host's files as they were."""
    try:
        on = (config._read_toml(config.HOME / config.CONFIG_NAME) or {}).get("machine_turns")
    except config.Error:    # a config.toml mid-edit fails no turn: it runs here
        on = False
    if places or on is not True or not _sessions(harness):
        return None
    held = [name for place in _conversation(harness, session)
            for name in glob.glob(place, root_dir=env["HOME"])]
    if session and not held:
        return None
    cwd, out_dir = Path(cwd).absolute(), Path(out_dir).absolute()
    away = helper.start(2, 1024, cwd, lambda line: None, shlex.join(cmd),
                        lambda tar: _parcel(tar, harness, cwd, out_dir, env, held))[0]
    if away is None:
        return None
    volumes = [f"work:{cwd}", f"out:{out_dir}", f"home:{env['HOME']}",
               *(f"ak/{name}:{config.REPO / name}:ro" for name in AK)]
    try:
        with (out_dir / "events.jsonl").open("ab") as events, \
                (out_dir / "stderr.log").open("ab") as err:
            code, _, killed = watch(helper._remote(
                away.alias, "turn", away.key, away.image, away.memory_mb, away.repo, *volumes,
                "--", cwd, config.REPO, away.branch, away.default, *cmd), stdout=events, stderr=err)
        if code == helper.FULL:    # its room went to another before it started: it runs here
            return None
        if not killed:    # the turn's own exit comes home with its results
            code = _home(away, harness, cwd, out_dir, env["HOME"]) if code == 0 else LOST
    finally:
        helper.finish(away)
    return code, killed


def _parcel(tar, harness, cwd, out_dir, env, held):
    """Adds the turn's own to its parcel: turn.sh, the out dir, ak, the uncommitted paths (`paths`
    lists them all, `dirty/` holds those the checkout has), info/exclude, the HOME's .gitconfig
    and `held`, the conversation it resumes, the harness and the environment, never the loop's
    whole one."""
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
    for name in held:
        tar.add(Path(env["HOME"], name), f"home/{name}")
    put("harness", f"{harness}/{config.harness_program(harness)}")
    put("env", "".join(f"{key}={value}\0" for key, value in {**env, "TMPDIR": "/var/tmp"}.items()
                       if key.startswith(("AK_", "BASH_"))
                       or key in (RUN_MARKER, "HOME", "LANG", "SHELL", "TMPDIR")))


def _home(away, harness, cwd, out_dir, home):
    """The turn's exit once all its results came home before any applied, else LOST: its commits,
    HEAD moved to its last, the checkout made its left commit and the index HEAD, so what it left
    uncommitted stays so; then the out dir, but the events and stderr streamed here already; last
    the conversation it reported, each file whole, which is all of its HOME that comes home: from
    the folders `sessions` start from, so its caches do not travel."""
    from .turns import session_of    # here, not at the top: the worker calls this module
    try:
        folders = {os.path.dirname(re.split(r"[*?[{]", place)[0]) for place in _sessions(harness)}
        reply = helper._remote(away.alias, "collect", away.key, *folders, timeout=600)
        if reply.returncode:
            return LOST
        # Its regular files by relative name alone: nothing it sends reaches past the out dir.
        with tarfile.open(fileobj=io.BytesIO(reply.stdout)) as tar:
            files = {member.name: tar.extractfile(member).read() for member in tar
                     if member.isfile() and ".." not in member.name.split("/")}
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
        globs = [place.split("/") for place in _conversation(harness, session_of(out_dir))]
        for name, data in files.items():
            parts = name.split("/")[1:]
            if name.startswith("home/") and any(
                    len(parts) >= len(place) and all(map(fnmatch.fnmatchcase, parts, place))
                    for place in globs):
                path = Path(home, *parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                # 0600, and a name no glob matches: a reader sees the old file or the whole new one.
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".", delete=False) as part:
                    part.write(data)
                Path(part.name).replace(path)
    except (OSError, subprocess.SubprocessError, tarfile.TarError, IndexError, KeyError,
            ValueError, config.Error):
        return LOST
    return code
