"""`ak standby ALIAS`: one pass of this machine's copy of the home it is a client of, at the same
paths: what a seat carrying on from the copy needs of each harness, its logins, every account's,
and the folders its conversations start from, the rest of that harness's folders this machine's
own; then ~/code, as rsync copies any folder: every file, a `.git` folder's too, a link as the
link it is; then ak's folder, but each `.git` folder in it, a clone's own git data, each box's
scratch, wherever it lies, a run's other scratch, and each name in the runs' folder that is no
run on either machine, such as each machine's own locks and queues.  Nor does what the home's
account cannot read under ~/code and ak's checkouts, `wt` and `work`, cross: each folder it
cannot list or enter, with all in it, and each regular file it cannot read, such as a test
stopped before it cleaned up leaves, which would fail every pass.  Elsewhere one fails the pass,
as any error of rsync's does, in a `.git` folder under ~/code too, which the walk enters none of;
and so do more of them than one command may be given, each an argument of rsync's.
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
The next that ends well evens it out.  While a transfer runs, the pass reads the clock ticks
rsync and its children have used (`host.work_ticks`) once a second; a transfer whose reading
stays the same for `TIMEOUT` seconds is sent SIGTERM, then SIGKILL `worker.KILL_GRACE` seconds
later, and fails the pass, while one that keeps working, or runs where there is no /proc, is
never ended for how long it takes.

Under its lock, first of all, it reads the record of a server again, as a pass that held the lock
meanwhile may have made this machine a home, has ak's tmux server here end each session marked as
a seat (`_close`), a client's being on its home, and asks whether ak's lease is this machine's own
(`lease.ours`).  Where it is, the remote has said this machine is the home, whose state a copy of
the old one would overwrite: the pass copies nothing and runs `install.sh --server`, exiting what
the install exited, whose record of a server says whether this machine is a home after it, and
where it exited 0 tells the owner (`_took_over`).  Else it watches its home's lease
(`lease.watch`), whose record is the lease's, kept whatever the pass does.  It may take the lease
only where the stamp, read before it, says a pass from this home ended well less than GONE ago, by
the clock calling it older: the machine that takes it carries on from its copy, and one holding
none, or an older one, would from a state the home has moved past.  Then it keeps this machine's
own job, which makes the pass again every three minutes, as the home's tick runs, after the keeper
of a move of ak here, as the tick's line runs it (`back`), then sends again, as a tick does, each
page of this machine's own the webhook did not take (`notify.retry_pending`), whether the home
answers or not.
A pass that ends well stamps when it began, and from which home, then why ak here stayed where it
was, if it did, and at its end does with the last move here what the end of a tick does on a home
(`versions.final`): a pass of the version that move put live makes it final.
One that fails, however it fails, stamps nothing and makes nothing final, for it cannot tell a
silent home from code that is broken, and `ak standby`, which reads the copy's age from the stamp,
shows passes failing as an age that goes on growing.  One that fails with a reason keeps when it
failed, beside the stamp and naming it, where none kept names the stamp, and asks `notify.page` to
tell the owner once every pass has failed since one at least `SILENT` ago, by the clock calling it
younger, under a key of the home and the stamp: notify alone keeps whether that went out, and
sends it once.  A pass's exit is its copy's alone: the copy is what a takeover needs first.

A home keeps a record of each machine that says it copied it (`_keep`), which `ak standby` and the
Machines page list there (`copies`), and of which its tick pages the owner once its copy is GONE old
(`tell`).  A pass asks the home for a stamp of its own where it takes its own (`_began`), and one
that ends well hands it back as printed, last: a record dated by the seconds since the pass began
would be dated younger than its copy by however late the request arrives, and one dated by the
home's stamp never is; with it goes the word the records here give (`_told`).  Neither request is
anything of the pass's own: what it prints, its exit and its copy are the same whatever the home
answers, or whether it does.
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
import subprocess
import sys
import tempfile
import time

from . import (box, command_help, config, host, lease, machine_turn, move, notify, orch,
               pair_clock, record, terminal, update, versions, worker)

# This machine's own in ak's folder, which a pass neither sends nor deletes: which server it is
# a client of, its ak install and whether its install.sh is owed, the pages it sent and owes
# (`back` pages from here), and what each machine keeps through a move.
KEPT = tuple(path for path in (config.STATE / "server", versions.repository(),
                               config.HOME / versions.VERSIONS, config.STATE / update.PENDING,
                               notify.outbox(), *move.KEPT)
             if path.is_relative_to(config.HOME))
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
# Under `wt` and `work`, it also enters no box's scratch: rsync leaves it out of ak's folder, and
# a live box makes folders of mode 000 inside it during a pass; under ~/code it still does.
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
folders = [(os.fsencode(top), skip_box)
           for top, skip_box in ((code, False), (wt, True), (work, True))
           if not os.path.islink(top)]
while folders:
    folder, skip_box = folders.pop()
    try:
        found = list(os.scandir(folder))
    except FileNotFoundError:
        found = []
    for entry in found:
        if entry.is_dir(follow_symlinks=False):
            if entry.name == b".git" or (
                    skip_box and entry.name.startswith({os.fsencode(box.SCRATCH)!r})):
                continue
            if os.access(entry.path, os.R_OK | os.X_OK):
                folders.append((entry.path, skip_box))
            else:
                sys.stdout.buffer.write(entry.path + b"\\0")
        elif entry.is_file(follow_symlinks=False) and not os.access(entry.path, os.R_OK):
            sys.stdout.buffer.write(entry.path + b"\\0")
""".encode()
# Seconds of silence from the home, or of a transfer whose `host.work_ticks` reading stays the
# same, that fail a pass: fewer where a key sets AK_STANDBY_TIMEOUT to 1 to 99, so one can wait
# out a machine or transfer that stalls.  Any other value leaves 300, as only shortening is of
# use, and none fails this module's import, which the tick makes before it reads ak's lease, nor a
# wait too long for a selector.
TIMEOUT = int((re.fullmatch(r"[1-9][0-9]?", os.environ.get("AK_STANDBY_TIMEOUT", ""))
               or ["300"])[0])
