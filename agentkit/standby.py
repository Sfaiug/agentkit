"""`ak standby ALIAS`: one pass of this machine's copy of ak's folder on the home it is a client
of, at the same path, but each `.git` folder in it, a clone's own git data, each run's scratch,
each name in the runs' folder that is no run on either machine, such as each machine's own locks
and queues, and what the home's account cannot read under ak's checkouts, `wt` and `work`: each
folder it cannot list or enter, with all in it, and each regular file it cannot read, such as a
test stopped before it cleaned up leaves, which would fail every pass.  Elsewhere one fails the
pass, as any error of rsync's does.  Every run crosses, open or ended, in every pass, so a
takeover has the home's whole record of its runs: on 17 Nov the home's runs but their scratch
were 440 000 files, which rsync compared from the copy in 52 s at the home's busiest.  Ended runs
copied hourly would hold the pass's lock as long as that took, or, beside the pass, write in the
runs' folder while it does.  Before it, what a seat carrying on from the copy needs of each
harness: its logins, every account's, and the folders its conversations start from, each at its
path, the rest of that harness's folders this machine's own.  After it, ak here moves as every
client's does (`update.follow`), to the commit ak is at on the home once the home's move there
is final, so the ak that takes over is the one that was live.

rsync writes straight into the copy, sending what changed within each file, compressed, over the
owner's line; each file lands whole, the old one or the new one.  A pass cut short leaves some
files newer than others, as any pass over a live home does within its own minutes, and the next
that ends well evens it out.

Before the pass it keeps this machine's own job, which makes the pass again every three minutes,
as the home's tick runs, after the keeper of a move of ak here, as the tick's line runs it
(`back`), then sends again, as a tick does, each page of this machine's own the webhook did not
take (`notify.retry_pending`), whether the home answers or not.  A pass that ends well stamps
when it began, and from which home, then why ak here stayed where it was, if it did, and at its
end does with the last move here what the end of a tick does on a home (`versions.final`): a pass
of the version that move put live makes it final.
That is all a pass keeps: one that fails, however it fails, writes nothing and makes nothing
final, for it cannot tell a silent home from code that is broken, and `ak standby`, which reads
the copy's age from the stamp, shows passes failing as an age that goes on growing.  A pass's
exit is its copy's alone: the copy is what a takeover needs first.
"""

import fcntl
import glob
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

from . import (command_help, config, machine_turn, move, notify, pair_clock, record, terminal,
               update, versions)

# This machine's own in ak's folder, which a pass neither sends nor deletes: which server it is
# a client of, its ak install and whether its install.sh is owed, the pages it sent and owes
# (`back` pages from here), and what each machine keeps through a move.
KEPT = tuple(path for path in (config.STATE / "server", versions.repository(),
                               config.HOME / versions.VERSIONS, config.STATE / update.PENDING,
                               notify.outbox(), *move.KEPT)
             if path.is_relative_to(config.HOME))
# A run's scratch, its folders of these names at any depth, which go when its turn ends: in one
# three-minute window on 9 Nov the owner's home wrote 1.8 GB in them against 26 MB outside.
SCRATCH = ("tmp", ".box-")
LINKED = 3      # the ask's exit for a home whose runs' folder is a link
# The ask of the home, each name NUL-ended: the names of its runs, each folder in its runs'
# folder, as `record.run_dirs` lists them; a runs' folder the home lacks holds none.  Then an
# empty name, and the path of each folder under the checkouts' folders the home's account cannot
# list or enter, and of each regular file it cannot read, as access(2) answers for it: rsync's
# sender exits 23 for one and deletes nothing.  The walk opens no file, of the million in them;
# it follows no link, which rsync copies as one, and skips each `.git` folder, which no pass
# copies.  By whatever python3 the home's ssh finds, which may be older than ak's: so it imports
# nothing of ak's, comes on its input and is given the folders.
ASK = f"""import os, sys
runs, wt, work = sys.argv[1:]
if os.path.islink(runs):
    sys.exit({LINKED})
try:
    found = list(os.scandir(os.fsencode(runs)))
except FileNotFoundError:
    found = []
for run in found:
    if run.is_dir():
        sys.stdout.buffer.write(run.name + b"\\0")
sys.stdout.buffer.write(b"\\0")
folders = [os.fsencode(top) for top in (wt, work) if not os.path.islink(top)]
while folders:
    try:
        found = list(os.scandir(folders.pop()))
    except FileNotFoundError:
        found = []
    for entry in found:
        if entry.is_dir(follow_symlinks=False) and entry.name != b".git":
            if os.access(entry.path, os.R_OK | os.X_OK):
                folders.append(entry.path)
            else:
                sys.stdout.buffer.write(entry.path + b"\\0")
        elif entry.is_file(follow_symlinks=False) and not os.access(entry.path, os.R_OK):
            sys.stdout.buffer.write(entry.path + b"\\0")
""".encode()
TIMEOUT = 300   # seconds of silence from the home that fail a pass
# This machine's own folder of the copy, in ak's tmp folder: the stamp of the last pass that ended
# well, and the lock a pass holds, which the kernel lets go of when the pass ends, however it ends.
# Names, not paths: each follows HOME, as config's places do.  install.sh keeps the runs, checkouts
# and work of a client with this folder, a standby.
FOLDER, COPIED, LOCK = "standby", "copied", "lock"
TAG = b"# agentkit standby"     # what the job's line in the crontab ends in


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


