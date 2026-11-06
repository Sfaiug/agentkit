"""Each test's last measured seconds, per repository on this host: a file's, or a part's as its
file timed it (`<file>::<part>`, tests/every_file.py).

A suite's box throws its HOME writes away, so the times live in ak's state instead: every check,
the lander's among them, keeps those its pieces printed (`passed`, wherever each piece ran), and
every piece of a suite gets one copy, AK_TIMES, taken as the suite starts, so all of them cut
the same shares (tests/every_file.py)."""

import json
from pathlib import Path
import re
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
    """The record of the repository `cwd` checks out, as AK_TIMES hands it: "" before any."""
    try:
        return _path(cwd).read_text()
    except OSError:
        return ""


def read(text):
    """{test ID: seconds} from AK_TIMES' `text`; {} from anything else."""
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
    """Added files owe each declared suite's own passing piece target, never earlier times."""
    added, failures = None, []
    # A rewritten declaration runs beside the target's; neither pass answers for the other.
    for command in dict.fromkeys((command, gitcall.declared(cwd, "tests"))):
        times, pieces = timings.get(command, ({}, 1))
        if not times:
            continue
        if added is None:
            added = set(gitcall.git(cwd, "diff", "--diff-filter=A", "--name-only", "-z",
                                    f"{base}...HEAD").split("\0"))
        # Many pieces must not turn an ordinary file of less than a minute into a refusal.
        target = max(60, sum(times.values()) / pieces)
        slow = [f"FAIL  {name}: {seconds:g}s exceeds the piece target {target:g}s; split the test file."
                for name, seconds in sorted(times.items()) if name in added and seconds > target]
        if slow:
            failures.append(f"$ {command}\n[test file over piece target]\n" + "\n".join(slow))
    return "\n\n".join(failures)


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
