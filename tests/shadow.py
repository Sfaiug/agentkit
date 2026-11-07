"""Run one ak command as Python, then Go, then Python again, each sealed over a home it cannot
write, and name every way Go differs.

    python3 tests/shadow.py [--python BIN] [--go BIN|python] [--home DIR] -- <ak argv>

`--python` is this checkout's bin/ak unless named, `--home` is $HOME, and `--go` is AK_BIN, a
relative name read from the checkout, else go/bin/ak built as tests/test_go_keys.py builds it.
`--go python` puts Python in Go's place: the noise floor, where nothing may differ.

Each run has a bubblewrap box of its own, and nothing ever runs outside one.  Its HOME is an
overlay over the home, and everything it writes lands in a fresh folder under /var/tmp.  What
the two Python runs disagree on belongs to the moment and is never compared.  A difference is
confirmed only if repeating the three runs straight away shows it again; one that does not is a
flake.  Each is printed with its kind, and the script exits 1 if any is confirmed, 2 if no box
can be built or Go cannot be built (then nothing runs), else 0.
"""

import argparse
from collections import namedtuple
import hashlib
import json
import os
from pathlib import Path
import resource
import select
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

from fixtures import akbin
from test_go import ENV

REPO = Path(__file__).resolve().parents[1]
CAP = 600   # seconds a run may take, what it detached included
# akbin's refusing fakes, and the copiers that would carry a file off to another machine
FAKES = (*akbin.REFUSED, "tmux", "scp", "rsync")
# The caller's own seat, run and tmux: a run that inherits them acts as somebody's.
CALLERS = ("AK_", "AGENTKIT_", "TMUX")
KINDS = ("line", "home", "page", "call")    # what a run did, compared fact by fact
# The program, then all it detached, which bwrap's init would kill as the program ends, waited out
# till only that init and this shell are left: a shell, so a run's peak memory is the program's.
WAIT = '"$@"; code=$?; while set -- /proc/[0-9]*; [ $# -gt 2 ]; do sleep 0.1; done; exit $code'

Run = namedtuple("Run", ("code", "handover", *KINDS))


def box(home, scratch):
    """bwrap's words sealing a command over `home`, its environment, and its folder in `scratch`:
    the overlay's upper and work folders, and `box`, the one folder it may write besides its
    HOME, /tmp and /dev, holding the fakes' logs and its notifications."""
    folder = Path(tempfile.mkdtemp(dir=scratch))
    inside = folder / "box"
    for part in ("upper", "work", "box/bin", "box/logs", "box/runtime"):
        (folder / part).mkdir(parents=True, mode=0o700)
    for name in FAKES:
        fake = inside / "bin" / name
        fake.write_text(akbin.REFUSE.format(python=shlex.quote(sys.executable), name=name,
                                            log=shlex.quote(str(inside / "logs" / f"{name}.log"))))
        fake.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if not key.startswith(CALLERS)}
    env.update(HOME=str(home), PATH=os.pathsep.join([str(inside / "bin"), env.get("PATH", os.defpath)]),
               # the box's own /tmp, which Go takes from TMPDIR without asking whether it can write there
               TMPDIR="/tmp",
               # empty: no user systemd manager or session bus to find
               XDG_RUNTIME_DIR=str(inside / "runtime"),
               # Pages go nowhere, and each one aimed at a configured webhook leaves a line here.
               AK_NOTIFY_SINK="dry-run", AK_NOTIFY_SINK_LOG=str(inside / "pages"),
               AK_HANDOVER=str(inside / "handover"))
    # /tmp before the overlay: a home under /tmp is mounted inside the box's own.
    return ["bwrap", "--unshare-all", "--die-with-parent", "--new-session",
            "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
            "--bind", inside, inside,
            "--overlay-src", home, "--overlay", folder / "upper", folder / "work", home,
            "--"], env, folder


def boxable(home, scratch):
    """Whether a box over `home` can be built here, saying why not."""
    command, env, _ = box(home, scratch)
    try:
        done = subprocess.run([*command, sys.executable, "-c", ""], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        why = done.returncode and (done.stderr.strip() or f"bwrap exited {done.returncode}")
    except (OSError, subprocess.TimeoutExpired) as error:
        why = str(error)
    if why:
        print(f"shadow: no box can be built here, so nothing ran: {why}", file=sys.stderr)
    return not why


def built():
    """go/bin/ak, built from this checkout, where Go finds its checkout; None if it fails."""
    program = REPO / "go" / "bin" / "ak"
    try:
        done = subprocess.run(["go", "build", "-o", program, "-trimpath", "./cmd/ak"], env=ENV,
                              cwd=REPO / "go", capture_output=True, text=True)
        why = done.returncode and done.stderr.strip()
    except OSError as error:
        why = str(error)
    if why:
        print(f"shadow: Go cannot be built, so nothing ran: {why}", file=sys.stderr)
        return None
    return str(program)


def run(label, program, argv, home, scratch):
    """One run of `program` in its box, with no input and for at most CAP seconds, and what it did."""
    command, env, folder = box(home, scratch)
    inside = folder / "box"
    began = time.monotonic()
    with (folder / "stdout").open("wb") as out, (folder / "stderr").open("wb") as err:
        proc = subprocess.Popen([*command, "sh", "-c", WAIT, "sh", program, *argv],
                                stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env)
    # Waited by hand: Popen's own wait drops the rusage that has the run's peak memory.
    waited = os.pidfd_open(proc.pid)
    try:
        ended = select.select([waited], [], [], CAP)[0]
    finally:
        # Killed if it ran too long, or this script was stopped.  Not yet waited, its pid is
        # still its own, even once it has ended.
        os.kill(proc.pid, signal.SIGKILL)
        _, status, usage = os.wait4(proc.pid, 0)
        proc.returncode = os.waitstatus_to_exitcode(status)
        os.close(waited)
    code = proc.returncode if ended else f"killed after {CAP // 60} minutes"
    # A run's peak takes in this script's own, which its box was forked from: a run that never
    # rose above that is known only to be at most that.
    ours = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"{label}: exit {code}, {time.monotonic() - began:.1f} s, "
          f"{'at most ' if usage.ru_maxrss <= ours else ''}{usage.ru_maxrss / 1024:.0f} MB "
          "at its peak", flush=True)
    handover = inside / "handover"
    return Run(code, handover.read_text(errors="replace") if handover.exists() else None,
               line={f"{stream}: {text}" for stream in ("stdout", "stderr")
                     for text in _lines(folder / stream)},
               home=touched(folder / "upper", home), page=set(_lines(inside / "pages")),
               call={f"{name} {shlex.join(json.loads(text))}" for name in FAKES
                     for text in _lines(inside / "logs" / f"{name}.log")})


def _lines(path):
    return path.read_text(errors="replace").splitlines() if path.exists() else []


def touched(upper, home):
    """Each path under `home` a run wrote, changed or removed, read off its overlay's upper
    layer.  That layer holds every path the run wrote, and marks a removed one with a whiteout.
    A folder the run removed and made again is marked opaque, and hides all the home held in it."""
    facts = set()

    def look(path, hidden):
        above, below = upper / path, home / path
        if not hidden and not os.path.lexists(above):
            return      # the home's own shows through, and so does all beneath it
        was, now = _state(below), _state(above)
        if was != now:
            facts.add(f"{'wrote' if was is None else 'removed' if now is None else 'changed'} {path}")
        folder = now is not None and stat.S_ISDIR(now[0])
        # The home's entries show only through a folder of the upper layer that is not opaque.
        # Where they do not show, each one is gone unless the run wrote it again.
        shows = folder and not hidden and not _opaque(above)
        names = set(os.listdir(above)) if folder else set()
        if not shows and was is not None and stat.S_ISDIR(was[0]):
            names |= set(os.listdir(below))
        for name in names:
            look(path / name, not shows)

    for name in os.listdir(upper):
        look(Path(name), False)
    return facts


def _state(path):
    """What a run can change of a path, None where there is none: its kind and mode, and a link's
    target or a file's time and bytes.  Never a folder's time, which each entry written in it
    moves."""
    try:
        found = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    if stat.S_ISCHR(found.st_mode) and found.st_rdev == 0:
        return None     # overlayfs's whiteout
    if stat.S_ISLNK(found.st_mode):
        return found.st_mode, os.readlink(path)
    if stat.S_ISREG(found.st_mode):
        with path.open("rb") as opened:
            return found.st_mode, found.st_mtime_ns, hashlib.file_digest(opened, "sha256").digest()
    return found.st_mode,


def _opaque(folder):
    try:
        return os.getxattr(folder, "user.overlay.opaque", follow_symlinks=False) == b"y"
    except OSError:
        return False


def differences(first, go, again):
    """Each way `go` differs from the Python runs either side of it, as (kind, what)."""
    found = set()
    if go.code != first.code == again.code:
        found.add(("exit", f"go exits {go.code}, python {first.code}"))
    if go.handover is not None:
        found.add(("hand-over", " ".join(go.handover.split()) or "an empty record"))
    for kind in KINDS:
        before, ours, after = (getattr(each, kind) for each in (first, go, again))
        found |= {(kind, f"only python: {fact}") for fact in (before & after) - ours}
        found |= {(kind, f"only go: {fact}") for fact in ours - before - after}
    return found


def remove(folder):
    """Remove the scratch folder.  Overlayfs leaves the `work` in a work folder unreadable, and an
    upper layer copies the modes of the home's folders, so each folder is opened up first."""
    for parent, names, _ in os.walk(folder):
        for name in names:
            path = os.path.join(parent, name)
            if not os.path.islink(path):
                os.chmod(path, 0o700)
    shutil.rmtree(folder)


def main():
    parser = argparse.ArgumentParser(usage=__doc__.split("\n\n")[1].strip())
    parser.add_argument("--python", default=str(REPO / "bin" / "ak"))
    parser.add_argument("--go")
    parser.add_argument("--home", default=os.environ.get("HOME"))
    own = sys.argv[1:]
    if "--" not in own:
        parser.error("the ak command comes after --")
    args, argv = parser.parse_args(own[:own.index("--")]), own[own.index("--") + 1:]
    python, home = os.path.abspath(args.python), Path(args.home).resolve()
    # A shadow gives the host's real work way: the build and every run at nice 19.
    os.nice(19)
    # A stop ends the script through its `finally`, which removes its scratch folder.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    scratch = Path(tempfile.mkdtemp(prefix="shadow-", dir="/var/tmp"))
    try:
        if not boxable(home, scratch):
            return 2
        go = (python if args.go == "python" else os.path.abspath(args.go) if args.go else
              akbin.AK if os.environ.get("AK_BIN") else built())
        if go is None:
            return 2

        def three():
            return differences(*(run(label, program, argv, home, scratch) for label, program in
                                 (("python", python), ("go", go), ("python again", python))))

        first = three()
        if first:
            print("repeated straight away, to confirm what differed:", flush=True)
        again = three() if first else set()
        for kind, what in sorted(first ^ again):
            print(f"flake {kind}: {what}")
        for kind, what in sorted(first & again):
            print(f"{kind}: {what}")
        return 1 if first & again else 0
    finally:
        remove(scratch)


if __name__ == "__main__":
    sys.exit(main())
