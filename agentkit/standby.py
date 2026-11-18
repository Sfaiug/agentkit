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
path, the rest of that harness's folders this machine's own; and as one more such path ~/code,
each project's `.git` folder too, so that a takeover finds the projects and the repositories its
runs' checkouts name: rsync compared the owner's 406 000 files in 31 s on 18 Nov.  Of ~/code a
pass leaves out, and as the copy has it, what would make the copy worse than it was.  What the
home's account cannot read, as under ak's checkouts.  A link to a folder outside ~/code, ~/code
itself as one, which rsync would put here in place of the folder the copy holds; where ~/code is
a link here, which rsync would put the home's folder in place of, none of it crosses.  A
repository, which crosses whole or not at all: one that keeps git data outside ~/code, or among
whose git data is something a pass leaves out or a link leading outside, would be new names for
objects the copy lacks.  A lock in a repository's git data, which is the home's git at work: no
git here would ever let go of its copy.  And each name in ~/code that is this machine's own, on
the way from its `ak` command to the ak it runs.
After it, ak here moves as every client's does (`update.follow`), to the commit ak is at on the
home once the home's move there is final, so the ak that takes over is the one that was live.

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
# The ask of the home, three lists, the names of each NUL-parted and each list ended by two.
# The names of its runs, each folder in its runs' folder, as `record.run_dirs` lists them; a runs'
# folder the home lacks holds none.  Then each path the pass leaves out, of ~/code and the
# checkouts' folders, themselves and all in them.  Each folder the home's account cannot list or
# enter, and each regular file it cannot read, as access(2) answers for one still there: rsync's
# sender exits 23 for one and deletes nothing.  The walk follows no link, which rsync copies as
# one, and skips each `.git` folder under the checkouts' folders, where no pass copies one.  In
# ~/code, each link to a folder outside it, and each repository that would not cross whole, its
# checkout and its git data.  A repository is what the home's git reads one from, asked at each
# `.git` and each folder holding a HEAD: where its git data is, where the data it shares with
# its other checkouts, and where its objects (`rev-parse`).  Whose objects it borrows, and they
# in turn, is in each store's `info/alternates`, a path a line, from the store if relative; a
# line in quotes, which git reads as C would and nothing writes, counts as outside ~/code.  The
# walk opens no other file, of the million there.  A repository does not cross whole if one of
# those folders is outside ~/code, holds what the pass leaves out or a link leading outside
# ~/code, or lies in what the pass leaves out, another repository too: so they are tried until
# none more goes.  Last, the git data of each repository that crosses, by its outermost
# folders, for its locks.  By
# whatever python3 the home's ssh finds, which may be older than ak's: so it imports nothing of
# ak's, comes on its input and is given the folders.
ASK = f"""import os, subprocess, sys
runs, code, *checkouts = map(os.fsencode, sys.argv[1:])
if os.path.islink(runs):
    sys.exit({LINKED})
def listed(folder):
    try:
        return list(os.scandir(folder))
    except FileNotFoundError:
        return []
def write(names):
    sys.stdout.buffer.write(b"\\0".join(names) + b"\\0\\0")
write(run.name for run in listed(runs) if run.is_dir())
inside = os.path.join(code, b"")
real = os.path.join(os.path.realpath(os.path.dirname(code)), os.path.basename(code), b"")
def within(path):
    path = os.path.join(os.path.realpath(path), b"")
    return inside + path[len(real):] if path.startswith(real) else None
def repository(git):
    asked = subprocess.run([b"git", b"--git-dir", git, b"rev-parse", b"--git-dir",
                            b"--git-common-dir", b"--git-path", b"objects"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL)
    if asked.returncode:
        return None
    *own, objects = asked.stdout.splitlines()
    lent = [objects]
    for store in lent:
        try:
            with open(os.path.join(store, b"info", b"alternates"), "rb") as file:
                lines = file.read().splitlines()
        except OSError:
            lines = []
        for line in lines:
            path = b"/" if line[:1] == b'"' else os.path.normpath(os.path.join(store, line))
            if line and line[:1] != b"#" and path not in lent:
                lent.append(path)
    return [within(path) for path in own], [within(path) for path in lent]
out, leads, repositories = [], [], []
found = [entry for top in (code, *checkouts) for entry in listed(os.path.dirname(top))
         if entry.path == top]
while found:
    entry = found.pop()
    whole = os.path.join(entry.path, b"").startswith(inside)
    folder = entry.is_dir(follow_symlinks=False) and (whole or entry.name != b".git")
    away = whole and entry.is_symlink() and not within(entry.path)
    if away and entry.is_dir() or (folder or entry.is_file(follow_symlinks=False)) \\
            and not os.access(entry.path, os.R_OK | os.X_OK if folder else os.R_OK) \\
            and os.path.lexists(entry.path):
        out.append(entry.path)
        continue
    if away:
        leads.append(entry.path)
    if whole and (entry.name == b".git"
                  or folder and os.path.lexists(os.path.join(entry.path, b"HEAD"))):
        data = repository(entry.path)
        if data:
            repositories.append(
                (os.path.dirname(entry.path) if entry.name == b".git" else entry.path, *data))
    if folder:
        found += listed(entry.path)
more = True
while more:
    more = False
    apart = [os.path.join(path, b"") for path in out + leads]
    for one in repositories[:]:
        checkout, own, lent = one
        if not all(tree and not any(tree.startswith(path) or path.startswith(tree)
                                    for path in apart) for tree in own + lent):
            repositories.remove(one)
            out += [checkout, *(tree[:-1] for tree in own if tree)]
            more = True
write(set(out))
trees = {{tree for checkout, own, lent in repositories for tree in own}}
write(tree[:-1] for tree in trees
      if not any(tree != other and tree.startswith(other) for other in trees))
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


def _own():
    """Each name in ~/code that is this machine's own: one the way from its `ak` command to the
    ak it runs leads through, by each link on it, and the one that ak lies in."""
    path, way = versions.installed_ak(), [config.REPO]
    # the first link from the root, and on from where it leads, at most as far as the kernel goes
    while len(way) < 40 and (link := next((part for part in (*reversed(path.parents), path)
                                           if part.is_symlink()), None)):
        way.append(link)
        path = Path(os.path.normpath(link.parent / os.readlink(link) / path.relative_to(link)))
    return {config.CODE / part.relative_to(config.CODE).parts[0] for part in way
            if config.CODE in part.parents}


def _copy(alias, home, copied):
    """One pass from `alias`: `copied` under `home`, then each run of the home's or this
    machine's, then the rest of ak's folder.  Why it failed, or None."""
    # The home's answer first, so one whose runs' folder is a link fails the pass before it
    # copies anything: rsync would put that link here in place of the runs' folder.
    try:
        asked = subprocess.run(
            ["ssh", alias, shlex.join(["python3", "-I", "-", str(config.RUNS), str(config.CODE),
                                       str(config.WT), str(config.WORK)])],
            input=ASK, stdout=subprocess.PIPE, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"what to copy was not read within {TIMEOUT} seconds"
    if asked.returncode == LINKED:
        return f"{config.tilde(config.RUNS)} is a link there"
    if asked.returncode:
        return f"reading what to copy exited {asked.returncode}"
    runs, out, locked = ([os.fsdecode(name) for name in names.split(b"\0") if name]
                         for names in asked.stdout.split(b"\0\0")[:-1])
    runs = sorted({*runs, *(run.name for run in record.run_dirs())})
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
    # link here at a run's folder, or deletes it, and never goes past it.  Nor does what the
    # home's answer leaves out cross, each named literally too, a folder with all in it:
    # perishable as well, what the copy holds of it stays till the folder it is in goes, and the
    # pass after the home's answer names it no more copies it.  A lock in what the answer calls
    # git data stays where it is, the home's there and this machine's here.  Those rules are as
    # many as a home has such paths, so each transfer they may reach takes its own on its input.
    # This machine's own names in ~/code are kept as each is here, the home's of that name too:
    # kept below one, rsync could not make way for what the home has in a folder's place.
    # rsync tries each rule on each file, on each machine, and the runs' names are thousands, more
    # than one command may be given: they come on its input, in a transfer of the runs' folder
    # alone, which takes all inside a run before a name is tried on it; the rest crosses after.
    # rsync keeps a hard link within one transfer alone: a file with names in a run and outside
    # the runs, as a package cache links one into each checkout, crosses as two of the same bytes.
    at = config.PLACES["RUNS"]
    rules = [*(f"--exclude=/{path.relative_to(config.HOME)}" for path in KEPT),
             "--filter=-p .git/"]

    def left(root):
        return b"".join(os.fsencode(f"/{_literal(Path(path).relative_to(root))}{rest}\0")
                        for paths, rest in ((out, ""), (locked, "/**.lock")) for path in paths
                        if Path(path).is_relative_to(root))
    names = b"".join(os.fsencode(f"/{at}/{_literal(run)}") + b"\0" for run in runs)
    for args, given in ((["-sR", "--no-implied-dirs", "--ignore-missing-args",
                          *(f"--exclude=/{_literal(path.relative_to(home))}" for path in _own()),
                          "--from0", "--filter=.-p -",
                          *(f"{alias}:{home}/./{path}" for path in copied), f"{home}/"],
                         left(home)),
                        ([*rules, *(f"--filter=-p /{at}/**/{name}*/" for name in SCRATCH),
                          f"--filter=+ /{at}/*/**", "--from0", "--include-from=-",
                          f"--filter=- /{at}/*", f"--filter=+ /{at}/", "--filter=- /*",
                          f"{alias}:{config.HOME}/", f"{config.HOME}/"], names),
                        ([f"--exclude=/{at}", *rules, "--from0", "--filter=.-p -",
                          f"{alias}:{config.HOME}/", f"{config.HOME}/"], left(config.HOME))):
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
    alias, home = argv[0], Path.home()
    # ~/code that is a link here stays one: rsync would put the home's folder in its place.
    copied = [*_harnesses(),
              *([] if config.CODE.is_symlink() else [str(config.CODE.relative_to(home))])]
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
