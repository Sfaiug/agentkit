"""A model turn on a rented machine once config.toml says `machine_turns = true`, its results back
here when it ends. Hidden here: the machine, picked as agentkit/helper.py picks a suite's among
those that take turns, and the ssh to it; the parcel beside a suite's: the out dir, the checkout's
uncommitted paths, ak itself and a HOME of the turn's own; the container tools/helper/turn.sh runs
the turn in, at this host's paths; and what comes back: the out dir and a bundle of the turn's
commits, the last holding what it left uncommitted, which git applies here.
"""

import io
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile

from . import config, gitcall, helper

AK = ("adapters", "agentkit", "bin", "tools")    # ak itself, read-only there, `bin` on PATH


def call(harness, cmd, cwd, out_dir, env, places, watch):
    """(exit, killed) of the turn `cmd` on a machine with room, or None: it runs here, as with the
    switch off, `places`, no recipe or no room. `watch(argv, **streams)` runs ssh as the worker's
    watchdog runs a turn, into the out dir's events.jsonl and stderr.log. A lost machine's turn
    fails, this host's checkout as it was."""
    try:
        on = (config._read_toml(config.HOME / config.CONFIG_NAME) or {}).get("machine_turns")
    except config.Error:    # a config.toml mid-edit fails no turn: it runs here
        on = False
    if places or on is not True:
        return None
    cwd, out_dir = Path(cwd).absolute(), Path(out_dir).absolute()
    away = helper.start(2, 1024, cwd, lambda line: None, shlex.join(cmd),
                        lambda tar: _parcel(tar, harness, cwd, out_dir, env))[0]
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
            code = _home(away, cwd, out_dir) if code == 0 else helper.LOST
    finally:
        helper.finish(away)
    return code, killed


def _parcel(tar, harness, cwd, out_dir, env):
    """Adds the turn's own to its parcel: turn.sh, the out dir, ak, the uncommitted paths (`paths`
    lists them all, `dirty/` holds those the checkout has), info/exclude, the HOME's .gitconfig,
    the harness and the environment, never the loop's whole one."""
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
    put("harness", f"{harness}/{config.harness_program(harness)}")
    put("env", "".join(f"{key}={value}\0" for key, value in {**env, "TMPDIR": "/var/tmp"}.items()
                       if key.startswith(("AK_", "BASH_"))
                       or key in (RUN_MARKER, "HOME", "LANG", "SHELL", "TMPDIR")))


def _home(away, cwd, out_dir):
    """The turn's exit once all its results came home before any applied, else LOST: its commits,
    HEAD moved to its last, the checkout made its left commit and the index HEAD, so what it left
    uncommitted stays so; then the out dir, but the events and stderr streamed here already."""
    try:
        reply = helper._remote(away.alias, "collect", away.key, timeout=600)
        if reply.returncode:
            return helper.LOST
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
    except (OSError, subprocess.SubprocessError, tarfile.TarError, IndexError, KeyError,
            ValueError, config.Error):
        return helper.LOST
    return code
