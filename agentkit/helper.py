"""A machine that runs a sharded suite's pieces beside this one: `suite_helper` in config.toml
names it by ssh alias. A Mac runs each piece in a Linux VM of Apple's `container` while it is awake
and on power; a Linux machine with docker (on Debian, its packages `docker.io`, `docker-cli`, `curl`,
the ssh user in group `docker`), which holds nothing but ak's work and gives it all its memory but
a tenth, in a container. Its image is built from the recipe the repository's `suite_image:` names,
else its tools/helper/Containerfile (ak's own), with only the tree under test and its repository's
history mounted, read-only, and nothing beyond loopback: the machine's own files, keys and logins
never reach it. A repository with neither runs its suite here. The machine keeps each repository's
history between suites, so a suite sends only the commits it lacks. A piece the machine lost -- a
Mac left its charger or slept, the connection, the VM or the container broke -- returns a helper
failure code.
"""

from collections import namedtuple
import fcntl
import hashlib
import io
import math
import os
import posixpath
import re
import secrets
import shlex
import subprocess
import tarfile
import tempfile
import time

from . import config, gitcall, google_cloud, machines, orch

LOST = 255            # ssh's own failure
LACKS = 3             # mac.sh's `prepare`: the copy there lacks history the parcel left out
SHORT = 254           # piece.sh: the kernel killed a process of the piece for memory
BATTERY, FULL, BROKEN = 251, 252, 253   # mac.sh: off power, no room for the piece, could not run
GONE = (LOST, SHORT, BATTERY, BROKEN)   # a piece's exit when the helper lost it
TOOLS = config.REPO / "tools" / "helper"
RECIPE = "tools/helper/Containerfile"     # a repository's recipe when `suite_image:` names none
SSH = ("ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15")
# Linux's MAX_ARG_STRLEN, the most one argument holds, its closing NUL counted: ssh is given a
# piece's whole line as one, and the machine's shell gets it as one, the piece's command in it.
MAX_ARG_STRLEN = 128 * 1024
VM_CPUS = 2     # the least a piece's VM gets (`room`)


# A suite on the helper: `key` names its directory there and its VMs, `repo` the history it
# keeps there, `image` its pieces' image, `most` the VMs it fits empty, `default` the branch
# origin/HEAD names, `programs` the harness programs this host has, stand-ins there.
Away = namedtuple("Away", "alias key repo image count cpus memory_mb most branch default "
                          "programs")


def _remote(alias, verb, *args, **kwargs):
    argv = [*SSH, *google_cloud.ssh_config(), alias, _line(verb, *args)]
    return subprocess.run(argv, capture_output=True, **kwargs) if kwargs else argv


def _line(verb, *args):
    # Every kind of machine is sent every kind's functions, and picks its own by `uname`.
    script = (TOOLS / "linux.sh").read_text() + (TOOLS / "mac.sh").read_text()
    return shlex.join(["bash", "-c", script, "mac.sh", verb, *map(str, args)])


def _recipe(cwd, repo):
    """(image, {name in the parcel: (mode, bytes)}) the suite's pieces run in, or None: the
    repository has no recipe. The recipe, `image/Containerfile`, is the file `suite_image:` names,
    else RECIPE; its build's context, under `context/`, each file it copies, as HEAD has them.
    Tagged by their hash, so a changed recipe or copied file builds anew and the image it
    replaces goes. ValueError: the recipe copies something other than files HEAD tracks, named
    by plain path, which ak cannot send."""
    path = gitcall.declared(cwd, "suite_image")
    if not path:
        if gitcall.git_out(cwd, "cat-file", "-e", f"HEAD:{RECIPE}")[0]:
            return None
        path = RECIPE
    files = {"image/Containerfile": _tracked(cwd, path)}
    for line in re.sub(r"\\\n", " ", files["image/Containerfile"][1].decode()).splitlines():
        words = line.split()
        if not words or words[0].upper() not in ("COPY", "ADD"):
            continue
        sources = [word for word in words[1:-1] if not word.startswith(("--chown=", "--chmod="))]
        if words[0].upper() == "ADD" or not sources or any(
                word.startswith(("-", "/", "[")) or set(word) & set("*?[$<") or
                ".." in word.split("/") for word in sources):
            raise ValueError(f"`{line.strip()}` copies something other than tracked files")
        files.update((f"context/{source}", _tracked(cwd, source)) for source in sources)
    digest = hashlib.sha256()
    for name in sorted(files):
        mode, data = files[name]
        digest.update(f"{name}\0{mode}\0{len(data)}\0".encode() + data)
    return f"ak-helper-{repo}:{digest.hexdigest()[:12]}", files


