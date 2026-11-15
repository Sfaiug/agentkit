"""`ak standby ALIAS`: one pass of this machine's copy of ak's folder on the home it is a client
of, at the same path, but the runs and their checkouts, which a pass of their own copies.  Before
it, what a seat carrying on from the copy needs of each harness: its logins, every account's, and
the folders its conversations start from, each at its path, the rest of that harness's folders
this machine's own.

rsync writes straight into the copy, sending what changed within each file, compressed, over the
owner's line; each file lands whole, the old one or the new one.  A pass cut short leaves some
files newer than others, as any pass over a live home does within its own minutes, and the next
that ends well evens it out.

Before the pass it keeps this machine's own job, which makes the pass again every three minutes,
as the home's tick runs, and a pass that ends well stamps when it began, and from which home.  That
stamp is all a pass keeps: one that fails, however it fails, writes nothing, so `ak standby`, which
reads the copy's age from the stamp, shows passes failing as an age that goes on growing.
"""

import fcntl
import glob
import math
import os
from pathlib import Path
import subprocess
import sys

from . import command_help, config, machine_turn, move, pair_clock, terminal, versions

# This machine's own in ak's folder, which a pass neither sends nor deletes: which server it is
# a client of, its ak install, and what each machine keeps through a move; then the runs and
# checkouts.
KEPT = tuple(path for path in (config.STATE / "server", versions.repository(),
                               config.HOME / versions.VERSIONS, *move.KEPT,
                               config.RUNS, config.WT, config.WORK)
             if path.is_relative_to(config.HOME))
TIMEOUT = 300   # seconds of silence from the home that fail a pass
GOES = 3        # a go during which files vanished on the home leaves their old copies here
# This machine's own folder of the copy: the stamp of the last pass that ended well, and the lock
# a pass holds, which the kernel lets go of when the pass ends, however it ends.
FOLDER = config.TMP / "standby"
COPIED, LOCK = FOLDER / "copied", FOLDER / "lock"
TAG = b"# agentkit standby"     # ends the job's line in the crontab


def _harnesses():
    """Each harness's logins under the home, `*` for every account's, and the folders its
    conversations start from, relative to the home."""
    home, paths = Path.home(), set()
    for harness, data in config.manifests():
        logins = config.manifest_paths(data.get("worker", {}).get("logins", ()),
                                       {config.ACCOUNT_ENV: "*"})
        paths |= {str(path.relative_to(home)) for path in logins if path.is_relative_to(home)}
        paths |= machine_turn.conversations(harness)
    return sorted(paths)


def _cron_word(word):
    """`word` as install.sh's `cron_word` quotes one: single-quoted, each % stepping out as \\%,
    which cron makes a %."""
    return "'" + str(word).replace("'", "'\\''").replace("%", "'\\%'") + "'"


