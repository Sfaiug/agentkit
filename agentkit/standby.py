"""`ak standby ALIAS`: one pass of this machine's copy of the home it is a client of, at the same
paths: what a seat carrying on from the copy needs of each harness, its logins, every account's,
and the folders its conversations start from, the rest of that harness's folders this machine's
own; then ~/code, as rsync copies any folder: every file, a `.git` folder's too, a link as the
link it is; then ak's folder, but each `.git` folder in it, a clone's own git data, each run's
scratch, and each name in the runs' folder that is no run on either machine, such as each
machine's own locks and queues.  Nor does what the home's account cannot read under ~/code and
ak's checkouts, `wt` and `work`, cross: each folder it cannot list or enter, with all in it, and
each regular file it cannot read, such as a test stopped before it cleaned up leaves, which would
fail every pass.  Elsewhere one fails the pass, as any error of rsync's does, in a `.git` folder
under ~/code too, which the walk enters none of; and so do more of them than one command may be
given, each an argument of rsync's.
A pass judges nothing in ~/code: what a path there names outside it, a link's target, a git
directory kept elsewhere, objects a repository borrows, is neither followed nor looked at, and
what this machine keeps in its own ~/code goes with what the home lacks there; it refuses an ak
here running from there.
Every run crosses, open or ended, in every pass, so a takeover has the home's whole record of its
runs: on 17 Nov the home's runs but their scratch were 440 000 files, which rsync compared from
the copy in 52 s at the home's busiest.  Ended runs copied hourly would hold the pass's lock as
long as that took, or, beside the pass, write in the runs' folder while it does.  After the copy,
ak here moves as every client's does (`update.follow`), to the commit ak is at on the home once
the home's move there is final, so the ak that takes over is the one that was live.

rsync writes straight into the copy, sending what changed within each file, compressed, over the
owner's line; each file lands whole, the old one or the new one.  A pass cut short leaves some
files newer than others, as any pass over a live home does within its own minutes: a repository
the home writes meanwhile is here as it held it at no one moment, a lock file of git's among it.
The next that ends well evens it out.

Before the pass it keeps this machine's own job, which makes the pass again every three minutes,
as the home's tick runs, after the keeper of a move of ak here, as the tick's line runs it
(`back`), then sends again, as a tick does, each page of this machine's own the webhook did not
take (`notify.retry_pending`), whether the home answers or not.  A pass that ends well stamps
when it began, and from which home, then why ak here stayed where it was, if it did, and at its
end does with the last move here what the end of a tick does on a home (`versions.final`): a pass
of the version that move put live makes it final.
That is all a pass keeps: one that fails, however it fails, writes nothing of its own and makes
nothing final, for it cannot tell a silent home from code that is broken, and `ak standby`, which
reads the copy's age from the stamp, shows passes failing as an age that goes on growing.  One
that fails with a reason, once the copy is `SILENT` old by the clock calling it younger, asks
`notify.page` to tell the owner, under a key of the home and the stamp: notify alone keeps whether
that went out, and sends it once.  A pass's exit is its copy's alone: the copy is what a takeover
needs first.

A home keeps a record of each machine that says it copied it (`_keep`), which `ak standby` lists
there (`_copies`).  A pass asks the home for a stamp of its own where it takes its own (`_began`),
and one that ends well hands it back as printed, last: a record dated by the seconds since the
pass began would be dated younger than its copy by however late the request arrives, and one
dated by the home's stamp never is.  Neither request is anything of the pass's own: what it
prints, its exit and its copy are the same whatever the home answers, or whether it does.
"""

