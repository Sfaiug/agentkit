"""Run one ak command as Python, then Go, then Python again, each sealed over a home it cannot
write, and name every way Go differs.

    python3 tests/shadow.py [--python BIN] [--go BIN|python] [--home DIR] -- <ak argv>
    python3 tests/shadow.py [those options] --record FILE [-- <ak argv>]

`--python` is this checkout's bin/ak unless named, `--home` is $HOME, and `--go` is AK_BIN, a
relative name read from the checkout, else go/bin/ak built as tests/test_go_keys.py builds it.
`--go python` puts Python in Go's place: the noise floor, where nothing may differ.

What the two Python runs disagree on belongs to the moment and is never compared.  A difference
is confirmed only if repeating the three runs straight away shows it again, else it is a flake.

`--record` writes FILE whole, once, at the end, a stop's too: for each command, whether it ran --
one a cap or a stop cut off did not -- and what it confirmed and what flaked, and why nothing ran
if nothing did.  Without an ak argv it shadows each of `PREVIEWS`, side by side, in half an hour
at most, its box's probe and Go's build included, and prints a line for each in their order:
tests/live.sh has it do so on each live check of a commit.

Exit 1 if any is confirmed, 2 if no box or no Go can be built (then nothing runs) or a file a
run touched cannot be read, 130 if stopped, else 0.
Besides FILE, go/bin/ak and Go's own cache, when it builds Go, it writes nothing outside its
scratch folder.
"""

import argparse
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True  # the helpers' bytecode would be a write outside the scratch folder
from fixtures import akbin  # noqa: E402
from test_go import ENV  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CAP = 600   # seconds a run may take, what it detached included
# What a live check shadows: commands that only read, which each home answers from its records.
PREVIEWS = (("watch", "--dry-run"), ("doctor",), ("run", "gc", "--dry-run"), ("run", "status"),
            ("orch", "list"))
WHOLE = 30 * 60     # seconds the previews may take in all: the live check's suite waits on them
# akbin's refusing fakes, tmux, and the copiers that would carry a file to another machine
FAKES = (*akbin.REFUSED, "tmux", "scp", "rsync")
# The host's memory and load, which ak's admission reads and `ak run status` prints: read once as
# the shadow begins, and so in each of its runs, else Go would differ by the moment it ran in.
MOMENT = ("meminfo", "loadavg")
# The calls a box makes only with these arguments, each (index, value, whether it must equal or
# differ from it), else they are refused.  A socket or a socket pair of the Unix family could reach
# a service of the host's by a path the read-only root still shows: the warm menu server's in HOME,
# a session bus.  The box's user owns the host's processes too, and Landlock keeps only signals and
# traces in, so a box sets limits, priority, I/O priority, scheduling and CPUs only of the caller
# itself, as `nice` and a raised file limit do: process 0, of the kind PRIO_PROCESS or
# IOPRIO_WHO_PROCESS, as another kind names a whole group or user.
UNIX, OWN = ((0, socket.AF_UNIX, False),), ((0, 0, True),)
RULED = dict(socket=UNIX, socketpair=UNIX, setpriority=((0, 0, True), (1, 0, True)),
             ioprio_set=((0, 1, True), (1, 0, True)), prlimit64=OWN, sched_setparam=OWN,
             sched_setscheduler=OWN, sched_setattr=OWN, sched_setaffinity=OWN)
# Each machine's architecture and the numbers of its calls `RULED` names.  On a machine not named
# here, every call is refused, so no box can run.
ARCH, NUMBER = {
    "x86_64": (0xC000003E, dict(socket=41, socketpair=53, setpriority=141, ioprio_set=251,
                                prlimit64=302, sched_setparam=142, sched_setscheduler=144,
                                sched_setattr=314, sched_setaffinity=203)),
    "aarch64": (0xC00000B7, dict(socket=198, socketpair=199, setpriority=140, ioprio_set=30,
                                 prlimit64=261, sched_setparam=118, sched_setscheduler=119,
                                 sched_setattr=274, sched_setaffinity=122)),
}.get(os.uname().machine, (0, {}))