def _keep_job(alias):
    """Keep the crontab's one line carrying TAG: the pass from `alias` every three minutes, on
    the PATH this one runs on, its output kept nowhere.  The other lines stay byte for byte.
    Whether it is kept."""
    path, ak, alias = map(_cron_word, (os.pathsep.join(os.get_exec_path()),
                                       config.REPO / "bin/ak", alias))
    job = f"*/3 * * * * export PATH={path}; {ak} standby {alias} >/dev/null 2>&1 ".encode()
    table = subprocess.run(["crontab", "-l"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL)
    # every crontab exits 1 for an account with no table yet; any other failure is a table
    # writing would replace
    if table.returncode not in (0, 1):
        print("ak standby: the crontab could not be read, so no pass is made; `crontab -l` says "
              "why", file=sys.stderr)
        return False
    rows = table.stdout.removesuffix(b"\n").split(b"\n") if table.stdout else []
    wanted = b"".join(row + b"\n" for row in rows if TAG not in row) + job + TAG + b"\n"
    if wanted != table.stdout and subprocess.run(["crontab", "-"], input=wanted).returncode:
        print("ak standby: the crontab refused this machine's job, so no pass is made",
              file=sys.stderr)
        return False
    return True


def _copy(alias, home, copied):
    """One pass from `alias`: `copied` under `home`, then ak's folder.  The exit of rsync that
    failed it, or 0."""
    # Each harness path a source of its own: one the home lacks is never read as a deletion.  The
    # home's rsync expands each `*` (-s), not its login shell, which as zsh fails on one matching
    # nothing.
    # Then ak's folder, last, so no seat's record here names a conversation the copy lacks.  A
    # home without the folder fails rsync's sender, 23, and rsync then deletes nothing here: as a
    # deletion it would empty the copy.  Times are compared to the nanosecond, as rsync's whole
    # seconds take a same-size write within one for no change, on every pass after.
    for args in (["-sR", "--no-implied-dirs", "--ignore-missing-args",
                  *(f"{alias}:{home}/./{path}" for path in copied), f"{home}/"],
                 [*(f"--exclude=/{path.relative_to(config.HOME)}" for path in KEPT),
                  f"{alias}:{config.HOME}/", f"{config.HOME}/"]):
        for _ in range(GOES):
            code = subprocess.run([
                "rsync", "-aHz", "--no-D", "--delete", "--modify-window=-1", f"--timeout={TIMEOUT}",
                *(["--info=progress2"] if sys.stdout.isatty() else []), *args]).returncode
            if code != move.VANISHED:
                break
        if code:
            print(f"ak standby: the pass from {alias} failed: rsync exited {code}", file=sys.stderr)
            return code
    return 0


def _shown():
    """Show the home this machine copies and the copy's age, from the stamp of the last pass
    that ended well: 0 only for a stamp of that home."""
    alias = config.server_alias()
    if not alias:
        print("ak standby: this machine is no home's client, so it keeps no copy", file=sys.stderr)
        return 1
    try:
        line, of = COPIED.read_text().splitlines()
    except (OSError, ValueError):     # none yet, or one cut short
        line = of = None
    stamp = pair_clock.read(line) if of == alias else None
    if not stamp:
        print(f"this machine copies {alias}: no pass from it has ended well yet")
        return 1
    # the older of the two clocks' ages: one set back never makes the copy look younger
    age = stamp.age_at_most()
    print(f"this machine copies {alias}: the copy is "
          + (f"{terminal.format_age(age)} old" if age < math.inf else "from before this boot"))
    return 0


def main(argv):
    if command_help.show("standby", argv):
        return 0
    if not argv:
        return _shown()
    if len(argv) != 1 or argv[0].startswith("-"):
        raise config.Error(command_help.COMMANDS["standby"][0])
    alias, home, copied = argv[0], Path.home(), _harnesses()
    refused = [f"this machine is not a client of {alias}"] * (config.server_alias() != alias)
    # rsync replaces a link here at what it copies of a harness, but writes through one at a
    # folder between that and the home.  What is kept are names: rsync would replace a link at
    # one, or at a folder between it and ak's folder, with the home's, or delete what it reaches.
    parts = {home / part for path in copied for folder in Path(path).parents[:-1]
             for part in glob.glob(str(folder), root_dir=home)}
    parts |= {part for path in KEPT for part in (path, *path.parents)
              if config.HOME in part.parents}
    refused += [f"{config.tilde(part)} is a link here" for part in sorted(parts)
                if part.is_symlink()]
    for reason in refused:
        print(f"ak standby: refused: {reason}", file=sys.stderr)
    if refused:
        return 1
    FOLDER.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("ak standby: a pass is under way already, so this one copies nothing",
                  file=sys.stderr)
            return 1
        if not _keep_job(alias):
            return 1
        began = pair_clock.now()
        if _copy(alias, home, copied):
            return 1
        COPIED.write_text(f"{began.line()}\n{alias}\n")
    return 0
