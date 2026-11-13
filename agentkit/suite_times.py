"""Each test's last measured seconds, per repository on this host: a file's, or a part's as its
file timed it (`<file>::<part>`, tests/every_file.py).

A suite's box throws its HOME writes away, so the times live in ak's state instead: every check,
the lander's among them, keeps those its pieces printed (`passed`, wherever each piece ran), and
every piece of a suite gets one copy, taken as the suite starts, in the file AK_TIMES names, so
all of them cut the same shares (tests/every_file.py)."""

import json
from pathlib import Path
import re
import subprocess
import tempfile

from . import config, gitcall

PASSED = re.compile(r"PASS  (\S+) \((\d+(?:\.\d+)?)s\)$")
LINE = 4096     # bytes read at a time: a check can print one line longer than memory holds


def passed(name, took):
    """The line a piece prints for a file that passed in `took` seconds, as `keep` reads it."""
    return f"PASS  {name} ({took:.1f}s)"


def _path(cwd):
    return config.STATE / f"test-times-{gitcall.repository_id(cwd)}.json"


def handed(cwd):
    """The record of the repository `cwd` checks out, as the file AK_TIMES names holds it: ""
    before any."""
    try:
        return _path(cwd).read_text()
    except OSError:
        return ""


def read(text):
    """{test ID: seconds} from a record's `text`; {} from anything else."""
    try:
        times = json.loads(text)
    except ValueError:
        return {}
    return {name: seconds for name, seconds in times.items()
            if type(seconds) in (int, float) and seconds >= 0} if isinstance(times, dict) else {}


def measured(log, offset=0):
    """The file times in this command's whole output, before the gate caps it."""
    found, start = {}, True
    try:
        with open(log, "rb") as lines:
            lines.seek(offset)
            while part := lines.readline(LINE):
                # Only a line read whole, from its start, is one `passed` printed.
                whole = part.endswith(b"\n") or len(part) < LINE
                if start and whole and (match := PASSED.match(part.decode(errors="replace"))):
                    found[match[1]] = float(match[2])
                start = whole
    except OSError:
        pass
    return found


def refusal(cwd, base, command, timings):
    """A test file the change adds owes each declared suite's own passing piece target, never
    earlier times, where that pass took it over the target.  So does one it edits -- a move or a
    new file type is an edit -- where the change put it there: timed again at once by the same
    suite (`timed`), over the target at HEAD and at most it on `base`.  Both versions on one
    machine at one moment leave host load and other changes' checks out; only both timings
    decide, so a version that could not be timed refuses nothing."""
    changed, failures = None, []
    # A rewritten declaration runs beside the target's; neither pass answers for the other.
    for command in dict.fromkeys((command, gitcall.declared(cwd, "tests"))):
        times, pieces = timings.get(command, ({}, 1))
        if not times:
            continue
        if changed is None:
            changed = origins(cwd, base)
        # Many pieces must not turn an ordinary file of less than a minute into a refusal.
        target = max(60, sum(times.values()) / pieces)
        over = {name: seconds for name, seconds in sorted(times.items())
                if name in changed and seconds > target}
        edited = {name: changed[name] for name in over if changed[name]}
        then, now = (timed(cwd, ((base, edited.values()), ("HEAD", edited)), command)
                     if edited else ({}, {}))
        slow = []
        for name, seconds in over.items():
            old = changed[name]
            if old and not (old in then and name in now and then[old] <= target < now[name]):
                continue
            said = f"{now[name]:g}s, up from {then[old]:g}s on {base}," if old else f"{seconds:g}s"
            slow.append(f"FAIL  {name}: {said} exceeds the piece target {target:g}s; "
                        "split the test file or make it faster.")
        if slow:
            failures.append(f"$ {command}\n[test file over piece target]\n" + "\n".join(slow))
    return "\n\n".join(failures)


def origins(cwd, base):
    """{each file the change adds or edits: its path on `base`, None for one it adds}."""
    fields, found = iter(gitcall.git(cwd, "diff", "--find-renames", "--name-status", "-z",
                                     f"{base}...HEAD").split("\0")), {}
    for status in fields:
        if not status:
            break       # the NUL ending the last record
        old = new = next(fields)
        if status.startswith("R"):
            new = next(fields)
        if status != "D":
            found[new] = None if status == "A" else old
    return found


def timed(cwd, versions, command):
    """For each (ref, files) of `versions`, {file: seconds} the suite `command` printed running
    just those files (`AK_ONLY`) at that commit on this machine, in one clone of `cwd`: each
    file's own, whatever became of the others.  A run that moved or edited its checkout timed
    something else, and times none.  None is kept (`keep`): an older commit lacks the files the
    change adds, and would drop their times from the record."""
    from . import gate, record, worker
    found = []
    config.ensure_dirs()
    with tempfile.TemporaryDirectory(prefix="timing-", dir=config.TMP) as tmp:
        checkout, log = Path(tmp) / "checkout", Path(tmp) / "timed.log"
        gitcall.clone_borrowing(cwd, checkout, "--no-checkout")
        for ref, files in versions:
            sha = gitcall.git(cwd, "rev-parse", f"{ref}^{{commit}}")
            gitcall.git(checkout, "checkout", "--quiet", "--force", "--detach", sha)
            gitcall.git(checkout, "clean", "-fdqx")
            with log.open("wb") as output:
                # `ran`: a runner given AK_ONLY may name what it ran in AK_RAN, as every other
                # run of named tests lets it.
                worker.boxed(["bash", "-c", command], 3600 * record.CEILING_HOURS,
                             cwd=str(checkout), env={**gate.suite_env(), "AK_SHARD": "1/1"},
                             only=list(files), ran=[], activity=log, output=output,
                             silence=60 * record.SILENCE_MINUTES, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL)
            kept = (gitcall.git(checkout, "rev-parse", "HEAD", check=False) == sha
                    and gitcall.git_out(checkout, "diff", "--quiet", "HEAD")[0] == 0)
            found.append(measured(log) if kept else {})
    return found


def keep(cwd, log):
    """Add the times the check whose whole output is the file `log` printed to the record of
    `cwd`, the checkout it ran on, the latest of a test's winning; a test whose file that
    checkout no longer has leaves it."""
    found = measured(log)
    if not found:
        return
    from . import watch
    path = _path(cwd)
    try:
        with watch.state_lock():
            times = {name: seconds for name, seconds in (read(handed(cwd)) | found).items()
                     if (Path(cwd) / name.partition("::")[0]).is_file()}
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", delete=False) as saved:
                json.dump(times, saved, sort_keys=True)
            Path(saved.name).replace(path)
    except OSError:
        pass    # the pieces cut by size until a later suite keeps its times
