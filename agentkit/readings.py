"""What each machine answered, check by check, for its owner to judge it by over time.  The
format, which nothing else in ak knows:

- A day's file is readings/YYYY-MM-DD.jsonl under ak's state folder, named by the UTC date of
  the check's time.
- A check appends to it in one os.write: a newline, then one line per reading, each ended by a
  newline.  The leading newline ends whatever an interrupted write left before it, so an empty
  line means nothing.  A check with no reading to write opens no file.
- A line is a JSON object: `at`, the check's time; then `home`, this host's name, for this
  machine, or `machine`, the name it was added under, for any other, so the two are never
  taken for each other; then the reading as machines.json takes it.  A reading JSON cannot hold
  (`allow_nan=False`) is left out.
- After its write, a check unlinks each file named a date `datetime.date.fromisoformat` reads
  and `.jsonl`, of a day before the check's less history.READINGS_KEPT_FOR; no other name.

Nothing here reads what it wrote, and what the disk refuses is skipped: the check goes on.
"""

from contextlib import suppress
import datetime
import json
import os
import socket
import time

from . import config, history


def keep(at, said):
    """Append the readings of `said`, each machine's name to what it answered, checked at `at`."""
    from .machines import HERE      # here, not at the top: machines calls this module
    lines = []
    for name, reading in said.items():
        # OSError: no name for this host; ValueError: a number JSON has no word for, nan or inf
        with suppress(OSError, ValueError):
            who = {"home": socket.gethostname()} if name == HERE else {"machine": name}
            lines.append(json.dumps({"at": at, **who, **reading}, allow_nan=False) + "\n")
    if not lines:
        return
    folder = config.STATE / "readings"
    with suppress(OSError):
        folder.mkdir(exist_ok=True)
        day = os.open(folder / f"{_date(at)}.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            os.write(day, "".join(["\n", *lines]).encode())
        finally:
            os.close(day)
        gone = _date(at - history.READINGS_KEPT_FOR)
        for name in os.listdir(folder):
            with suppress(OSError, ValueError):     # ValueError: a name that is no date
                if name.endswith(".jsonl") and \
                        datetime.date.fromisoformat(name.removesuffix(".jsonl")) < gone:
                    os.unlink(folder / name)


def _date(at):
    # gmtime drops the fraction of a second, which datetime would round into the next day
    return datetime.date(*time.gmtime(at)[:3])