def _filter():
    """Every box's seccomp filter, classic BPF as bwrap takes it: `RULED`, and io_uring refused,
    which makes a socket without either call, as is every call of another architecture or x32's.
    An argument is read by its low 32 bits: the kernel reads a pid, a kind or a family as an int."""
    allowed, refused = (0x06, 0, 0, 0x7FFF0000), (0x06, 0, 0, 0x50000 | errno.EACCES)
    program = [(0x20, 0, 0, 4), (0x15, 0, "refused", ARCH), (0x20, 0, 0, 0),
               (0x35, "refused", 0, 0x40000000), (0x15, "refused", 0, 425),
               *((0x15, name, 0, number) for name, number in NUMBER.items()), allowed]
    at = {}     # where each jump to a name lands
    for name in NUMBER:
        at[name] = len(program)
        for index, value, equal in RULED[name]:
            program += [(0x20, 0, 0, 16 + 8 * index),
                        (0x15, 0, "refused", value) if equal else (0x15, "refused", 0, value)]
        program.append(allowed)
    at["refused"] = len(program)
    program.append(refused)
    return b"".join(struct.pack("HBBI", code, *(at[jump] - n - 1 if isinstance(jump, str) else jump
                                                for jump in (true, false)), k)
                    for n, (code, true, false, k) in enumerate(program))


FILTER = _filter()
# The first breath in every box: Landlock lets nothing open for writing outside the folders it is
# given, the run's own, and no signal or trace leave the box, then the command runs.  The read-only
# root still opens a named pipe or a device for writing, which would reach whatever of the host's
# reads it.  The box shares the host's process table, so ak reads each process there as it is: by
# its /proc/<pid>/stat, and by kill(pid, 0), which Landlock answers with EPERM for one alive
# outside, as ak reads alive.  Its calls are 444-446 on every machine, and a kernel whose Landlock
# cannot keep signals in, below ABI 6, builds no box.
SEAL = """import ctypes, os, struct, sys
libc, cut = ctypes.CDLL(None, use_errno=True), sys.argv.index("--")
def call(number, *args):
    if (done := libc.syscall(number, *args)) < 0:
        sys.exit("landlock: " + os.strerror(ctypes.get_errno()))
    return done
if (abi := call(444, None, 0, 1)) < 6:
    sys.exit(f"landlock: ABI {abi}, which cannot keep signals inside a box, as ABI 6 can")
# it rules writing to a file, right 2, and signals, scope 2
ruleset = call(444, struct.pack("QQQ", 2, 0, 2), 24, 0)
for path in sys.argv[1:cut]:
    call(445, ruleset, 1, struct.pack("=Qi", 2, os.open(path, os.O_PATH)), 0)
libc.prctl(38, 1, 0, 0, 0)     # no new privileges, which Landlock asks of what it binds
libc.prctl(36, 1, 0, 0, 0)     # subreaper: what the command's children detach is its to reap
call(446, ruleset, 0)
os.execvp(sys.argv[cut + 1], sys.argv[cut + 1:])
"""
# A run in its box: the program, then all it detached, waited out.  The seal made this shell their
# reaper, so each is its child once what started it ends, and a Python the shell becomes, which
# keeps them, waits till it has no child left, none of the run's.  Their peaks are its children's
# too, and it writes them down: a child's peak starts from its parent's, some 20 MB for this
# script.  The shell's own words, as its `Killed` for what is killed at the cap, go nowhere: only
# the program's are compared.  dash says it on the killed command's stderr, so the program is a
# subshell that becomes it.
WAIT = """python=$1 peak=$2; shift 2
exec 3>&2 2>/dev/null
("$@" 2>&3 3>&-); code=$?
exec "$python" -I -c 'import os, resource, sys
try:
    while True:
        os.wait()
except ChildProcessError:
    print(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
sys.exit(int(sys.argv[1]))' "$code" >"$peak"
"""
# A run's keeper, outside its box and so out of reach of the box's signals: bwrap's parent, and a
# subreaper, so the parent of all the box runs once the shell waiting in it is gone, as what that
# shell ran may end it.  Once bwrap ends, it ends all left.  A SIGTERM, the shadow's or at the
# shadow's end, halts the box first: it kills all the box runs but that shell and wakes the shell,
# which what it ran may have stopped, till it writes down the peak and ends, for 10 seconds at most.
# It waits for a SIGTERM and never handles one, so no stop cuts its cleanup short.
KEEP = """import ctypes, os, signal, subprocess, sys, time
WAKE = {signal.SIGTERM, signal.SIGCHLD}
signal.pthread_sigmask(signal.SIG_BLOCK, WAKE)
libc = ctypes.CDLL(None)
libc.prctl(36, 1, 0, 0, 0)                  # subreaper
libc.prctl(1, signal.SIGTERM, 0, 0, 0)      # its parent's death, a SIGTERM
def below():
    parent = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/stat") as stat:
                parent[int(pid)] = int(stat.read().rsplit(")", 1)[1].split()[1])
        except OSError:
            pass    # ended meanwhile
    under = {os.getpid()}
    while more := {pid for pid, up in parent.items() if up in under} - under:
        under |= more
    return {pid: parent[pid] for pid in under - {os.getpid()}}
def kill(pid, sig):
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass    # ended meanwhile
bwrap = subprocess.Popen(sys.argv[1:],
                         preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_UNBLOCK, WAKE))
while bwrap.poll() is None and signal.sigwaitinfo(WAKE).si_signo == signal.SIGCHLD:
    pass    # what ended was not bwrap
end = time.monotonic() + 10
while bwrap.poll() is None and time.monotonic() < end:
    for pid, up in below().items():
        if pid != bwrap.pid:
            kill(pid, signal.SIGCONT if up == bwrap.pid else signal.SIGKILL)
    time.sleep(0.1)
while left := below():
    for pid in left:
        kill(pid, signal.SIGKILL)
    os.wait()
sys.exit(bwrap.returncode)
"""


