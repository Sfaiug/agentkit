"""A Mac that runs a sharded suite's pieces while it is awake and on power: `suite_helper` in
config.toml names it by ssh alias. Each piece runs in a Linux VM of Apple's `container`, built
from tools/helper/Containerfile, with only the tree under test mounted, read-only, and nothing
beyond loopback: the Mac's own files, keys and logins never reach it. A piece the Mac lost --
it left its charger or slept, the connection or the VM broke -- exits `LOST`.
"""

from collections import namedtuple
import hashlib
import io
import secrets
import shlex
import subprocess
import tarfile

from . import config, gitcall, orch

LOST = 255            # ssh's own failure, and tools/helper/mac.sh's for each failure of its own
TOOLS = config.REPO / "tools" / "helper"
SSH = ("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15")


# A suite on the helper: `key` names its directory there and its VMs, `default` the branch
# origin/HEAD names, `programs` the harness programs this host has, stand-ins there.
Away = namedtuple("Away", "alias key count cpus memory_mb branch default programs")


def _remote(alias, verb, *args, **kwargs):
    script = (TOOLS / "mac.sh").read_text()
    argv = [*SSH, alias, shlex.join(["bash", "-c", script, "mac.sh", verb, *map(str, args)])]
    return subprocess.run(argv, capture_output=True, **kwargs) if kwargs else argv


def image():
    """Named by its recipe's hash, so a changed recipe builds anew and the old image goes."""
    return "ak-helper:" + hashlib.sha256((TOOLS / "Containerfile").read_bytes()).hexdigest()[:12]


def room(alias, piece_cpus, piece_mem_mb):
    """(pieces, CPUs each, MiB each) the Mac fits now, or None: no answer, on battery, another
    suite holds it or no room. Its CPUs less its load; half the memory macOS calls free, so the
    Mac stays its owner's. A VM gets a whole CPU and twice the piece's measured memory: it also
    holds its own kernel, page cache and clone."""
    try:
        probe = _remote(alias, "probe", text=True, timeout=30)
        readings = {key: float(value) for key, value in
                    (line.split(None, 1) for line in probe.stdout.splitlines() if " " in line)}
        spare = readings["cpus"] - readings["load"]
        free_mb = readings["memory_mb"] * readings["free_percent"] / 200
    except (OSError, subprocess.TimeoutExpired, KeyError, ValueError):
        return None
    count = min(int(spare // max(piece_cpus, 1)), int(free_mb // (2 * piece_mem_mb)))
    if probe.returncode or count < 1:
        return None
    return count, int(spare // count), int(free_mb // count)


def _parcel(cwd, default):
    """HEAD and the origin branch the suite compares against, the recipe and the piece's script."""
    bundle = subprocess.run(["git", "-C", str(cwd), "bundle", "create", "-", "HEAD",
                             *([f"refs/remotes/origin/{default}"] if default else [])],
                            capture_output=True, check=True).stdout
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        tar.add(TOOLS / "Containerfile", "image/Containerfile")
        tar.add(TOOLS / "piece.sh", "piece.sh")
        info = tarfile.TarInfo("repo.bundle")
        info.size = len(bundle)
        tar.addfile(info, io.BytesIO(bundle))
    return data.getvalue()


def start(piece_cpus, piece_mem_mb, cwd, log):
    """The suite at `cwd` sent to the helper, or None to run it here."""
    alias = config.suite_helper()
    fit = room(alias, piece_cpus, piece_mem_mb) if alias else None
    if fit is None:
        return None
    code, branch = gitcall.git_out(cwd, "symbolic-ref", "-q", "--short", "HEAD")
    named, default = gitcall.git_out(cwd, "rev-parse", "--abbrev-ref", "origin/HEAD")
    programs = {program for program in orch.agent_programs() if config.harness_binary(program)}
    away = Away(alias, secrets.token_hex(6), *fit, "" if code else branch,
                "" if named else default.removeprefix("origin/"), " ".join(sorted(programs)))
    try:
        sent = _remote(alias, "prepare", away.key, image(), input=_parcel(cwd, away.default),
                       timeout=1800).returncode   # a new recipe's build fetches packages
    except (OSError, subprocess.SubprocessError):
        sent = LOST
    if sent:
        log(f"WARN the suite helper {alias} did not take the suite; it runs here")
        finish(away)
        return None
    log(f"suite on {alias}: {fit[0]} pieces, {fit[1]} CPUs and {fit[2]} MiB each")
    return away


def piece(away, shard, command):
    """The argv of one piece on the helper: it exits as the piece did, or `LOST`."""
    return _remote(away.alias, "run", away.key, image(), f"ak-{away.key}-{shard.replace('/', '-')}",
                   away.cpus, away.memory_mb, shard, away.branch, away.default, away.programs,
                   command)


def finish(away):
    """The suite's tree leaves the Mac; one that does not answer clears it a day later."""
    try:
        _remote(away.alias, "finish", away.key, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass
