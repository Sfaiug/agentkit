"""Run one ak command as Python, then Go, then Python again, each sealed over a home it cannot
write, and name every way Go differs.

    python3 tests/shadow.py [--python BIN] [--go BIN|python] [--home DIR] -- <ak argv>

`--python` is this checkout's bin/ak unless named, `--home` is $HOME, and `--go` is AK_BIN, a
relative name read from the checkout, else go/bin/ak built as tests/test_go_keys.py builds it.
`--go python` puts Python in Go's place: the noise floor, where nothing may differ.

What the two Python runs disagree on belongs to the moment and is never compared.  A difference
is confirmed only if repeating the three runs straight away shows it again, else it is a flake.
Exit 1 if any is confirmed, 2 if no box or no Go can be built (then nothing runs), else 0.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
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
# akbin's refusing fakes, tmux, and the copiers that would carry a file to another machine
FAKES = (*akbin.REFUSED, "tmux", "scp", "rsync")
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
    # /tmp before the overlay: a home under /tmp is mounted inside the box's own.
    return ["bwrap", "--unshare-all", "--die-with-parent", "--new-session",
            "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
            "--bind", inside, inside,
            "--overlay-src", home, "--overlay", folder / "upper", folder / "work", home,
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
    print(f"{label}: exit {code}, {seconds:.1f} s, {peak}", flush=True)
    record = inside / "handover"
    return dict(code=code, handover=record.read_text(errors="replace") if record.exists() else None,
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
        # The home's entries show only through a folder of the upper layer that is not opaque.
        # Where they do not show, each one is gone unless the run wrote it again.
        shows = folder and not hidden and "user.overlay.opaque" not in os.listxattr(above)
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
    target or a file's time and bytes.  Never a folder's time: each entry written in it moves it."""
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


def differences(first, go, again):
    """Each way `go` differs from the Python runs either side of it, as (kind, what)."""
    found = set()
    if go["code"] != first["code"] == again["code"]:
        found.add(("exit", f"go {go['code']}, python {first['code']}"))
    if go["handover"] is not None:
        found.add(("hand-over", " ".join(go["handover"].split()) or "an empty record"))
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
        # Where bwrap is, it says why it cannot build the box.
        if not shutil.which("bwrap") or subprocess.run(
                [*command, sys.executable, "-c", ""], env=env, stdin=subprocess.DEVNULL).returncode:
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