import contextlib
import fcntl
import glob
import io
import math
import os
from pathlib import Path
import re
import selectors
import shlex
import socket
import stat
import subprocess
import sys
import tempfile
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
# The ask's exit for a home where each of these is a link, which rsync would put here in place
# of the folder: the runs' folder, which a pass writes into, and ~/code.
LINKED = {3: config.RUNS, 4: config.CODE}
# The ask of the home, each name NUL-ended: the names of its runs, each folder in its runs'
# folder, as `record.run_dirs` lists them; a runs' folder the home lacks holds none.  Then an
# empty name, and the path of each folder under ~/code and ak's checkouts' folders the home's
# account cannot list or enter, and of each regular file it cannot read, as access(2) answers for
# it: rsync's sender exits 23 for one and deletes nothing.  The walk opens no file, of the
# million in them; it follows no link, which rsync copies as one, and enters no `.git` folder:
# none crosses from ak's folder, and under ~/code what the home cannot read in one fails the pass.
# By whatever python3 the home's ssh finds, which may be older than ak's: so it imports nothing of
# ak's, comes on its input and is given the folders, LINKED's first.
ASK = f"""import os, sys
runs, code, wt, work = sys.argv[1:]
for status, top in zip({tuple(LINKED)}, (runs, code)):
    if os.path.islink(top):
        sys.exit(status)
try:
    found = list(os.scandir(os.fsencode(runs)))
except FileNotFoundError:
    found = []
for run in found:
    if run.is_dir():
        sys.stdout.buffer.write(run.name + b"\\0")
sys.stdout.buffer.write(b"\\0")
folders = [os.fsencode(top) for top in (code, wt, work) if not os.path.islink(top)]
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
# The copy's age at which a failed pass pages the owner: on a Mac, ak's own check starts a dead
# Linux machine again after 10 minutes without an answer, and 20 leave it the time to come back.
SILENT = 20 * 60
# This machine's own folder of the copy, in ak's tmp folder: the stamp of the last pass that ended
# well, and the lock a pass holds, which the kernel lets go of when the pass ends, however it ends.
# Names, not paths: each follows HOME, as config's places do.  install.sh keeps the runs, checkouts
# and work of a client with this folder, a standby.
FOLDER, COPIED, LOCK = "standby", "copied", "lock"
# A home's own, in ak's tmp folder, which no pass copies, beside FOLDER and never in it, as FOLDER
# there is what makes a client a standby: a record of each machine that says it copied this one,
# named by its host name.
COPIES = "copies"
# The words of `ak standby --copied HOST SECONDS yes|no`, each matched whole: a host name of at
# most 64 characters, as Linux's, whole seconds since its pass began, and whether it takes over.
HOST = "[A-Za-z0-9][A-Za-z0-9.-]{0,63}"
TAKES = "yes|no"
SAID = (HOST, "[0-9]{1,9}", TAKES)
# The words of this machine's stamp, as `--began` prints it and `--copied HOST WALL SINCE BOOT
# yes|no` hands it back: each clock in decimals, no sign or exponent, and a boot no dash begins,
# so that no word is taken for a flag.
CLOCK = "[0-9]{1,12}(?:[.][0-9]{1,17})?"
STAMP = (CLOCK, CLOCK, "[A-Za-z0-9][A-Za-z0-9-]{0,63}")
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


def _left_out(unread, top, root):
    """The rules of a transfer from `root` leaving out each of `unread` under `top`, named
    literally, a folder with all in it.  Perishable: what the copy holds of one stays till the
    folder holding it goes, and the pass after the home reads it again copies it."""
    return [f"--filter=-p /{_literal(path.relative_to(root))}" for path in unread
            if path.is_relative_to(top)]


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
    # The home's runs and what it cannot read first, so one whose runs' folder or ~/code is a link
    # fails the pass before it copies anything.
    try:
        asked = subprocess.run(
            ["ssh", alias, shlex.join(["python3", "-I", "-", *map(str, LINKED.values()),
                                       str(config.WT), str(config.WORK)])],
            input=ASK, stdout=subprocess.PIPE, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"what to copy was not read within {TIMEOUT} seconds"
    if asked.returncode in LINKED:
        return f"{config.tilde(LINKED[asked.returncode])} is a link there"
    if asked.returncode:
        return f"reading what to copy exited {asked.returncode}"
    names = asked.stdout.split(b"\0")[:-1]
    gap = names.index(b"")
    runs = sorted({*map(os.fsdecode, names[:gap]), *(run.name for run in record.run_dirs())})
    unread = [Path(os.fsdecode(path)) for path in names[gap + 1:]]
    # Each harness path a source of its own, and ~/code: one the home lacks is never read as a
    # deletion.  The home's rsync expands each `*` (-s), not its login shell, which as zsh fails on
    # one matching nothing.
    # Then ak's folder, last, so no seat's record here names a conversation the copy lacks.  A
    # home without the folder fails rsync's sender, 23, and rsync then deletes nothing here: as a
    # deletion it would empty the copy.  Times are compared to the nanosecond, as rsync's whole
    # seconds take a same-size write within one for no change, on every pass after.  No `.git`
    # folder crosses, the git data a clone carries in itself; the rest of its checkouts does, what
    # git ignores too, and each run but its scratch.  Perishable (-p), the rules leaving out a
    # `.git` folder and a run's scratch still let rsync's delete take a checkout or run the home
    # removed, whatever it holds here.  A run is named literally, as any file is: rsync replaces a
    # link here at a run's folder, or deletes it, and never goes past it.  Nor does what the home
    # cannot read in ~/code and its checkouts cross (`_left_out`).
    # rsync tries each rule on each file, on each machine, and the runs' names are thousands, more
    # than one command may be given: they come on its input, in a transfer of the runs' folder
    # alone, which takes all inside a run before a name is tried on it; the rest crosses after.
    # rsync keeps a hard link within one transfer alone: a file with names in a run and outside
    # the runs, as a package cache links one into each checkout, crosses as two of the same bytes.
    at = config.PLACES["RUNS"]
    rules = [*(f"--exclude=/{path.relative_to(config.HOME)}" for path in KEPT),
             "--filter=-p .git/", *_left_out(unread, config.HOME, config.HOME)]
    names = b"".join(os.fsencode(f"/{at}/{_literal(run)}") + b"\0" for run in runs)
    for args, given in ((["-sR", "--no-implied-dirs", "--ignore-missing-args",
                          *_left_out(unread, config.CODE, home),
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


def _fits(words, grammar):
    """Whether `words` are `grammar`'s, each matched whole."""
    return len(words) == len(grammar) and all(map(re.fullmatch, grammar, words))