# How long every pass has failed, from the first to fail after the stamp, when a failed pass pages
# the owner: on a Mac, ak's own check starts a dead Linux machine again after 10 minutes without an
# answer, and 20 leave it the time to come back.  Not the copy's age: a pass over a home at work
# takes 5 to 15 minutes, so one failing after a slow one would page, and the next heal it.
SILENT = 20 * 60
# This machine's own folder of the copy, in ak's tmp folder: the stamp of the last pass that ended
# well, when the first pass to fail after it failed, and the lock a pass holds, which the kernel
# lets go of when the pass ends, however it ends.  Names, not paths: each follows HOME, as config's
# places do.  install.sh keeps the runs, checkouts and work of a client with this folder, a standby.
FOLDER, COPIED, FAILING, LOCK = "standby", "copied", "failing", "lock"
# A home's own, in ak's tmp folder, which no pass copies, beside FOLDER and never in it, as FOLDER
# there is what makes a client a standby: a record of each machine that says it copied this one,
# named by its host name.
COPIES = "copies"
# A record's age at which the home's tick pages the owner: a first pass after a long gap may take
# half an hour, and no other pass begins while it runs, so an hour without one is no slow copy.
# A standby whose copy is this old takes no lease: the owner has been told, and ak waits for a
# machine to come back.
GONE = 60 * 60
# The bytes of a record or a stamp read at most: more than any ak writes, whose boot from
# `pair_clock.NOW` Linux keeps under 128 KiB, as a damaged one may be any size.
MOST = 2**20
# The words of `ak standby --copied HOST WALL SINCE BOOT yes|no|back`, each matched whole: a host
# name of at most 64 characters, as Linux's, this machine's stamp as `--began` prints it, and
# whether that host takes over: `back` as `yes` does, and home goes back to it once it is steady.
# Each clock in decimals, no sign or exponent, and a boot no dash begins, so that no word is taken
# for a flag.
HOST = "[A-Za-z0-9][A-Za-z0-9.-]{0,63}"
TAKES = "yes|no|back"
OVER = ("yes", "back")      # the words of a record whose machine takes over
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