def _literal(path):
    """`path` as an rsync rule's pattern that matches it alone: each `*`, `?`, `[` and backslash
    in a class of its own, stepped out of there.  A backslash alone would not do: rsync reads one
    as stepping out only in a pattern that holds a wildcard."""
    return re.sub(r"[*?[\\]", lambda found: f"[\\{found[0]}]", str(path))


def _cron_word(word):
    """`word` as install.sh's `cron_word` quotes one: single-quoted, each % stepping out as \\%,
    which cron makes a %."""
    return "'" + str(word).replace("'", "'\\''").replace("%", "'\\%'") + "'"


def _keep_job(alias):
    """Keep the crontab's one line ending in TAG: the pass from `alias` every three minutes, on
    the PATH this one runs on, its output kept nowhere.  The other lines stay byte for byte.
    Whether it is kept."""
    path, keeper, ak, alias = map(_cron_word, (os.pathsep.join(os.get_exec_path()),
                                               config.TMP / versions.KEEP,
                                               config.REPO / "bin/ak", alias))
    # As the tick's line (install.sh), the keeper first: the version a move replaced decides
    # whether the move stays, from outside the new one, which may be what cannot pass; whatever
    # the keeper does, the pass runs.
    job = (f"*/3 * * * * export PATH={path}; [ -x {keeper} ] && {keeper} back --when-broken"
           f" >/dev/null 2>&1; {ak} standby {alias} >/dev/null 2>&1 ").encode()
    table = subprocess.run(["crontab", "-l"], stdin=subprocess.DEVNULL, capture_output=True)
    # Every crontab exits 1 both for an account with no table yet and for a table it could not
    # read, which writing would replace: only its words tell them apart, `no crontab for USER` in
    # cronie's, Vixie's and the BSDs'.  Any other crontab's missing table is one it cannot read.
    if table.returncode and not (table.returncode == 1 and b"no crontab for " in table.stderr):
        said = table.stderr.decode(errors="replace").strip() or f"exit {table.returncode}"
        print(f"ak standby: the crontab could not be read, so no pass is made: {said}",
              file=sys.stderr)
        return False
    rows = table.stdout.removesuffix(b"\n").split(b"\n") if table.stdout else []
    wanted = b"".join(row + b"\n" for row in rows
                      if not row.rstrip().endswith(TAG)) + job + TAG + b"\n"
    if wanted != table.stdout and subprocess.run(["crontab", "-"], input=wanted).returncode:
        print("ak standby: the crontab refused this machine's job, so no pass is made",
              file=sys.stderr)
        return False
    return True