def box(home, scratch):
    """bwrap's words sealing a command over `home`, its environment, and its folder in `scratch`,
    whose `box` is all it may write besides HOME, /tmp and /dev: the fakes' logs, its pages.  Its
    /proc shows the MOMENT `scratch` holds."""
    folder = Path(tempfile.mkdtemp(dir=scratch))
    inside = folder / "box"
    for part in ("upper", "work", "box/bin", "box/logs", "box/runtime"):
        (folder / part).mkdir(parents=True, mode=0o700)
    # The box's HOME shows the mode and extended attributes of the upper layer's folder, not the
    # home's, so that folder starts as the home: a run then changes HOME only where it changes it.
    # Its attributes become the home's exactly, a default ACL it inherited from `scratch` gone.  The
    # user's own come first, as only they need a folder its user may write, then the rest, an
    # access ACL among them, which sets the mode as chmod does; the mode comes last.
    upper, attributes = folder / "upper", _attributes(home)
    for name in _attributes(upper).keys() - attributes.keys():
        os.removexattr(upper, name)
    for name, value in sorted(attributes.items(), key=lambda item: not item[0].startswith("user.")):
        if value is not None:
            os.setxattr(upper, name, value)
    upper.chmod(stat.S_IMODE(home.stat().st_mode))
    for name in FAKES:
        fake = inside / "bin" / name
        fake.write_text(akbin.REFUSE.format(python=shlex.quote(sys.executable), name=name,
                                            log=shlex.quote(str(inside / "logs" / f"{name}.log"))))
        fake.chmod(0o755)
    (folder / "filter").write_bytes(FILTER)
    # Not the caller's own seat, run or tmux: a run that inherits them acts as somebody's.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("AK_", "AGENTKIT_", "TMUX"))}
    env.update(HOME=str(home),
               PATH=os.pathsep.join([str(inside / "bin"), env.get("PATH", os.defpath)]),
               # The box's own: a caller's TMPDIR is read-only here, which Python's tempfile
               # passes over and Go's os.TempDir does not.
               TMPDIR="/tmp",
               # empty: no user systemd manager or session bus to find
               XDG_RUNTIME_DIR=str(inside / "runtime"),
               # Pages go nowhere, and each one aimed at a configured webhook leaves a line here.
               AK_NOTIFY_SINK="dry-run", AK_NOTIFY_SINK_LOG=str(inside / "pages"),
               AK_HANDOVER=str(inside / "handover"))
    # A shell hands bwrap the filter on descriptor 3.  All --unshare-all unshares but the process
    # table, whose /proc the read-only root shows, the MOMENT over it.  /tmp comes before the
    # overlay: a home under /tmp is mounted inside the box's own.
    return ["sh", "-c", 'exec "$@" 3<"$0"', folder / "filter",
            "bwrap", "--unshare-user-try", "--unshare-ipc", "--unshare-net", "--unshare-uts",
            "--unshare-cgroup-try", "--die-with-parent", "--new-session", "--seccomp", "3",
            "--ro-bind", "/", "/", "--dev", "/dev",
            *(arg for name in MOMENT for arg in ("--ro-bind", scratch / name, f"/proc/{name}")),
            "--tmpfs", "/tmp", "--bind", inside, inside,
            "--overlay-src", home, "--overlay", folder / "upper", folder / "work", home,
            "--", sys.executable, "-I", "-c", SEAL, home, "/tmp", "/dev", inside, "--"], env, folder