def _rsync(cmd, given):
    """Run rsync as `cmd`, with `given` on its input from a file where given, in this pass's own
    process group and on its terminal where it has one.  Read `host.work_ticks` of it once a
    second: a transfer whose reading stays the same for `TIMEOUT` seconds is sent SIGTERM, then
    SIGKILL where it has not exited `worker.KILL_GRACE` seconds later, and fails the pass.  Why
    it failed, or None."""
    # The runs' names are thousands, more than a pipe holds, so they come from a file before
    # rsync starts rather than a pipe ak feeds while it watches.  No `with Popen`: its exit
    # waits without end on a process that ignored SIGKILL.
    if given is None:
        proc = subprocess.Popen(cmd)
    else:
        with tempfile.TemporaryFile() as feed:
            feed.write(given)
            feed.flush()
            feed.seek(0)
            proc = subprocess.Popen(cmd, stdin=feed)
    def outcome(code):
        # A file the home deleted while rsync read it is no failure, as in a move: all that is
        # still there crossed, and what this machine held of the file goes with the next pass.
        # A home at work deletes in its checkouts all the time: on 17 Nov a second and a third
        # go each met more, and the passes failed for it.
        return None if code in (0, move.VANISHED) else f"rsync exited {code}"

    last, idle = None, 0
    while True:
        try:
            return outcome(proc.wait(timeout=1))
        except subprocess.TimeoutExpired:
            pass
        ticks = host.work_ticks(proc.pid)
        if (code := proc.poll()) is not None:
            return outcome(code)
        if ticks is None or ticks != last:
            last, idle = ticks, 0
        elif (idle := idle + 1) >= TIMEOUT:
            proc.terminate()
            # `Popen.terminate` polls first and skips SIGTERM where rsync exited meanwhile.
            if proc.returncode is not None:
                return outcome(proc.returncode)
            try:
                proc.wait(timeout=worker.KILL_GRACE)
            except subprocess.TimeoutExpired:
                proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=worker.KILL_GRACE)
            return f"rsync did nothing for {TIMEOUT} seconds"


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
    # folder crosses, the git data a clone carries in itself, nor scratch, which goes when its turn
    # ends: in one three-minute window on 9 Nov the owner's home wrote 1.8 GB in it against 26 MB
    # outside.  A box's, wherever it lies, as a test suite in a checkout makes runs and boxes of
    # its own there: one made after the ask, holding its overlay's work folder of mode 000, failed
    # rsync's sender reading the checkouts (25 Nov).  A run's `tmp…` folders, scratch in a run
    # alone, as in a checkout one is the project's.  The rest of the checkouts crosses, what git
    # ignores too.  Perishable (-p), the rules leaving out a `.git` folder and scratch still let
    # rsync's delete take a checkout or run the home removed, whatever it holds here.  A run is
    # named literally, as any file is: rsync replaces a link here at a run's folder, or deletes
    # it, and never goes past it.  Nor does what the home cannot read in ~/code and its checkouts
    # cross (`_left_out`).
    # rsync tries each rule on each file, on each machine, and the runs' names are thousands, more
    # than one command may be given: they come on its input, in a transfer of the runs' folder
    # alone, which takes all inside a run before a name is tried on it; the rest crosses after.
    # rsync keeps a hard link within one transfer alone: a file with names in a run and outside
    # the runs, as a package cache links one into each checkout, crosses as two of the same bytes.
    at = config.PLACES["RUNS"]
    rules = [*(f"--exclude=/{path.relative_to(config.HOME)}" for path in KEPT),
             *(f"--filter=-p {name}/" for name in (".git", f"{box.SCRATCH}*")),
             *_left_out(unread, config.HOME, config.HOME)]
    names = b"".join(os.fsencode(f"/{at}/{_literal(run)}") + b"\0" for run in runs)
    for args, given in ((["-sR", "--no-implied-dirs", "--ignore-missing-args",
                          *_left_out(unread, config.CODE, home),
                          *(f"{alias}:{home}/./{path}" for path in copied), f"{home}/"], None),
                        ([*rules, f"--filter=-p /{at}/**/tmp*/", f"--filter=+ /{at}/*/**",
                          "--from0", "--include-from=-",
                          f"--filter=- /{at}/*", f"--filter=+ /{at}/", "--filter=- /*",
                          f"{alias}:{config.HOME}/", f"{config.HOME}/"], names),
                        ([f"--exclude=/{at}", *rules, f"{alias}:{config.HOME}/",
                          f"{config.HOME}/"], None)):
        if why := _rsync([
            "rsync", "-aHz", "--no-D", "--delete", "--modify-window=-1", f"--timeout={TIMEOUT}",
            *(["--info=progress2"] if sys.stdout.isatty() else []), *args], given):
            return why
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