def _copy(alias, home, copied):
    """One pass from `alias`: `copied` under `home`, then each run of the home's or this
    machine's, then the rest of ak's folder.  Why it failed, or None."""
    # The home's runs and what it cannot read first, so one whose runs' folder is a link fails the
    # pass before it copies anything: rsync would put that link here in place of the runs' folder.
    try:
        asked = subprocess.run(
            ["ssh", alias, shlex.join(["python3", "-I", "-", str(config.RUNS), str(config.WT),
                                       str(config.WORK)])],
            input=ASK, stdout=subprocess.PIPE, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"what to copy was not read within {TIMEOUT} seconds"
    if asked.returncode == LINKED:
        return f"{config.tilde(config.RUNS)} is a link there"
    if asked.returncode:
        return f"reading what to copy exited {asked.returncode}"
    names = asked.stdout.split(b"\0")[:-1]
    gap = names.index(b"")
    runs = sorted({*map(os.fsdecode, names[:gap]), *(run.name for run in record.run_dirs())})
    unread = [Path(os.fsdecode(path)).relative_to(config.HOME) for path in names[gap + 1:]]
    # Each harness path a source of its own: one the home lacks is never read as a deletion.  The
    # home's rsync expands each `*` (-s), not its login shell, which as zsh fails on one matching
    # nothing.
    # Then ak's folder, last, so no seat's record here names a conversation the copy lacks.  A
    # home without the folder fails rsync's sender, 23, and rsync then deletes nothing here: as a
    # deletion it would empty the copy.  Times are compared to the nanosecond, as rsync's whole
    # seconds take a same-size write within one for no change, on every pass after.  No `.git`
    # folder crosses, the git data a clone carries in itself; the rest of its checkouts does, what
    # git ignores too, and each run but its scratch.  Perishable (-p), the rules leaving out a
    # `.git` folder and a run's scratch still let rsync's delete take a checkout or run the home
    # removed, whatever it holds here.  A run is named literally, as any file is: rsync replaces a
    # link here at a run's folder, or deletes it, and never goes past it.  Nor does what the home
    # cannot read in its checkouts cross, each named literally too, a folder with all in it:
    # perishable as well, what the copy holds of it stays till its checkout goes, and the pass
    # after the home reads it again copies it.
    # rsync tries each rule on each file, on each machine, and the runs' names are thousands, more
    # than one command may be given: they come on its input, in a transfer of the runs' folder
    # alone, which takes all inside a run before a name is tried on it; the rest crosses after.
    at = config.PLACES["RUNS"]
    rules = [*(f"--exclude=/{path.relative_to(config.HOME)}" for path in KEPT),
             "--filter=-p .git/", *(f"--filter=-p /{_literal(path)}" for path in unread)]
    names = b"".join(os.fsencode(f"/{at}/{_literal(run)}") + b"\0" for run in runs)
    for args, given in ((["-sR", "--no-implied-dirs", "--ignore-missing-args",
                          *(f"{alias}:{home}/./{path}" for path in copied), f"{home}/"], None),
                        ([*rules, *(f"--filter=-p /{at}/**/{name}*/" for name in SCRATCH),
                          f"--filter=+ /{at}/*/**", "--from0", "--include-from=-",
                          f"--filter=- /{at}/*", f"--filter=+ /{at}/", "--filter=- /*",
                          f"{alias}:{config.HOME}/", f"{config.HOME}/"], names),
                        ([f"--exclude=/{at}", *rules, f"{alias}:{config.HOME}/",
                          f"{config.HOME}/"], None)):
        code = subprocess.run([
            "rsync", "-aHz", "--no-D", "--delete", "--modify-window=-1", f"--timeout={TIMEOUT}",
            *(["--info=progress2"] if sys.stdout.isatty() else []), *args],
            input=given).returncode
        # A file the home deleted while rsync read it is no failure, as in a move: all that is
        # still there crossed, and what this machine held of the file goes with the next pass.
        # A home at work deletes in its checkouts all the time: on 17 Nov a second and a third
        # go each met more, and the passes failed for it.
        if code not in (0, move.VANISHED):
            return f"rsync exited {code}"
    return None


def _stamp(own, *lines):
    """The stamp of a pass that ended well, whole or not at all: a write cut short leaves the
    last."""
    new = own / f"{COPIED}.new"
    new.write_bytes("".join(f"{line}\n" for line in lines).encode())
    new.replace(own / COPIED)


def _shown():
    """Show the home this machine copies and the copy's age, from the stamp of the last pass
    that ended well: 0 only for a stamp of that home."""
    alias = config.server_alias()
    if not alias:
        print("ak standby: this machine is no home's client, so it keeps no copy", file=sys.stderr)
        return 1
    try:
        line, of, *stayed = (config.TMP / FOLDER / COPIED).read_text().splitlines()
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
    for why in stayed:
        print(f"ak here does not follow {alias} yet: {why}")
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
    # So would it at the runs' folder, which it writes into.
    parts |= {part for path in (*KEPT, config.RUNS) for part in (path, *path.parents)
              if config.HOME in part.parents}
    refused += [f"{config.tilde(part)} is a link here" for part in sorted(parts)
                if part.is_symlink()]
    for reason in refused:
        print(f"ak standby: refused: {reason}", file=sys.stderr)
    if refused:
        return 1
    own = config.TMP / FOLDER
    own.mkdir(parents=True, exist_ok=True)
    with (own / LOCK).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("ak standby: a pass is under way already, so this one copies nothing",
                  file=sys.stderr)
            return 1
        if not _keep_job(alias):
            return 1
        notify.retry_pending()
        began = pair_clock.now()
        if why := _copy(alias, home, copied):
            print(f"ak standby: the pass from {alias} failed: {why}", file=sys.stderr)
            return 1
        _stamp(own, began.line(), alias)
        if why := update.follow(alias)[1]:
            _stamp(own, began.line(), alias, why)
        versions.final(time.time())
    return 0