def _began():
    """Print this machine's stamp now, which a pass hands back to date its record by: 0, or 1 for
    one that cannot be taken or that `--copied` would not take."""
    try:
        line = pair_clock.now().line()      # whose boot Linux may not say
    except OSError as error:
        print(f"ak standby: this machine's stamp cannot be taken: {error.strerror}",
              file=sys.stderr)
        return 1
    if not _fits(line.split(), STAMP):
        print("ak standby: this machine's stamp is not one a record can be dated by",
              file=sys.stderr)
        return 1
    print(line)
    return 0


def _home(alias, *words):
    """ssh's words running `ak standby` with `words` by the home's installed ak, which install.sh
    links, under the home's HOME as its shell names it, so a Mac's under /Users answers too:
    asking for no password, each word quoted, as `_copy`'s are."""
    return ["ssh", "-o", "BatchMode=yes", alias,
            '"$HOME"/' + shlex.join([".local/bin/ak", "standby", *words])]


def _home_began(alias):
    """This machine's host name and the words of the stamp `alias` prints now, as `--copied`
    hands them back; none for a host name that cannot be read or that `--copied` would not take,
    which asks nothing, nor for any answer within TIMEOUT but 0 and, byte for byte, a line
    `--began` prints."""
    try:
        host = socket.gethostname()
    except OSError:
        return []
    if not re.fullmatch(HOST, host):
        return []
    end, printed = time.monotonic() + TIMEOUT, b""
    try:
        # a selector, as select(2) takes no descriptor past 1023
        with selectors.DefaultSelector() as ready, subprocess.Popen(
                _home(alias, "--began"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL) as asked:
            try:
                ready.register(asked.stdout, selectors.EVENT_READ)
                # Read to its end, as reading what to copy is, but only its first KiB kept: longer
                # than any line STAMP fits, so a longer answer is never taken for one, and a home
                # that prints on and on holds no more of this machine's memory.
                while (left := end - time.monotonic()) > 0 and ready.select(left):
                    if not (more := os.read(asked.stdout.fileno(), 1 << 16)):
                        break
                    printed = (printed + more)[:1 << 10]
                else:
                    return []
                code = asked.wait(max(end - time.monotonic(), 0))
            finally:
                asked.kill()
    except (OSError, subprocess.SubprocessError):
        return []
    said = printed.decode(errors="replace").split()
    if code or not _fits(said, STAMP) or printed != f"{' '.join(said)}\n".encode():
        return []
    return [host, *said]


def _set_back(seconds):
    """This machine's stamp now, both clocks set back by `seconds`, as a line: when the copy was
    taken by this machine's clocks alone, a wall clock off there changing nothing."""
    now = pair_clock.now()      # whose boot Linux may not say
    return now._replace(wall=now.wall - seconds, since=now.since - seconds).line()


def _keep(host, dated, takes):
    """Keep `host`'s record, whole or not at all: the stamp `dated()` gives, and whether it
    `takes` over.  0, or 1 for a record that cannot be written."""
    folder = config.TMP / COPIES
    try:
        began = dated()
        folder.mkdir(parents=True, exist_ok=True)
        # a name no host name is, as none begins with a dot, so no listing shows one
        handle, new = tempfile.mkstemp(dir=folder, prefix=".")
        try:
            with open(handle, "w") as record:
                record.write(f"{began}\n{takes}\n")
            os.replace(new, folder / host)
        except OSError:
            with contextlib.suppress(OSError):  # a folder no longer writable keeps it, unlisted
                os.unlink(new)
            raise
    except OSError as error:
        print(f"ak standby: the record of {host} could not be written: {error.strerror}",
              file=sys.stderr)
        return 1
    return 0


def _age(stamp):
    """How old the copy taken at `stamp` is, by the older of the two clocks: one set back never
    makes a copy look younger."""
    age = stamp.age_at_most()
    return f"{terminal.format_age(age)} old" if age < math.inf else "from before this boot"


def _record(path):
    """The stamp of the record at `path`, None for one that cannot be read, and whether its machine
    takes over.  Opened without waiting, so that a named pipe there holds up neither `ak standby`
    nor the tick, and read only as a regular file."""
    try:
        opened = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            if not stat.S_ISREG(os.fstat(opened).st_mode):
                return None, False
            os.set_blocking(opened, True)
            # A MiB at most, more than any record ak writes, whose boot from `pair_clock.NOW` Linux
            # keeps under 128 KiB: a damaged one may be any size.
            with open(opened, "rb", closefd=False) as record:
                held = record.read(2**20 + 1)
        finally:
            os.close(opened)
        line, takes = held.decode().splitlines() if len(held) <= 2**20 else (None, None)
    except (OSError, ValueError):     # one that may not be read, or not two lines of text
        line = takes = None
    stamp = pair_clock.read(line) if takes in ("yes", "no") else None
    return stamp, takes == "yes"


def _copies():
    """Show each machine that says it copied this one, from its record: how old its copy is and
    whether it takes over when this one stops; or that none does."""
    folder = config.TMP / COPIES
    try:
        hosts = sorted(name for name in os.listdir(folder) if re.fullmatch(HOST, name))
    except FileNotFoundError:
        hosts = []
    if not hosts:
        print("no machine copies this one")
    for host in hosts:
        stamp, takes = _record(folder / host)
        over = ", and it takes over as home when this one stops" * takes
        try:
            said = f"its copy is {_age(stamp)}{over}" if stamp else "its record cannot be read"
        except OSError:     # no age is read across a boot Linux cannot say
            said = f"its copy is of an age unknown here, as this boot cannot be read{over}"
        print(f"{host} copies this machine: {said}")
    return 0


def takes_over():
    """Whether a record this machine keeps says its machine takes over as home when this one
    stops, as `ak standby` lists one: a folder that is not there or cannot be listed holds none."""
    folder = config.TMP / COPIES
    try:
        hosts = [name for name in os.listdir(folder) if re.fullmatch(HOST, name)]
    except OSError:
        return False
    return any(stamp and takes for stamp, takes in (_record(folder / host) for host in hosts))


def _stamp(own, *lines):
    """The stamp of a pass that ended well, whole or not at all: a write cut short leaves the
    last."""
    new = own / f"{COPIED}.new"
    new.write_bytes("".join(f"{line}\n" for line in lines).encode())
    new.replace(own / COPIED)


def _copied(alias):
    """The stamp of the last pass from `alias` that ended well, and why ak here stayed where it
    was, if it did; no stamp for none yet, one cut short or one of another home."""
    try:
        line, of, *stayed = (config.TMP / FOLDER / COPIED).read_text().splitlines()
    except (OSError, ValueError):     # none yet, or one cut short
        return None, []
    return pair_clock.read(line) if of == alias else None, stayed


def _page(alias, why):
    """Tell the owner the pass from `alias` failed, `why`, once the copy is SILENT old: asked
    again at every failed pass, notify sends it once per stamp, and owed still after a move of
    ak here, which leaves the copy no younger.  What notify says of a page the webhook did not
    take is not the pass's: the next failed pass asks again."""
    try:
        stamp = _copied(alias)[0]
        # no age is read across a boot Linux cannot say, which may have gone since the pass began
        if not stamp or (age := stamp.age_at_least()) < SILENT:
            return
        # red, as the page of a project down is
        line = (f"\U0001f534 the copy of {alias} is {terminal.format_age(age)} old; the pass from "
                f"it failed: {why}")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            notify.page(f"standby:{alias}:{stamp.line()}", alias, line, line=line, owed=True)
    except Exception as exc:    # whatever it meets, the pass's exit is its copy's
        # one line, however the error reads, and its kind where it says nothing
        said = " ".join(str(exc).split()) or type(exc).__name__
        print(f"ak standby: the owner could not be told: {said}", file=sys.stderr)


def _shown():
    """Show the home this machine copies and the copy's age, from the stamp of the last pass
    that ended well: 0 only for a stamp of that home.  On no home's client, what copies it."""
    alias = config.server_alias()
    if not alias:
        return _copies()
    stamp, stayed = _copied(alias)
    if not stamp:
        print(f"this machine copies {alias}: no pass from it has ended well yet")
        return 1
    print(f"this machine copies {alias}: the copy is {_age(stamp)}")
    for why in stayed:
        print(f"ak here does not follow {alias} yet: {why}")
    return 0


def main(argv):
    if command_help.show("standby", argv):
        return 0
    if not argv:
        return _shown()
    if argv == ["--began"]:
        return _began()
    flag, *said = argv
    if flag == "--copied" and _fits(said, SAID):
        host, seconds, takes = said
        return _keep(host, lambda: _set_back(int(seconds)), takes)
    if flag == "--copied" and _fits(said, (HOST, *STAMP, TAKES)):
        host, *stamp, takes = said
        return _keep(host, lambda: " ".join(stamp), takes)
    if len(argv) != 1 or argv[0].startswith("-"):
        raise config.Error(command_help.COMMANDS["standby"][0])
    alias, home = argv[0], Path.home()
    copied = [*_harnesses(), str(config.CODE.relative_to(home))]
    refused = [f"this machine is not a client of {alias}"] * (config.server_alias() != alias)
    # The home's ~/code would take the place of the ak running here.  realpath, as Python 3.11's
    # `Path.resolve` raises at a link here that loops.
    refused += [f"ak runs from {config.tilde(config.REPO)} here, under "
                f"{config.tilde(config.CODE)}"] * config.REPO.is_relative_to(
                    os.path.realpath(config.CODE))
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
        began, held = pair_clock.now(), _home_began(alias)
        if why := _copy(alias, home, copied):
            print(f"ak standby: the pass from {alias} failed: {why}", file=sys.stderr)
            _page(alias, why)
            return 1
        _stamp(own, began.line(), alias)
        if why := update.follow(alias)[1]:
            _stamp(own, began.line(), alias, why)
        versions.final(time.time())
        if held:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(_home(alias, "--copied", *held, "no"), stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=TIMEOUT)
    return 0