def _keep(host, line, takes):
    """Keep `host`'s record, whole or not at all: the stamp's `line`, and TAKES's word `takes`.
    0, or 1 for a record that cannot be written."""
    folder = config.TMP / COPIES
    try:
        folder.mkdir(parents=True, exist_ok=True)
        _stamp(folder / host, line, takes)
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
    """The stamp of the record at `path` and its word of TAKES, both None for one that cannot be
    read."""
    try:
        held = config.read_regular(path, MOST + 1)
        line, takes = held.decode().splitlines() if len(held) <= MOST else (None, None)
    except (OSError, ValueError):     # one that may not be read, or not two lines of text
        line = takes = None
    stamp = pair_clock.read(line) if re.fullmatch(TAKES, takes or "") else None
    return (stamp, takes) if stamp else (None, None)


def copies():
    """Each machine a record here says copied this one, in the order of their names: its host
    name, how old its copy is or why that cannot be said, and its record's word of TAKES; for a
    record that cannot be read, that it cannot, and no word.  None on a client, which no machine
    stands in for.  config.Error for a folder of records that cannot be listed, which may hold
    one that takes over."""
    if config.server_alias():
        return []
    folder = config.TMP / COPIES
    try:
        hosts = sorted(name for name in os.listdir(folder) if re.fullmatch(HOST, name))
    except FileNotFoundError:
        hosts = []
    except OSError as error:
        raise config.Error(f"the records of the machines that copy this one cannot be read: "
                           f"{error.strerror}") from None
    found = []
    for host in hosts:
        stamp, takes = _record(folder / host)
        try:
            age = _age(stamp) if stamp else "its record cannot be read"
        except OSError:     # no age is read across a boot Linux cannot say
            age = "of an age unknown here, as this boot cannot be read"
        found.append((host, age, takes))
    return found


def _copies():
    """Show each machine that says it copied this one, from its record: how old its copy is and
    whether it takes over when this one stops, and home goes back to it once it is steady; or
    that none does."""
    found = copies()
    if not found:
        print("no machine copies this one")
    for host, age, takes in found:
        over = ", and it takes over as home when this one stops" * (takes in OVER)
        over += ", and home goes back to it once it is steady" * (takes == "back")
        said = f"its copy is {age}{over}" if takes else age
        print(f"{host} copies this machine: {said}")
    return 0


def _records():
    """The path of each record this machine keeps, named by its machine's host name: a folder
    that is not there or cannot be listed holds none."""
    folder = config.TMP / COPIES
    try:
        return [folder / name for name in os.listdir(folder) if re.fullmatch(HOST, name)]
    except OSError:
        return []


def _takes(path):
    """Whether the record at `path` reads as a stamp and says its machine takes over."""
    return _record(path)[1] in OVER


def takes_over():
    """Whether a record this machine keeps says its machine takes over as home when this one
    stops, as `ak standby` lists one."""
    return any(map(_takes, _records()))


def _takers():
    """Print the name of each machine a record here says takes over, one a line in the order of
    their names, for a client that must reach one once this home no longer answers."""
    for path in sorted(_records()):
        if _takes(path):
            print(path.name)
    return 0


def _told():
    """The word another machine's record of this one shall say, by the words of the records here
    that read as a stamp: `back` where one says `yes`, which the machine home first holds; else
    `yes`, as home goes back to a machine a record here says `back` of, never to this one, which
    stood in for it.  No record is picked out: a machine is told by its ssh alias and its record
    here is named by its host name, and nothing ties the two."""
    return "back" if "yes" in {_record(path)[1] for path in _records()} else "yes"


def tell():
    """Tell the owner of each machine whose copy of this one is GONE old, by the clock calling it
    younger: asked again at every firing of the tick, notify sends a page once for each record's
    stamp, and a pass by that machine meanwhile leaves a new stamp.  Whatever a record holds, or
    listing, reading or paging meets, is dropped unsaid, as is what notify says of a page the
    webhook did not take, and the tick goes on as it would: its next firing asks again."""
    with (contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()),
          contextlib.suppress(Exception)):
        for path in _records():
            with contextlib.suppress(Exception):    # one record's failure leaves the rest paged
                stamp = _record(path)[0]
                # no age is read across a boot Linux cannot say
                if stamp and (age := stamp.age_at_least()) >= GONE:
                    # red, as the page of a project down is
                    line = (f"\U0001f534 the copy of this home on {path.name} is "
                            f"{terminal.format_age(age)} old")
                    notify.page(f"copy:{path.name}:{stamp.line()}", path.name, line, line=line,
                                owed=True)


def _stamp(path, *lines):
    """`lines` at `path`, whole or not at all: a write cut short leaves the last.  Through a file
    made new, as one already at a fixed name, a named pipe, would hold the write up."""
    # a name no host name is, as none begins with a dot, so no listing of records shows one
    handle, new = tempfile.mkstemp(dir=path.parent, prefix=".")
    try:
        with open(handle, "wb") as file:
            file.write("".join(f"{line}\n" for line in lines).encode())
        os.replace(new, path)
    except OSError:
        with contextlib.suppress(OSError):  # a folder no longer writable keeps it, unlisted
            os.unlink(new)
        raise


def _last():
    """The stamp of the last pass that ended well, the home it copied, and why ak here stayed
    where it was, if it did; no stamp nor home for none yet, one cut short or one whose first
    line is no stamp, and no home for a name no pass takes, which ssh would read as an option.
    Of one longer than MOST, only the whole lines in its first MOST bytes are read: what follows
    them may be anything, but those still say which home it copied."""
    try:
        held = config.read_regular(config.TMP / FOLDER / COPIED, MOST + 1)
        if len(held) > MOST:
            held = held[:MOST].rpartition(b"\n")[0]
        line, of, *stayed = held.decode().splitlines()
    except (OSError, ValueError):     # none yet, or one cut short
        return None, None, []
    stamp = pair_clock.read(line)
    return stamp, of if stamp and not of.startswith("-") else None, stayed


def _copied(alias):
    """The stamp of the last pass from `alias` that ended well, and why ak here stayed where it
    was, if it did; no stamp for none yet, one cut short or one of another home."""
    stamp, of, stayed = _last()
    return stamp if of == alias else None, stayed


def _failing(stamp):
    """When the first pass to fail since the one that ended well at `stamp` failed: now, kept,
    where what is kept names another stamp, is cut short or cannot be read.  One that cannot be
    kept begins the count at every pass, which pages nobody early and fails none."""
    path = config.TMP / FOLDER / FAILING
    with contextlib.suppress(OSError, ValueError):  # ValueError: not two whole lines of text
        held = config.read_regular(path, MOST + 1)
        # each line whole, as a line cut short may still read as a stamp, of another boot
        named, first, end = held.decode().split("\n") if len(held) <= MOST else ()
        if (named, end) == (stamp.line(), "") and (first := pair_clock.read(first)):
            return first
    first = pair_clock.now()
    with contextlib.suppress(OSError):
        _stamp(path, stamp.line(), first.line())
    return first


def _page(alias, why):
    """Tell the owner the pass from `alias` failed, `why`, once every pass has failed for SILENT:
    asked again at every failed pass, notify sends it once per stamp, and owed still after a move
    of ak here, which ends no failing.  What notify says of a page the webhook did not take is not
    the pass's: the next failed pass asks again."""
    try:
        stamp = _copied(alias)[0]
        # no age is read across a boot Linux cannot say, which may have gone since the pass began
        if not stamp or _failing(stamp).age_at_least() < SILENT:
            return
        # red, as the page of a project down is
        line = (f"\U0001f534 the copy of {alias} is {terminal.format_age(stamp.age_at_least())} "
                f"old; the pass from it failed: {why}")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            notify.page(f"standby:{alias}:{stamp.line()}", alias, line, line=line, owed=True)
    except Exception as exc:    # whatever it meets, the pass's exit is its copy's
        # one line, however the error reads, and its kind where it says nothing
        said = " ".join(str(exc).split()) or type(exc).__name__
        print(f"ak standby: the owner could not be told: {said}", file=sys.stderr)


def _took_over(alias, value):
    """Tell the owner ak's home is this machine now, in place of `alias`, once for the lease of
    `value` it took: a pass whose install left this machine a client asks again under the same key,
    and notify sends a page once per key.  Not why, as the same pass follows a home that stopped
    and one that handed home back.  Whatever paging meets, the pass's exit is the install's."""
    with contextlib.suppress(Exception):
        # red, as the page of ak going back from a version is
        line = f"\U0001f534 ak's home is {socket.gethostname()} now: it took over from {alias}"
        notify.page(f"home:{value.decode()}", "ak", line, line=line, happened=True)


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


def _elsewhere(alias):
    """Why a pass from `alias` is refused by the record of a server: one reason, or none where the
    record names `alias`."""
    return [f"this machine is not a client of {alias}"] * (config.server_alias() != alias)


def _refused(reasons):
    """Whether a pass is refused, saying so for each of `reasons`."""
    for reason in reasons:
        print(f"ak standby: refused: {reason}", file=sys.stderr)
    return bool(reasons)


def _close():
    """Have ak's own tmux server here, then the user's default one, where seats older than ak's
    own server are (`orch.sessions`), list its sessions and, at each one's turn, by its id, end it
    where tmux's format reads a seat's mark (`orch.MARK`) as `1` for it then and it has an option
    of its own under that mark, without which its turn fails there: a seat `orch.start` opened,
    which on a client carries on a conversation its home carries on too.  A session's name
    decides nothing, nor a mark every session inherits, nor one set or cleared between the
    listing and the session's turn.  Nothing is read back, and the pass goes on the same whatever
    tmux did: a session made since the listing, and one tmux did not end, failing or not running,
    is the next pass's.  A pass run inside a session it ends ends with it, as any command does
    whose terminal closes."""
    # The owner, 26 Nov 2026, "stop here": a seat's own hooks stay unrefused on a client, tmux's
    # `pane-died` (`ak orch ended`) and the harness's stop hook (`watch.hook_look`).  Either
    # needs a seat's session already here, which this ends.
    # One call a server, so the server that lists is the one that ends: one started at the socket
    # between two calls numbers its sessions from $0 again, under the pid of one gone.
    # `run-shell -C` reads what its loop (`#{S:}`) lists as one command list, so each session's
    # turn is a `{}` of its own, which one failing stops alone; `#{l:}` keeps the mark's reading
    # for that turn.
    session = "'#{session_id}'"
    turn = (f"if-shell -F -t {session} '#{{l:#{{==:#{{{orch.MARK}}},1}}}}' "
            f"{{ show-options -t {session} {orch.MARK} ; kill-session -t {session} #}}\n")
    for socket in (None, ""):
        orch.tmux_out("run-shell", "-C", f"#{{S:{turn}}}", socket=socket)


def main(argv):
    if command_help.show("standby", argv):
        return 0
    if not argv:
        return _shown()
    if argv == ["--began"]:
        return _began()
    if argv == ["--takers"]:
        return _takers()
    if argv == ["--home"]:
        from . import pause     # here, as pause imports this module
        return 0 if pause.holds() else 1
    if argv == ["--steady"]:
        from . import hand_back     # here, as it imports this module
        return 0 if hand_back.steady() else 1
    flag, *said = argv
    if flag == "--copied" and _fits(said, (HOST, *STAMP, TAKES)):
        host, *stamp, takes = said
        return _keep(host, " ".join(stamp), takes)
    if len(argv) != 1 or argv[0].startswith("-"):
        raise config.Error(command_help.COMMANDS["standby"][0])
    alias, home = argv[0], Path.home()
    copied = [*_harnesses(), str(config.CODE.relative_to(home))]
    refused = _elsewhere(alias)
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
    if _refused(refused):
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
        # again: a pass that held the lock may have made this machine a home since
        if _refused(_elsewhere(alias)):
            return 1
        _close()
        if taken := lease.ours():
            checkout = update.agentkit_dir()
            code, said = versions.run([str(checkout / "install.sh"), "--server"], checkout,
                                      **update.PINS)
            if code:
                print(f"{said}\nak standby: this machine holds ak's lease, and "
                      f"{checkout / 'install.sh'} --server exited {code}", file=sys.stderr)
                return code
            _took_over(alias, taken)
            return 0
        # Only from a copy under GONE old by the clock calling it older: an older one would carry
        # ak on from a state its home has moved past, then be copied over the home's own once it
        # is back.
        lease.watch(bool(stamp := _copied(alias)[0]) and stamp.age_at_most() < GONE)
        if not _keep_job(alias):
            return 1
        notify.retry_pending()
        began, held = pair_clock.now(), _home_began(alias)
        if why := _copy(alias, home, copied):
            print(f"ak standby: the pass from {alias} failed: {why}", file=sys.stderr)
            _page(alias, why)
            return 1
        _stamp(own / COPIED, began.line(), alias)
        if why := update.follow(alias)[1]:
            _stamp(own / COPIED, began.line(), alias, why)
        versions.final(time.time())
        if held:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(_home(alias, "--copied", *held, _told()), stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=TIMEOUT)
    return 0
