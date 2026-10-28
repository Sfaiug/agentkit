"""Each test file's last measured seconds, per repository on this host.

A suite's box throws its HOME writes away, so the times live in ak's state instead: every check,
the lander's among them, keeps those its pieces printed (`passed`, wherever each piece ran), and
every piece of a suite gets one copy, AK_TIMES, taken as the suite starts, so all of them cut
the same shares (tests/every_file.py)."""

import hashlib
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
    # Every worktree of a repository shares its record.
    repo = hashlib.sha256(str(gitcall.main_checkout(cwd)).encode()).hexdigest()[:12]
    return config.STATE / f"test-times-{repo}.json"


def handed(cwd):
    """The record of the repository `cwd` checks out, as AK_TIMES hands it: "" before any."""
    try:
        return _path(cwd).read_text()
    except OSError:
        return ""


def read(text):
    """{checkout-relative path: seconds} from AK_TIMES' `text`; {} from anything else."""
    try:
        times = json.loads(text)
    except ValueError:
        return {}
    return {name: seconds for name, seconds in times.items()
            if type(seconds) in (int, float) and seconds >= 0} if isinstance(times, dict) else {}


def keep(cwd, log):
    """Add the times the check whose whole output is the file `log` printed to the record of
    `cwd`, the checkout it ran on, the latest of a file's winning; a file that checkout no
    longer has leaves it."""
    found, start = {}, True
    try:
        with open(log, "rb") as lines:
            while part := lines.readline(LINE):
                # Only a line read whole, from its start, is one `passed` printed.
                whole = part.endswith(b"\n") or len(part) < LINE
                if start and whole and (match := PASSED.match(part.decode(errors="replace"))):
                    found[match[1]] = float(match[2])
                start = whole
    except OSError:
        return
    if not found:
        return
    from . import watch
    path = _path(cwd)
    try:
        with watch.state_lock():
            times = {name: seconds for name, seconds in (read(handed(cwd)) | found).items()
                     if (Path(cwd) / name).is_file()}
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", delete=False) as saved:
                json.dump(times, saved, sort_keys=True)
            Path(saved.name).replace(path)
    except OSError:
        pass    # the pieces cut by size until a later suite keeps its times