def _tracked(cwd, path):
    """(mode, bytes) of the file HEAD has at `path`; ValueError: none there, or a link."""
    entry = subprocess.run(["git", "-C", str(cwd), "ls-tree", "-z", "HEAD", "--", path],
                           capture_output=True, text=True).stdout
    info, _, name = entry.partition("\t")
    mode, _, blob = info.partition(" blob ")
    if name != posixpath.normpath(path) + "\0" or mode not in ("100644", "100755"):
        raise ValueError(f"{path} is not a file HEAD tracks")
    return int(mode[3:], 8), subprocess.run(["git", "-C", str(cwd), "cat-file", "blob", blob],
                                            capture_output=True, check=True).stdout


def room(alias, piece_cpus, piece_mem_mb, least_mb=0, turns=False):
    """((pieces, CPUs each, MiB each, most pieces), reason): a fit, or (None, why it cannot run
    there). With `turns`, only a machine whose probe says `turns 1` fits: a Mac runs test suites
    alone. Its CPUs less its load, split equally, as VMs time-share them; the memory ak's VMs
    may still be given there (`left`), beside other suites' VMs. A VM gets two CPUs or more, as a
    one-CPU VM's kernel hands a terminal's bytes over late and the suite's terminal tests read
    them at once, and `each_mb`. The most pieces are its CPUs' fit with no load."""
    try:
        probe = _remote(alias, "probe", text=True, timeout=30)
        if probe.returncode:
            return None, failure(probe.returncode)
        readings = {key: float(value) for key, value in
                    (line.split(None, 1) for line in probe.stdout.splitlines() if " " in line)}
        if turns and readings.get("turns") != 1:
            return None, "takes no model turns"
        cpus, room_mb = readings["cpus"], readings["room_mb"]
        spare, each_cpus = cpus - readings["load"], max(piece_cpus, VM_CPUS)
        mb = each_mb(piece_mem_mb, least_mb)
        count = min(int(spare // each_cpus), int(room_mb // mb))
    except (OSError, subprocess.TimeoutExpired, KeyError, ValueError, OverflowError):
        return None, "did not answer (asleep or away)"
    if count < 1:
        return None, f"has no room ({spare:g} spare CPUs and {room_mb:g} MiB)"
    return (count, int(spare // count), mb, int(cpus // each_cpus)), ""


def each_mb(piece_mem_mb, least_mb):
    """The MiB a piece's VM gets: twice the piece's, as it holds its own kernel, page cache and
    clone too, or `least_mb` where that is more."""
    return int(max(2 * piece_mem_mb, least_mb))


def cpu_mb(piece_cpus, piece_mem_mb, least_mb):
    """The MiB a CPU of a piece's VM, rounded up: what each CPU of a machine to rent must hold."""
    return -(-each_mb(piece_mem_mb, least_mb) // int(max(piece_cpus, VM_CPUS)))


def failure(code):
    """The helper's reason, decided from its exit, never its diagnostic output."""
    return {LOST: "did not answer (asleep or away)", BATTERY: "is on battery", FULL: "has no room",
            BROKEN: "could not prepare or run the container", SHORT: "ran out of memory"}.get(
                code, f"failed (exit {code})")


def _known(alias, repo):
    """The commits the helper's copy of the repository has history up to; None: no answer."""
    try:
        reply = _remote(alias, "known", repo, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None if reply.returncode else reply.stdout.split()


def _parcel(cwd, default, known, recipe, parcel, turn=None):
    """Writes to the file `parcel` the recipe's files, the piece's script, `heads` (HEAD, then the
    origin branch the suite compares against) and a bundle of their history the helper lacks:
    the whole history the first time, which can outgrow memory; `turn(tar)` adds a turn's own."""
    revs = ["HEAD", *([f"refs/remotes/origin/{default}"] if default else [])]
    heads = subprocess.run(["git", "-C", str(cwd), "rev-parse", *revs], capture_output=True,
                           text=True, check=True).stdout.split()
    have = [sha for sha in known
            if not gitcall.git_out(cwd, "cat-file", "-e", sha + "^{commit}")[0]]
    with tarfile.open(fileobj=parcel, mode="w") as tar, tempfile.TemporaryFile() as bundle:
        tar.add(TOOLS / "piece.sh", "piece.sh")
        for name, (mode, data) in [*recipe.items(),
                                   ("heads", (0o644, (" ".join(heads) + "\n").encode()))]:
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
        if turn:
            turn(tar)
        # `git bundle` refuses one with nothing in it: the helper has every commit already.
        if not subprocess.run(["git", "-C", str(cwd), "bundle", "create", "-", *revs, "--not",
                               *have], stdout=bundle, stderr=subprocess.DEVNULL).returncode:
            bundle.seek(0)
            tar.addfile(tar.gettarinfo(arcname="repo.bundle", fileobj=bundle), bundle)


def start(piece_cpus, piece_mem_mb, cwd, log, command, turn=None, lasting=0):
    """(the suite sent to a helper that takes it, reason): an Away, or (None, why it runs here).
    `command` is what each of its pieces runs there (`piece`): one whose line is longer than one
    argument holds keeps the suite here. With `turn`, a model turn's (agentkit/machine_turn.py),
    it goes to a machine that takes turns, holding `piece_cpus` of it until it starts, not half,
    `turn(tar)` adding its own files to the parcel. None goes to a machine Google ends within
    `lasting` seconds of when it would start there."""
    try:
        aliases = machines.helpers()
    except config.Error:  # a config.toml mid-edit fails no run's suite: it runs here
        aliases = []
    if not aliases and not google_cloud.renting():
        return None, "no suite helper set up"
    ends = google_cloud.serving()

    def lasts(alias):
        """Whether Google ends `alias` `lasting` seconds from now or later: asked before its probe,
        and again once it is prepared, which may take 30 minutes, as the work starts then."""
        return ends.get(alias, math.inf) >= time.time() + lasting
    aliases = list(filter(lasts, aliases))
    # A checkout's repository is the one its main checkout has, wherever the suite runs.
    repo = hashlib.sha256(str(gitcall.main_checkout(cwd)).encode()).hexdigest()[:12]
    try:
        image, recipe = _recipe(cwd, repo) or (None, None)
    except ValueError as exc:
        log(f"WARN the suite helper cannot build suite_image: {exc}; the suite runs here")
        return None, f"the suite helper cannot build suite_image: {exc}"
    if not image:
        return None, "no recipe for the suite helper"
    code, branch = gitcall.git_out(cwd, "symbolic-ref", "-q", "--short", "HEAD")
    named, default = gitcall.git_out(cwd, "rev-parse", "--abbrev-ref", "origin/HEAD")
    programs = {program for program in orch.agent_programs() if config.harness_binary(program)}
    wide = 2 ** 64 - 1    # the shard, CPUs and MiB, unknown before the probe, at their widest
    away = Away("", secrets.token_hex(6), repo, image, wide, wide, wide, wide,
                "" if code else branch,
                "" if named else default.removeprefix("origin/"), " ".join(sorted(programs)))
    size = len(os.fsencode(piece(away, f"{wide}/{wide}", command)[-1]))
    if size >= MAX_ARG_STRLEN:
        return None, (f"a piece's line to the suite helper would take {size} bytes, more than "
                      f"one argument holds ({MAX_ARG_STRLEN}, Linux's MAX_ARG_STRLEN)")
    rooms = {alias: room(alias, piece_cpus, piece_mem_mb, _least(repo), bool(turn))
             for alias in aliases}
    why = {alias: reason for alias, (_, reason) in rooms.items()}
    # A suite splits into as many pieces as fit, so most room first; a turn takes one place and
    # is as fast on a busy machine, so least first, and one it leaves empty goes back
    # (google_cloud.IDLE_FOR): 12 turns kept three 72-core machines a tenth busy at €46 a day
    # (31 Oct 2026). On to the next where that refuses: its room can go between the probe and
    # `prepare`, and 40 checks in two hours then ran here on a host out of CPU (30 Oct 2026).
    for alias in sorted(filter(lambda alias: rooms[alias][0], aliases),
                        key=lambda alias: rooms[alias][0][0] * (1 if turn else -1)):
        fit = rooms[alias][0]
        away = away._replace(alias=alias, count=fit[0], cpus=fit[1], memory_mb=fit[2], most=fit[3])
        sent, known = LOST, _known(alias, repo)
        try:
            while known is not None:
                with tempfile.TemporaryFile() as parcel:
                    _parcel(cwd, away.default, known, recipe, parcel, turn)
                    parcel.seek(0)
                    # a new recipe's build fetches packages, a first suite sends the whole history
                    sent = _remote(alias, "prepare", away.key, image, repo,
                                   *([piece_cpus] if turn else []), stdin=parcel,
                                   timeout=1800).returncode
                # The copy went since `known` answered: the whole history, once.
                known = [] if known and sent == LACKS else None
        except (OSError, subprocess.SubprocessError):
            sent = LOST
        if not sent and lasts(alias):
            log(f"suite on {alias}: {fit[0]} pieces, {fit[1]} CPUs and {fit[2]} MiB each")
            return away, ""
        finish(away)
        why[alias] = failure(sent) if sent else "ends too soon"
    google_cloud.need(cpu_mb(piece_cpus, piece_mem_mb, _least(repo)))
    return None, " · ".join(f"helper {alias} {reason}" for alias, reason in why.items()) or (
        "no suite helper set up")


def _least(repo):
    """The MiB each VM of the repository's suites gets at least, more than one ran out of."""
    try:
        return int((config.STATE / f"helper-memory-{repo}").read_text())
    except (OSError, ValueError):
        return 0


def short(away):
    """A VM of the suite ran out of memory (`SHORT`): its repository's next ones each get twice
    as much; the MiB they get. Measured here, a piece's memory is its share of all the pieces' peak; there, each VM
    holds its own piece's peak."""
    least = 2 * away.memory_mb
    path = config.STATE / f"helper-memory-{away.repo}"
    # Suites of one repository's stacks end at once: each reads, raises and replaces it whole.
    with path.with_name(f".{path.name}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        least = max(least, _least(away.repo))
        temp = path.with_name(f".{path.name}.tmp")
        temp.write_text(f"{least}\n")
        temp.replace(path)
    return least


def _vm(away, shard):
    return f"ak-{away.key}-{shard.replace('/', '-')}"


def piece(away, shard, command):
    """The argv of one piece on the helper: it exits as the piece did, or a helper failure."""
    return _remote(away.alias, "run", away.key, away.image, _vm(away, shard), away.cpus,
                   away.memory_mb, away.repo, shard, away.branch, away.default, away.programs,
                   command)


def failed(away, shard, named="failed"):
    """The tests the ended piece of `shard` named as failed there (`AK_FAILED`), or with `named`
    "flaky" as failed, then passed (`AK_FLAKY`), from the file piece.sh gives it, never from
    what it printed; none where the helper does not answer."""
    try:
        reply = _remote(away.alias, "failed", away.key, _vm(away, shard), named, text=True,
                        errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [] if reply.returncode else list(dict.fromkeys(
        line.strip() for line in reply.stdout.splitlines() if line.strip()))


def finish(away):
    """The suite's tree leaves the helper; one that does not answer clears it a day later."""
    try:
        _remote(away.alias, "finish", away.key, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass
