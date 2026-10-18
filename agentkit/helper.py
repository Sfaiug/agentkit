"""A Mac that runs a sharded suite's pieces while it is awake and on power: `suite_helper` in
config.toml names it by ssh alias. Each piece runs in a Linux VM of Apple's `container`, built
from tools/helper/Containerfile, with only the tree under test and its repository's history
mounted, read-only, and nothing beyond loopback: the Mac's own files, keys and logins never
reach it. The Mac keeps each repository's history between suites, so a suite sends only the
commits it lacks. A piece the Mac lost -- it left its charger or slept, the connection or the
VM broke -- exits `LOST`.
"""

from collections import namedtuple
import hashlib
import io
import secrets
import shlex
import subprocess
import tarfile
import tempfile

from . import config, gitcall, orch

LOST = 255            # ssh's own failure, and tools/helper/mac.sh's for each failure of its own
LACKS = 3             # mac.sh's `prepare`: the Mac's copy lacks history the parcel left out
TOOLS = config.REPO / "tools" / "helper"
SSH = ("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15")


# A suite on the helper: `key` names its directory there and its VMs, `repo` the history it
# keeps there, `default` the branch origin/HEAD names, `programs` the harness programs this host
# has, stand-ins there.
Away = namedtuple("Away", "alias key repo count cpus memory_mb branch default programs")


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
    Mac stays its owner's. A VM gets two CPUs or more, as a one-CPU VM's kernel hands a
    terminal's bytes over late and the suite's terminal tests read them at once, and twice the
    piece's measured memory: it also holds its own kernel, page cache and clone."""
    try:
        probe = _remote(alias, "probe", text=True, timeout=30)
        readings = {key: float(value) for key, value in
                    (line.split(None, 1) for line in probe.stdout.splitlines() if " " in line)}
        spare = readings["cpus"] - readings["load"]
        free_mb = readings["memory_mb"] * readings["free_percent"] / 200
    except (OSError, subprocess.TimeoutExpired, KeyError, ValueError):
        return None
    count = min(int(spare // max(piece_cpus, 2)), int(free_mb // (2 * piece_mem_mb)))
    if probe.returncode or count < 1:
        return None
    return count, int(spare // count), int(free_mb // count)


def _known(alias, repo):
    """The commits the helper's copy of the repository has history up to; None: no answer."""
    try:
        reply = _remote(alias, "known", repo, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None if reply.returncode else reply.stdout.split()


def _parcel(cwd, default, known, parcel):
    """Writes to the file `parcel` the recipe, the piece's script, `heads` (HEAD, then the origin
    branch the suite compares against) and a bundle of their history the helper lacks: the
    whole history the first time, which can outgrow memory."""
    revs = ["HEAD", *([f"refs/remotes/origin/{default}"] if default else [])]
    heads = subprocess.run(["git", "-C", str(cwd), "rev-parse", *revs], capture_output=True,
                           text=True, check=True).stdout.split()
    have = [sha for sha in known
            if not gitcall.git_out(cwd, "cat-file", "-e", sha + "^{commit}")[0]]
    with tarfile.open(fileobj=parcel, mode="w") as tar, tempfile.TemporaryFile() as bundle:
        tar.add(TOOLS / "Containerfile", "image/Containerfile")
        tar.add(TOOLS / "piece.sh", "piece.sh")
        text = (" ".join(heads) + "\n").encode()
        info = tarfile.TarInfo("heads")
        info.size = len(text)
        tar.addfile(info, io.BytesIO(text))
        # `git bundle` refuses one with nothing in it: the helper has every commit already.
        if not subprocess.run(["git", "-C", str(cwd), "bundle", "create", "-", *revs, "--not",
                               *have], stdout=bundle, stderr=subprocess.DEVNULL).returncode:
            bundle.seek(0)
            tar.addfile(tar.gettarinfo(arcname="repo.bundle", fileobj=bundle), bundle)


def start(piece_cpus, piece_mem_mb, cwd, log):
    """The suite at `cwd` sent to the helper, or None to run it here."""
    alias = config.suite_helper()
    fit = room(alias, piece_cpus, piece_mem_mb) if alias else None
    if fit is None:
        return None
    code, branch = gitcall.git_out(cwd, "symbolic-ref", "-q", "--short", "HEAD")
    named, default = gitcall.git_out(cwd, "rev-parse", "--abbrev-ref", "origin/HEAD")
    programs = {program for program in orch.agent_programs() if config.harness_binary(program)}
    # A checkout's repository is the one its main checkout has, wherever the suite runs.
    repo = hashlib.sha256(str(gitcall.main_checkout(cwd)).encode()).hexdigest()[:12]
    away = Away(alias, secrets.token_hex(6), repo, *fit, "" if code else branch,
                "" if named else default.removeprefix("origin/"), " ".join(sorted(programs)))
    sent, known = LOST, _known(alias, repo)
    try:
        while known is not None:
            with tempfile.TemporaryFile() as parcel:
                _parcel(cwd, away.default, known, parcel)
                parcel.seek(0)
                # a new recipe's build fetches packages, a first suite sends the whole history
                sent = _remote(alias, "prepare", away.key, image(), repo, stdin=parcel,
                               timeout=1800).returncode
            # The copy went since `known` answered: the whole history, once.
            known = [] if known and sent == LACKS else None
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
                   away.cpus, away.memory_mb, away.repo, shard, away.branch, away.default,
                   away.programs, command)


def finish(away):
    """The suite's tree leaves the Mac; one that does not answer clears it a day later."""
    try:
        _remote(away.alias, "finish", away.key, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass
