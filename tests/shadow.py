"""Run one ak command as Python, then Go, then Python again, each sealed over a home it cannot
write, and name every way Go differs.

    python3 tests/shadow.py [--python BIN] [--go BIN|python] [--home DIR] -- <ak argv>

`--python` is this checkout's bin/ak unless named, `--home` is $HOME, and `--go` is AK_BIN, a
relative name read from the checkout, else go/bin/ak built as tests/test_go_keys.py builds it.
`--go python` puts Python in Go's place: the noise floor, where nothing may differ.

What the two Python runs disagree on belongs to the moment and is never compared.  A difference
is confirmed only if repeating the three runs straight away shows it again, else it is a flake.
Exit 1 if any is confirmed, 2 if no box or no Go can be built (then nothing runs), else 0.
Besides go/bin/ak and Go's own cache, when it builds Go, it writes nothing outside its scratch
folder.
"""

import argparse
import errno
import hashlib
import json
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
# akbin's refusing fakes, tmux, and the copiers that would carry a file to another machine
FAKES = (*akbin.REFUSED, "tmux", "scp", "rsync")
# Every box's seccomp filter, classic BPF as bwrap takes it.  It refuses a socket or a socket pair
# of the Unix family, either of which could reach a service of the host's by a path the read-only
# root still shows: the warm menu server's in HOME, a session bus.  It refuses io_uring, which
# makes one without either call, and every call of an architecture whose numbers it does not know:
# on a machine not named here, all of them, so no box can run.
ARCH, SOCKET, PAIR = {"x86_64": (0xC000003E, 41, 53),
                      "aarch64": (0xC00000B7, 198, 199)}.get(os.uname().machine, (0, 0, 0))
FILTER = b"".join(struct.pack("HBBI", *op) for op in (
    (0x20, 0, 0, 4), (0x15, 0, 8, ARCH),                # the architecture
    (0x20, 0, 0, 0), (0x35, 6, 0, 0x40000000),          # the call, by number: x32's refused
    (0x15, 5, 0, 425),                                  # io_uring_setup refused
    (0x15, 1, 0, SOCKET), (0x15, 0, 2, PAIR),           # socket(2) or socketpair(2) ...
    (0x20, 0, 0, 16), (0x15, 1, 0, socket.AF_UNIX),     # ... of the Unix family refused
    (0x06, 0, 0, 0x7FFF0000), (0x06, 0, 0, 0x50000 | errno.EACCES)))    # allowed, refused
# The first breath in every box: Landlock lets nothing open for writing outside the folders it is
# given, the run's own, then the command runs.  The read-only root still opens a named pipe or a
# device for writing, which would reach whatever of the host's reads it.  Its calls are 444-446 on
# every machine, and a kernel without Landlock builds no box.
SEAL = """import ctypes, os, struct, sys
libc, cut = ctypes.CDLL(None, use_errno=True), sys.argv.index("--")
def call(number, *args):
    if (done := libc.syscall(number, *args)) < 0:
        sys.exit("landlock: " + os.strerror(ctypes.get_errno()))
    return done
ruleset = call(444, struct.pack("Q", 2), 8, 0)     # it rules writing to a file, right 2
for path in sys.argv[1:cut]:
    call(445, ruleset, 1, struct.pack("=Qi", 2, os.open(path, os.O_PATH)), 0)
libc.prctl(38, 1, 0, 0, 0)     # no new privileges, which Landlock asks of what it binds
call(446, ruleset, 0)
os.execvp(sys.argv[cut + 1], sys.argv[cut + 1:])
"""
# A run in its box: the program, then all it detached, which bwrap's init would kill as the
# program ends, waited out till only that init and this shell are left.  The shell then becomes a
# Python that writes down its children's peak memory, which exec keeps: a child's peak starts
# from its parent's, some 20 MB for this script.
WAIT = """python=$1 peak=$2; shift 2
"$@"; code=$?
while set -- /proc/[0-9]*; [ $# -gt 2 ]; do sleep 0.1; done
exec "$python" -I -c 'import resource, sys
print(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
sys.exit(int(sys.argv[1]))' "$code" >"$peak"
"""


def box(home, scratch):
    """bwrap's words sealing a command over `home`, its environment, and its folder in `scratch`,
    whose `box` is all it may write besides HOME, /tmp and /dev: the fakes' logs, its pages."""
    folder = Path(tempfile.mkdtemp(dir=scratch))
    inside = folder / "box"
    for part in ("upper", "work", "box/bin", "box/logs", "box/runtime"):
        (folder / part).mkdir(parents=True, mode=0o700)
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
    # A shell hands bwrap the filter on descriptor 3.  /tmp comes before the overlay: a home under
    # /tmp is mounted inside the box's own.
    return ["sh", "-c", 'exec "$@" 3<"$0"', folder / "filter",
            "bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--seccomp", "3",
            "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
            "--bind", inside, inside,
            "--overlay-src", home, "--overlay", folder / "upper", folder / "work", home,
            "--", sys.executable, "-I", "-c", SEAL, home, "/tmp", "/dev", "/proc", inside,
            "--"], env, folder


def run(label, program, argv, home, scratch):
    """One run of `program` in its box, with no input and for at most CAP seconds: what it did."""
    command, env, folder = box(home, scratch)
    inside = folder / "box"
    began = time.monotonic()
    with (folder / "stdout").open("wb") as out, (folder / "stderr").open("wb") as err:
        proc = subprocess.Popen([*command, "sh", "-c", WAIT, "sh", sys.executable,
                                 inside / "peak", program, *argv],
                                stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env)
    try:
        code = proc.wait(CAP)
    except subprocess.TimeoutExpired:
        code = f"none (killed at {CAP // 60} minutes)"
    finally:
        proc.kill()     # past its cap, or this script was stopped: the box goes with it
        proc.wait()
    seconds, peak = time.monotonic() - began, _lines(inside / "peak")
    peak = f"{int(peak[0]) / 1024:.0f} MB at its peak" if peak else "its peak unread"
    record = inside / "handover"
    said = f", handed over: {' '.join(_lines(record))}" if record.exists() else ""
    print(f"{label}: exit {code}, {seconds:.1f} s, {peak}{said}", flush=True)
    return dict(code=code, handover=record.exists(),
                line={f"{stream}: {text}" for stream in ("stdout", "stderr")
                      for text in _lines(folder / stream)},
                home=touched(folder / "upper", home), page=set(_lines(inside / "pages")),
                call={f"{name} {shlex.join(json.loads(text))}" for name in FAKES
                      for text in _lines(inside / "logs" / f"{name}.log")})


def _lines(path):
    return path.read_text(errors="replace").splitlines() if path.exists() else []


def touched(upper, home):
    """Each path under `home` a run wrote, changed or removed, read off its overlay's upper layer:
    a written path is in it, a removed one is a whiteout, and a folder made again is opaque."""
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

    for name in os.listdir(upper):
        look(Path(name), False)
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
            digest = None   # its mode, changed or not, is all there is to tell
        return *state, found.st_mtime_ns, digest
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        # none there, gone while it was read (the home is live), or in a home folder its user
        # cannot enter
        return None


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=str(REPO / "bin" / "ak"))
    parser.add_argument("--go", default=os.environ.get("AK_BIN") and akbin.AK)
    parser.add_argument("--home", default=os.environ.get("HOME"))
    parser.add_argument("argv", nargs="*", metavar="-- <ak argv>")
    args = parser.parse_args()
    python, home = os.path.abspath(args.python), Path(args.home).resolve()
    # A shadow gives the host's real work way: the build and every run at nice 19.
    os.nice(19)
    # A stop ends the script through its `finally`, which removes its scratch folder.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    scratch = Path(tempfile.mkdtemp(prefix="shadow-", dir="/var/tmp"))
    try:
        command, env, _ = box(home, scratch)
        # bwrap, or the shell that finds no bwrap, says why
        if subprocess.run([*command, sys.executable, "-c", ""], env=env,
                          stdin=subprocess.DEVNULL).returncode:
            print("shadow: bwrap cannot build a box here, so nothing ran", file=sys.stderr)
            return 2
        go = python if args.go == "python" else args.go and os.path.abspath(args.go)
        if not go:
            go = str(REPO / "go" / "bin" / "ak")    # in the checkout, where Go finds it
            if subprocess.run(["go", "build", "-o", go, "-trimpath", "./cmd/ak"], env=ENV,
                              cwd=REPO / "go").returncode:
                return 2    # Go has said why, and nothing ran

        def three():
            return differences(*(run(label, program, args.argv, home, scratch) for label, program
                                 in (("python", python), ("go", go), ("python again", python))))

        first, again = three(), set()
        if first:
            print("repeated straight away, to confirm what differed:", flush=True)
            again = three()
        for kind, what in sorted(first ^ again):
            print(f"flake {kind}: {what}")
        for kind, what in sorted(first & again):
            print(f"{kind}: {what}")
        return 1 if first & again else 0
    finally:
        # Overlayfs leaves the `work` in a work folder unreadable, and an upper layer keeps the
        # modes of the home's folders it copied.  The system's chmod: the caller's PATH may lack it.
        subprocess.run(["chmod", "-R", "u+rwx", scratch], env={"PATH": os.defpath})
        shutil.rmtree(scratch)


if __name__ == "__main__":
    sys.exit(main())