def run(label, program, argv, home, scratch):
    """One run of `program` in its box, with no input and for at most CAP seconds: what it did."""
    command, env, folder = box(home, scratch)
    inside, keeper = folder / "box", None
    began = time.monotonic()
    try:
        with (folder / "stdout").open("wb") as out, (folder / "stderr").open("wb") as err:
            # Its own session keeps the box from a stop meant for this script, as a terminal's
            # ^C, till its keeper halts it.
            keeper = subprocess.Popen([sys.executable, "-I", "-c", KEEP, *command, "sh", "-c",
                                       WAIT, "sh", sys.executable, inside / "peak", program,
                                       *argv], start_new_session=True,
                                      stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env)
        code, cut = keeper.wait(CAP), False
    except subprocess.TimeoutExpired:
        code, cut = f"none (killed at {CAP // 60} minutes)", True
    finally:
        # past the cap, or this script was stopped, the box begun or not: its keeper halts it,
        # and its shell writes down the peak
        if keeper:
            keeper.terminate()
            keeper.wait()
    seconds, peak = time.monotonic() - began, _lines(inside / "peak")
    peak = f"{int(peak[0]) / 1024:.0f} MB at its peak" if peak else "its peak unread"
    record = inside / "handover"
    said = f", handed over: {' '.join(_lines(record))}" if record.exists() else ""
    print(f"{label}: exit {code}, {seconds:.1f} s, {peak}{said}", flush=True)
    return dict(code=code, cut=cut, handover=record.exists(),
                line={f"{stream}: {text}" for stream in ("stdout", "stderr")
                      for text in _lines(folder / stream)},
                home=touched(folder / "upper", home), page=set(_lines(inside / "pages")),
                call={f"{name} {shlex.join(json.loads(text))}" for name in FAKES
                      for text in _lines(inside / "logs" / f"{name}.log")})


def _lines(path):
    return path.read_text(errors="replace").splitlines() if path.exists() else []


def touched(upper, home):
    """Each path of `home`, `.` itself, a run wrote, changed or removed, read off its overlay's
    upper layer: a written path is in it, a removed one is a whiteout, and a folder made again is
    opaque."""
    facts = set()

    def look(path, hidden):
        above, below = upper / path, home / path
        if not hidden and not os.path.lexists(above):
            return      # the home's own shows through, and so does all beneath it
        was, now = _state(below), _state(above)
        if was != now:
            verb = "wrote" if was is None else "removed" if now is None else "changed"
            facts.add(f"{verb} {path}")
        folder = now is not None and stat.S_ISDIR(now[0])
        if folder:
            os.chmod(above, stat.S_IMODE(now[0]) | stat.S_IRWXU)     # the scratch's, to read
        # The home's entries show only through a folder of the upper layer that is not opaque.
        # Where they do not show, each one is gone unless the run wrote it again.
        shows = folder and not hidden and "user.overlay.opaque" not in os.listxattr(above)
        names = set(os.listdir(above)) if folder else set()
        if not shows and was is not None and stat.S_ISDIR(was[0]):
            names |= _names(below)
        for name in names:
            look(path / name, not shows)

    look(Path("."), False)
    return facts


def _state(path):
    """What a run can change of a path, None where there is none: its kind, mode and extended
    attributes, and a link's target or a file's time and bytes.  Never a folder's time: each entry
    written in it moves it."""
    try:
        found = path.lstat()
        if stat.S_ISCHR(found.st_mode) and found.st_rdev == 0:
            return None     # overlayfs's whiteout
        state = found.st_mode, _attributes(path)
        if stat.S_ISLNK(found.st_mode):
            return *state, os.readlink(path)
        if not stat.S_ISREG(found.st_mode):
            return state
        try:
            with path.open("rb") as opened:
                digest = hashlib.file_digest(opened, "sha256").digest()
        except PermissionError:
            digest = _read_as_root(path)
        return *state, found.st_mtime_ns, digest
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        # none there, gone while it was read (the home is live), or in a home folder its user
        # cannot enter
        return None


def _read_as_root(path):
    """The sha256 of a file its user cannot read, whose bytes a run may change before putting back
    its mode and time.  Root of a user namespace of the script's own reads past the mode of a file
    whose owner and group are its user's; where it cannot, the runs cannot be judged."""
    try:
        with subprocess.Popen(["unshare", "--map-root-user", "cat", "--", path],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as cat:
            digest = hashlib.file_digest(cat.stdout, "sha256").digest()
        if cat.returncode == 0:
            return digest
    except OSError:
        pass    # no unshare to run
    path.lstat()    # gone since, as the home is live: none there
    print(f"shadow: cannot read {path}, even through unshare, so whether a run changed it is "
          "unknown", file=sys.stderr)
    raise SystemExit(2)


def _attributes(path):
    """A path's extended attributes but overlayfs's own, which its upper layer alone holds: each
    one's value, or None where its user cannot read it."""
    found = {}
    for name in os.listxattr(path, follow_symlinks=False):
        if not name.startswith("user.overlay."):
            try:
                found[name] = os.getxattr(path, name, follow_symlinks=False)
            except PermissionError:
                found[name] = None
            except OSError as error:    # ENODATA: removed since it was listed, as the home is live
                if error.errno != errno.ENODATA:
                    raise
    return found


def _names(folder):
    """A home folder's entries: none of one its user cannot read, whose removal names it alone."""
    try:
        return set(os.listdir(folder))
    except PermissionError:
        return set()


def differences(first, go, again):
    """Each way `go` differs from the Python runs either side of it, as (kind, what)."""
    found = set()
    if go["code"] != first["code"] == again["code"]:
        found.add(("exit", f"go {go['code']}, python {first['code']}"))
    if go["handover"]:
        found.add(("hand-over", "go left a hand-over record"))
    for kind in ("line", "home", "page", "call"):     # what a run did, compared fact by fact
        before, ours, after = (each[kind] for each in (first, go, again))
        found |= {(kind, f"only python: {fact}") for fact in (before & after) - ours}
        found |= {(kind, f"only go: {fact}") for fact in ours - before - after}
    return found


def shadow(argv, python, go, home, scratch):
    """Shadow one ak command, telling how each run went as it ends: what it confirmed and what
    flaked, each as (kind, what), and whether a cap cut off any of its runs."""
    runs = []

    def three():
        runs.extend(run(label, program, argv, home, scratch) for label, program
                    in (("python", python), ("go", go), ("python again", python)))
        return differences(*runs[-3:])

    first, again = three(), set()
    if first:
        print("repeated straight away, to confirm what differed:", flush=True)
        again = three()
    for kind, what in sorted(first ^ again):
        print(f"flake {kind}: {what}")
    for kind, what in sorted(first & again):
        print(f"{kind}: {what}")
    return first & again, first ^ again, any(done["cut"] for done in runs)


def ready(go, python, home, scratch, until):
    """The Go to run, and why nothing can run where nothing can: no box, or no Go, built by
    `until` on the monotonic clock."""

    def done(argv, **kwargs):
        try:
            return not subprocess.run(argv, timeout=until - time.monotonic(), **kwargs).returncode
        except (OSError, subprocess.TimeoutExpired):
            return False

    command, env, _ = box(home, scratch)
    # bwrap, the shell that finds no bwrap, or the seal says what failed
    if not done([*command, sys.executable, "-c", ""], env=env, stdin=subprocess.DEVNULL):
        return None, "no box can be built here"
    if go:
        return python if go == "python" else os.path.abspath(go), None
    go = str(REPO / "go" / "bin" / "ak")    # in the checkout, where Go finds it
    # Go says why it failed, if it ran
    if not done(["go", "build", "-o", go, "-trimpath", "./cmd/ak"], env=ENV, cwd=REPO / "go"):
        return None, "no Go was built"
    return go, None


def previews(found, python, go, home, scratch, until):
    """Put in `found` what each of PREVIEWS found by `until`, or by a stop: each is shadowed by a
    run of this script of its own, side by side, which ends through its own `finally`."""
    shadows = []
    try:
        for n, argv in enumerate(PREVIEWS):
            written = scratch / f"{n}.json"
            shadows.append((written, subprocess.Popen(
                [sys.executable, __file__, "--python", python, "--go", go, "--home", home,
                 "--record", written, "--", *argv],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)))
        for _, proc in shadows:
            try:
                proc.wait(max(0, until - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
    finally:
        for _, proc in shadows:
            proc.terminate()
        for _, proc in shadows:
            proc.wait()
        for n, (written, _) in enumerate(shadows):
            if written.exists():
                found[n] = json.loads(written.read_text())["previews"][0]


def _on_stop(handler):
    """Have a stop, SIGTERM or SIGINT, call `handler` from now on."""
    for each in (signal.SIGTERM, signal.SIGINT):
        signal.signal(each, handler)


def _stopped(*_):
    """End the script through its `finally`s, which halt the box and remove the scratch folder.
    A second stop waits for them: a preview's run is stopped by its parent and by the check's own
    stop alike."""
    _on_stop(signal.SIG_IGN)
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=str(REPO / "bin" / "ak"))
    parser.add_argument("--go", default=os.environ.get("AK_BIN") and akbin.AK)
    parser.add_argument("--home", default=os.environ.get("HOME"))
    parser.add_argument("--record", metavar="FILE")
    parser.add_argument("argv", nargs="*", metavar="-- <ak argv>")
    args = parser.parse_args()
    python, home = os.path.abspath(args.python), Path(args.home).resolve()
    every = bool(args.record and not args.argv)
    found = [dict(ak=list(argv), ran=False, differences=[], flakes=[])
             for argv in (PREVIEWS if every else [args.argv])]
    why = None
    # A shadow gives the host's real work way: the build and every run at nice 19.
    os.nice(19)
    _on_stop(_stopped)
    until = time.monotonic() + WHOLE if every else math.inf
    scratch = Path(tempfile.mkdtemp(prefix="shadow-", dir="/var/tmp"))
    try:
        for name in MOMENT:
            (scratch / name).write_bytes((Path("/proc") / name).read_bytes())
        go, why = ready(args.go, python, home, scratch, until)
        confirmed = False
        if why:
            print(f"shadow: {why}, so nothing ran", file=sys.stderr)
        elif every:
            previews(found, python, go, home, scratch, until)
            confirmed = any(each["differences"] for each in found)
        else:
            confirmed, flakes, cut = shadow(args.argv, python, go, home, scratch)
            if not cut:
                found[0].update(ran=True, differences=sorted(confirmed), flakes=sorted(flakes))
        for each in found if every else ():
            print(f"shadow: ak {shlex.join(each['ak'])}: " + (
                f"ran, differences: {len(each['differences'])}, flakes: {len(each['flakes'])}"
                if each["ran"] else "not run"))
        return 2 if why else 1 if confirmed else 0
    except KeyboardInterrupt:   # a stop, as a preview's run gets at the cap, has nothing to tell
        return 130
    finally:
        _on_stop(signal.SIG_IGN)    # a stop waits for the cleanup and the record
        # Overlayfs leaves the `work` in a work folder unreadable, and an upper layer keeps the
        # modes of the home's folders it copied.  The system's chmod: the caller's PATH may lack it.
        subprocess.run(["chmod", "-R", "u+rwx", scratch], env={"PATH": os.defpath})
        shutil.rmtree(scratch)
        # On every way out, a stop's too: what ended, and the rest not run.  Last, so a write
        # that fails leaves no scratch behind.
        if args.record:
            written = Path(f"{args.record}.tmp")    # a reader finds all of it or none
            written.write_text(json.dumps({"nothing_ran": why, "previews": found}, indent=1))
            written.replace(args.record)


if __name__ == "__main__":
    sys.exit(main())
