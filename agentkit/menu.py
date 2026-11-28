"""`ak`: the menu.  Numbers and single letters, and nothing else: on a terminal each one acts
the moment it is pressed, and from a pipe it is a line.

    agentkit                                                              14:02
    ────────────────────────────────────────────────────────────────────────
      Claude I    ━━────────  21% left   ChatGPT     ━━━━━━━───  69% left


    atoll
    › 1  atoll-speed-check   fable   ! needs you   ━━━━━━━━━━━━━──────── 3 of 5
           Merge the MOV helper before or after?
      2  fix-api             fable   ● working     ━━━━╸───────────────── 2 of 9
      3  web-portal          fable   ✓ done

      ↑↓←→ move   ⏎ open   n new   c config   esc leave

`n` asks for a name, then shows the orchestrator and both roles with the last created session's
chosen already.
Enter leaves naming to the orchestrator once it knows the work. The name is the row, the
status bar and the title of every message it sends until a rename of its conversation or
`ak orch rename` changes it.

A session is **working**, **needs you**, **done**, **idle** or **out of usage**, and nothing else
exists: it works until it is done or it is blocked on him, or it rests with nothing running,
asked or owed, or its usage is spent until it comes back.  `watch.session_state` decides which, once, from the
facts -- an expired login, its own runs, a turn in flight, a seat
nobody is in any more, what it last said with `ak notify` -- and every screen here reads that
one answer: the row, the top line, `ak orch list`, `ak orch why`, the
seat's own status bar and its window title.  `ak orch why <seat>` says what decided it.

A row is one line: number, name, orchestrator, state, and one last column, its progress line
in the room the row has (`terminal.plan_bar`, from `~/.agentkit/state/plan-<session>.md`, under
any name a rename led from, else from its unfinished jobs) while it is not at rest, its work
waiting to land too, else empty, then whatever its word how many tasks it has in flight
(`own_tasks`), `3 of 8 · 2 tasks`, `2 tasks` -- and `¶ unsent` after it where the owner left
text unsent.
What the owner left unsent, then who builds and reviews (`crew`), open under the row
(`detail`), never what a seat said nor a task's squares.  Never two state words on a row,
never `N running`, and never a time estimate.

`ak orch list` carries, after the word, a tally of the runs that seat launched, read from
their run.json records and nothing else: `<n> running`, then one finished figure -- `<n> needs
you` (this week's interrupted, failed or errored runs, and its PASSes nobody merged, that
nobody has acknowledged) whenever there are any, otherwise `<n> merged` over the last seven
days; a seat that has launched nothing says `no runs yet`.

The title is `agentkit` and the clock, and says nothing about the machine or the build;
drawing the menu calls git for nothing at all; behind its first frame a detached process asks
origin whether ~/agentkit is behind and updates it (update_first).  A usage row is one
account's *shared* weekly meter -- the one every model of it draws on: a provider that lists
`accounts` has one row per account in config order, numbered in roman numerals (`Claude I`,
`Claude II`), each from its own reading, and a provider without them keeps its
single row.  A bar and `NN% left`, then `resets <weekday> <HH:MM>` in local time, then
`Fable 41%` for a scoped cap that reads differently, then `5h 40% left` for the 5-hour
window (`5h spent until 14:00` once it reads 100% used), then `1 reset in hand` while the
subscription holds usage-limit resets for the owner to spend from its meter, then `? <reason>`
when the last probe errored though the meter it read still stands, and `as of HH:MM` beside it when
that reading is older than half an hour, with the weekday when it is not from today.
A probe the endpoint would not answer says nothing at all: its reading stands as it was,
and past half an hour its age says the rest.
The bar's filled cells are in the text's colour, amber while its login ends soon; the rows run
in the order config.toml names their providers.  `—` is drawn
only when there is no shared week to draw -- no reading at all, or nothing but one model's
private cap -- and the words after it say why.  Everything else `ak usage` knows -- week
elapsed, headroom, budget, outlook -- stays in `ak usage`.

The main screen is live.  It draws at once from the cached meters, then probes every provider
in the background and draws again when the answer lands, and again every ten seconds after
that, so the clock, the seat rows, the counts and the usage stay true while it is open.  A
reading younger than `usage.PROBE_EVERY` is fresh, so the probe asks an adapter at most once a
minute -- the cadence is the host's and not this screen's -- and never blocks a keypress or a
draw; Muse's adapter keeps its own ten-minute cache, because its probe is a billed request.
Those ten seconds hold whatever stdin is, a script's half-written line included, and a key typed
during a draw is read by the next wait.  At rest one thing moves: on a terminal of 256 colours or
more each working seat's `●` breathes, all in one phase, on `motion`'s clock (`moving`); and
news seen while the menu is up moves once on it -- a `!` pulses, a `✓` settles, a usage bar
glides -- then is still.  A seat's `c` follows its record within a second; other sub-screens
are read once, like any other question, except a project's feature switches, which draw again
within a second of their `list` landing.

Six keys: the numbers, `n`, `x` (in the popup only), `p` (the sessions you stopped, offered while there is one),
`c` (the popup's own seat's models, else new seats', every model's effort,
providers, discord, version), and Esc, which leaves, as it goes back from every
screen and question under it; `q` is no key.  Nothing needs a manual: the pointer lights what
a click there acts on and says nothing more of it on the key line.  A question typed inside the
menu is typed on its keys (`terminal.field`), so Esc cancels it at once.  From a pipe an empty
line or the end of input leaves, or goes back.
On a terminal one seat row is highlighted as well: ↑/↓, k/j and the wheel move it, Enter or a
click opens a seat, and a click on the key line does what its key does (`loop`,
`terminal.Keyboard`).  `x` is
only in the popup, and only its own seat's, whichever row is highlighted: a done one is closed at
once, and any other is asked about under its row, `Keep` or `Stop` -- so the key line says
`x close` while that seat is done.  A stopped
seat leaves its project for the past screen, `p` (`show_past`), listed by the day it closed;
Enter reopens it where it stopped and `x` asks before it takes it off.  `c` holds
the orchestrator, executors and reviewers of the seat the popup is over, or of new seats in a
window of its own: the orchestrator moves the seat at once, the roles flip with the same keys
and save at once; new seats' `a` gives theirs to every seat on the main screen (apply_defaults).
`ak run status` and `ak browser` stay as commands for
orchestrators; the menu no longer offers them. A gone session keeps its row, and its number
reopens it; one you stopped has no row under its project, only its row on the past screen; an
ended run is its orchestrator's business, so no row ever says `press r`.

The screen is budgeted by height as well as width: the usage stays on top and the keys at the
bottom, and a list of seats longer than the room between them is drawn a page at a time -- on a terminal the page the highlight is on, which ← and →
turn, from a pipe the one `j` and `k` turn to -- and a row keeps the number it has in the whole list on whichever page
it is drawn, so what a number opens never depends on the page that is up.

`ak attach --overlay` is the same menu inside a seat, where `ak orch` binds it to `Ctrl-b m` as
a tmux popup: the same rows, keys and acts, `x` added, its highlight starting on that seat.  What
hands this client a seat -- a number, Enter, `n`, a past session reopened -- and `x` close the
popup, so the seat is seen.

On the server the menu is this process.  On a client -- a machine where install.sh recorded the
server's ssh alias in ~/.agentkit/state/server -- `ak` runs the same menu over `ssh -t <alias>
ak --client`.  `ak attach` is the same menu under the name the phone
key uses.
"""

import copy
import datetime
import decimal
import errno
import hashlib
import heapq
import json
import math
import os
import re
import select
import shlex
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path

from . import command_help, config, gitcall, handback, history, matrix, motion, notify, orch, owner, plan, quality, staffing, terminal, transitions, update, usage, worker
from . import carried, done_check, logins, look, machines, money, open_runs, parsed, readings, record, releases
from . import size_table, standby, takers, warm
from .harness import load as harness_plugin

KEYS = "n new   c config   esc leave"
STOP_ASK = "Stop {} and everything it runs?"   # what `x` asks under a seat that is not done
PAGE_KEYS = "j more   k previous"   # added to the key line when the list runs to more pages
BORN = " new"            # the name of the row `n` makes: none of a seat's, which holds no space
BORN_KEYS = "⏎ start   tab models   esc back"
UNFILED = "not assigned yet"   # the heading of the seats no project has yet, the new row's too
LEAST = 3                # rows a page keeps; the usage block folds before it holds fewer
OPENS = 4                # lines a page keeps for what a row opens before the usage folds
# The whole vocabulary, worst first: a rollup of seats says the one that wants him, and an idle
# seat sorts last in its project.  `watch.session_state` is what decides which of the five a
# seat is.
STATE_ORDER = ("needs you", "out of usage", "working", "done", "idle")
TICK = terminal.TICK     # the longest the main screen waits for a key before drawing itself again
WALK_EVERY = 60          # seconds one walk of a quiet run answers for: silence is told in hours, so
                         # a minute never shows, however many files a run's sandbox leaves behind
_WALKED = {}             # a quiet run's directory: when it was walked, on time.monotonic, and what
                         # that found
STIR = 1.0               # ... and the longest it goes between looks for a seat's word or the meters
LOOK_EVERY = 0.25        # ... the wait between two looks after the first: a word a seat holds for
                         # half a second is drawn, and looking costs four looks a second, less on a
                         # quicker host as all the screen's work is.  A wait of a hundred times what
                         # the last look cost spent a hundredth of a thread on any host, a third of
                         # what a screen over sixty gone seats may spend on a quiet one
                         # (tests/test_key_gone_seats_cost_an_open_screen_little.py)
# A menu starts over once a read it asked for is owed STUCK times the slowest a read lately took
# to land, from its ask or its round's start, OWED at the least (`Live.stuck`).  A read slower
# than any lately raises that wait as it lands; as reads quicken it halves every SLOW_HALF
# seconds: a host where reads take 20 s waits minutes, a quick one OWED.  The slowest crosses the
# restart (SLOWEST), so one stuck again waits as long.
STUCK = 10
OWED = 3 * TICK
SLOW_HALF = 300
SLOWEST = "AK_MENU_SLOWEST"
CLOCK = time.monotonic   # a read is owed in the time its thread takes: not `time`'s, which a
                         # test stills to draw frame by frame
# What the `—` says, from the error the last probe left; the first match wins.  No pattern here
# guesses at a login: `token`, `401` and `login` turn up in lines a logged-in seat produces too,
# and the one party that can say is the harness's `auth` verb, which the probe asks and records.
UNREAD = ((re.compile(r"already reset"), "window reset"),
          (re.compile(r"without a name"), "bad reading"),
          (re.compile(r"returned no meters"), "no reading yet"))
USAGE = ("usage: ak [--client] [--overlay] [--dry-run]   "
         "(the menu; `ak attach` is the same)")
RUN_RECORDS = "run-records.db"   # under STATE: one independently replaceable row per run.json
_RUN_RECORDS = None
_RUN_RECORDS_LOCK = threading.Lock()
# The code `found` and `groups` are made and read in: a read crosses a restart only to the same.
CODE = hashlib.sha256(b"".join(Path(__file__).with_name(name).read_bytes()
                               for name in ("menu.py", "orch.py"))).hexdigest()


def read(prompt, default=None):
    """One line, stripped; `default` at end of input, which is how a script goes back.

    `terminal.readline` is where the line actually comes off stdin -- for every screen here
    and for the questions `orch` asks under them -- so the main screen's bounded wait and the
    sub-screens read the same stdin one after another with nothing stranded between them.
    """
    answer = terminal.readline(prompt)
    if not sys.stdout.isatty():
        print()    # the prompt was answered from a pipe: keep the transcript on separate lines
    return default if answer is None else answer.strip()


def rows(cfg, kept=None):
    """The seats, their runs and their groups, as the main screen reads them (`Live.read`), its
    rows `kept` between its reads (`v5o_groups`)."""
    with look.one_look():              # one look a read: filing, looking, drawing
        # stat'ed before the pass reads what they hold: a write after is news to the next read
        files = None if kept is None else seat_file_stats()
        found = orch.listing()
        records = run_records(rest_may_lag=True)
        orch.file_projectless(found, [state for _, state in records])
        return found, records, v5o_groups(cfg, found, records, look=False, kept=kept,
                                          files=files)


def config_mark():
    """config.toml's inode and mtime, None while there is none: a save replaces the file, a hand
    edit rewrites it."""
    try:
        stat = (config.HOME / config.CONFIG_NAME).stat()
    except OSError:
        return None
    return stat.st_ino, stat.st_mtime_ns


def configured(cfg, mark):
    """(`cfg`, config.toml's mark now), the config read again where the file changed since it
    was read at `mark` (config_mark), whoever wrote it, as the main screen (`Live.configure`)
    and `c` (config_matrix) both follow it.  One that does not load, a hand edit with an error,
    leaves `cfg` until the file's next change."""
    now = config_mark()
    if now != mark:
        try:
            cfg = config.load()
        except (config.Error, OSError, ValueError, TypeError, KeyError):
            pass
    return cfg, now


# The config `c` or Subscriptions holds and config.toml's mark as it last read or saved it
# (holding): that config is written only over that file (_saved)
_held = None, None
# The mark of a config whose read is the caller's, maybe long gone: unlike any file's, a missing
# one's None too, so the first pass reads config.toml again (configured)
NOT_READ = object()
# What a screen says of a key whose save it refused, config.toml changed since it read it
CHANGED = "config.toml changed since this screen read it: that key was not taken"


class Changed(Exception):
    """A save refused over a config.toml changed since it was read (_saved).  It closes the page
    it was made on, whose state was made of the config held, and the screen back says
    CHANGED."""


def holding(cfg):
    """`cfg`, or config.toml read again where it changed since the read `_held` keeps
    (configured), a read that loaded held in its place; one that did not leaves every save
    refused (_saved) until the file loads."""
    global _held
    now, mark = configured(cfg, _held[1])
    if now is not cfg:
        _held = now, mark
    return now


class Live:
    """The main screen's usage probe and its reads, off the thread that draws, and their way of
    asking for a draw.

    The menu never waits for an adapter: it draws from state/usage.json, and this starts
    `usage.collect(refresh=True)` in a thread that writes that same file, so the *next* draw
    is the one that shows fresh meters.  A finished probe writes a byte to a pipe the read is
    already selecting on, so that next draw happens the moment the answer lands rather than at
    the following tick.  Every open menu on the box shares one cadence with the tick and with
    `ak usage` -- `usage.PROBE_EVERY` -- so a second seat's screen costs no adapter request at
    all; Muse's adapter keeps its own ten-minute cache besides.  The same pipe is how a seat's
    word moving anywhere asks for a draw, and how a read landing does: see `watch`; and how
    a warning maintenance gives does (`tidy`).  `cfg` is config.toml as it last loaded, read again
    whenever the file changes, whoever wrote it (`configure`).
    """

    def __init__(self, cfg, every=None):
        self.cfg, self.configured = cfg, config_mark()
        self.configuring = threading.Lock()   # one reload at a time (`configure`)
        self.every = usage.PROBE_EVERY if every is None else every
        self.started = None          # when the probe now running was started, or None
        self.thread = None
        self.lock = threading.Lock()   # so the pipe is never given back under a probe's write
        self.reader, self.writer = os.pipe()
        os.set_blocking(self.reader, False)
        os.set_blocking(self.writer, False)
        self.watcher, self.done = None, threading.Event()
        self.watching = threading.Event()  # clear while the owner is away
        self.watching.set()
        self.leaves = 0                  # how often the owner has gone away (`away`)
        self.reading = threading.Lock()  # held while a read lands and its pass is decided (`away`)
        self.seen = None                 # the records the last read was read from, as they stood
        self.looker = None               # the thread of the last pass looking at every seat
        self.passing = threading.Lock()  # held while a pass is going
        self.met = set()                 # the listed seats a pass of this menu's has looked at
        self.asked, self.looking = threading.Event(), False   # a read asked for, and a look
        self.last = None                 # where each read leaves the seats and their groups
        self.read_from = None            # the seats and runs it read them from, a pass's too
        self.kept = {}                   # each seat's row as its reads last decided it
        self.said = []                   # warnings no notice has shown yet (`loop`, `tidy`)
        self.tidied = threading.Event()  # a notice can land before maintenance's effects do
        try:                             # its reads' slowest lately, the last menu's (`hand_on`)
            self.slowest = float(os.environ.pop(SLOWEST, 0))
        except ValueError:
            self.slowest = 0.0
        self.landed, self.owed = CLOCK(), None   # when a read landed, since when one is owed

    def close(self):
        """Give the pipe back, and wait on no thread: Esc leaves at once.

        Whatever a thread is in the middle of -- a read, a look, maintenance -- is safe to leave
        there: every state file is written whole, the `ak watch` tick runs the same reconcile and
        sweep, and the thread is a daemon.  The lock is the whole point: a descriptor closed
        while a thread is writing could already be somebody else's file, and a byte in the wrong
        file is worse than a draw nobody asked for.
        """
        self.done.set()
        self.asked.set()                 # the watcher out of its waits, to see it is done
        self.watching.set()
        with self.lock:
            for fd in (self.reader, self.writer):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            self.reader = self.writer = None

    def probe(self, now=None):
        """Start a probe when one is due and none is running; say whether one started.

        A menu nobody is sitting at is never probed.  The read still comes round on its own
        clock there -- the ten seconds are the read's promise, not the keyboard's -- but a
        script, a pipe or the smoke suite is nobody to spend a billed adapter call on, and
        the cache it draws from is answer enough for output nobody is watching fill.
        """
        now = time.time() if now is None else now
        if not sys.stdin.isatty():
            return False
        if (self.thread is not None and self.thread.is_alive()) or (
                self.started is not None and now - self.started < self.every):
            return False
        self.started = now
        self.thread = threading.Thread(target=self._work, daemon=True)
        self.thread.start()
        return True

    def _work(self):
        try:
            usage.collect(self.cfg, refresh=True)
        except (config.Error, OSError, ValueError, TypeError, KeyError):
            pass    # an adapter that cannot answer leaves the cache as it was; the row says why
        self._wake()

    def look(self, found, records):
        """Look at every seat again, off the read, and wait for none of it.

        The looks are `v5o_groups`' own -- each seat captured, decided, and written to its record
        and its bar -- in a thread of their own, so a seat whose capture hangs holds up no read
        and no draw: the read is the records as they stand, and a look landing has them read
        again (`ask`) for its words to be drawn.  They decide on `records`, the runs the read
        that started them read, so a pass reads nothing of its own.  One pass at a time; one
        still going is not doubled, and a menu that has left starts none: whether this one
        started is the answer.
        """
        if not self.done.is_set() and self.passing.acquire(blocking=False):
            self.looker = threading.Thread(target=self._look, args=(found, records), daemon=True)
            self.looker.start()
            return True
        return False

    def _look(self, found, records):
        try:
            with look.one_look():      # a pass of its own, off the read's thread (`rows`)
                held = _RUN_RECORDS    # the read's, as `records` are: a look reads no runs itself
                if held is not None and held.root[:3] == (config.RUNS, config.STATE, os.getpid()):
                    held.reader.lend()
                v5o_groups(self.cfg, found, records)
        except (config.Error, OSError, ValueError, TypeError, KeyError):
            pass    # a seat that cannot be looked at keeps what its record says
        finally:
            # Over before the next is decided, not when its thread ends: a seat listed while this
            # one was going gets its own pass here, on what the read listing it read (`away`).
            self.passing.release()
        with self.reading:
            self.meet()
        self.ask()

    def tidy(self, work):
        """`work(log)` -- `main`'s maintenance -- in a thread of its own, begun behind the first
        frame: each line it says goes to the tick's log, and a warning is kept for the loop's next
        notice too and asks for a draw (`tidy_log`); once it is done everything is read again,
        for what it reaped and retired to leave the rows."""
        def run():
            work(tidy_log(self.say))
            self.ask()
            self.tidied.set()
        threading.Thread(target=run, daemon=True).start()

    def say(self, message):
        self.said.append(message)
        self._wake()

    def heard(self):
        """The warnings no notice has shown yet, once."""
        return [self.said.pop(0) for _ in range(len(self.said))]

    def read(self, look=False, began=None):
        """The seats, their runs and their rows, read now into `last`, the words as recorded, in
        a round that `began` then, its records' stats before it (`watch`).

        The one place the main screen reads them, and never between a key and its frame: a draw
        is whatever the last read left, so a key that moves the highlight costs a draw and
        nothing more, and one back from another screen, a seat among them, shows the list at
        once, read again behind it (`back`).  None begins while the owner is away, and one the
        owner leaves during is let go, back by its end or not: nobody draws it, and it starts no
        look (`away`).  With `look`
        every seat is looked at as well, behind it (`look`); and without, when one is listed
        that no pass of this menu's has looked at yet: a seat started elsewhere while the menu
        is open is drawn on what there is (`seat_row_state`), a word its bar has never been
        told, and opening it keeps every later look away for as long as its owner stays in it.
        The pass is always over every seat, each under the number it is listed by (`meet`).
        """
        with self.reading:
            if not self.watching.is_set():
                return
            leaves = self.leaves
        # timed as the wait is (`stuck`), from the ask it answers or its round's start if that
        # came first: its records' stats and all
        began = min(stamp for stamp in (self.owed, began, CLOCK()) if stamp is not None)
        found, records, groups = rows(self.cfg, self.kept)
        with self.reading:
            if self.leaves != leaves:
                return
            self.read_from = found, records
            self.meet(look)
            self.last[:] = found, groups
            now = CLOCK()
            self.slowest = max(now - began, self.slowest * 0.5 ** ((now - self.landed) / SLOW_HALF))
            self.landed, self.owed = now, None

    def meet(self, look=False):
        """Start a pass over what the last read read with `look`, or for a seat it listed that no
        pass has looked at."""
        found, records = self.read_from
        listed = {seat["name"] for seat in found}
        self.met &= listed            # one that went and came back is new
        if (look or listed - self.met) and self.look(found, records):
            self.met = listed

    def ask(self, look=False):
        """Have everything read again, and with `look` every seat looked at, off the draw."""
        self.looking = self.looking or look
        if self.owed is None:
            self.owed = CLOCK()
        self.asked.set()

    def stuck(self):
        """The tick's log line saying why this menu starts over, once a read it asked for is owed
        far longer than its reads take (STUCK); else "".  It says how long none has landed,
        whether the watcher is alive, and each thread's innermost line of agentkit's own, so
        what held the read is on record."""
        now = CLOCK()
        if self.owed is None or now - self.owed < max(OWED, STUCK * self.slowest):
            return ""
        names = {thread.ident: thread.name for thread in threading.enumerate()}
        package, places = os.path.dirname(__file__) + os.sep, []
        for ident, frame in sys._current_frames().items():
            while frame and not frame.f_code.co_filename.startswith(package):
                frame = frame.f_back
            places.append(f"{names.get(ident, ident)} at " + (
                f"{os.path.relpath(frame.f_code.co_filename, config.REPO)}:{frame.f_lineno}"
                if frame else "no line of agentkit's"))
        alive = self.watcher is not None and self.watcher.is_alive()
        return (f"menu started over: no read landed for {now - self.landed:.0f} s, its watcher "
                f"{'alive' if alive else 'gone'}; " + "; ".join(places))

    def hand_on(self):
        """What the menu this one starts again as takes of it: how slow its reads were."""
        return {SLOWEST: repr(self.slowest)}

    def watch(self, last):
        """Read into `last` once, now, for the first draw -- in a menu the warm server forked, its
        last read is the first draw's (`warm`), and in one new code started again on the same code
        the old one's (`warm.handed`), read again within STIR -- then again in a thread
        within STIR of any record changing, or when asked (`ask`): the seats and their groups,
        for each draw to draw.

        Whatever decides a seat -- its own hook, the tick, `ak orch`, another menu -- writes the
        word to that seat's record and to its bar in one go, and a run's step, round and ending
        touch `config.runs_moved_path` before they move its bar (`handback.redress_seat`), so a screen
        that reads again when a record changes, as recorded, never shows a row its bar
        contradicts for longer than this.  A run at rest is the exception: a read finds one that
        moved only at its next full read, up to `open_runs.CEILING` later (the owner, 2 Nov 2026),
        and so is what git says of a checkout, held as long (`orch.git_dirs`).
        The records are noted before every read, so one written while it reads is still news.
        Looking is a `stat` per file -- its inode as well as its mtime, since every write
        replaces the file -- and nothing here captures a pane.  A read on news starts a look
        only when a seat is listed that it has not met (`read`), once, and writes nothing else,
        so no menu's read keeps waking another, or itself; each one landing asks for one draw.
        """
        self.last, primed = last, warm.primed() or warm.handed(CODE)
        if primed:
            # a read in hand, read again at the watcher's first look: a read beside the first
            # frame would hold it back, the two on one interpreter
            last[:], self.seen, self.looking = primed, None, True
        else:
            began, self.seen = CLOCK(), self.recorded()
            self.read(look=True, began=began)
        if self.watcher is None:
            self.watcher = threading.Thread(target=self._watch, daemon=True)
            self.watcher.start()

    def away(self):
        """The owner is going into a seat, or to the screen that opens one: nothing draws a read
        until the menu is back, so the watcher makes none, nor a `stat`, until `back`, and a
        read going as the owner leaves is let go when it ends (`read`); the seat opens at once,
        waiting at most on a read landing.  A seat listed while a pass was going still gets its
        own once that one ends, on what was read with it (`_look`): opened, it gets no other
        look while its owner is in it."""
        with self.reading:
            self.leaves += 1
            self.watching.clear()

    def back(self):
        """The owner is back: the menu draws what the last read left at once, and the watcher
        reads again behind it, every seat looked at, each read landing drawn as it lands."""
        self.watching.set()
        self.owed = None                 # none was owed while away: its wait starts here
        self.ask(look=True)

    def recorded(self):
        """usage.json, the runs' moved mark, the background a menu kept (terminal.kept) and every
        seat record: each one's name, inode and mtime; and each project's feature switches as its
        `list` last answered, so their landing is news too."""
        found = []
        for path in [config.STATE / "usage.json", config.runs_moved_path(), config.STATE /
                     terminal.KEPT, *(path for _, path in config.seat_files("seat"))]:
            try:
                stat = path.stat()
            except OSError:
                continue
            found.append((path.name, stat.st_ino, stat.st_mtime_ns))
        with _SWITCHES_LOCK:
            found += [(key, entry["rows"], entry["error"]) for key, entry in _SWITCHES.items()]
        return found

    def configure(self):
        """config.toml read again if it changed (configured) -- `c` in this window or another
        saved it -- and everything read again on it (`ask`), so every read, probe, draw and
        key after it acts on the config as saved.  The watcher and the draw both call it, one
        at a time, so a slow load never lands over a newer one."""
        with self.configuring:
            cfg, self.configured = configured(self.cfg, self.configured)
            news, self.cfg = cfg is not self.cfg, cfg
        if news:
            self.ask()

    def _watch(self):
        wait = STIR                  # the first look leaves the first frame the interpreter
        while True:
            self.asked.wait(wait)
            wait = LOOK_EVERY
            self.watching.wait()
            if self.done.is_set():
                return
            if not self.watching.is_set():
                continue                 # away since the wait: what it would read, nobody draws
            try:
                self.poll()
            except Exception:
                # This thread is the only one reading the menu's rows, so a round that raises is
                # dropped, not let end it, and what it could not read stays drawn as last read; a
                # full STIR, asked or not, so one that always raises never spins.
                self.done.wait(STIR)

    def poll(self):
        """One round of the watcher: the records noted, and config.toml read again if it changed,
        which asks for a read (`configure`); then, if the records moved or a read is asked for,
        everything read again and one draw asked for.  Whether it asked."""
        began, now = CLOCK(), self.recorded()
        self.configure()
        if now == self.seen and not self.asked.is_set():
            return False
        self.asked.clear()
        look = self.looking
        if look:
            self.looking = False     # a look asked for since is this one: it starts after
        self.seen = now
        self.read(look, began=began)
        self._wake()
        return True

    def _wake(self):
        """Ask for one draw: a byte on the pipe the read is selecting on."""
        with self.lock:
            try:
                if self.writer is not None:
                    os.write(self.writer, b".")
            except OSError:
                pass   # nobody is waiting any more: the menu has moved on or come down

    def drain(self):
        """Take back whatever a finished probe wrote, so one answer asks for one draw.

        True where something had: the wait ended on news, and not on the clock.
        """
        try:
            return bool(os.read(self.reader, 4096))
        except (BlockingIOError, InterruptedError, OSError, TypeError):
            return False


def wait_key(prompt, timeout=None, wake=None):
    """One line, or None when `timeout` seconds pass with nothing typed and nothing to redraw for.

    `select` on stdin -- what macOS and Linux both have -- is the wait, and `wake` is the read
    end of the pipe a finished probe writes to, so the screen comes round on its own clock and
    again the moment there are fresh meters.  A key pressed while the screen is being drawn
    stays in the terminal's own line buffer, or in `terminal`'s, and is read by the next call:
    nothing typed is ever lost.  The wait is bounded whatever stdin is -- a keyboard, a pipe a
    script is dribbling into, a file -- because a half-written line must not be able to stop
    the clock.  A terminal's line discipline already grants that, so waiting on one is a
    single `select`; anything else is waited on by `terminal.wait_line`, which can be
    interrupted mid-line.  Either way `read` takes the line, and it is the only thing that
    does.  Only a stdin with no descriptor to wait on at all (a StringIO, a closed one) falls
    back to the plain blocking read, and so does a caller asking for no timeout.

    While the menu has the keyboard (`terminal.Keyboard`) there are no lines: the wait is
    `terminal.read_key`'s, the answer one `terminal.Key`, and no prompt is drawn.
    """
    if terminal.taken():
        return terminal.read_key(timeout, wake)
    if timeout is None:
        return read(prompt, "")
    try:
        keyboard = sys.stdin.fileno()
        terminal_input = sys.stdin.isatty()
    except (OSError, ValueError):
        return read(prompt, "")    # nothing to select on; the prompt has not been printed yet
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        if terminal_input:
            ready, _, _ = select.select([keyboard] + ([wake] if wake is not None else []),
                                        [], [], timeout)
            waiting = keyboard in ready
        else:
            waiting = terminal.wait_line(timeout, wake)
    except (OSError, ValueError, InterruptedError):
        return read("", "")        # the prompt is already on screen
    if not waiting:
        print()                    # the prompt this leaves behind belongs to the draw, not him
        return None
    return read("", "")


def moving(clock, wake=None, timeout=TICK, going=None, rest=True):
    """`wait_key` on the main screen, its digit wait and a card asked, and on a screen whose
    content is fetched: `timeout` seconds at most -- None, no end but `going()`'s, which it is
    then given -- and each of `clock`'s frames drawn while something moves and no key is
    waiting.  A key but the pointer's writes the last frame of the highlight's motion before it
    at once (`motion.Clock.rest`), whatever reads next, but to what draws itself again or goes
    on reading it (`rest` False: a card, `asking`).

    Only a wait that ran to its frame draws one.  One that ended before it, on news, returns
    None, its cells forgotten, for the caller to draw the screen again; so does one a resize
    ended, at any time, and the clock forgets what it had seen as well: a resize moves every
    cell, and the draw after it shows the values as they are (`motion.Clock.forget`).  So does
    one on content being fetched once `going()` says it has landed, looked at every frame
    whether or not anything moves, for the screen to draw what came.
    """
    until = time.monotonic() + (left := math.inf if timeout is None
                                else max(0, min(timeout, terminal.whole_in())))
    terminal.asked_again()          # a draw asked for before the one just made is answered
    while True:
        due = clock.wait()
        if due is None and going is not None:
            due = motion.FRAME      # nothing moves, and what is waited on is looked at as often
        key = wait_key("> ", left if due is None else max(0, min(due, left)), wake)
        if key is None and terminal.asked_again():
            clock.clear()
            (clock.settle if terminal.unseen() else clock.forget)()
            return None
        if rest and isinstance(key, terminal.Key) and key.name != "point":
            terminal.over(clock.rest())
        if key is not None or due is None or time.monotonic() >= until:
            return key
        if going is not None and not going():
            return None
        if (clock.wait() or 0) > 0:
            clock.clear()
            return None
        terminal.over(clock.frame())
        left = until - time.monotonic()


def asking(clock, around, going=lambda: None, title=""):
    """How a screen drawn on `clock` asks yes or no: `ask(question, meaning, answer, doing="")`,
    the answer on the card terminal.confirm draws by `around(card, keys)`, which comes up on that
    clock as a page's rows do, as touched news, `asked`, from the first frame that shows it
    (`framed`, and `draw` on the ak screen).  Its frames are drawn while the answer is waited for
    (`moving`), `going()`'s fetch looked at, and a key, not the pointer, ends them, answered as
    it is read on the card as it was drawn: one that keeps it draws it at rest, as a resize
    does, and no more of it is drawn after one that answers.  With nothing to draw, a key, a
    resize or the fetch landing alone is waited for, as on a page that draws nothing more.  Its
    highlight comes up with it, and news that moves the card, a count landing, moves the
    highlight with it (`motion.Clock.hold`): only a key or the pointer moves it on the card.
    When `doing` is given and `answer` is picked on a taken terminal, `terminal.doing` puts the
    screen up again with `title` then `doing` in the header before the caller's work runs."""
    def wait():
        fetching, moves = going(), clock.wait() is not None
        if fetching or moves:     # no TICK's redraw where nothing moves: it scrolls eight rows
            key = moving(clock, timeout=TICK if moves else None, going=fetching, rest=False)
        elif (key := wait_key("> ")) is None:
            clock.forget()            # a resize: drawn as it is (moving)
        if key is None:
            clock.hold()
        elif key.name != "point":
            clock.settle()
        return key

    def ask(question, meaning, answer, doing=""):
        clock.swept = None
        clock.touch(("asked",))
        clock.hold()
        if not terminal.confirm(question, meaning, answer, around, wait):
            return False
        if doing and terminal.taken():
            terminal.doing(" · ".join(filter(None, (title, doing))))
        return True
    return ask


def framed(clock, title, lines, at, card, keys, places=None):
    """`title`'s screen of `lines` (terminal.frame) drawn on `clock`, the card terminal.confirm
    asks on among them from line `at`, before the first where its top gives way, its lines
    there coming up on the clock (`asking`): the screen row of the card's first line.
    `places` are the screen's own on the lines over the card (page_places), nothing the pointer
    lands on while it asks (terminal.choose): by them the clock knows what the highlight left
    where it was, and fades it there (`motion.Clock.light`)."""
    terminal.frame(title, lines, keys, places=places, drawn=lambda: clock.drawn(
        [(line, ("asked",), True, motion.fading(lines[line]))
         for line in range(max(0, at), min(len(lines), at + len(card)))], lambda line: 3 + line))
    return 3 + at


def fade_out(clock, rows):
    """Fade screen `rows` (from 1), as they stand, into the background in `motion.LEAVES`, and
    return once they are: a page calls it between the answer and the act, so its list never
    holds a row that has gone.  It hides reading them as they stand (terminal.standing), what
    moves on them too, settling the clock, mixing text and highlight backgrounds into the
    screen's, the frame loop, ending at once on a resize meanwhile without reading a key, and
    doing nothing where nothing can move (`motion.movable`)."""
    if not motion.movable():
        return
    terminal.asked_again()          # a resize the last draw answered is none meanwhile
    leaving = terminal.standing(rows)
    if not leaving:
        return
    clock.settle()
    clock.clear()
    began, size, shown, due = motion.moment(), (terminal.width(), terminal.height()), {}, 0
    while not terminal.resized(due):
        now, step = motion.moment(), time.monotonic()
        done, amount = now >= began + motion.LEAVES, motion.eased((now - began) / motion.LEAVES)
        out = ""
        for row, parts in leaving:
            text = "".join(f"\033[{row};{column}H{terminal.fade(part, amount, backs=True)}"
                           for column, part in ([] if done else parts)) or f"\033[{row};1H\033[K"
            if shown.get(row) != text:
                shown[row] = text
                out += text
        if terminal.resized(0) or (terminal.width(), terminal.height()) != size:
            return                  # resized, by a signal or not: no frame at the old layout
        terminal.over(out)
        if done:
            clock.last = time.monotonic()
            return
        due = max(0, step + motion.FRAME - time.monotonic())


class Back(Exception):
    """Esc, the end of input or a click on `esc back`, read while a screen waited on what it
    fetches (`waited`); or Esc out of a list another list opened (`config_add`)."""


class Fetch(threading.Thread):
    """`work()`, asked off the drawing thread from `began`; `answer` once it has landed."""

    def __init__(self, work):
        super().__init__(daemon=True)
        self.work, self.began, self.got = work, motion.moment(), {}
        self.start()

    def run(self):
        try:
            self.got["answer"] = self.work()
        except Exception as exc:        # raised again on the drawing thread, as if asked there
            self.got["error"] = exc

    def answer(self):
        """What `work` answered, waiting for it; what it raised is raised here."""
        self.join()
        if "error" in self.got:
            raise self.got["error"]
        return self.got["answer"]


LEFT = "reading what each subscription has left"     # what `usage.collect` is waited on for


def waited(work, title, body=list, keys="esc back", keyboard=None, doing=""):
    """What `work()` answers, asked off the drawing thread while the screen it is asked on waits
    on it: `title` over the lines `body()` lays out at the terminal's width and `keys`, as
    terminal.frame draws it, then, where the screen has room, what it waits on in words,
    `doing`, a spinner turning beside it (motion.spinning).

    A fetch that lands within a frame is simply had, and so is one with no keyboard to read, as
    it always was.  Over one that takes longer, on the keyboard a screen has -- or `keyboard`,
    taken for the wait -- the screen is drawn, and again after a resize, and its rule glides
    once the fetch is past motion.WAIT (motion.fetching), on the clock's own frames.  Esc, the
    end of input or a click on `esc back` raises Back, `work` left to finish on its own
    and its answer unused; any other key is let go, and the pointer draws it again.
    """
    fetch = Fetch(work)
    fetch.join(motion.FRAME)
    given = (fetch.is_alive() and not terminal.taken() and keyboard is not None
             and keyboard.take())
    try:
        while fetch.is_alive() and terminal.taken():
            lines = body()            # laid out again after a resize: no line wider than it
            said = [*([""] if lines else []), "  " + motion.spinning(fetch.began)(
                motion.moment()) + " " + terminal.styled(terminal.cut(
                    doing, terminal.layout_width() - 4), "dim")] if doing else []
            # only on a screen it fits: one that scrolls leaves the clock writing on rows moved
            if 3 + len(lines) + len(said) + len(terminal.key_line(keys)) >= terminal.height():
                said = []
            lines = [*lines, *said]
            spots = terminal.frame(title, lines, keys)
            clock = motion.fetching(motion.Clock(), fetch.began)
            if said:                  # under the header and its rule
                clock.start([(2 + len(lines), 3)], motion.spinning(fetch.began))
            key = moving(clock, timeout=TICK, going=fetch.is_alive)
            while key is not None and key.name != "point":    # the rule glides on as it was
                if (key.name in ("esc", "eof")
                        or key.name == "click" and terminal.under(key, spots).cell == "esc"):
                    raise Back
                key = moving(clock, timeout=TICK, going=fetch.is_alive)
    finally:
        if given:
            keyboard.give()
    return fetch.answer()


@terminal.clicks_its_own
def pause(*lines):
    """Say something and, when someone is there to read it, wait until they have: Esc or Enter,
    in a frame while the menu holds the screen, whose pages ↑/↓ turn, so none of a note taller
    than the screen is lost; else printed where the terminal was given back, with only the keys
    taken so Esc goes back at once here too.  Its lines are no row: no pointer takes a highlight
    off them, which Enter would then only bring back (`terminal.unseen`)."""
    if terminal.taken():
        top = 0
        while True:
            body = ["  " + part for line in lines for part in
                    (terminal.wrap(line, terminal.layout_width() - 2) or [""])]
            room = max(1, page_room([], "esc back"))
            top = max(0, min(top, len(body) - room))
            spots = terminal.frame("note", body[top:top + room])
            key = terminal.read_key()
            if key is None:
                continue
            if (key.name in ("esc", "enter", "eof")
                    or key.name == "click" and terminal.under(key, spots).cell == "esc"):
                return
            top += room * terminal.step(key)
    for line in lines:
        print(line)
    if sys.stdin.isatty() and sys.stdout.isatty():
        with closing(terminal.Keyboard(screen=False)) as keys:
            if not terminal.taken():
                keys.take()
            read("esc back ", "")


def seat_state(cfg, session, **facts):
    """What this seat is, in the one vocabulary: `watch.session_state` and nothing else.

    Every reading of a seat on every screen comes through here, so no listing can invent a
    word or a reason of its own.  `facts` are one draw's shared records, numbers and index.
    """
    from . import watch
    return watch.session_state(session["name"], session=session, cfg=cfg, **facts)


def seat_row_state(cfg, session, look=True, **facts):
    """The same answer, off a fresh look at the seat, with its bar brought up to it.

    A drawn row is what a seat's screen has always been read from and what its bar has
    always been refreshed from, beside the watch tick: the two agree because they read the
    one function. Drawing writes no word of its own; the tick is what writes that down.
    Without `look` the row is the word as recorded -- what whoever looked last wrote to the
    record and the bar together -- and nothing is captured or written; a seat nobody has
    recorded yet is decided on what there is, until a look records it, and so is a gone one,
    which has no screen to look at and whose reason names the number it is listed by now.
    """
    from . import watch
    if look:
        return watch.announce_state(session, cfg=cfg, look=True, **facts)
    recorded = watch.seat_read(session["name"])
    if recorded.get("word") and not any(session.get(key) for key in orch.CLOSED):
        return {"word": recorded["word"], "reason": recorded.get("reason"),
                "unsent": recorded.get("unsent"), "since": recorded.get("word_since"),
                "resumes_at": (recorded.get("usage_wait") or {}).get("until")}
    return seat_state(cfg, session, **facts)


def status(session, cfg=None):
    """(what the row says about the seat, the time that became true or None)."""
    found = seat_row_state(cfg, session)
    return found["word"], found["since"]


def state(session):
    """The one word the row says about that seat."""
    return status(session)[0]


def selection_of(cfg, name):
    """The seat's saved selection -- its orchestrator, executors and reviewers -- or None
    where it has none, or one that no longer reads."""
    try:
        return config.load_session(cfg, name, required=False)
    except config.Error:
        return None


def row(cfg, number, session):
    """One seat's cells: number, name, worker, word, reason, age."""
    selection = selection_of(cfg, session["name"])
    found = seat_row_state(cfg, session)
    text = found["reason"]
    # the word is aged from when it began, and from the seat's own start where
    # nothing knows when that was, which is what the row has always shown
    since = found["since"]
    return [str(number), session["name"], selection["orchestrator"] if selection else "-",
            found["word"], text, orch.age(since if since is not None else session["created"])]


def tally(counts):
    """What a seat's runs add up to, for `ak orch list`: `1 running · 1 merged`,
    `0 running · 1 needs you`, or `no runs yet` for a seat that has launched nothing.

    `counts` is the seat's entry from handback.seat_tallies -- (running, needing him, merged) -- or
    None.  Endings that need him come before the merges, because they are what the number
    is for; the merges are the last seven days' only.
    """
    if counts is None:
        return "no runs yet"
    running, look, merged = counts
    return f"{running} running · " + (f"{look} needs you" if look else f"{merged} merged")


def rollup(words):
    """The one word a group of seats and runs reads: the one that wants him first."""
    return min(words, key=STATE_ORDER.index) if words else "done"


def projects(cfg, found):
    """Group rows without changing the global seat numbers used by Discord and selection.

    Kept for older tests; the menu itself draws `v5o_groups`, which is seats only.
    (`ak orch list` reads its tallies straight from `menu.run_records()`.)
    No run ever makes a project or a row here either: `runs` stays
    empty and every group comes from a seat.
    """
    from . import handback
    groups = {}

    def group(repo, fallback="no project"):
        name = orch.project_name(repo, fallback)
        return groups.setdefault(name, {"name": name, "rows": [], "runs": [], "words": []})

    # one pass over run.json for the rows' tallies
    records = run_records()
    tallies = handback.seat_tallies(state for _, state in records)
    for number, session in enumerate(found, 1):
        item = row(cfg, number, session)
        counts = tallies.get(session["name"])
        item.append(tally(counts))
        project = group(session.get("repo"))
        project["rows"].append(item)
        project["words"].append(item[3])
    for project in groups.values():
        project["rows"].sort(key=lambda item: item[1])
        project["word"] = rollup(project["words"])
    return [groups[name] for name in sorted(groups)]


# --- v5o: the menu at rest answers one question ---------------------------------
#
# The menu at rest is the header, the usage block and the keys line exactly as
# they are today, and between them one line that answers the question
# (`nothing needs you` / `N need you`), then the projects. A seat row is who,
# how many, worker, sentence, progress. Run rows only when they are somebody's
# problem. See docs/cli-design.md for the visual system; every helper it names
# lives in agentkit/terminal.py and is used here, never re-implemented.


def job_for_seat(seat_name):
    """(done, total, waiting_on) over the seat's unfinished jobs, or None without one. No fake bar.

    Reads each job's receipt through `job.read_jobs`, nothing without one. A job is the seat's
    until it records `finished_at`, when its `seat` -- that field alone, never the job's
    directory name -- leads here through rename pointers: an orchestrator renamed since
    launched it under its old name. `done` is
    tasks merged, passed or skipped of all those jobs' tasks; `waiting_on` is the first
    job's `waiting on <dep>` sentence. Unreadable or task-less jobs are no job at all.
    """
    from . import job as jobs   # here, not at the top: a job runs through run.py, the whole loop
    try:
        receipts = jobs.read_jobs()
    except OSError:
        return None
    done = total = 0
    waiting = ""
    for job in receipts:
        if not isinstance(job, dict) or job.get("finished_at"):
            continue
        try:
            owner = config.resolve_session(job["seat"]) if isinstance(job.get("seat"), str) else None
        except config.Error:
            owner = None
        if owner != seat_name:
            continue
        said = (job.get("waiting_on") or job.get("waiting") or
                job.get("waiting_for") or job.get("blocked_on"))
        if isinstance(said, dict):
            said = said.get("dep") or said.get("name")
        waiting = waiting or (str(said).strip() if said else "")
        tasks = job.get("tasks")
        if isinstance(tasks, dict):
            tasks = tasks.get("items", [])
        if not isinstance(tasks, list):
            try:
                counted = (int(job.get("done", job.get("merged"))),
                           int(job.get("total", job.get("tasks_total"))))
            except (TypeError, ValueError):
                continue
            done, total = done + counted[0], total + counted[1]
            continue
        total += len(tasks)
        for task in tasks:
            if not isinstance(task, dict):
                continue
            status = str(task.get("status") or task.get("state") or
                         task.get("result") or "").strip().lower()
            if status in ("merged", "pass", "passed", "skipped", "done",
                          "ok", "complete", "completed"):
                done += 1
    return (done, total, waiting) if total > 0 or waiting else None


def seat_progress(name):
    """(done, total) behind a working seat's bar: its plan, else its unfinished jobs.

    (0, 0) with neither. The menu row and the seat's own status bar both read this one
    helper, so the two always draw the same bar.
    """
    from . import watch as _watch
    try:
        done, total = _watch.plan_progress(name)
    except (OSError, ValueError):
        done, total = 0, 0
    if total > 0:
        return done, total
    job = job_for_seat(name)
    return (job[0], job[1]) if job else (0, 0)


# The three squares of a task in flight: build (its executor, its checks, a fix after review),
# review, land (the line, the merge, the deploy until it proves itself live).
STAGES = {"executor": 0, "done-when": 0, "reviewer": 1, "merge": 2}


class Task(tuple):
    """A task in flight, (stage, state) as it unpacks, and `run`, the run it is: what tells one
    task's squares from another's from one draw to the next."""

    def __new__(cls, stage, state, run):
        task = super().__new__(cls, (stage, state))
        task.run = run
        return task

    def __getnewargs__(self):
        return (*self, self.run)      # pickled whole: the warm server's read (`warm`)


def seat_tasks(name, records=None, now=None):
    """`own_tasks` of the runs among `records` that seat launched."""
    records = run_records() if records is None else records
    return own_tasks(transitions.runs_by_seat(records).get(name, []), now)


def own_tasks(mine, now=None):
    """Each task in flight among a seat's own runs, as (stage, state), furthest behind first: its
    stage 0, 1 or 2 (`STAGES`), and `moving` while a model or ak works on it, `spent` while every
    model it may go on with is out of usage, `waiting` while it waits -- for a slot, behind an
    older change, for a login, for its turn in the line, for the live check.  A run that ended is no task in flight, whatever it delivered:
    the owner's word of 19 Oct 2026, as red squares of ended runs read as work still going."""
    from . import gate, watch   # here, not at the top: watch imports this module
    now = time.time() if now is None else now
    found = []
    for run_dir, state in mine:
        stage, run = STAGES.get(state.get("step"), 0), Path(run_dir).name
        if transitions.landing_line(state):
            found.append(Task(2, "waiting", run))
        elif state.get("state") == "running":
            paused = gate.gate_turn_note(state) or watch.loop_wait(state) > now
            found.append(Task(stage, "waiting" if paused else "moving", run))
        elif transitions.going(state, now=now):
            spent = transitions.exhausted_wait(state) == "window"     # every pick out of usage
            found.append(Task(stage, "spent" if spent else "waiting", run))
        elif watch.awaiting_live(state, now=now):
            found.append(Task(2, "waiting", run))
    return sorted(found, key=lambda task: (task[0], task[1] == "waiting"))


def _paint(text, kind, tmux=False):
    """`text` in `kind`'s colour, as `terminal.styled` draws it, or as tmux text."""
    if not tmux:
        return terminal.styled(text, kind)
    return f"#[fg=#{terminal.colour(kind, tmux)}]{orch.tmux_text(text)}#[default]" if text else ""


def grow_line(clock, row, line, span, moving, counted=None):
    """Move `span` of a seat's `line` on screen `row` by `moving` (its cells to their animations
    and when still), and its count with it, counting up from `counted` (motion.counting)."""
    written = terminal.cell_texts(line)
    animations, until = moving(written[span])
    clock.span(row, terminal.cells("".join(written[:span.start])) + 1, animations, until)
    after = terminal.ANSI.sub("", "".join(written[span.stop:]))
    if count := re.match(r" \d+ of \d+", after):
        cells = written[span.stop + 1:span.stop + count.end()]
        clock.span(row, terminal.cells("".join(written[:span.stop])) + 2, *(
            motion.counting(cells, *counted) if counted else
            ([lambda now, text=text: text for text in cells], until)))


def line_at(line):
    """Slice of `terminal.cell_texts` holding the rendered progress line, before highlighting.

    Its coloured spans distinguish it from completion prose holding the same glyphs.
    """
    count = rf"(?= (?:\033\[[\d;]+m)?(?:\d+ of \d+|{terminal.NO_PLAN}))"
    match = re.search(r"(?:\033\[[\d;]+m[━╸=─-]+\033\[0m)+" + count, line)
    if match:
        start = len(terminal.cell_texts(line[:match.start()]))
        return slice(start, start + len(terminal.cell_texts(match.group())))


def tips(line):
    """Plain-text offset of the rendered progress tip, if one breathes.

    Read its working-colour span before highlighting: draft glyphs are plain.  Every full cell
    shares the tip's colour, so only the last one breathes.
    """
    if terminal.colour_depth() <= 8:
        return []
    tip = max(line.rfind(terminal.styled(char, "working")) for char in ("━", "╸"))
    return [len(terminal.ANSI.sub("", line[:tip]))] if tip >= 0 else []


def squares(tasks, room=float("inf"), tmux=False, most=None):
    """`tasks` (`seat_tasks`) drawn in `room` cells, `most` of them at the most: three squares
    each, two cells apart, the stages it has reached filled -- in working's colour while it
    moves, out of usage's while it waits for usage, dim while it waits on anything else -- and
    the rest dim and empty; those not drawn
    counted, `+3`.  No colour: the shapes alone; no UTF-8: `#--`.  `tmux` draws it as tmux
    text."""
    full, empty = "■□" if terminal.utf8() else "#-"
    kinds = {"moving": "working", "spent": "out of usage", "waiting": "dim"}
    # a group takes five cells with its gutter, the count of the rest as many as its digits
    fit = len(tasks[:most])
    while fit and 5 * fit - 2 + (len(f"  +{len(tasks) - fit}") if fit < len(tasks) else 0) > room:
        fit -= 1
    drawn = [_paint(full * (stage + 1), kinds[state], tmux)
             + _paint(empty * (2 - stage), "dim", tmux) for stage, state in tasks[:fit]]
    rest = len(tasks) - fit
    return "  ".join(drawn + ([_paint(f"+{rest}", "dim", tmux)] if rest else []))


def seat_crew(cfg, selection):
    """(who builds, who reviews) a seat's work, from its saved selection: its workers; its
    reviewers, else its workers, each named at the effort it runs that role at
    (`config.model_at`).  A seat whose orchestrator builds alone names no builder, and nothing
    says so: no `build` is the seat itself building (the owner's word of 21 Oct 2026).  No
    selection: nobody.  The menu row and the seat's own bar both read this, as they read
    `seat_tasks`."""
    if not selection:
        return [], []
    workers = list(selection.get("workers") or [])
    return ([config.model_at(cfg, selection, model, "executor") for model in workers],
            [config.model_at(cfg, selection, model, "reviewer")
             for model in selection.get("reviewers", workers)])


def crew(info, tmux=False, room=None):
    """`build: Opus 5.5 xhigh, 4 Carbon high   review: 6.1 Sol max`: each role, then who is in it
    at the effort they run it at (`seat_crew`), all muted, as the row's orchestrator is; one
    `build and review:` where both hold the same, and a model in both of two lists that differ
    named in each (the owner, 20 Nov 2026, asked whether it should get a group of its own: "Keep
    as built").  Never the orchestrator: its row names it.  The
    owner, 17 Nov 2026: "we name the orch double, and name it explicitely which is not needed",
    "it should be the other way around, role and what models are in this role".  Nothing where
    nobody is beside the orchestrator.  Cut to `room` cells where given; `tmux` draws it as tmux
    text."""
    builds, reviews = info.get("crew") or ((), ())
    roles = ((("build and review", builds),) if set(builds) == set(reviews)
             else (("build", builds), ("review", reviews)))
    text = "   ".join(f"{role}: " + ", ".join(map(terminal.plain, models))
                       for role, models in roles if models)
    if not text:
        return ""
    return _paint(text if room is None else terminal.cut(text, room, spaced=True), "muted", tmux)


def silent_for_run(run_dir, state, now=None):
    """`2h` when a running run has had no write for more than an hour, else None.

    A run in `running` whose directory under ~/.agentkit/runs/<id> has had no write
    for more than an hour is stuck in one step. The age is the newest file under the
    run directory, whatever the step. Under an hour nothing changes.
    """
    if state.get("state") not in record.ACTIVE:
        return None
    at = time.time() if now is None else now
    # its record and its log are written as it goes: either within the hour is a newest file
    # within it, and the walk through every file it holds -- a twentieth of a second for a
    # busy run, on every read of the menu -- is left for one that went quiet
    for name in ("run.json", "log.txt"):
        try:
            if at - (Path(run_dir) / name).stat().st_mtime <= 3600:
                return None
        except OSError:
            continue
    try:
        from . import watch as _watch
        kept = _WALKED.get(os.fspath(run_dir))
        if kept is None or time.monotonic() - kept[0] >= WALK_EVERY:
            kept = _WALKED[os.fspath(run_dir)] = (time.monotonic(),
                                                  _watch.run_last_write(Path(run_dir)))
        newest = kept[1]
    except (OSError, ValueError, AttributeError):
        newest = 0.0
    if not newest:
        try:
            newest = record.read_state(Path(run_dir)).get("started_at") or 0
        except (OSError, ValueError, AttributeError):
            newest = 0
    try:
        newest = float(newest)
    except (TypeError, ValueError):
        return None
    if not newest or at - newest <= 3600:
        return None
    return terminal.format_age(at - newest)


def v5o_needs_look(state, all_states=None, index=None, now=None):
    """Whether an ending is still his: unreplaced, unacknowledged and this week's.

    Five endings are his -- a FAIL, an unscheduled error, a `blocked`, an interruption
    and a PASS nobody merged -- and so is an `exhausted` run the tick cannot resume
    (`transitions.exhausted_wait`), which is no ending: told or old, it stays unfinished
    -- and the seat's own word would call it recovering -- until `ak run resume` or
    `ak run stop`, unless a later merged run replaced it. Nothing else is, and only
    while nobody else has it. A run parked `exhausted` on a window or a dead reviewer,
    or `stalled`, is the
    tick's to take on when the window refills, the reviewer is back or the stall
    is recovered, an error with a scheduled retry is the tick's the same way, and
    a `queued` or `running` one is nobody's problem yet. An
    ending older than gc.GC_AGE has aged out and counts for nobody, acknowledged
    or not; `ak run status` still lists it.

    An ending handed back to the seat that launched it is that orchestrator's from then on,
    and one waiting for that seat's next quiet prompt is about to be: neither is his, so
    neither is in a tally.

    `index` is a `transitions.supersession_index` over the same states: pass it when testing
    many runs so one draw scans the records once instead of once per run per seat.
    """
    from . import gc
    if state.get("recovery_acknowledged_at"):
        return False
    if state.get("state") in ("error", "exhausted") and transitions.going(state, now=now):
        return False  # the tick owns its retry or its resume; nothing here needs him
    if state.get("state") == "exhausted":
        # no ending: a hand-back or its age settles nothing, but a later merged
        # run does -- the work is done, elsewhere. Without the records that
        # replacement cannot be read, and the run stays his.
        if index is not None:
            if transitions.is_superseded(state, None, index, merged_only=True):
                return False
        elif all_states is not None and transitions.is_superseded(state, all_states,
                                                           merged_only=True):
            return False
        return True
    if state.get("handed_back") or state.get("handback_pending"):
        return False
    if state.get("merged"):
        return False
    if state.get("state") not in (*record.FAILED, "interrupted", "pass"):
        return False
    at = time.time() if now is None else now
    ended = (state.get("finished_at") or state.get("interrupted_at")
             or state.get("started_at"))
    # Only a date we can read ages an ending out; an undated record stays his.
    if isinstance(ended, (int, float)) and not isinstance(ended, bool) and at - ended > gc.GC_AGE:
        return False
    if index is not None:
        if transitions.is_superseded(state, None, index):
            return False
    elif all_states is not None and transitions.is_superseded(state, all_states):
        return False
    if state.get("state") == "pass":
        return bool(state.get("repo")) and not (state.get("no_merge") or state.get("review_pr")
                                                or state.get("review_posted"))
    return True


def v5o_seat_info(cfg, number, session, records, silent_map, jobs_cache, now, index=None,
                  run_numbers=None, look=True, mine=None):
    """Number, name, orchestrator, state and one last column for one offered seat.

    The word is `watch.session_state`'s and no screen's own: `working`, `needs you` or
    `done`. The last column is its progress line from `seat_progress` -- its plan, else its
    unfinished jobs -- while it is not at rest, and for `working` its place in the landing line,
    else empty, then whatever its word how many `tasks` it has in flight (`_last_text`), then
    `¶ unsent` where the owner left text unsent -- never two state words on one row; who builds, who reviews and
    its tasks open under it (`detail`).
    Every seat `orch.listing` offers gets a row: the ones tmux holds, and the ones only their
    record does -- a seat whose tmux instance is gone keeps its row and its number opens the
    conversation where it stopped.
    Seats with nothing to resume into never reach `found`. `jobs_cache` and `run_numbers`
    are kept for callers that still hand them down; `seat_progress` reads the jobs itself and
    gone seats name their own number now.  `mine` is the runs each seat launched, by its name
    now, so a pass over every seat reads every run once (`transitions.runs_by_seat`).
    """
    name = session["name"]
    own = (transitions.runs_by_seat(records) if mine is None else mine).get(name, [])
    found = seat_row_state(cfg, session, look=look, records=records, mine=own, now=now,
                           number=number, run_numbers=run_numbers, index=index, silent=silent_map)
    selection = selection_of(cfg, name)
    orchestrator = selection["orchestrator"] if selection else "-"
    shown = config.model_at(cfg, selection, orchestrator, "orchestrator")
    done, total = seat_progress(name)
    bar = (done, total) if total > 0 else None
    word = found["word"]
    back = found.get("resumes_at") if word == "out of usage" else None
    return {"number": str(number), "name": name, "session": session, "back": back,
            "crew": seat_crew(cfg, selection),
            "tasks": own_tasks(own, now),
            "count": word, "orchestrator": shown, "worker": shown,
            "model": config.model_name(cfg, orchestrator),
            "unsent": found.get("unsent"), "bar": bar,
            "word": word, "since": found["since"], "repo": session.get("repo")}


class Folds:
    """What `v5o_groups` folds out of every run -- the replacements by title and branch
    (`transitions.supersession_index`), each seat's runs (`transitions.runs_by_seat`) and the
    silent ones (`silent_for_run`) -- worked out from the open runs alone, equal to folding them
    all.

    It hides that the runs at rest at the last full read (`open_runs.Reader`) are folded once and
    kept, their entries under each key they are listed under and their runs by the name each was
    launched from, so a read folds only its other runs, resolves every name again, a rename showing
    on that very read, and merges the two in the order a whole fold has, never adding to a kept
    list; and that a pass over the records of
    the read before it, with no read since, gets that read's answers.  Records no read of the
    screen's gave out are folded whole.  Nothing it keeps is changed after: two threads asking at
    once each get a whole answer.
    """

    def __init__(self):
        self.kept = None, {}, {}, {}   # the runs at rest, their index, it `_tagged`, runs by name
        self.last = None, None         # a read's `open_runs.Reader.split` and its answers

    def of(self, records, now):
        """(supersession_index, runs_by_seat, {run name: its silence}) of `records`."""
        split = _RUN_RECORDS.reader.split if _RUN_RECORDS is not None else (None,)
        if split[0] is not records:
            return (transitions.supersession_index(records), transitions.runs_by_seat(records),
                    _silent(records, now))
        last = self.last
        if last[0] is split:
            return last[1]
        _, rest, moving = split
        kept = self.kept
        if kept[0] is not rest:
            tagged = _tagged(rest)
            kept = self.kept = rest, {key: [entry for _, entry in entries]
                                      for key, entries in tagged.items()}, tagged, _named(rest)
        _, index, tagged, named = kept
        index = dict(index)
        for key, entries in _tagged(moving).items():
            index[key] = [entry for _, entry in heapq.merge(tagged.get(key, ()), entries,
                                                            key=_newest)]
        lists = {}
        for name, runs in named.items():
            try:
                lists.setdefault(config.resolve_session(name), []).append(runs)
            except config.Error:
                continue        # left out, as `runs_by_seat` leaves it
        for seat, runs in transitions.runs_by_seat(moving).items():
            lists.setdefault(seat, []).append(runs)
        # a run at rest is never active, so only the others can be silent (`silent_for_run`)
        answers = index, {seat: _in_order(*runs) for seat, runs in lists.items()}, _silent(moving, now)
        self.last = split, answers
        return answers


def _tagged(runs):
    """`transitions.supersession_index` of those runs, each entry with its run's name, in that
    index's order (`_newest`)."""
    tagged = {}
    for run in runs:
        for key, (entry,) in transitions.supersession_index((run,)).items():
            tagged.setdefault(key, []).append((run[0].name, entry))
    for entries in tagged.values():
        entries.sort(key=_newest)
    return tagged


def _newest(tagged):
    """The order of a `supersession_index` list: newest first, then as `records` has them, which is
    by name (`_in_order`)."""
    name, (when, *_) = tagged
    return -when, name


def _named(runs):
    """Those runs under the name each was launched from (`transitions.launched_name`), in order."""
    named = {}
    for run in runs:
        name = transitions.launched_name(run[1])
        if name is not None:
            named.setdefault(name, []).append(run)
    return named


def _in_order(*lists):
    """The runs of lists each in a read's order, in that order: by name, as `open_runs` lists the
    run directories under the one parent; one list alone is itself."""
    lists = [runs for runs in lists if runs]
    return lists[0] if len(lists) == 1 else list(heapq.merge(*lists, key=lambda run: run[0].name))


def _silent(runs, now):
    """{run name: its silence} of those runs silent for over an hour (`silent_for_run`)."""
    silent = {}
    for run_dir, state in runs:
        age = silent_for_run(run_dir, state, now=now)
        if age:
            silent[run_dir.name] = age
    return silent


FOLDS = Folds()


def v5o_groups(cfg, found, records=None, now=None, look=True, kept=None, files=None):
    """The projects and their seats, in the order their numbers go (`orch.numbered`).

    A project is a checkout under ~/code, or agentkit's own at ~/agentkit -- one of
    `orch.checkouts()` -- and a seat is filed under the one its repo *is* (`orch.checkout_of`):
    the one `ak orch project` filed it under, else the project most of its runs vote for, a
    queued run's included (`handback.join_session_project`), whether it works in one checkout or
    across them from ~/code. Only a seat nobody filed and none of whose runs votes files under
    the fallback heading.
    A run makes no project and no row: no worktree, no throwaway repo under
    ~/.agentkit/tmp and no run id is ever a heading. A project with no offered seat is not
    listed, whatever its AGENTS.md says; one whose AGENTS.md names its feature switches carries
    `switches`, the rows its `list` last answered ([] before any).

    `found` is what `orch.listing` offers -- live seats and gone ones with a
    conversation to resume into -- in its order, so every seat's number is its place on the
    screen; a seat the owner stopped (`closed`, `orch.ghost`) comes after them, numbered on
    the past screen (`show_past`), and has no row under its project.

    `kept`, a screen's own between its reads, holds each seat's row as a read decided it, with the
    stamp it was decided from (`stamps`, over `files`, `seat_file_stats` taken before anything
    the read decides from) and when, on time.monotonic: a read without `look` draws
    it again while the stamp is the same and it is younger than `open_runs.CEILING`, so the
    seats whose inputs did not change cost a read next to nothing (the owner, 2 Nov 2026), and
    what the stamp misses -- the clock, other seats' runs, the meters -- is a minute late at most.
    Ages are drawn from `since`, so a kept row still ages on screen; a row is never changed once
    made, so every read's list is its own.
    """
    at = time.time() if now is None else now
    records = run_records() if records is None else records
    if not isinstance(records, list):
        records = list(records)
    index, mine, silent_map = FOLDS.of(records, at)
    jobs_cache = {}
    infos = []
    keeping = kept is not None and not look
    if keeping and files is None:
        # stat'ed after `found` was listed: a write between shows a minute late at most, which
        # is why `rows` stats them first
        files = seat_file_stats()
    stamped = stamps(cfg, found, mine, files) if keeping else {}
    clock, held = time.monotonic(), {}
    for number, session in enumerate(found, 1):
        if session.get("closed"):
            continue          # stopped: numbered after every seat with a row, on the past screen
        stamp, row = stamped.get(session["name"]), kept.get(session["name"]) if keeping else None
        if row is None or row[0] != stamp or clock - row[2] >= open_runs.CEILING:
            row = stamp, v5o_seat_info(cfg, number, session, records, silent_map, jobs_cache,
                                       at, index, None, look, mine), clock
        held[session["name"]] = row
        infos.append(row[1])
    if keeping:
        kept.clear()
        kept.update(held)          # a seat no longer listed, or listed by a new name, goes
    stands = orch.listed()       # ~/code looked at once a read
    groups = by_project(infos, stands)
    for checkout in orch.checkouts(stands=stands):     # a project with no seat shown has no heading
        if str(checkout) in groups and switches_command(checkout):
            groups[str(checkout)]["switches"] = switches(checkout) or []
    return tallied(list(groups.values()), infos, silent_map)    # each where its first seat is


def seat_file_stats():
    """{(seat, file): its stat} for every file of a seat under STATE (`config.seat_file_owner`)."""
    try:
        listed = sorted(parsed.read(config.STATE, os.listdir))
    except OSError:
        return {}
    state, found = os.fspath(config.STATE), {}
    for entry in listed:
        owner = config.seat_file_owner(entry)
        if owner:
            try:
                info = os.stat(os.path.join(state, entry))  # no Path: a read stats every file
            except OSError:
                continue
            found[owner[1], entry] = info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size
    return found


def stamps(cfg, found, mine, files):
    """Each listed seat's stamp of what its row is decided from (`v5o_groups`): its number and
    listing, its runs (`mine`), the config as it reads now and what the tick last found of logins
    and of its stalls, and `files`' stats of its own under every name that leads to it
    (`config.session_aliases`)."""
    from . import watch   # here, not at the top: watch imports this module
    leads, own = config.session_aliases(), {}
    for (name, entry), stat in files.items():
        own.setdefault(leads.get(name, name), []).append((entry, stat))
    saved = look.once("watch state", watch.load_state)
    # the config's text, not the dict: one changed in place reads as the stamp's own otherwise
    every = repr(cfg), saved.get("auth_out"), saved.get("gh_out"), saved.get("worker_tokens")
    return {session["name"]: (every, number, dict(session), saved["stalls"].get(session["name"]),
                              tuple(mine.get(session["name"], ())),
                              tuple(own.get(session["name"], ())))
            for number, session in enumerate(found, 1)}


def tallied(ordered, infos, silent_map):
    """`v5o_groups`' answer for those projects and rows: each project's seats that need the owner
    and its word, and the top line's count of them all."""
    for project in ordered:
        project["needing"] = sum(1 for info in project["seats"] if info["word"] == "needs you")
        project["has_needs"] = bool(project["needing"])
        project["word"] = rollup([info["word"] for info in project["seats"]])
    # The top line counts the seats whose word is `needs you`, each once, and says so once.
    return ordered, infos, sum(project["needing"] for project in ordered), silent_map


def by_project(infos, stands, unfiled=UNFILED):
    """Seat rows grouped by the checkout each one's repo is, so a project can never be listed
    twice and a run can never make one: {str(checkout) or None: {"name", "checkout", "seats"}},
    each project where its first seat is, the seats under none headed `unfiled`.  `stands` is
    what `orch.listed` answered for the read asking."""
    groups = {}
    for info in infos:
        checkout = orch.checkout_of(info["repo"], stands=stands)
        groups.setdefault(str(checkout) if checkout else None,
                          {"name": orch.project_name(checkout, unfiled), "seats": [],
                           "checkout": checkout})["seats"].append(info)
    return groups


def project_pages(projects, room, apart=True, opens={}):
    """`projects`, (heading, blocks) each in order, a block one seat's lines, each line with its
    seat's name, in pages of `room` lines, the main screen's and the past screen's alike: a
    blank line between two projects on a page where `apart`, as on the screen that holds them
    all.  A page keeps free the most lines a seat on it opens under its row, `opens` by name,
    so one seat asking at length takes lines from its own page only."""
    # Seat blocks packed whole under their project header, so a seat's lines never split
    # across pages: one taller than a page under its header is cut to it, as the highlight
    # shows only a seat's first page. A screen without room for a row and a line under it
    # falls back to bare line splits so tiny screens still fit.
    pages, cur, cur_header, kept = [], [], None, 0
    for header, own in projects:
        for block in own or [[]]:     # a heading with no seat under it still has its place
            need = (block if cur and cur_header == header else
                    [("", None)] * (bool(cur) and apart) + [header] + block)
            own_opens = opens.get(block[0][1], 0) if block else 0
            if cur and len(cur) + len(need) + max(kept, own_opens) > room:
                pages.append(cur)
                cur, cur_header, kept = [], None, 0
                need = [header] + block
            if len(need) > room:
                pages.append([header])
                for i in range(0, len(block), room):
                    pages.append(block[i:i + room])
                cur_header = header
                continue
            cur.extend(need)
            cur_header, kept = header, max(kept, own_opens)
    if cur:
        pages.append(cur)
    return pages


def v5o_header(project, term_width):
    """`<project>`, the checkout's basename in bold; the seats filed under none have a dim one,
    which is no project.

    How many need the owner is said by their rows.  A project naming its feature switches says
    how many are hidden -- off for everyone -- dim at the right, `23 hidden features`, and leaves
    room for the highlight's mark in front of it.
    """
    room = terminal.layout_width(term_width)
    hidden = sum(1 for row in project.get("switches", ()) if not row.get("everyone"))
    count = f"{hidden} hidden feature{'' if hidden == 1 else 's'}" if hidden else ""
    if terminal.cells(count) > room - 5:  # mark, name and gap must fit beside the whole count
        count = ""
    name = terminal.cut(project["name"],
                        room - 2 - (terminal.cells(count) + 2 if count else 0))
    gap = room - 2 - terminal.cells(name) - terminal.cells(count)
    return (terminal.styled(name, "bold" if project.get("checkout") else "dim")
            + (" " * gap + terminal.styled(count, "dim") if count else ""))


def _styled_cell(plain_text, width, kind=None, right=False):
    """Cut, then style, then pad: pads land outside escapes, so lines rstrip clean."""
    cut_text = terminal.cut(plain_text, width)
    styled = terminal.styled(cut_text, kind) if kind else cut_text
    space = " " * max(0, width - terminal.cells(styled))
    return space + styled if right else styled + space


def back_at(when, now=None):
    """When a seat out of usage comes back, in the reader's own time: `19:20` today, `Fri 19:20`
    within the week, `23 Oct` past it; "" for no moment."""
    now = time.time() if now is None else now
    if not isinstance(when, (int, float)) or isinstance(when, bool):
        return ""
    at, today = time.localtime(when), time.localtime(now)
    if when - now > 6 * 86400:
        return f"{at.tm_mday} {time.strftime('%b', at)}"
    return time.strftime("%H:%M" if at[:3] == today[:3] else "%a %H:%M", at)


def unsent_mark(text="unsent"):
    """`¶ <text>`, `* <text>` without UTF-8: what the owner left unsent, which never changes the
    word (owner, 20 Oct 2026) -- the mark ends its row and its whole text opens under it."""
    return f"{'¶' if terminal.utf8() else '*'} {text}"


def last_column(word, done, total, room=8, narrow=False, tmux=False, unsent="", back=None,
                tasks=0):
    """The one last column of a seat's row, and of its status bar's line one: its progress
    (`terminal.plan_bar`, a smooth line and `done of total`) in `room` cells, in its word's
    colour, while `seat_progress` finds a plan or an unfinished job and it is not at rest, its
    work waiting in the line to land too, which its bar's squares say; a `working` seat
    with neither draws that line with nothing done and `no plan yet`, a light going round it
    on the menu alone (`motion.circling`).  A seat out of usage says when it comes back,
    `back 19:20` (`back`), in its word's colour, in its progress's place; any other is empty
    -- never `N running`, and no other sentence.  Then, whatever its word, a row's `tasks` in
    flight, `· 2 tasks`, alone where nothing is before them (`terminal.with_tasks`); a bar's
    line one leaves them to its squares.  Where the owner left text `unsent`, `¶ unsent`
    follows two cells after, in the needs-you colour.  The line keeps 8 cells at least; where
    `room` is all there is (`narrow`) -- a row's last column, each width of a seat's bar -- it
    takes that room and never more, the count alone where no cell of line fits, without its
    tasks where they do not fit either, the mark alone where neither count does; a `room` of
    None, the fewest cells that hold the plan's count and mark both.
    `tmux` draws it for a seat's bar.  The row and the bar read this one function, so their
    progress can never disagree."""
    mark = unsent_mark() if unsent else ""
    left = (room or 0) - (terminal.cells(mark) + 2 if mark else 0)
    if word not in (None, "idle", "out of usage") and (total or word == "working"):
        text = terminal.plan_bar(done, total, left, 0, tasks=tasks)
        bar = terminal.plan_bar(done, total, left, 0 if narrow else 8, word, tmux, tasks)
    else:
        said = f"back {back_at(back)}" if word == "out of usage" and back_at(back) else ""
        text = terminal.with_tasks(said, tasks, left if narrow else None)
        bar = _paint(said, word, tmux) + _paint(text[len(said):], "muted", tmux)
    if narrow and mark and room is not None and terminal.cells(text) > left:
        bar = ""
    if not mark:
        return bar
    mark = _paint(mark, "needs you", tmux)
    return f"{bar}  {mark}" if bar else mark


def _last_text(info, room, narrow=False):
    """The row's one last column in `room` cells (`last_column`), counting its tasks in flight
    (`own_tasks`), the ones its seat's bar draws as squares."""
    bar = info.get("bar")
    done, total = bar if bar and len(bar) == 2 else (0, 0)
    return last_column(info.get("word"), done, total, room, narrow, unsent=info.get("unsent"),
                       back=info.get("back"), tasks=len(info.get("tasks") or ()))


def detail(info, room):
    """The lines under a seat's row, in `room` cells: first `¶` and the whole text the owner left
    unsent, in the needs-you colour; then, whatever its word, who builds and who reviews (`crew`)
    alone.  The owner, 17 Nov 2026: "on the menu screen, we never show the task status but just
    have the 'x task' indicator, and then when we open the seat it shows the actual task
    status": the row counts its tasks (`last_column`), and the seat's bar draws their squares
    (`statusbar.whys`).  Never a sentence the seat, or ak about it, says: its row says its word
    and its progress, and the seat itself what it said, for the owner to open (the owner, 9 Nov
    2026).  On a terminal the highlighted row alone opens them; from a pipe every row does, as
    there is no highlight to open one."""
    if not info:
        return []
    if "born" in info:
        return born_lines(info, room)
    unsent = [terminal.styled(line, "needs you") for line in
              terminal.wrap(unsent_mark(info["unsent"]), room)] if info.get("unsent") else []
    who = crew(info, room=room)
    return unsent + ([who] if who else [])


def v5o_column_widths(infos, term_width):
    """Fixed columns sized once per draw from every row on screen.

    Number, name, orchestrator, state and the last-column room come from all infos,
    so the table does not step sideways between projects. `widths` rides into
    `v5o_seat_blocks`; callers that draw one group alone pass nothing and get
    widths sized from those rows.
    """
    room = terminal.content_width(term_width)
    num_w = min(max([terminal.cells(info["number"]) for info in infos] + [1]), 4)
    name_w = min(max([born_cells(info["born"]) if "born" in info else terminal.cells(info["name"])
                      for info in infos] + [1]), 24)
    # a model's full name whole where the row has room, cut by the loop below where it has not
    orch_w = max([terminal.cells(info.get("orchestrator") or info.get("worker") or "")
                  for info in infos] + [0])
    count_w = max([terminal.cells(terminal.state_text(info["count"]))
                   for info in infos] + [1])
    # Keep up to eight cells of each label beside the state; otherwise it goes below the
    # row so the name and orchestrator can use its space.
    state_w = 2 + count_w
    if 2 + num_w + 2 + min(name_w, 8) + 2 + min(orch_w, 8) + state_w > room:
        count_w = state_w = 0
    # an effort gives way, whole, before any name is cut (`_orchestrator`)
    fits = room - (2 + num_w + 2 + name_w + 2 + state_w)
    orch_w = max([terminal.cells(_orchestrator(info, fits)) for info in infos] + [0])
    while 2 + num_w + 2 + name_w + 2 + orch_w + state_w > room and max(name_w, orch_w) > 1:
        if name_w >= orch_w:
            name_w -= 1
        else:
            orch_w -= 1
    fixed = 2 + num_w + 2 + name_w + 2 + orch_w + state_w + 2
    # Every row's last column stands beside it, its line taking what its count leaves, or --
    # on a phone, or where that room would not hold some row's count or mark -- every row's
    # goes under it: never some rows one way and some the other (the owner, 29 Oct 2026).
    least = max([10] + [terminal.cells(_last_text(info, None, narrow=True)) for info in infos])
    return {"room": room, "narrow": term_width < 60, "num": num_w, "name": name_w,
            "orch": orch_w, "count": count_w, "worker": orch_w,
            "under": term_width < 60 or room - fixed < least,
            "sent": max(10, room - fixed), "free": room - fixed}


def _orchestrator(info, room):
    """What a row's orchestrator column says in `room` cells: its model at its effort
    (`config.model_at`) where that fits, else the model alone, which the column may cut."""
    said = info.get("orchestrator") or info.get("worker") or ""
    return said if terminal.cells(said) <= room else info.get("model", said)


def _head(info, widths):
    """A seat row's fixed columns -- number, name, orchestrator, state -- in `widths`.
    Where even their narrowest do not fit, the number keeps its place behind the indent the
    highlight's `›` takes. A zero state width puts that column below the row instead."""
    number = "  " + _styled_cell(info["number"], widths["num"], "dim", right=True)
    orchestrator = _orchestrator(info, widths["orch"])
    rest = [born_name(info["born"], widths["name"]) if "born" in info else
            terminal.pad(terminal.cut(info["name"], widths["name"]), widths["name"]),
            _styled_cell(orchestrator, widths["orch"], "muted")]
    if widths["count"]:
        rest.append(_styled_cell(terminal.state_text(info["count"]), widths["count"],
                                  terminal.state_colour(info["count"])))
    head = "  ".join([number, *rest])
    if terminal.cells(head) <= widths["room"]:
        return head
    left = widths["room"] - terminal.cells(number) - 2
    return number + ("  " + terminal.cut(" ".join(rest), left) if left > 0 else "")


def v5o_seat_blocks(infos, term_width, widths=None, most=None, details=None):
    """One block of lines per seat, in order; no rendered line keeps trailing space.

    Fixed columns with two-space gutters, from `widths` (one `v5o_column_widths`
    per draw): number, name, orchestrator, state, and one last column, the seat's progress
    line (`_last_text`) where it has a plan, in the room beside the row. Content is capped at
    100 columns. On a narrow phone, or where that room holds no row's count, every row's line
    goes whole on the indented line under it (`v5o_column_widths`).
    `details` are the lines each seat named in it opens under its row (`detail`), indented
    under the name; a block of more than `most` lines is cut to them, ending in `…`. Never cut
    inside a glyph or a colour sequence.
    """
    if widths is None:
        widths = v5o_column_widths(infos, term_width)
    room, narrow = widths["room"], widths["narrow"]
    if not infos:
        return []
    indent = " " * (2 + widths["num"] + 2)        # under the name
    blocks = []
    for info in infos:
        head = _head(info, widths)
        last = "" if widths["under"] else _last_text(info, widths["free"], narrow=True)
        if last:
            block = [head + "  " + last]
        else:
            # a line is never wrapped, which drops its colours: on a screen whose rows have no
            # room beside them it goes under its row, in that room
            cont = max(1, room - 4)
            under = _last_text(info, cont, narrow=narrow)
            if terminal.cells(under) > cont:       # a count alone, on the narrowest screens
                lines = [terminal.cut(under, cont)]
            else:
                lines = [under] if under else []
            block = [head] + ["    " + line for line in lines]
        if not widths["count"]:
            block[1:1] = ["    " + terminal.styled(line, terminal.state_colour(info["count"]))
                          for line in terminal.wrap(terminal.state_text(info["count"]), room - 4)]
        block += [indent + line for line in (details or {}).get(info["name"], [])]
        if most is not None and len(block) > max(1, most):
            # the row itself always stays: what is under it is cut, the last line ending in `…`,
            # indented after the cut since `cut` drops leading space
            keep = max(1, most)
            block = block[:1] if keep == 1 else block[:keep - 1] + [indent + terminal.cut(
                " ".join(terminal.plain(line) for line in block[keep - 1:]), room - len(indent))]
        blocks.append(block)
    return [[line.rstrip() for line in block] for block in blocks]


def draw(cfg, found, keys=KEYS, page=0, cursor=None, drawn=None, ask=None, look=True,
         records=None, groups=None, clock=None, updating=None, pointing=True, doing=None):
    """The menu at rest, and (page, pages) as drawn.

    The frame is the header (`agentkit` at the left, the clock at the right),
    one dim rule the width of the layout, then the usage grid, always, and the key line,
    always last, and between them the projects and their seats -- the needing ones first --
    and nothing else.  Where a seat that needs the owner is on another page, the arrow that turns
    to it is amber (`page_mark`).
    A row's number is its place in the whole list, on
    whichever page it is drawn. Uses terminal.header_line, terminal.rule_line,
    terminal.key_line, terminal.STATES, terminal.state_text,
    terminal.state_colour and terminal.format_age; see docs/cli-design.md.

    `drawn` is handed in only while the menu has the keyboard: then the seat named `cursor`
    -- or the first one, when there is no such seat any more -- is highlighted, the page up is
    the one it is on, the screen is written over in place instead of cleared, and `drawn` is
    filled with what a key, a click or the pointer is read against: `order`, the grid's meters,
    ("usage", number) each, then the seats' names top to bottom, with the checkout of a project
    naming its feature switches where its heading is; `cursor`, the one highlighted; `spots`,
    the meter, seat or heading on each screen row and the key line's items (`terminal.under`),
    the one under the pointer lit; `words`, each seat's word.  A seat's state word and any other
    project's heading are cells that only explain (`terminal.Spot`), and nothing says what any
    of them is on the key line; the meter the pointer or the highlight is on is lit over its
    whole cell (`usage_lines`), Enter or a click anywhere on it opening its row on
    `Subscriptions` (`config_subscriptions`), and the blank line under the grid says the rest
    of it (`usage_detail`).  The highlighted seat's line opens under it only while the owner
    points at it (`pointing`: the pointer on it, or ↑/↓ moved there since the pointer last
    was), and closes once the pointer is on no row
    (`terminal.away`) or the row moves from under it (`terminal.pointer`), and stays closed
    until the pointer or ↑/↓ moves onto a row (`drawn["pointing"]`).

    `p past` is on the key line while a seat the owner stopped is
    offered (`closed` on its row, `orch.ghost`), the past screen's.  `ask` is the seat `x` is
    asking about and the card it
    asks on (`terminal.confirm`): the card is drawn under its row, the rows below moving down,
    and `drawn["ask"]` is the screen row of its first line.

    `look` is whether the seats are looked at for this draw or drawn as recorded, and
    `records` the run records it is drawn from, read here when they are not handed in;
    `groups`, `v5o_groups`' answer already in hand, is drawn as it is, and nothing is read.

    `clock`, the menu's `motion.Clock`, is handed each working seat's `●` to breathe while the
    menu has the keyboard, and the news since the draw before: a `!` that turned `needs you`
    pulses, a `✓` that turned `done` settles and a usage bar that moved glides, and a seat `n`
    makes (`born`) and the card `ask` draws (`asked`) come up as a page's rows do.  Their
    first frame goes out in the draw's own write, at the clock's phase, so nothing jumps when
    the screen is drawn over.  While a popup's content fades in, the whole screen is handed to
    it, to come up out of the background (`motion.Clock.rise`).

    `doing` is a job the menu waits on with no key read: the screen is written at rest, its
    header naming it (`terminal.doing`), and `drawn["titled"]` says whether it has a header of
    its own to name a job in.
    """
    owned = drawn is not None
    if (not owned and sys.stdout.isatty() and os.environ.get("TERM", "dumb") != "dumb"
            and "NO_COLOR" not in os.environ):
        print("\033[2J\033[H", end="")
    width, height = terminal.width(), terminal.height()
    layout = terminal.layout_width(width)
    ordered, infos, total_needing, _silent = (v5o_groups(cfg, found, records, look=look)
                                              if groups is None else groups)
    words = {info["name"]: info["word"] for info in infos}
    # The heading of a project naming its feature switches is a row as well, its checkout the name.
    order = [name for project in ordered for name in
             ([project["checkout"]] if "switches" in project else [])
             + [info["name"] for info in project["seats"]]]
    if past_offered(found):
        keys = keys.replace("c config", "p past   c config", 1)
    asking, card = ask or (None, ())
    asked = list(card) if asking in words else []
    # Seat columns are sized once per draw from every row on screen, so the
    # sentence column starts at the same column under every project.
    widths = v5o_column_widths([seat for project in ordered
                                for seat in project["seats"]], width)
    # one reading of the wall clock, cached meters and logins for the whole draw, so the grid
    # the screen is laid out around, its news and every frame of a gliding meter are of those
    # cells, and a click signs in what was drawn amber
    now = time.time()
    rows = usage_rows(cfg)
    ending = login_notes(rows, now)
    cells = usage_cells(cfg, now, rows=rows)
    meters_full = usage_lines(cfg, layout, rows=rows, ending=ending, cells=cells)
    # Height is budgeted the way width is: the frame, the usage and the keys always, and the
    # rows in what is left, a page at a time. Sized from the rows on screen, leaving one
    # line for the prompt and one to spare, exactly as the tests check.
    key_text = keys
    # With the keyboard ← and → turn the pages; in a pipe `j` and `k` do.  Either way the key
    # line starts with where the owner is (`page_mark`), budgeted at its widest.
    paged_keys = key_text + ("" if owned else "   " + PAGE_KEYS)
    # A question under a row is budgeted with the key line, so it never pushes a row off.
    k_single = len(terminal.key_line(key_text, width)) + len(asked)
    k_paged = len(terminal.key_line(paged_keys, width, page_mark(98, 99, owned))) + len(asked)

    def _flat(blocks):
        flat = []
        for block in blocks:
            flat.extend(block)
            flat.append(("", None))  # one blank line between projects
        if flat:
            flat.pop()
        return flat

    # What opens under a row (`detail`): from a pipe under every row, as nothing is highlighted
    # there; with the keyboard under the highlighted row alone, below.
    said_room = max(1, widths["room"] - (2 + widths["num"] + 2))
    # A seat out of usage opens what any row opens and offers nothing: ak takes it on when its
    # usage is back.  The owner, 12 Nov 2026, of `Wait for` and `Go on now with` under it: "I
    # dont like either. I want both to be removed", "the same view as needs you and done".
    said = {info["name"]: detail(info, said_room) for info in infos}
    opened = {} if owned else said

    def _seat_blocks(most=None):
        # Every line travels with the name of the seat it draws, or None, so the highlight and a
        # click find a seat on whichever page it lands.
        return [[[(line, info["name"]) for line in block] for info, block in
                 zip(project["seats"], v5o_seat_blocks(project["seats"], width, widths, most,
                                                       opened))]
                for project in ordered]

    def heading(project):
        # one naming no switches is no row, yet it explains the project it heads
        return v5o_header(project, width), (
            project["checkout"] if "switches" in project
            else ("project", project["name"]) if project["checkout"] else None)
    headings = [heading(project) for project in ordered]
    seat_blocks = _seat_blocks()
    blocks = [[head] + [pair for block in own for pair in block]
              for head, own in zip(headings, seat_blocks)]
    flat = _flat(blocks) or [("  no sessions; n starts one", None)]     # a row, budgeted as one

    # The highlighted seat's lines go under its row: as many kept on its page as the most any
    # seat on it opens, up to half the screen, so no page overflows or turns as the highlight
    # moves; a question longer than that is cut to them, ending in `…`.
    opens = (min(max(map(len, said.values()), default=0), max(1, height // 2))
             if owned and not asked else 0)
    # a worker login that ends soon, or has, stands under the usage on every screen, grid or
    # folded, keyboard or not, while no pointer is there; a compact screen gives it a row
    from . import watch    # here, not at the top: the menu draws without the tick
    token = watch.token_standing()
    standing = ("  " + terminal.styled(terminal.cut(token, layout - 2),
                                       "amber" if "expired" in token else "dim")
                if token else "")

    def _room(meters, paged, compact=False, opened=None):
        keys = (k_paged if paged else k_single) + (opens if opened is None else opened)
        if compact:
            return height - 2 - (keys + len(meters) + bool(standing))
        chrome = 2 + len(meters) + 2 + 1 + keys
        return height - 2 - chrome

    # The usage stays on top and the keys at the bottom, whatever the number of seats: those
    # that do not fit between them turn pages.  Its form is the screen's size alone, so it
    # keeps it while seats come, go and open (the owner, 29 Oct 2026): the whole block wherever
    # that leaves a page `least` rows and OPENS lines for what one of them opens, else its
    # readings, each whole (`usage_summary`); a screen too short for those drops the frame and
    # the blank lines too (compact), and only one with no room for a seat under its heading
    # even then cuts the readings.
    least = LEAST * (2 if width < 60 else 1)
    summary = usage_summary(cfg, layout, rows=rows, cells=cells)
    block = meters_full or summary     # a width with no grid says the readings
    meters, compact = next((meters, compact) for meters, compact
                           in ((block, False), (summary, False), (summary, True))
                           if compact or _room(meters, True, compact, OPENS) >= least)
    if compact:
        # the readings a turning page leaves a seat under its heading, with a line under it, by
        # the screen's size too; else what leaves one row
        spare = _room(meters, True, True, 0) - 3
        if spare < 0 and len(meters) > 1:
            meters = usage_summary(cfg, layout, max(1, len(meters) + spare), rows, cells=cells)
        meters = meters[:max(0, len(meters) + _room(meters, True, True, 0) - 1)]
    paged = len(flat) > 1 and len(flat) > _room(meters, False, compact)     # one page first
    room = _room(meters, paged, compact)
    # a seat under its heading: its row and, where it has one, a line under it
    longest = max((len(block) for own in seat_blocks for block in own), default=0)
    need = 1 + min(2, longest)
    # the opened lines take only what a page of `least` rows leaves -- on a compact screen what
    # a seat under its heading does -- and a page that fits once they have is one
    opens = max(0, opens - max(0, (need if compact or not paged else least) - room))
    paged = paged and len(flat) > _room(meters, False, compact)
    room = max(1, _room(meters, paged, compact))
    # the grid's meters are rows the keys reach too, over the seats
    reach = ([("usage", number) for number in range(1, len(rows) + 1)]
             if meters and meters is meters_full else [])
    if cursor not in order and cursor not in reach:
        cursor = next((name for name in order if isinstance(name, str)),
                      order[0] if order else None)      # a seat before any heading
    order = reach + order
    trimmed = seat_blocks if longest <= max(1, room - 1) else _seat_blocks(room - 1)
    pages = (project_pages(list(zip(headings, trimmed)), room + opens,
                           opens={name: min(len(lines), opens) for name, lines in said.items()})
             if paged else [flat])
    if owned and cursor is not None:
        page = next((number for number, lines in enumerate(pages)
                     if any(name == cursor for _, name in lines)), page)
    page = min(max(page, 0), len(pages) - 1)
    key_lines = terminal.key_line(key_text, width)
    if len(pages) > 1 and not ask:        # a question's key line is its own: no page turns
        needing = [any(words.get(name) == "needs you" for _, name in lines) for lines in pages]
        key_lines = terminal.key_line(paged_keys, width, page_mark(
            page, len(pages), owned, (any(needing[:page]), any(needing[page + 1:]))))
    # The layout is min(terminal width, 120); beyond that the margin grows, never the text.
    out = []
    # what may move: (key, the word it shows, its first cell, highlighted)
    moves = []
    explains = {}   # each seat row's state word, a cell that explains it
    if not compact:
        out += [terminal.header_line("updating" if updating is not None else "",
                                     time.strftime("%H:%M"), width),
                terminal.rule_line(width, updating or 0)]
    grid = len(out) + 1 if reach else None     # its first row
    out += meters
    if not compact:
        out += [standing, ""]       # the line under the usage, then one blank above the projects
    elif standing:
        out.append(standing)
    body = pages[page] if ordered else flat
    top, above = len(out), None
    own_rows = [number for number, (_, name) in enumerate(body, 1) if name == cursor]
    under = max(own_rows, default=0)
    info = next((info for info in infos if info["name"] == cursor), None)
    indent = " " * (2 + widths["num"] + 2)     # under the name
    newborn = info is not None and "born" in info      # whose line is open while it is typed
    lines = (said.get(cursor, []) if opens and under and info and (pointing or newborn)
             and not terminal.away() else [])
    if len(lines) > opens:
        lines = lines[:opens - 1] + [terminal.cut(" ".join(lines[opens - 1:]), said_room)]
    pointer = terminal.pointer()
    if pointer and not newborn and not (top + min(own_rows, default=0) <= pointer.row
                                        <= top + under + len(lines)):
        lines, pointing = [], False    # a line above closed and moved the row from under it
    if lines:
        body = body[:under] + [(indent + line, cursor) for line in lines] + body[under:]
    opened = range(top + under + 1, top + under + 1 + len(lines))   # the rows they are on
    at = max((number for number, (_, name) in enumerate(body, 1) if name == asking), default=0)
    if asked and at:
        body = body[:at] + [(line, None) for line in asked] + body[at:]
    else:
        at = 0
    # the meter the pointer, else the highlight, is on
    usage_spots = meter_spots(layout, len(rows), grid) if grid else {}
    on = None if terminal.away() else terminal.pointer_spot(usage_spots).what or cursor
    pointed = on[1] if on in reach else None
    seats = {info["name"]: info for info in infos}
    breaths = []    # what breathes while a model works: (cell, character, highlighted)
    bars = {}       # each progress line's screen row and slice of terminal.cell_texts
    for line, name in body:
        # a heading is flush left, so its mark goes in front of it
        lit = owned and name is not None and name == cursor and not terminal.away()
        text, word = terminal.ANSI.sub("", line), words.get(name)
        if word == "working":
            for tip in tips(line):
                breaths.append(((len(out) + 1, terminal.cells(text[:tip]) + 1), text[tip], lit))
        out.append(terminal.highlight(("  " if isinstance(name, Path) else "") + line,
                                      mark=name != above) if lit else line)
        above = name
        info = seats.get(name)
        if info and name not in bars and (span := line_at(line)):
            bars[name] = len(out), span
            if info.get("bar"):       # a line that glides to its new length as its plan moves
                moves.append((("bar", name), info["bar"], (len(out), span), lit))
        if word and terminal.state_text(word) in text:
            first = terminal.cells(text[:text.index(terminal.state_text(word))]) + 1
            moves.append((("word", name), word, (len(out), first), lit))
            explains[len(out)] = [(first, first + terminal.cells(terminal.state_text(word)) - 1,
                                   ("state", word))]
    if not compact:
        out.append("")
    if owned:
        # the keys at the bottom, wherever the rows end, over the two lines every draw keeps
        out += [""] * max(0, height - 2 - len(out) - len(key_lines))
    keys_top = len(out)
    out += key_lines
    if not owned:
        print("\n".join(out))
        return page, (len(pages) if ordered else 1)
    heads = {}      # each row's first line: its others say which of them they are from it
    spots = {top + number: ((None, [(1, layout, name)]) if isinstance(name, tuple)
                            else (name, explains.get(top + number, []),
                                  number - heads.setdefault(name, number)))
             for number, (_, name) in enumerate(body, 1) if name}
    spots.update(usage_spots)
    spots.update(terminal.key_spots(key_lines, keys_top + 1))
    if grid and pointed:
        # the one the pointer or the highlight is on lit, and under the grid what its cell has
        # no room for
        out[grid - 1:grid - 1 + len(meters)] = usage_lines(cfg, layout, lit=pointed, rows=rows,
                                                           ending=ending, cells=cells)
        out[grid + len(meters) - 1] = "  " + usage_detail(cfg, pointed, layout, now=now, rows=rows,
                                                          ending=ending)
    out = terminal.lit(out, spots)
    moved, rising = "", False
    if clock is not None:
        clock.clear()
        rising = clock.rise(out)
        # keyed on the highlight alone: a line opening under a row already highlighted, as a
        # seat turns done, is news of that seat and stays still
        moves += [(("opened",), ("seat", cursor), None, False),
                  (("page",), page, None, False)]
        if newborn:       # the row `n` makes: its news touched as it is made
            moves.append((("born",), True, None, False))
        if at:            # the card `x` asks on: its news touched as it is asked (`asking`)
            moves.append((("asked",), True, None, False))
        # each meter's (left, said), by its subscription, and the whole grid's cells, while drawn
        # as a grid (None without one, so a draw with no grid at this width changes at once)
        prev = clock.seen and clock.seen.get(("usage",), (None,))[0]
        readings = [(("usage", subscription(row)), cell[2:] if grid else None)
                    for row, cell in zip(rows, cells)]
        news = clock.look({key: shown for key, shown, _, _ in moves} | dict(readings)
                          | {("usage",): tuple(cells) if grid else None})

        def line(name, moving, counted=None):
            row, span = bars[name]
            grow_line(clock, row, out[row - 1], span, moving, counted)
        # As it opens each seat's line grows to its length, row after row, and on through the
        # draws until it has -- the read that lands as it opens draws the screen again at once --
        # each from its own start, until news moves the line instead.
        if clock.grows is None:
            clock.grows = {name: motion.moment() + n * motion.STAGGER
                           for n, name in enumerate(bars)}
        for name, began in clock.grows.items():
            if name in bars:
                line(name, lambda cells: motion.growing(cells, began), (0, began, motion.GROW))
        # Older effects must not overwrite newer news at a shared cell.
        for key, shown, cell, lit in sorted(moves, key=lambda move: news.get(move[0], (0,))[0]):
            since, before = news.get(key, (None, None))
            if shown == "working":
                clock.start([cell], motion.breathing(terminal.state_glyph(shown), shown, lit))
                if key[1] in bars and not seats[key[1]].get("bar"):     # no plan yet
                    line(key[1], motion.circling)
            elif since is None:
                continue
            elif key[0] == "bar" and before:    # the plan moved: its line glides there
                clock.grows.pop(key[1], None)
                if words.get(key[1]) == "done" and news.get(("word", key[1]), (0,))[0] >= since:
                    continue    # turned done as it moved: swept, and full once the light has
                ticked = before[1] == shown[1] and before[0] < shown[0]     # its count counts on
                line(key[1], lambda cells: motion.growing(
                    cells, since, motion.GLIDE, round(len(cells) * before[0] / max(1, before[1])),
                    words.get(key[1]) or "working"), ticked and (before[0], since, motion.GLIDE))
            elif key[0] in ("opened", "page", "born", "asked"):    # what comes up
                coming = {"opened": opened, "page": range(top + 1, top + len(body) + 1),
                          "born": range(top + min(own_rows, default=opened.start), opened.stop),
                          "asked": range(top + at + 1, top + at + 1 + len(asked))}
                for row in coming[key[0]]:
                    clock.begin(key, motion.fading(out[row - 1]), row, since, None)
            elif shown in ("needs you", "done"):
                # its row glows in its word's colour and fades, and a line just done is crossed
                # by one light
                row = cell[0]
                motion.glowing(out[row - 1], shown, motion.NEWS)(clock, row, since, None)
                clock.start([cell], *(motion.pulsing if shown == "needs you" else motion.settling)(
                    terminal.state_glyph(shown), shown, since, lit))
                if shown == "done" and key[1] in bars:
                    clock.grows.pop(key[1], None)
                    line(key[1], lambda cells: motion.sweeping(cells, since))
        # Each gliding meter is news of `clock.look` alone (nothing kept on `clock`), as a seat's
        # line is: timed from the draw that saw the change, a reading landing mid-glide gliding
        # from the reading the draw before was gliding to, a draw at a new width before a resize
        # is noticed gliding on at that width where both draws have a grid there, arrows leaving
        # it gliding, and `Clock.settle`/`Clock.forget` ending it; where motion is off nothing
        # glides (`clock.start`).  A meter this draw shows at once is settled in `seen` so a
        # later draw never revives a change it already jumped to.
        moment = motion.moment()
        glides = {}
        if (grid and prev and motion.movable() and usage_lines(
                cfg, layout, rows=[], ending=[(None, None, None)] * len(prev), cells=prev)):
            for n, (key, shown) in enumerate(readings):
                since, before = news.get(key, (None, None))
                if gliding(shown, before) and since + motion.GLIDE > moment:
                    at_now = meter_at(shown[0], since, before, moment)
                    probe = [*cells[:n], (*cells[n][:2], *at_now), *cells[n + 1:]]
                    if usage_lines(cfg, layout, rows=rows, ending=ending, cells=probe):
                        glides[n] = since, before
        for n, (key, shown) in enumerate(readings):
            if n not in glides and key in news:
                clock.seen[key] = (shown, None, None)
        if glides:
            until = max(since for since, _ in glides.values()) + motion.GLIDE

            def grid_at(when):
                if when >= until:
                    return [terminal.cleared(text)
                            for text in out[grid - 1:grid - 1 + len(meters)]]
                shown = [(*cell[:2], *meter_at(cell[2], *glides[n], when)) if n in glides else cell
                         for n, cell in enumerate(cells)]
                return [terminal.cleared(text) for text in usage_lines(
                    cfg, layout, lit=pointed, rows=rows, ending=ending, cells=shown)]

            for n in range(len(meters)):
                clock.start([(grid + n, 1)], lambda when, n=n: grid_at(when)[n], until)
        for cell, char, bright in breaths:
            breathe, growing = motion.breathing(char, "working", bright), clock.cells.get(cell)
            if growing:       # a tip still growing in breathes once it is there
                breathe = (lambda now, grow=growing[0], until=growing[1], breathe=breathe:
                           grow(now) if now < until else breathe(now))
            clock.start([cell], breathe)
        moved = clock.frame()
    if doing:
        terminal.doing(doing, not compact)
    else:
        terminal.written(out, moved, rising, screen=page)     # another page is another screen
    # each page's first seat or heading drawn on no page before it, so the highlight resting
    # there has that page up: a heading over its project's next page, or a tall seat's rest, is not
    turns, before = [], set()
    for lines in pages:
        turns.append(next((name for _, name in lines
                           if isinstance(name, (str, Path)) and name not in before), None))
        before.update(name for _, name in lines)
    drawn.update(order=order, cursor=cursor, pointing=pointing, words=words,
                 ask=top + at + 1 if at else None, spots=spots, turns=turns, titled=not compact)
    return page, (len(pages) if ordered else 1)


def would_stop(name):
    """A dry run's `x`: the runs stopping that seat would stop (`transitions.seat_runs`)."""
    for run_dir in transitions.seat_runs(name):
        print(f"would stop {run_dir.name}")


def stop_means(runs):
    """What `Stop` means on the card `x` asks on: `runs`, how many runs stop with the seat, or
    None while they are counted, and what becomes of the seat: `orch.cmd_stop` keeps its record,
    so the past screen reopens it (`show_past`)."""
    stop = ("Its runs stop" if runs is None else "No runs stop" if not runs
            else "1 run stops" if runs == 1 else f"{runs} runs stop")
    return f"{stop} with it; the session moves to past sessions, p, where it reopens where it stopped."


def stop_question(name):
    """The one confirmation `x` asks: the seat, and everything that goes with it."""
    return f"stop {name} and everything it is running? [y/N] "


def close_seat(name, dry_run, refused=None):
    """End that seat and everything it runs, asking nothing: `x` on a done seat, or `Stop`, in
    a process of their own (`teardown`); on a stopped seat, `x` on the past screen, take it off
    the list.

    `orch.cmd_stop` ends the tmux session and then its runs, takes their checkouts and keeps
    the seat -- or, stopped already, takes it.  A refusal goes to `refused`, a notice waiting
    for its Enter unless it says otherwise.
    """
    if dry_run:
        would_stop(name)
        print(f"would stop {name}")
        return
    try:
        orch.cmd_stop([name])
    except config.Error as exc:
        (refused or pause)(f"stop: {exc}")


def stop_behind(name, dry_run):
    """Stop the popup's own seat behind it, in a process of its own (`teardown`), so the popup
    going ends nothing halfway."""
    try:
        subprocess.Popen(teardown(name, dry_run), cwd=config.REPO,
                         env=owner.unmarked(config.owner_env()),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        pause(f"stop: {exc}")


def teardown(name, dry_run):
    """The process `x` stops the popup's own seat in (`stop_behind`, and the past screen's `x`
    removes a stopped one in), marked as its own: `close_seat`, leaving a refusal as a job's
    notice (`orch.job_notices`), since the popup it came from is gone by then."""
    return [sys.executable, "-c", "import sys; from agentkit import menu, orch, owner; "
            "owner.mark('seat stop'); "
            "menu.close_seat(sys.argv[1], sys.argv[2] == '1', refused=orch.leave_notice)",
            name, "1" if dry_run else "0"]


def stop_session(name, dry_run):
    """`x` read a line at a time -- a pipe, a file -- in the popup over seat `name`: one question,
    and nothing else; whether to stop it, which the menu does as the keyboard's `x` does
    (`stop_behind`).  Anything but `y` goes back to the menu; the question says, as the keyboard's
    card does, that the past screen reopens the seat.
    """
    if dry_run:
        would_stop(name)
        print(f"would stop {name}")
        return False
    terminal.frame("stop", terminal.wrap(stop_means(None), terminal.width()))
    return read(stop_question(name), "") == "y"


def open_session(cfg, session, dry_run, keyboard=None, starting=None):
    """A number: into that seat, or back into the conversation it left behind.

    A seat whose orchestrator has exited, and one tmux no longer holds at all, are both opened
    by resuming their owned conversation or clearly starting fresh -- the same key either way.
    `keyboard`, the one a screen holds the terminal by, is given to the seat at once; but while
    a harness is put back in it, not in a dry run, `starting()` puts that screen up again naming
    the job (`terminal.doing`), and the terminal is given once the harness is back
    (`orch.resume`'s `give`), or before a refusal is said.
    """
    name = session["name"]
    closed = any(session.get(key) for key in orch.CLOSED)
    give = keyboard.give if keyboard else lambda: None
    if starting and closed and not dry_run and terminal.taken():
        starting()
    else:
        give()
    if not closed:
        if dry_run:
            print(f"would attach {name}")
            return
        orch.attach(name, wait=True, session=session)
        return
    if dry_run:
        print(f"would resume {name}")
        return
    try:
        # what it says while the screen is held would be written over it
        orch.resume(cfg, name, wait=True, give=give,
                    log=lambda line: None if terminal.taken() else print(line))
    except config.Error as exc:
        give()
        pause(f"resume: {exc}")


def new_session(cfg, dry_run, keyboard=None, found=None):
    """`n` with no menu drawn: the name, then the orchestrator, a question at a time
    (`orch.select`); Esc goes back, nothing created. Enter at the name leaves it for the
    orchestrator to choose, and a dry run only says what it would start: it creates no
    session, so neither its record nor its harness's rulebook. The terminal is given back once
    all is chosen, for the seat to open on.  `found` is the menu's last listing, so the name is
    asked without another."""
    terminal.frame("new session")
    if not cfg:
        return None               # no configuration means no models to offer
    cfg = config.load()           # the last creation's [defaults], whichever process made it
    taken = orch.taken_names(found)
    name = orch.ask_name(taken, auto=True, screen="new session")
    if name is orch.BACK:
        return None
    unnamed = name is None
    try:
        if keyboard is not None:    # the menu's own, given back below for the seat to open on
            providers = waited(lambda: usage.collect(cfg), "new session", keyboard=keyboard)
        else:
            with closing(terminal.Keyboard()) as own:     # Esc read while the usage is asked
                providers = waited(lambda: usage.collect(cfg), "new session", keyboard=own)
    except Back:
        return None
    selected = orch.select(cfg, providers, prompting=True)
    if selected is orch.BACK:
        return None
    if keyboard is not None:
        keyboard.give()
    if unnamed:
        taken = orch.taken_names()        # its name is chosen now: the questions may have waited
        name = orch.character_name(taken)
    if dry_run:
        orch.refuse_name(name, taken)         # a preview refuses what `orch.create` would
        orch.refuse_start(cfg, selected[0], providers, True)
        reviewers = cfg["defaults"].get("reviewers")
        print(f"would start {name}: {selected[0]}, workers {' '.join(selected[2])}"
              + (f", reviewers {' '.join(reviewers)}" if reviewers is not None else ""))
    elif orch.create(cfg, name, orch.seat_cwd(), prompting=True,
                     selection=(providers, selected), unnamed=unnamed, taken=taken) is None:
        return None
    open_session(cfg, {"name": name}, dry_run)
    return name


def born(found):
    """What `n` makes on a terminal, wherever the highlight is: a seat born last under `UNFILED`,
    which its runs or its orchestrator file it under once it knows the job
    (`orch.file_projectless`, `ak orch project`), with the last creation's executors and
    reviewers (`orch.default_crew`), named as typed (`born_key`), else the free character's name
    it opens with (`orch.character_name`) until its orchestrator names it.  Off the listing in
    hand and the usage cache, so the row is up on the next frame; Back where Esc ends a slow
    read."""
    cfg = config.load()           # the last creation's [defaults], whichever process made it
    providers = waited(lambda: usage.collect(cfg), "new session", doing=LEFT)
    default, reason = orch.choose(cfg, providers)
    selected = orch.default_crew(cfg, providers, default)
    taken = orch.taken_names(found)
    return {"cfg": cfg, "typed": "", "taken": taken,
            "name": orch.character_name(taken), "providers": providers, "selected": selected,
            "default": default, "reason": reason}


def born_groups(groups, born):
    """`groups` with the born seat's row last under `UNFILED` -- a heading of its own, after
    every project, where none is on the screen -- and every row numbered down the screen again,
    as the seat will be once it is made (`orch.numbered`)."""
    ordered, infos, *rest = groups
    selected = born["selected"]
    cfg = born["cfg"]
    shown = config.model_at(cfg, selected, selected["orchestrator"], "orchestrator")
    row = {"number": "", "name": BORN, "born": born, "orchestrator": shown, "worker": shown,
           "model": config.model_name(cfg, selected["orchestrator"]),
           "count": "new", "word": "new", "crew": seat_crew(cfg, selected), "tasks": [],
           "repo": None}
    ordered = [{**project, "seats": list(project["seats"])} for project in ordered]
    home = next((project for project in ordered if project["checkout"] is None), None)
    if home is None:
        home = {"name": UNFILED, "seats": [], "checkout": None, "needing": 0, "has_needs": False,
                "word": "idle"}
        ordered.append(home)
    home["seats"].append(row)
    shown = []
    for project in ordered:
        project["seats"] = [{**info, "number": str(len(shown) + n)}
                            for n, info in enumerate(project["seats"], 1)]
        shown += project["seats"]
    return (ordered, shown, *rest)


def born_cells(born):
    """How wide the born row's name is: what is typed and the caret, or its name before a key."""
    return 1 + terminal.cells(born["typed"] or born["name"])


def born_name(born, width):
    """The born row's name cell in `width` cells: what is typed so far in bold -- its end, as a
    field shows it, where it runs past -- then the caret, and before a key, dim, the name Enter
    alone gives it."""
    caret = "▏" if terminal.utf8() else "_"
    typed = born["typed"][-(width - 1):] if width > 1 else ""
    hint = "" if born["typed"] else terminal.cut(born["name"], max(0, width - 1))
    text = (terminal.styled(typed, "bold") + terminal.styled(caret, "accent")
            + terminal.styled(hint, "dim"))
    return text + " " * max(0, width - terminal.cells(typed) - 1 - terminal.cells(hint))


def born_refusal(born):
    """Why Enter makes nothing on the born row: a seat or a rename has the name typed, or its
    crew has no pair that can run (`orch.role_refusal`); else ""."""
    name = orch.session_name(born["typed"]) if born["typed"] else ""
    if name in born["taken"]:
        return f"a seat is called {name} already"
    return orch.role_refusal(born["cfg"], born["selected"], born["providers"])


def born_lines(info, room):
    """What the born row opens under itself: who will build and review (`crew`) -- or, amber on
    lines of its own, wrapped whole for a phone, why Enter makes nothing."""
    refusal = born_refusal(info["born"])
    if refusal:
        return [terminal.styled(line, "amber") for line in terminal.wrap(refusal, room)]
    return [crew(info, room=room)]


def born_key(born, key, drawn):
    """One key on the born row: "start", "back" and "models" for Enter, Esc and Tab or a click
    on their keys, "gone" for a keyboard that is gone, else None, having typed a name's
    character -- a space as `-`, as `orch.session_name` would -- or taken the last one back."""
    if key.name == "click":
        item = terminal.under(key, drawn["spots"]).cell
        key = terminal.Key({"⏎": "enter", "enter": "enter", "esc": "esc", "tab": "tab"}
                           .get(item, "other"))
    if key.name in ("enter", "esc", "tab", "eof"):
        return {"enter": "start", "esc": "back", "tab": "models", "eof": "gone"}[key.name]
    if key.name == "backspace":
        born["typed"] = born["typed"][:-1]
    elif key.name in ("char", "space") and len(born["typed"]) < orch.NAME_CAP:
        char = "-" if key.name == "space" else key.char.lower()
        if re.fullmatch(r"[a-z0-9_-]", char):
            born["typed"] += char
    return None


def born_models(born, keyboard):
    """Tab on the born row: its models and efforts on `c`'s screen (config_matrix), changed on
    the row alone; true where Enter there starts the seat, false where Esc brings them to the
    row."""
    return config_matrix(born["cfg"], keyboard, update.agentkit_version(),
                         selected=born["selected"], providers=born["providers"], born=True)


def start_born(born, dry_run, give):
    """Make the born seat and open it, filed under its project: by the name typed, else the
    one the row showed, which its orchestrator replaces (`unnamed`); a dry run only says what it
    would start.  The name, or None where `orch.create` made nothing.  The names taken are read
    again: another menu may have made a seat since the row opened, and `create` would write
    over its record, so a name taken since is another free character's.  `give` gives the
    terminal back once the seat is made, for it to open on, or where its harness takes this
    terminal itself (`orch.create`)."""
    taken = orch.taken_names()
    unnamed = not born["typed"]
    name = (orch.session_name(born["typed"]) if not unnamed else born["name"]
            if born["name"] not in taken else orch.character_name(taken))
    selected = born["selected"]
    if dry_run:
        orch.refuse_name(name, taken)         # as `orch.create` would
        orch.refuse_start(born["cfg"], selected["orchestrator"],
                          born.get("providers") or {}, True)
        print(f"would start {name}: {selected['orchestrator']}, workers "
              f"{' '.join(selected['workers'])}, reviewers {' '.join(selected['reviewers'])}")
    elif orch.create(born["cfg"], name, orch.seat_cwd(), prompting=True,
                     selection=(born["providers"], (selected["orchestrator"], born["reason"]
                                if selected["orchestrator"] == born["default"] else "selected",
                                selected["workers"], selected["reviewers"],
                                selected.get("efforts") or {})),
                     unnamed=unnamed, taken=taken, give=give) is None:
        return None
    give()
    open_session(born["cfg"], {"name": name}, dry_run)
    return name


def smoke_run(state, resolved=None):
    """The suite's task or repo lives in its sandbox; a run's title proves nothing.  A pass over
    every run hands each call the same `resolved`, so a path many runs name, and the sandbox
    itself, are resolved once; in strings, since pathlib's own was most of a read of a few
    thousand runs."""
    resolved = {} if resolved is None else resolved
    if None not in resolved:          # the sandbox, under the one key no path is
        resolved[None] = os.path.join(os.path.realpath(config.TMP), "")
    for key in ("task", "repo"):
        value = state.get(key)
        if not isinstance(value, str) or not value:
            continue
        if value not in resolved:
            try:
                path = os.path.expanduser(value)
                real = os.path.realpath(path)
            except (OSError, ValueError):
                real = ""
            resolved[value] = (real.startswith(resolved[None])
                               and real[len(resolved[None]):].startswith("smoke-")
                               and not looped(path) and not looped(real))
        if resolved[value]:
            return True
    return False


def looped(path):
    """Whether stat finds a loop: `realpath` can erase `loop/..` or cross a missing `gone/..`,
    so `smoke_run` checks both spellings before calling a run the suite's."""
    try:
        os.stat(path)
    except OSError as error:
        return error.errno == errno.ELOOP
    return False


class _RunRecords:
    """The census a starting screen reads in place of every run.json: what `parsed` keeps of
    each run's record, a row per run under the stat it keeps it by."""

    def __init__(self, root, *, cache=True):
        self.root, self.saved, self.db, self.reader = root, {}, None, open_runs.Reader()
        if not cache:
            return
        # The cache before RUN_RECORDS: nothing reads it, and a run still on that install that
        # writes it again loses it to the next process here.
        for old in ("run-records.jsonl", "run-records.lock", "run-records.tmp"):
            try:
                (config.STATE / old).unlink(missing_ok=True)
            except OSError:
                pass
        try:
            self.db = sqlite3.connect(config.STATE / RUN_RECORDS, timeout=0,
                                      check_same_thread=False)
            self.db.execute("CREATE TABLE IF NOT EXISTS records (name TEXT PRIMARY KEY, value TEXT)")
            for name, value in self.db.execute("SELECT name, value FROM records"):
                try:
                    stamp, state = json.loads(value)
                    if isinstance(stamp, list) and isinstance(state, dict):
                        self.saved[name] = stamp = tuple(stamp)
                        parsed.keep(config.RUNS / name / "run.json", record._state, stamp, state)
                except (ValueError, TypeError, RecursionError):
                    continue
        except sqlite3.Error:
            self.close()       # the run files remain authoritative, even with no writable cache

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None

    def save(self, run_dirs, went=None):
        """Write down what `parsed` keeps of those runs that the census does not hold.  A run gone
        takes its record out of both, since nothing reads its path again for `parsed` to forget
        it: those `went` names, or with None every one the census holds that is not among them."""
        names, changed = set(), []
        for run_dir in run_dirs:
            stamp, state = parsed.kept(run_dir / "run.json", record._state) or (None, None)
            if state is None:
                continue
            names.add(run_dir.name)
            if self.saved.get(run_dir.name) != stamp:
                self.saved[run_dir.name] = stamp
                if self.db is not None:
                    changed.append((run_dir.name, json.dumps([stamp, state])))
        removed = self.saved.keys() - names if went is None else went
        for name in removed:
            parsed.forget(config.RUNS / name / "run.json", record._state)
            self.saved.pop(name, None)
        if self.db is not None and (changed or removed):
            try:
                with self.db:
                    self.db.executemany("INSERT INTO records VALUES (?, ?) ON CONFLICT(name) "
                                        "DO UPDATE SET value = excluded.value", changed)
                    self.db.executemany("DELETE FROM records WHERE name = ?",
                                        ((name,) for name in removed))
            except sqlite3.Error:
                pass           # another process can fill the cache; this one keeps its reads


def attended(state, resolved=None):
    """Whether a screen counts a run: it is neither unattended nor the suite's own (`smoke_run`)."""
    return not state.get("unattended") and not smoke_run(state, resolved)


def run_records(*, cache=True, rest_may_lag=False):
    """Every run's record, each every reader's (`record.runs`), so only read.

    A process's first pass hands `parsed` the census saved in SQLite, so it opens only a run.json
    changed since; each pass saves what `parsed` keeps anew.  SQLite commits only changed rows
    and keeps other processes' reads whole.  Cache failures leave the run files authoritative.
    With cache=False, no persistent cache is read or written.  Either way a run gone leaves
    memory at the next pass.

    Unattended runs and tasks or repos resolving under ~/.agentkit/tmp/smoke-* are left out.
    Paths are resolved on every pass that looks at every run: a symlink can move without a run.json
    changing. Bad run files are skipped, never repaired.

    With `rest_may_lag`, the main screen's read all day, only the open runs are looked at and a
    run at rest is as the last full read found it (`open_runs`), on the rows and in what a look
    decides from them; an open run's paths are resolved only once its record changed, so a symlink
    that moved shows by the next full read; the list comes back the same object while nothing
    changed.  Every other caller decides on what it reads, and looks at every run.
    """
    global _RUN_RECORDS
    with _RUN_RECORDS_LOCK:
        root = config.RUNS, config.STATE, os.getpid(), cache
        if _RUN_RECORDS is None or _RUN_RECORDS.root != root:
            if _RUN_RECORDS is not None:
                _RUN_RECORDS.close()
            _RUN_RECORDS = _RunRecords(root, cache=cache)
        if rest_may_lag:
            return _RUN_RECORDS.reader.read(attended, _RUN_RECORDS.save)
        runs, resolved = record.runs(), {}
        _RUN_RECORDS.save(run_dir for run_dir, _ in runs)
        return [(run_dir, state) for run_dir, state in runs if attended(state, resolved)]


def unread(prov, weekly, readable, now):
    """Why a usage row has no reading to draw: the two or three words after the `—`.

    `readable` with no shared week among it is the one case where a number *was* read and
    still cannot be drawn: every week this provider reports is some model's own cap, and a
    private cap is never shown as the provider's.

    `no login` is said here and nowhere else, and only on the harness's own `auth` verb saying
    no: the seat's credentials are absent or expired, and the remedy is to log in.  A probe the
    endpoint refused says nothing anywhere: its reading stands on the row where there is one,
    and where there is none the words below say that instead.
    """
    if readable:
        return "no shared week"
    if prov.get("none") and not prov.get("error"):
        return "no meter"
    if weekly and all(usage._past(m, now) for m in weekly):
        return "window reset"
    if weekly:
        return "bad reading"
    if prov.get("logged_in") is False:
        return "no login"
    error = str(prov.get("error") or "")
    for pattern, words in UNREAD:
        if pattern.search(error):
            return words
    if prov.get("meters"):
        return "no weekly meter"
    return "not reached" if error else "no reading yet"


def scoped_notes(cfg, provider, weekly, shared):
    """(named, claimed): notes on these weekly meters that are one model's own cap.

    A cap its provider names (`scope`) is `Fable 100% left`, whatever the shared week reads:
    the owner asked to see what it has left beside when the week resets (10 Nov 2026).  One
    only a model's `meter` in config.toml claims is `Fable 41%`, said only where a shared week
    reads otherwise: the note is there for the gap.
    """
    named, claimed = [], []
    for meter in weekly:
        if meter.get("scope"):
            named.append(f"{meter['scope']} {percent_left(meter)}% left")
            continue
        if shared is None or meter is shared or percent_left(meter) == percent_left(shared):
            continue
        owner = next((name for name, entry in cfg["models"].items()
                      if entry.get("provider") == provider
                      and entry.get("meter") == meter.get("name")), None)
        if owner:
            claimed.append(f"{owner.capitalize()} {percent_left(meter)}%")
    return named, claimed


def percent_left(meter):
    """What this meter has left, as the row shows it: a whole number of percent."""
    return round(max(0, min(100, 100 - meter["used"])))


def in_hand(prov):
    """`1 reset in hand`, `2 resets in hand`: the usage-limit resets this subscription holds,
    for the owner to spend on `c` (config_spend_reset); "" with none, or none known.  Where its
    reading names their kinds it says them in its order: `1 weekly, 3 Fable resets in hand`."""
    held = int(usage._number(prov.get("resets")) or 0)
    kinds = ", ".join(f"{kind['left']:g} {kind['kind']}" for kind in prov.get("reset_kinds") or [])
    said = f"{kinds or held} reset{'' if held == 1 else 's'} in hand" if held > 0 else ""
    # its kinds are the reading's words: drawn as limit_notes draws them, by which it is found
    # among those notes
    return terminal.plain(said)


def resets_note(meter, now):
    """`resets Fri 14:00`, `resets 23 Oct` or `resets in 3d`: `ak usage`'s `resets`, as words."""
    when = usage.reset_when(meter, now)
    return f"resets {when}" if when else ""


def session_window(prov, now):
    """The 5h window this account reports that a note can be read from, or None.

    The furthest along of its session meters with a numeric used% in a window that has not
    rolled over; the week aside, this is what stops a turn first.
    """
    meters = [m for m in usage.legible(prov, now) if m.get("window_secs") == usage.SESSION_SECS]
    return max(meters, key=lambda m: m["used"]) if meters else None


def session_note(prov, now):
    """(rank, note) for what is left of the 5h window, or None when it reports none.

    `5h 40% left` while it has room; once it reads 100% used, when it opens again (`5h
    spent until 14:00`, the local hour).  The spent note ranks first, so it is the note that
    survives where only one can.
    """
    meter = session_window(prov, now)
    if meter is None:
        return None
    if meter["used"] >= 100:
        when = usage.reset_when(meter, now)
        if when and ":" in when:
            return -1, f"5h spent until {when.split()[-1]}"
        if when and when.startswith("in "):
            return -1, f"5h spent {when}"
        if when:
            return -1, f"5h spent until {when}"
        return -1, "5h spent"
    return 2, f"5h {percent_left(meter)}% left"


def fault(prov):
    """`? <reason>`: the adapter's own one line for a probe that failed, or "" when it did not.

    The meter the failed probe read still stands, so the row keeps its bar; the reason is
    beside it because a bare `?` sends the reader to `ak usage` to learn a single sentence.
    A refusal is not a reason: words that only say the probe was refused say nothing here,
    and the reading's age says the rest.
    """
    if usage.refusal_text(prov, prov.get("error")):
        return ""
    reason = " ".join(str(prov.get("error") or "").split()).removeprefix("unknown: ")
    return ("? " + reason).strip() if prov.get("error") else ""


def fitting(notes, room):
    """Which of these notes fit in `room` cells, drawn in the order the row reads them.

    A note too long for the room gives way on its own, and the ones after it are not thrown
    out with it: `as of 14:02` is worth having on a phone even where
    `resets Fri 14:00` will never fit.  Each note carries how much it is worth keeping when
    only some can be -- a spent 5h window first, then when the week is back, then why the
    reading may be wrong, then the 5h window, then a cap config.toml claims -- and they are
    offered in that order and drawn in the row's.
    """
    kept, used = set(), 0
    for index in sorted(range(len(notes)), key=lambda i: notes[i][0]):
        needs = terminal.cells(notes[index][1]) + (3 if kept else 0)
        if used + needs <= room:
            kept.add(index)
            used += needs
    return [note for index, (_, note) in enumerate(notes) if index in kept]


def _note_styled(part):
    """A note in the dim style, with a fault's `?` kept in the attention style it earns."""
    if part.startswith("?"):
        return terminal.styled("?", "attention") + terminal.styled(part[1:], "dim")
    return terminal.styled(part, "dim")


def usage_rows(cfg):
    """Each usage row `usage_lines` draws, in its order: the provider, the row's label, the
    reading it is drawn from, out of the cached meters, and its account, None for the
    provider's single row.  A provider whose table says `mode = "free"` is no subscription
    and has no row; the rest run in the order config.toml names them."""
    try:
        providers = json.loads((config.STATE / "usage.json").read_text())["providers"]
        if not isinstance(providers, dict):
            providers = {}
    except (OSError, ValueError, KeyError, TypeError):
        providers = {}
    rows = []
    for name in cfg["providers"]:
        if cfg["providers"][name].get("mode") == "free":
            continue
        top = providers.get(name)
        top = top if isinstance(top, dict) else {}
        found = top.get("accounts") if isinstance(top.get("accounts"), dict) else {}
        for account in config.accounts(cfg, name) or [None]:
            rec = top if account is None else found.get(account)
            rows.append((name, config.account_label(cfg, name, account),
                         rec if isinstance(rec, dict) else {}, account))
    return rows


def subscription(row):
    """A usage row's subscription (usage_rows): its provider and account, the usual login one
    whether config.toml lists it as `default` or lists no account."""
    return row[0], row[3] or config.DEFAULT_ACCOUNT


def followed(meter, was, rows):
    """`meter`, ("usage", number) of usage rows `was` (usage_rows), on `rows`: its
    subscription's, wherever it went; None where it went, or where `was` has no such row."""
    return metered(subscription(was[meter[1] - 1]) if meter[1] <= len(was) else None, rows)


def metered(mine, rows):
    """The meter, ("usage", number), of subscription `mine` (`subscription`) on usage rows
    `rows`; None where they have none."""
    return next((("usage", number) for number, row in enumerate(rows, 1)
                 if subscription(row) == mine), None)


def restored(handed, meter, cfg):
    """The highlight `loop`'s restart hands new code: in JSON, as a seat may be named anything,
    a meter as its subscription, so it is that one's on `cfg` -- another process may change
    config.toml before new code reads it -- or None.  Code from before handed a bare name, a
    seat's, and a meter as its number, `meter`."""
    if meter:
        return "usage", int(meter)
    try:
        cursor = json.loads(handed)
    except ValueError:
        cursor = handed
    if isinstance(cursor, list):
        return metered(tuple(cursor), usage_rows(cfg))
    cursor = cursor if isinstance(cursor, str) else handed    # a bare `123`, read as a number
    return Path(cursor) if cursor.startswith("/") else cursor


def usage_summary(cfg, width, most=None, rows=None, cells=None):
    """The usage block folded, for a screen too short for it and a few rows under it: each
    subscription's label and what it has left -- `17%`, a spent week's credits where they fit,
    else `0%`, as on its row, `0%` once spent until its reset, `—` with no reading -- whole, as
    many to a line as fit, ` · ` between; in `most` lines, the last ending in ` · …` where
    readings are left out."""
    def fill(found, room):
        lines = [[]]
        for _, label, left, said in found:
            figure = (f"{left}%" if left else said if left == 0 and terminal.cells(said) <= room
                      else "—" if said[0] == "—" else "0%")
            # a label too long for the room gives way, never what it has left
            spare = room - 1 - terminal.cells(figure)
            part = f"{terminal.cut(label, spare)} {figure}" if spare > 0 else figure
            if lines[-1] and terminal.cells(" · ".join(lines[-1] + [part])) > room:
                lines.append([])
            lines[-1].append(part)
        return [line for line in lines if line]
    found = usage_cells(cfg, rows=rows) if cells is None else cells
    lines = fill(found, width - 2)
    if most is not None and len(lines) > most:
        # the last line keeps room for ` · …`, a label giving way to it as to the width
        lines = lines[:most - 1]
        lines.append(fill(found[sum(map(len, lines)):], width - 6)[0] + ["…"])
    return ["  " + " · ".join(line) for line in lines]


def reading(cfg, name, prov, now):
    """(shared week or None, why it has none (`unread`), readable meters) of reading `prov`."""
    try:
        weekly = [m for m in prov.get("meters") or [] if m.get("window_secs") != usage.SESSION_SECS]
        readable = usage.readable(prov, now)
        week = usage.shared_week(cfg, name, prov, now)
        return week, week is None and unread(prov, weekly, readable, now), readable
    except (AttributeError, KeyError, TypeError, ValueError):
        return None, "bad reading", []


def usage_cells(cfg, now=None, rows=None):
    """Each subscription's (provider, label, left, said), in `usage_rows`' order: `left` 1 to
    100 and `said` its `NN% left`; 0 for a spent week on credits, which count as usage left,
    `said` them; or None, `said` its `empty until <when>`, or `—` and why (`unread`).  `rows`
    is `usage_rows`' answer already in hand, read here when it is not handed in."""
    now = time.time() if now is None else now
    found = []
    for name, label, prov, _ in usage_rows(cfg) if rows is None else rows:
        week, why, _ = reading(cfg, name, prov, now)
        if week is None:
            found.append((name, label, None, f"—  {why}"))
            continue
        left, credits = percent_left(week), usage.credits_note(prov)
        if left or credits:
            found.append((name, label, left, f"{left}% left" if left else credits))
        else:
            when = resets_note(week, now).removeprefix("resets ")
            found.append((name, label, None, f"empty until {when}" if when else "empty"))
    return found


def meter_at(left, since, before, now):
    """(left, said), as `usage_cells` says them, of a meter gliding (`gliding`) to `left` from
    `before` at `now`, eased in GLIDE seconds from `since`, and `before` while that is 0."""
    first = before[0] or 0
    shown = round(first + (left - first) * motion.eased((now - since) / motion.GLIDE))
    return (shown, f"{shown}% left") if shown else before


def gliding(shown, before):
    """Whether a meter glides (`meter_at`) to `shown` from `before`, the reading the draw before
    showed, each (left, said) as `usage_cells` says them: where it has a share left now and had
    a reading before, from `empty until …` counting up from 0; one unread (`—`) before, or
    empty or unread now, changes at once."""
    return bool(shown and shown[0] and before and (before[0] or before[1][:1] != "—"))


def meter_moves(rows, cells, lines, drawing):
    """A page's meters as its `moves` (matrix_key), hiding which glide to a new reading, from
    where, till when and what each frame draws: one a meter, ("usage", subscription) its key
    and its reading, of `usage_cells`' `cells` of `rows`, its value.  Meter n is on line
    `lines[n]` of those `drawing(cells)` draws, {line: text}.  The meters gliding in one draw
    are its moves' together, each start animating its line whole till the last of them on it
    ends, then at rest, each frame the page's drawing of the line with every one at its reading
    then -- the line at rest where that draws other lines, or that one wider than the screen --
    so no frame can fail.  A meter shown at once is settled (`Clock.seen`), so no later draw
    that can move, as a short screen grown taller, revives it."""
    rest, glides = drawing(cells), {}

    def frame(line, until, when):
        if when < until:
            drawn = drawing([(*cell[:2], *meter_at(cell[2], *glides[n], when)) if n in glides
                             else cell for n, cell in enumerate(cells)])
            if drawn.keys() == rest.keys() and terminal.cells(drawn[line]) <= terminal.width():
                return terminal.cleared(drawn[line])
        return terminal.cleared(rest[line])

    def move(n, key, value):
        def start(clock, row, since, before):
            if (motion.movable() and gliding(value, before)
                    and since + motion.GLIDE > motion.moment()):
                glides[n] = since, before
            else:
                clock.seen[key] = value, None, None
            ends = [glides[m][0] + motion.GLIDE for m in glides if lines[m] == lines[n]]
            if ends:
                until = max(ends)
                clock.start([(row, 1)], lambda when: frame(lines[n], until, when), until)
        return lines[n], key, value, start
    return [move(n, ("usage", subscription(row)), cell[2:]) for n, (row, cell) in
            enumerate(zip(rows, cells))]


METER = 10        # cells of a subscription's meter on the ak screen
COLUMN = 33       # ... and of its whole cell, its label, meter and share or `empty until` date


def usage_columns(width):
    """How many subscriptions a line of the grid holds at `width`: one to three, two apart."""
    return max(1, min(3, width // (COLUMN + 2)))


def usage_cell(width, n):
    """(first, last), the columns from 1 of the `n`th cell, from 0, of a line of the grid
    `usage_lines` draws `width` wide: all of it a meter's, its padding too."""
    room = min(COLUMN, width - 2)
    return 3 + n * (room + 2), 2 + n * (room + 2) + room


def usage_lines(cfg, width, lit=None, rows=None, ending=None, columns=None, cells=None):
    """The cached weekly allowances as a grid, without probing adapters or spending a reset:
    each subscription (`usage_cells`), as many to a line as `usage_columns` fits, by its label,
    a meter -- the bar (terminal.share_parts), full for what is left -- and what its cell says.
    One whose login ends soon (`login_notes`) has what is left in amber, and `lit`, from 1, the
    one the pointer or the highlight is on, is on the selection over its whole cell, as any cell
    is lit (terminal.selected), every colour in it kept.  The rest is said under the grid
    (`usage_detail`).  What each cell says is whole: the labels give way to the longest, and a
    width with no room for a label beside it has no grid (`[]`), the screen saying the readings
    (`usage_summary`).  `ending`, `login_notes` of `rows` where the caller has read them already;
    `columns`, as many to a line as `Subscriptions` draws, one; `cells`, `usage_cells`' answer
    already in hand, or with gliding meters at their frame's reading (`gliding`)."""
    rows = usage_rows(cfg) if rows is None else rows
    found = [(*cell[:3], terminal.plain(cell[3]))
             for cell in (usage_cells(cfg, rows=rows) if cells is None else cells)]
    if not found:
        return []
    columns, room = columns or usage_columns(width), min(COLUMN, width - 2)
    # what a cell says beside its label: its meter at the least, four cells, then its share
    said_room = max(terminal.cells(said) + (6 if left else 0) for _, _, left, said in found)
    label_room = min(12, room - 2 - said_room,
                     max(terminal.cells(terminal.plain(label)) for _, label, _, _ in found))
    if label_room < 1:
        return []
    # a phone's one column is its width: the meter gives way first, down to four cells
    meter = max(4, min(METER, room - label_room - 13))
    ending = login_notes(rows) if ending is None else ending
    lines = []
    for start in range(0, len(found), columns):
        cells = []
        for number, (_, label, left, said) in enumerate(found[start:start + columns], start + 1):
            warn = ending[number - 1][0]
            shown = terminal.cut(terminal.plain(label), label_room)
            text = shown + " " * (label_room - terminal.cells(shown) + 2)
            if not left:     # no meter: `empty until`, or why there is none, or the credits
                text += (terminal.styled(said, "amber") if warn
                         else terminal.styled(said, "dim") if left is None else said)
            else:
                full, rest = terminal.share_parts(left / 100, meter)
                text += ((terminal.styled(full, "amber") if warn else full)
                         + terminal.styled(rest, "border") + "  " + said)
            cells.append(text + " " * max(0, room - terminal.cells(text)))
        line = ("  " + "  ".join(cells)).rstrip()
        if lit and start < lit <= start + columns:
            line = terminal.selected(line, *usage_cell(width, lit - 1 - start))
        lines.append(line)
    return lines


def login_notes(rows, now=None):
    """Of each of `rows`' (`usage_rows`') login, in one read of the logins, so all three are
    always one login's: when it ends while that is within logins.WARN_WITHIN or past, `ends Mon
    26 Oct 04:47 (in 2 days)` (logins.ending), its meter amber meanwhile, else None; its email as
    kept, None where what is kept is no text or only spaces; and its plan as logins.whose has it."""
    now = time.time() if now is None else now
    found = logins.read()
    notes = []
    for name, _, _, account in rows:
        login = found.get(name)
        login = login.get(account or config.DEFAULT_ACCOUNT) if isinstance(login, dict) else None
        login = login if isinstance(login, dict) else {}
        email = login.get("email")
        notes.append((logins.ending(login, now),
                      email if isinstance(email, str) and email.strip() else None,
                      login.get("plan")))
    return notes


def ending_note(email, when):
    """What a screen says of a login ending `when` (login_notes), naming `email` where given:
    `login owner@acme.test ends Mon 26 Oct 04:47 (in 2 days)`."""
    return " ".join(filter(None, ("login", email, when)))


def _writes(text):
    """Whether the screen's stream writes `text`: JSON keeps a lone surrogate, which a stream
    escaping surrogates writes as the byte it stands for and any other refuses, ending the menu."""
    try:
        text.encode(sys.stdout.encoding or "utf-8", sys.stdout.errors or "strict")
    except UnicodeEncodeError:
        return False
    return True


def meter_spots(width, count, first):
    """Where each of `count` subscriptions' meters sits on the grid `usage_lines` draws `width`
    wide from line `first`: {line: (None, [(first, last, ("usage", number), ("usage", number))])},
    `number` from 1, the columns counted from 1 as the terminal counts, its whole cell, as it is
    lit (usage_cell), each meter a row of its own (terminal.under), on the ak screen and `c`
    alike."""
    columns = usage_columns(width)
    return {first + line: (None, [(*usage_cell(width, n), *(("usage", line * columns + n + 1),) * 2)
                                  for n in range(min(columns, count - line * columns))])
            for line in range(-(-count // columns))}


def limit_notes(cfg, name, prov, now):
    """What provider `name`'s reading `prov` says of its limits, (worth, note) each in the order
    a line reads them (`fitting`), each where it applies: the credits it holds, when its week
    resets and what each cap its provider names has left, the resets in hand (`in_hand`), each
    cap config.toml claims that differs (`scoped_notes`), its 5-hour window (`session_note`), why
    its last probe failed (`fault`) and how old the reading is (`usage.as_of`); for one with no
    week to draw, why (`unread`), what each cap its provider names has left and its 5-hour
    window, read apart from any week.  The line under the usage grid says them (usage_detail),
    and so does the one under Subscriptions' lit row."""
    week, why, readable = reading(cfg, name, prov, now)
    named, claimed = scoped_notes(cfg, name, readable, week)
    # a cap its provider names is one note with the reset time, or with why there is no week to
    # reset: it gives way only with it
    first = (0, " · ".join(filter(None, (resets_note(week, now) if week else why, *named))))
    session = session_note(prov, now) or (0, "")
    notes = [first, session] if week is None else [
        (-1, usage.credits_note(prov)), first, (1, in_hand(prov)),
        *((3, note) for note in claimed),
        session, (1, fault(prov)), (1, usage.as_of(prov, now))]
    # each on one line a screen can draw, whatever a model's or cap's name or an error holds
    return [(worth, shown) for worth, note in notes if (shown := terminal.plain(note))]


def usage_detail(cfg, number, width=None, now=None, rows=None, ending=None):
    """What the line under the usage grid says of subscription `number`, from 1, while the
    pointer is on it: its label, then -- joined with ` · ` -- a login that ends soon, in amber,
    else its login's email (`login_notes`), and its limit_notes, the resets in hand in `info`.
    In `width` cells the notes give way one by one, the least worth keeping first (`fitting`),
    the login's last, and the label too, past the notes but before a login that ends soon;
    `rows` as `usage_cells`', and `ending` as `usage_lines`'."""
    now = time.time() if now is None else now
    rows = usage_rows(cfg) if rows is None else rows
    if not 0 < number <= len(rows):
        return ""
    name, label, prov, _ = rows[number - 1]
    hand = in_hand(prov)
    when, email, _ = (login_notes(rows[number - 1:number], now) if ending is None
                      else ending[number - 1:number])[0]
    # this line is written as kept, and what the screen's stream cannot write would end the menu
    email = email if email and _writes(email) else None
    login = when and ending_note(email, when)
    # each note styled as it is made: an email is any text, so no note is known by its words
    told = ([(-2, terminal.styled(login, "amber")), (-2, _note_styled("click to log in again"))]
            if login else [(-2, terminal.styled(email, "dim"))] if email else [])
    notes = [*told, *((worth, terminal.styled(part, "info") if part == hand else
                       _note_styled(part)) for worth, part in limit_notes(cfg, name, prov, now))]
    room = 10 ** 6 if width is None else width - 4
    # a login ending is kept before the label, which the lit cell above already shows; a label
    # too long for the line gives way, as in its cell
    held = terminal.cells(login or "")
    label = terminal.cut(label, room - (held if held <= room else 0))
    room -= terminal.cells(label)
    return label + "  " + terminal.styled(" · ", "dim").join(fitting(notes, room))


def run_state_word(state):
    """The listings' word for a run, read from terminal.STATES.

    A run is working, needs you or done, like everything else here. Still queued or
    running, and parked on a provider window, a dead reviewer, a stall or a scheduled
    error retry it resumes itself from, is `working`; an interruption, a FAIL, an
    unscheduled error, a `blocked` and an `exhausted` run nothing resumes are `needs
    you`, because nobody is going to take them up unless
    he does; a run that passed, one stopped on purpose, or a merge wait the tick no
    longer admits is `done`. The last is history, not a fresh ending to page him for. What it is
    waiting for, what failed, or what blocked it, lives on its note line, since the
    column stays glyph and word from STATES on every row.

    One run says more than a word: a login expired under it, and until somebody logs in
    again neither the loop nor the tick can move it, so the column reads `waiting for
    <harness> login` under `waiting`'s open circle rather than claiming it is working.
    It is still nobody's to take up -- the tick resumes it the moment the `auth` verb
    passes -- which is what the circle, and not `needs you`, says.
    """
    if state.get("state") == "waiting_login":
        return staffing.waiting_word(state)
    if transitions.going(state):
        return "working"
    if transitions.needs_recovery(state) or state.get("state") in record.FAILED:
        return "needs you"
    return "done"


def run_age_secs(state):
    """The seconds the age column and the follow header read for a run."""
    now = time.time()
    started = state.get("started_at") or 0
    if transitions.needs_recovery(state):
        return max(0.0, now - (state.get("interrupted_at") or started or now))
    if state.get("state") in record.ACTIVE or transitions.landing_line(state):
        return max(0.0, now - (started or now))
    if not started:
        return 0.0
    return max(0.0, (state.get("finished_at") or 0) - started)


def table(rows):
    """The same six columns as the sessions, with details below on a phone."""
    print("\n".join(terminal.seats(rows, terminal.width())))


def tidy_log(notice):
    """The log the menu hands what it does by itself as it opens (`orch.maintenance`,
    `watch.resume_after_boot`): each line goes to the tick's log (`watch.note`), where the tick's
    same sweep writes it every three minutes, and a warning -- a line opening with WARN, as every
    one of ak's does -- to `notice` as well; the rest asked nothing of the owner.  A line the log
    cannot take is the owner's to read instead, and the work goes on: a sweep stopped there would
    keep the record it was retiring, a boot resume the turn it was bringing back."""
    from . import watch    # here, not at the top: watch imports this module

    def log(line):
        try:
            watch.note(line)
        except OSError as exc:
            return notice(f"WARN not logged ({exc}): {line}")
        if line.startswith("WARN"):
            notice(line)
    return log


def show_notices(messages):
    """Read warnings, a job's results and an update's lines once, before the main screen clears
    them: on the screen the menu holds, in the note frame (`pause`); elsewhere printed whole at
    words."""
    said = [message.replace(os.path.expanduser("~") + "/", "~/") for message in messages]
    if not terminal.taken():
        said = [" " + part for message in said for part in terminal.wrap(
            message, terminal.width() - 1)]
    if said:
        pause(*said)


# The rows under the models, each running its own step.  Owner, 10 Nov 2026: "Remove the weekly
# audit feature for now. Dont delete it, but remove it."  `Weekly audit` (AUDIT), its value
# audit_value's, stood between `Discord` and `Done check`.
CONFIG_ROWS = ("Models", "Subscriptions", "Discord", "Done check", "Machines", "Limits", "Money")
AUDIT = ("row", "Weekly audit")  # on or off, and the models its seat takes (config.audit)
DONE_CHECK = ("row", "Done check")   # on or off, and the model that makes it (done_check.setting)
MACHINES = ("row", "Machines")
LIMITS = ("row", "Limits")       # config.POLICY's numbers (config_limits)
MONEY = ("row", "Money")         # the currency prices are in (config_money)
# The config.POLICY numbers on `Limits`: each one's name there, how `Limits`' value on `c` says
# it, before the number and its unit after, None where `c` leaves it out, and the steps ← and →
# move it through (limit_step), None where they count by one from 0 with no top, as config.toml
# has none.  `c`'s line holds the first four, a fifth passing 100 cells.
# Owner, 3 Nov 2026: the keys' own names were unclear to users; 5 Nov 2026: "The executor cap
# moves in steps of 100, the orchestrator's in steps of 25."; 22 Nov 2026: "Let the page count on."
LIMIT_NAMES = {"review_rounds": ("Review rounds", "review", "rounds", range(0, 6)),
               "executor_lines": ("Max lines per executor task", "executor", "lines",
                                  (*range(0, 1001, 100), "no limit")),
               "orchestrator_lines": ("Max lines per orchestrator task", "orchestrator", "lines",
                                      (*range(0, 201, 25), "no limit")),
               "extra_rounds": ("Extra rounds with one or two findings left", "extra", "rounds",
                                None),
               "rescope_findings": ("Findings that end a run for rescoping", None, None, None)}
# What a subscription offers on its row of `Subscriptions`, each where it applies
# (subscription_acts), and without UTF-8.
# The second is one act for each kind of reset it can spend now, named after it (`spend a
# Fable reset`), as the owner reads what a press spends before pressing.
# Its line opens lit on the first, where offered, and on nothing else: `spend a reset`
# spends at once (config_spend_reset), so Enter lands on it only after a move or a click there.
SUBSCRIPTION_ACTS = (("→ log in again", "log in again"), ("→ spend a {}reset", "spend a {}reset"),
                     ("− remove", "- remove"))


def act_text(act, kind=None):
    """`act`, one of SUBSCRIPTION_ACTS, as this terminal draws it, naming `kind` where it is
    `spend a reset` of one."""
    return act[0 if terminal.utf8() else 1].format(f"{kind} " if kind else "")


def act_word(text):
    """What Enter does on an act, as the key line names it: its text without its glyph, `log in
    again` for `→ log in again`."""
    return text.lstrip("→−- ")


# The company each provider the shipped default has is (company_name).
COMPANIES = {"anthropic": "Anthropic", "openai": "OpenAI", "meta": "Meta", "xai": "xAI",
             "google": "Google"}


def company_name(cfg, provider):
    """What `provider`'s subscriptions sit under, bold, on `Subscriptions` and on `+ add a
    subscription` alike: its company (COMPANIES), else its own name."""
    return COMPANIES.get(provider) or config.provider_name(cfg, provider)


# What `− remove` asks, and what it means; then the same about one subscription of a provider.
REMOVE_PROVIDER_ASK = ("Remove {} and its models?",
                       "Its models leave the config, and its logins are signed out on this machine.")
REMOVE_SUBSCRIPTION_ASK = ("Remove {}?",
                           "Nothing new starts on it, and its login is signed out on this machine.")
# `c`'s cells along a model's row: each role's mark, 0 to 2, and beside it that role's effort, 3
# to 5 (config.ROLE_EFFORTS's order), the owner's pick of 24 Oct 2026 (config_columns).
CONFIG_ORDER = (0, 3, 1, 4, 2, 5)
# The key on the config screen that opens what `ak models` recommends per role.
ADVICE_KEY = "r recommended"
APPLY_KEY = "a apply to all sessions"     # new seats' `c` alone: a seat's marks are its own
APPLY_ASK = "Give new seats' models and efforts to {}?"
APPLY_ANSWER = "Apply"
# Whom `c`'s marks are for when they are no seat's: [defaults], what the next `n` starts from.
NEW_SEATS = "new seats"
MOVE_ASK = "Restart {} on {}?"     # what another model's orchestrator mark asks, and what it means
MOVE_MEANS = {True: "It keeps its conversation.",
              False: "It starts a new conversation, handed the one it had."}
RESTART_ASK = "Restart {} on {} at {}?"   # what a move of a seat's orchestrator at an effort asks
# Every effort word, weakest first -- the widest list a manifest names (adapters/muse.toml) --
# so a new model id that does not take its model's effort takes the nearest one it does.
EFFORT_RANK = ("none", "minimal", *config.EFFORTS)
ADD_STEPS = ("model", "effort")   # `add a subscription`'s lists, each opening under the last


def _secret(name):
    """What ~/.agentkit/secrets/<name> holds, or "": the file install.sh and `Discord` write."""
    try:
        return (config.SECRETS / name).read_text().strip()
    except OSError:
        return ""


def discord_shown():
    """Who a card pings and where it goes, as `Discord` shows them: `@acme-owner` -- the name a
    delivered card's receipt gave this user id (notify.pinged), the id's last 4 digits until
    one has -- and `…a1B2c3`, the only part of the webhook ever shown; "" for one not set."""
    hook, user = _secret("discord_webhook"), _secret("discord_user_id")
    name = notify.pinged(user) if user else None
    return (f"@{name}" if name else f"id …{user[-4:]}" if user else "",
            f"…{hook[-6:]}" if hook else "")


def discord_value():
    """`Discord`'s value on `c`: `@acme-owner · webhook …a1B2c3`, or `not connected`."""
    who, hook = discord_shown()
    return " · ".join(filter(None, (who, f"webhook {hook}"))) if hook else "not connected"


def config_models(cfg):
    """The offered models in the order the `c` screen lists them: config.offered's, under their
    harnesses."""
    return config.offered(cfg)


def model_label(cfg, name, width):
    """The model's full name on `c` and `n` (`config.model_name`), cut only to the space its
    row has."""
    return terminal.cut(config.model_name(cfg, name), width)


def model_heading(harness):
    """The same heading over the models on `c` and `n`: their harness's name, bold."""
    return terminal.styled(config.harness_name(harness), "bold")


# each role's group in a record (its config role: matrix.CONFIG_ROLES), which a take sets
TAKEN = {"orchestrate": "orchestrator", "execute": "workers", "review": "reviewers"}


def stands(found, row):
    """Whether `row`, of a role's answer `found` (matrix.answer), stands among its bars and
    steps beside the choices where the role used it, the owner, 12 Nov 2026: no choice, `whys`
    holding it (matrix._choices), and with a cost to stand at."""
    return id(row) in found["whys"] and row["cost"] is not None


def role_steps(found, kept):
    """The rows ← and → step among (next_choice) of a role's answer `found` (matrix.answer): its
    `choices`, and the row of `kept` (model, effort, row) where it stands (`stands`)."""
    return found["choices"] + ([kept[2]] if stands(found, kept[2]) else [])


def step_take(cfg, found, kept, row):
    """(model, effort) a step to `row`, one of role_steps, asks a take at (take_choice): a
    choice's, the model a take of it takes (matrix.takes) at its effort; the row of `kept`'s, as
    the role used it."""
    return ((matrix.takes(cfg, row), row["effort"]) if any(one is row for one in found["choices"])
            else kept[:2])


def next_choice(cfg, found, row, step, kept):
    """What ← (`step` -1) or → (1) takes off `row`, the row a role uses, of its answer `found`
    (matrix.answer), the owner's design of 5 Nov 2026: (model, effort) of its next step down or
    up (role_steps, step_take), in order of cost and on a tie of quality; None past either end.
    A `row` that is no step stands at its cost and quality, one with no cost as its best
    choice.  A choice a take takes no model of is passed by: a harness changed since `found`
    was answered may leave one so."""
    steps = [(one, *step_take(cfg, found, kept, one)) for one in role_steps(found, kept)]
    here = row if row and row["cost"] is not None else next(reversed(found["choices"]), None)
    if here is None:
        return None
    steps += [] if any(one is here for one, *_ in steps) else [(here, None, None)]
    steps = sorted(steps, key=lambda one: (one[0]["cost"], one[0]["quality"]))[::step]
    at = next(n for n, (one, *_) in enumerate(steps) if one is here)
    return next(((model, level) for _, model, level in steps[at + 1:] if model), None)


def take_choice(cfg, name, selected, providers, role, model, effort, ask):
    """A take (next_choice): seat `name`'s `role` becomes `model` at `effort`, its model set up
    first where none of yours runs it (set_up), the role staying where that fails.  An executor or
    reviewer takes it as the seat's own effort for that role (`exec_effort`, `review_effort`;
    one at the model's effort or at none leaves it following the effort, _follows), the role
    and the effort saved to the seat's record as it stands in one write (roles_saved), or
    neither.  The orchestrator moves the seat, asked first on the card `ask` asks on where
    that restarts it (seat_effort).  With no `name`, `selected` being [defaults], the role is
    taken there, the orchestrator at `effort` as the entry's `effort`, and the entry and
    [defaults] are saved in one write (defaults_saved), no open seat changing.  What to say
    under the rows, "" once taken; None where the restart was not picked.  `effort` is taken
    as the model takes it (_taken_at), the one it is set up at too."""
    effort = _taken_at(cfg, model, effort)
    model, note = set_up(cfg, model, effort)
    if note:
        return note
    if name is not None and role == "orchestrate":
        return seat_effort(cfg, name, selected, model, effort, ask, providers=providers)
    key = config.ROLE_EFFORTS[matrix.CONFIG_ROLES[role]]
    taken = {TAKEN[role]: model if role == "orchestrate" else [model]}
    if name is not None:
        return roles_saved(cfg, name, selected, lambda record, now: orch.role_groups(
            now, record, providers, **taken), [(model, key, effort)])
    changed, note = orch.role_groups(cfg, selected, providers, **taken)
    if note:
        return note
    before = copy.deepcopy(cfg)
    # the orchestrator's effort leaves the model's builds and reviews where they stood, as a
    # seat's move does (config.orchestrating_at)
    _set_effort(cfg["models"][model], key, effort, config.ROLE_EFFORTS.values())
    return defaults_saved(cfg, selected, changed, before)


def _taken_at(cfg, model, effort):
    """`effort` where `model`, a take's (matrix.takes), takes it, else the nearest it takes
    (_nearest), as its harness's saved list (config.catalog_held, then its `[catalog]` table, as
    config.efforts reads them) lists that model's: a take asks no harness.  `effort` as it is
    for a model whose list is not held, and None, a row's that names none, too: the model's own
    (_set_effort)."""
    if effort is None:
        return None
    entry = cfg["models"][model] if isinstance(model, str) else model
    listed = config.catalog_held(entry["harness"], cfg) + config.catalog_table(entry["harness"])
    levels = next((one["efforts"] for one in listed
                   if one["id"] == entry["model"] and one["efforts"]), None)
    return _nearest(effort, levels) if levels else effort


def set_up(cfg, model, effort):
    """`model` as a take takes it (matrix.takes): a configured model's name as it is, else the
    model set up as the take begins, so the config holds only what a role took: beside one of
    yours as a seat's harness running a model no entry runs adds one (watch._taken_in), asking no
    harness, at `effort` where the model takes it; `c`'s mark follows the file where nothing
    else changed it since `c` read it (_saved).  (its name, ""), else (None, why it was not
    added)."""
    global _held
    if isinstance(model, str):
        return model, ""
    from . import watch     # here, not at the top: the menu draws without the tick
    try:
        with config._config_lock():
            ours = _held[0] is cfg and config_mark() == _held[1]
            names = watch._taken_in(cfg, model, (model["model"], effort), None)
            if ours:
                _held = cfg, config_mark()
    except (config.Error, OSError) as exc:
        return None, f"config: {exc}"
    return (names[0], "") if names else (None, f"config: {model['model']} is listed no more")


def efforts_saved(cfg, name, selected, steps):
    """Seat `name`'s efforts with each (model, key, effort) of `steps` set (_set_effort), saved
    to its record at once and into `selected`, the model entries left alone.  Each is set on the
    record as it stands, under its lock (config.change_efforts), so a key saved since is kept;
    a model it holds none for starts from its entry's.  What to say under the rows, or ""."""
    try:
        saved = config.change_efforts(config.resolve_session(name),
                                      lambda record: _stepped(cfg, record, steps))
    except (config.Error, OSError) as exc:
        return f"session: {exc}"
    if saved is None:
        return f"session: {name} has no saved models"
    if selected is not None:      # a record that will not read is written all the same
        selected["efforts"] = saved["efforts"]
    return ""


def _stepped(cfg, record, steps):
    """Seat `record`'s efforts with each (model, key, effort) of `steps` set (_set_effort), the
    rest kept on an effort's own (orchestrating_at); one holding none starts from its entry's."""
    efforts = dict(record.get("efforts") or {})
    for model, key, effort in steps:
        efforts[model] = dict(efforts.get(model) or config.efforts_of(cfg["models"][model]))
        _set_effort(efforts[model], key, effort,
                    config.ROLE_EFFORTS.values() if key == "effort" else ())
    return efforts


def roles_saved(cfg, name, selected, change, steps=()):
    """Seat `name`'s record as `change` makes it, (record, why not), of the record and the
    config as they stand, each (model, key, effort) of `steps` set on it (_stepped), saved at
    once (config.change_session): nothing else the screen holds is written, so another
    window's save since stays.  `selected` then holds the record as the screen reads it
    (seat_read), its bar redrawn (handback.redress_seat); a refusal or a save that fails
    leaves all alone.  What to say under the rows, or ""."""
    seat = config.resolve_session(name)     # a screen open across a rename has the old name

    def judged(record, now):
        changed, note = change(record, now)
        if note:
            raise config.Error(note)
        return {**changed, "efforts": _stepped(now, changed, steps)} if steps else changed
    try:
        saved = config.change_session(seat, judged)
    except config.Error as exc:
        return str(exc)
    except OSError as exc:
        return f"session: {exc}"
    if saved is None:
        return f"session: {name} has no saved models"
    handback.redress_seat(seat)
    seat_read(cfg, seat, selected)
    return ""


def seat_read(cfg, name, selected):
    """`selected` as seat `name`'s record reads over `cfg` now, as `c` reads it each tick; kept
    as it was where the record will not read, until it reads again."""
    try:
        current = config.load_session(cfg, name, required=False)
    except (config.Error, OSError):
        return
    if current is not None:
        selected.clear()
        selected.update(current)


# What the models screen counts a cost in, as `u` turns through them, the owner's design of 5 Nov
# 2026: dollars a task, the points of its plan's week a task takes, how many such tasks a week
# holds; each with how a row's why says its cost (models_why), `cost` as cost_said gives it
UNITS = {"$ a task": "{cost} a {run}", "% of a week": "{cost} of a week a {run}",
         "a week": "{cost} {run}s a week"}
UNBOARDED, UNMARKED = "not on the boards", "none"     # a model no row is; a role marking none
# the why's words: what a row does in each role and a run of it, each measure's evaluation by
# its name, where each `cost_rule` says a cost comes from, and a count under ten
DOES = {"orchestrate": "orchestrates", "execute": "builds", "review": "reviews"}
RUN = {"orchestrate": "task", "execute": "build", "review": "review"}
MEASURES = {"aa.automationBenchPartialScore": "AutomationBench", "arena.agent": "Arena Agent",
            "aa.omniscience": "AA-Omniscience", "aa.briefcaseBreakdown.overall.elo": "AA-Briefcase",
            "aa.frontierCode20": "FrontierCode 2.0", "aa.terminalBench40": "Terminal-Bench 4.0"}
SOURCES = {"measured": "from {runs} of your {run}s",
           "provider": "estimated: its board price, times what your runs on its provider cost "
                       "a board dollar",
           "global": "estimated: its board price, times what your runs on every provider cost "
                     "a board dollar at list prices, at its own plan's rate",
           "board": "its board price alone: no {run} of yours priced a model"}
# why each of a role's `others` is no choice, by its `why` (matrix._why)
WHYS = {"beaten": "beaten by {by}", "close": "within {apart} of {by}",
        "far below": "{below} below the best",
        "no room": "the {places} places go to better choices",
        "not set up": "would be a choice, but it is listed nowhere a model of yours runs",
        "no cost": "no board prices it",
        "not converted": "a board prices it, but your runs and plans give that price no cost"}
# Why a release compared is none of a role's when the role rates no row of it (quality.rated)
UNRATED = "fewer than {fewest} of this role's benchmarks score it"
NUMBERS = "zero one two three four five six seven eight nine".split()


def unit_path():
    """Where the unit the models screen last counted in is kept: in ak's state, never the
    config, as it is the owner's view of the screen, not a setting of ak's."""
    return config.STATE / "models-unit"


def models_unit():
    """The unit of UNITS the models screen counts costs in: the one `u` last turned to, else the
    first."""
    try:
        unit = unit_path().read_text()
    except (OSError, ValueError):
        unit = None
    return unit if unit in UNITS else next(iter(UNITS))


def next_unit(unit):
    """The unit `u` turns to after `unit`, kept for the screen to open in (models_unit)."""
    units = list(UNITS)
    unit = units[(units.index(unit) + 1) % len(units)]
    _moved_in(unit_path(), unit)
    return unit


def _moved_in(path, text):
    """`text` as `path`, a file of the models screen's in ak's state: moved in whole from a file
    of its own, so screens writing it at once each leave a whole one."""
    config.ensure_dirs()
    with tempfile.NamedTemporaryFile("w", dir=config.STATE, prefix=f".{path.name}-",
                                     delete=False) as part:
        part.write(text)
    os.replace(part.name, path)


# the field of a seat's record each role's kept price is (keep_price)
PRICE_FIELDS = {role: f"{word}_price" for role, word in matrix.CONFIG_ROLES.items()}


def price_path(role):
    """Where new seats' kept price for `role` is (keep_price): in ak's state beside the unit's
    (unit_path), never the config, so no writer of [defaults] need know of it."""
    return config.STATE / f"models-{matrix.CONFIG_ROLES[role]}-price"


def keep_price(cfg, session, selected, answer, role, before):
    """Once a take (take_choice) has moved `role` of seat `session`, else of new seats, off the
    row `before` as `selected` now reads (matrix.uses), the price it stopped at, the owner's
    design of 5 Nov 2026: the choice's `limit` (matrix.answer's `limits`), the `cost_unit` and
    the `model` and `effort` the role then uses, so a better model that gets that cheap later
    can take over; a row no choice removes it.  Written after the take, off the reading it is
    judged by, so no other write need know of it: in the seat's record as it stands, under its
    lock, following a rename meanwhile, else in price_path.  What to say under the rows, or ""."""
    model, effort, row = matrix.uses(cfg, selected, answer)[role]
    if row is before:
        return ""               # a take onto the model and effort it ran: no row changed
    found = answer[role]
    entry = {"limit": found["limits"][id(row)], "cost_unit": found["cost_unit"], "model": model,
             "effort": effort} if id(row) in found["limits"] else None
    try:
        if session is not None:
            with look.aside():      # a rename meanwhile is on the disk now, never in a pass
                seat = config.resolve_session(session)
                for _ in range(config.RENAME_HOPS + 1):
                    if config.update_session(seat, **{PRICE_FIELDS[role]: entry}) is not None:
                        return ""
                    if (moved := config.resolve_session(seat)) == seat:
                        return f"session: {session} has no saved models"
                    seat = moved
            return (f"session: {config.session_path(session)}: more than {config.RENAME_HOPS} "
                    "renames deep")
        if entry is None:
            price_path(role).unlink(missing_ok=True)
        else:
            _moved_in(price_path(role), json.dumps(entry))
    except (config.Error, OSError) as exc:
        return f"{'session' if session is not None else 'state'}: {exc}"
    return ""


def price_held(session, role, used, found):
    """The price `role` of seat `session`, else of new seats, keeps (keep_price) where it holds,
    else None, judged at each read, the owner's design of 5 Nov 2026: while the role uses the
    model and effort it names, as `used` (matrix.uses) reads them, and, one with a limit, while
    the role's answer `found` (matrix.answer) counts costs in its `cost_unit`.  One that will
    not read holds none."""
    try:
        entry = json.loads(price_path(role).read_text()) if session is None else (
            config.session_record(config.resolve_session(session)) or {}).get(PRICE_FIELDS[role])
    except (config.Error, OSError, ValueError):
        return None
    if not isinstance(entry, dict) or (entry.get("model"), entry.get("effort")) != used[:2]:
        return None
    limit = entry.get("limit", "")
    held = limit is None or type(limit) in (int, float) and decimal.Decimal(
        repr(limit)).is_finite() and entry.get("cost_unit") == found["cost_unit"]
    return entry if held else None


def price_fit(cfg, found, price):
    """The choice `price` (price_held) takes in its role's answer `found` (matrix.answer): the
    best of its choices a configured model runs (matrix.runner), as by itself nothing is set up,
    costing no more than its limit, the best for none; None where none does."""
    return next((row for row in reversed(found["choices"]) if matrix.runner(cfg, row)
                 and (price["limit"] is None or row["cost"] <= price["limit"])), None)


def price_said(price, role, kept="the best"):
    """What `role` keeps where it holds `price` (price_held): `kept` up to its limit in the unit
    it was kept in, whatever `u` counts in, to two decimals or every figure it has where it has
    more, `the best up to $0.30 a build`; `the best, whatever it costs` with none."""
    if price["limit"] is None:
        return "the best, whatever it costs"
    exact = decimal.Decimal(repr(price["limit"]))
    cost = f"{exact:.{max(2, -exact.as_tuple().exponent)}f}"
    share = price["cost_unit"] == "share"
    return f"{kept} up to " + UNITS["% of a week" if share else "$ a task"].format(
        cost=f"{cost}%" if share else f"${cost}", run=RUN[role])


class _Unjudged(Exception):
    """A seat's record no longer holds what a take was judged on (price_take)."""


def price_take(cfg, session, selected, providers, answer, role):
    """Where `role` of seat `session`, else of new seats, keeps a price that holds (price_held),
    the choice it takes in `answer` (price_fit), once that is not the row it uses, the owner's
    design of 5 Nov 2026: taken as ← and → take it
    (take_choice), its entry then naming the model and effort the role uses, its limit and unit
    as they were.  A seat's in one write of the record under its lock
    (roles_saved), only while that still holds the model, effort and entry judged here; else
    nothing is written, said or read again, the screen as stale as it is while another window
    saves.  A seat's orchestrator stays, as moving it moves the seat's own session: only ← or →
    does.  New seats' take into [defaults], their orchestrator's too, as no session moves with
    it, no open seat changing; the entry is then moved in whole (price_path), one that cannot be
    written saying why, the take standing and the role keeping no price.  What to say under the
    rows: the take, and why its entry was not written, or why it was refused; else ""."""
    if session is not None and role == "orchestrate":
        return ""
    used, found = matrix.uses(cfg, selected, answer)[role], answer[role]
    price = price_held(session, role, used, found)
    best = price and price_fit(cfg, found, price)
    if best is None or best is used[2]:
        return ""
    model, field = matrix.runner(cfg, best), PRICE_FIELDS[role]
    if session is None:
        note = take_choice(cfg, None, selected, providers, role, model, best["effort"], None)
        if note:
            return note
        name, effort, _ = matrix.uses(cfg, selected, answer)[role]
        try:
            _moved_in(price_path(role), json.dumps({**price, "model": name, "effort": effort}))
        except OSError as exc:
            note = f"state: {exc}"
    else:
        step = (model, config.ROLE_EFFORTS[matrix.CONFIG_ROLES[role]],
                _taken_at(cfg, model, best["effort"]))
        judged = []     # a record gone or renamed since is never judged: change_session finds none

        def taken(record, now):
            judged.append(record)
            if matrix.uses(now, record, answer)[role][:2] != used[:2] or record.get(field) != price:
                raise _Unjudged
            changed, why = orch.role_groups(now, record, providers, **{TAKEN[role]: [model]})
            if why:             # the model may have left the config: nothing to step
                return record, why
            changed = {**changed, "efforts": _stepped(now, changed, [step])}
            name, effort, _ = matrix.uses(now, changed, answer)[role]
            return {**changed, field: {**price, "model": name, "effort": effort}}, ""
        try:
            note = roles_saved(cfg, session, selected, taken)
        except _Unjudged:
            return ""
        if not judged:
            return ""
        if note:
            return note
    _, effort, _ = matrix.uses(cfg, selected, answer)[role]
    return "\n".join(filter(None, [
        f"{matrix.CONFIG_ROLES[role]} took {best['name']} {effort}, {price_said(price, role)}",
        note]))


def figures(value, many=2):
    """`value`, above 0, to `many` significant figures: `1,200`, `40`, `4.5`; to one, `0.004`."""
    value = float(f"{value:.{many}g}")
    return f"{value:,.{max(0, many - 1 - math.floor(math.log10(value)))}f}"


def cost_in(found, row, unit):
    """`row`'s cost in its role's answer `found` counted in `unit` (UNITS), rounded as the
    screen says it (cost_said), so a bar stands as tall as the number on its top (models_bars):
    a week to two significant figures, else to cents, to whole units from 100 on, where cents
    tell no two rows apart, so five bars' costs side by side fit 40 cells, and under half a
    cent to its first figure, where two decimals would say a model that costs something is
    free.  None where it has none: dollars, where no run's provider has a price
    (matrix._costs's `share`), and a week, where it has no `points` of one (matrix._costs)."""
    points = row["points"]
    value = {"$ a task": None if found["cost_unit"] == "share" else row["cost"],
             "% of a week": points, "a week": 100 / points if points else None}[unit]
    if value is None:
        return None
    if unit == "a week":
        return float(f"{value:.2g}")
    return (float(f"{value:.1g}") if 0 < value < .005 else
            round(value, 2 if round(value, 2) < 100 else 0))


def cost_said(found, row, unit):
    """`row`'s cost in its role's answer `found` as cost_in rounds it: `$0.60`, `2.00%`,
    `$0.004`, `50` a week.  `≈` before one no runs measured -- the owner, 3 Nov 2026: a cost on
    screen must never look more certain than it is.  `-` where it has none."""
    value = cost_in(found, row, unit)
    if value is None:
        return "-"
    about = "" if row["cost_rule"] == "measured" else "≈" if terminal.utf8() else "~"
    if unit == "a week":
        return about + figures(value)
    # under a cent, as no cents rounding leaves one, a cost cost_in took to its first figure
    cost = figures(value, 1) if 0 < value < .01 else f"{value:.{2 if value < 100 else 0}f}"
    return about + (f"{cost}%" if unit == "% of a week" else f"${cost}")


def models_said(cfg, answer, used, unit):
    """Each role's (role, row, what follows it) off `used` (matrix.uses): its quality and cost in
    `unit` (cost_said), else UNBOARDED, or UNMARKED for no model."""
    said = []
    for role, (name, effort, row) in used.items():
        if row is None:
            row = {"name": config.model_name(cfg, name) if name else UNMARKED,
                   "effort": None if effort == "none" else effort}
            after = UNBOARDED if name else ""
        else:
            after = (f"{row['quality']:.1f}", cost_said(answer[role], row, unit))
        said.append((role, row, after))
    return said


def named(row):
    """A row's model and its effort.  A board's name or a config's effort may hold control
    characters: none reaches the terminal (terminal.plain), each made plain on its own, so an
    escape one leaves open cannot take the other."""
    return " ".join(filter(None, (terminal.plain(row[key] or "") for key in ("name", "effort"))))


def packed(parts, gap, room):
    """`parts` on as few lines of `room` cells as hold them, `gap` between two on one line; a
    part too long for a line of its own goes on at its words (terminal.wrap), never past `room`,
    where the terminal would break it mid-word."""
    lines = []
    for part in parts:
        if lines and terminal.cells(lines[-1] + gap + part) <= room:
            lines[-1] += gap + part
        else:
            lines += terminal.wrap(part, room) if terminal.cells(part) > room else [part]
    return lines


def models_body(said, unit, at=None):
    """The models screen's lines and {line: (("row", role), [])}: per role (models_said) its
    word, its row and what follows, under `quality` and `unit` over the first with numbers,
    `at`'s highlighted (terminal.highlight).  A row too wide beside the words goes on the lines
    under its word, wrapped at its words, what follows it staying on the word's line, else on
    lines of its own under the model: a model is named in full (docs/cli-design.md)."""
    room = terminal.layout_width()
    word = max(terminal.cells(matrix.CONFIG_ROLES[role]) for role, *_ in said)
    numbers = [after for _, _, after in said if isinstance(after, tuple)]
    widths = [max(map(terminal.cells, column)) for column in zip(("quality", unit), *numbers)]

    def follows(after, space=math.inf):     # what follows a row, on lines of `space` cells
        if not isinstance(after, tuple):
            return [terminal.styled(line, "dim") for line in terminal.wrap(after, space)]
        line = f"{after[0]:>{widths[0]}}  {after[1]:>{widths[1]}}"
        if terminal.cells(line) <= space:
            return [line]
        # else the quality over the cost at one width, a part wider than `space` broken at its
        # spaces and thousands (`% of a` over `week`), else wherever it must: no line passes
        # the edge, where the terminal would wrap it into rows the page does not count
        width = max(1, min(max(widths), space))
        return [f"{piece:>{width}}" for part in after for broken in columned(part, width, " ,")
                for piece in terminal.wrap(broken, width)]
    models = [named(row) for _, row, *_ in said]
    full = max(map(terminal.cells, models))
    tail = max((2 + terminal.cells(line) for *_, after in said for line in follows(after)),
               default=0)
    wide = 2 + word + 2 + full + tail <= room
    column = 2 + word + (2 + full if wide else 0)      # where what follows a row begins
    beside = column + tail <= room      # else what follows takes lines of its own, two in
    column = column if beside else 2
    lines, places, headed = [], {}, False
    for (role, row, after), model in zip(said, models):
        if isinstance(after, tuple) and not headed:     # a role with no numbers heads nothing
            headed = True
            lines += [" " * (column + 2) + terminal.styled(line, "dim")
                      for line in follows(("quality", unit), room - column - 2)]
        lead = "  " + terminal.pad(matrix.CONFIG_ROLES[role], word)
        own = [lead + "  " + model] if wide else [
            lead, *("    " + part for part in columned(model, room - 4))]
        shown = ["  " + line for line in follows(after, room - column - 2)]
        if beside:
            own[0] += " " * (column - terminal.cells(own[0])) + "".join(shown)
        else:
            own += [" " * column + line for line in shown]
        for number, line in enumerate(own):
            places[len(lines)] = (("row", role), [])
            lines.append(terminal.highlight(line.rstrip(), number == 0) if role == at
                         else line.rstrip())
    return lines, places


# The bars, the owner's design of 5 Nov 2026: the tallest TALL cells high, a column WIDE cells
# wide, each at most
TALL, WIDE = 7, 12
COUNTS = ("no", "one", "two", "three", "four", "five")      # up to matrix.PLACES
EIGHTHS = " ▁▂▃▄▅▆▇"     # a bar's top, the eighths of a cell it fills
# a bar's glyphs, by whether the terminal takes UTF-8: a choice's, the rest's, under the row used
GLYPHS = {True: "█░━", False: "#:="}


def columned(text, room, after=" -."):
    """`text` on lines of `room` cells, never cut (docs/cli-design.md): wrapped at its spaces, a
    word wider than a line broken after each hyphen in it, a part still wider after each dot
    (`Acme-` over `7.1`, a version kept whole where it can be), and a part with neither left
    whole, wider than `room`, as models_bars widens its column to it; `text` plain, as a board's
    name may hold control characters (terminal.plain).

    A part wider than the screen wraps there, off the rows this page counts: left so.  Of the
    boards' 128 names on 18 Nov 2026 the widest such part is 11 cells, a screen is 40 and
    wider, and cutting inside one failed three reviews on which glyphs may part (run
    20261118-1126): a name nobody has is not served."""
    text = terminal.plain(text)
    if terminal.cells(text) <= room or not after:
        return [text]
    lines = []
    for part in filter(None, re.split(f"(?<={re.escape(after[0])})", text)):
        if lines and terminal.cells((lines[-1] + part).rstrip()) <= room:
            lines[-1] += part
        else:
            lines.append(part)
    return [piece for line in lines for piece in columned(line.rstrip(), room, after[1:])]


def models_standing(found, kept, unit):
    """The bars of an answer `found` (matrix.answer) that stand at the screen's width, the
    owner's design of 5 Nov 2026, as (size, rows, labels, words, widths): its choices, solid,
    then shaded `kept`, a row the role used, where it stands (`stands`), one more where the
    choices leave no place (the owner, 12 Nov 2026), then as many of its `others` that stand,
    best first, as fill matrix.PLACES.  `rows` (row, its glyph), cheapest first, on a tie the
    worse; each one's labels its cost in `unit`, quality and effort, its words its name and a
    shaded one's why led by its glyph, and its column as wide as those and `size`, its words
    columned.  Where a word too wide for its column widens it past the screen, fewer stand: the
    shaded ones go first, `kept` last, then the cheapest choices, as matrix._chosen keeps the
    costliest.  A why counts drawn or not, so the same bars stand at a width however tall the
    page, the why page's `shaded` among them."""
    width, choices, whys = terminal.layout_width(), found["choices"], found["whys"]
    solid, shade, _ = GLYPHS[terminal.utf8()]
    own = [kept] if stands(found, kept) else []
    shaded = [*own, *(row for row in found["others"] if row is not kept and stands(found, row))][
        :max(len(own), matrix.PLACES - len(choices))]
    while True:
        rows = sorted([(row, solid) for row in choices] + [(row, shade) for row in shaded],
                      key=lambda one: (one[0]["cost"], one[0]["quality"]))
        size = max(1, min(WIDE, (width - 2 * len(rows)) // max(1, len(rows))))
        labels = [(cost_said(found, row, unit), f"{row['quality']:.1f}", row["effort"] or "")
                  for row, _ in rows]
        words = [[row["name"], *([f"{shade} {whys[id(row)][0]}"] if fill == shade else [])]
                 for row, fill in rows]
        widths = [max(size, *map(terminal.cells, [*three, *(
            line for text in texts for line in columned(text, size))]))
                  for three, texts in zip(labels, words)]
        if sum(widths) + len(rows) - 1 <= width:      # one-cell gutters and no indent hold them
            return size, rows, labels, words, widths
        choices, shaded = (choices, shaded[:-1]) if shaded else (choices[1:], shaded)


def models_bars(found, role, used, kept, unit, room, marked=True, why=True, price=""):
    """`role`'s answer `found` (matrix.answer) drawn as bars under the role lines, the owner's
    design of 5 Nov 2026: under a heading counting them and ending with `price`, what the role
    keeps where it keeps one (models_screen), those that stand (models_standing), side by
    side, its cost in `unit` on its top (cost_said) and under it its quality, its name
    (columned) and its effort.  Each stands as tall as the number on its top over the largest
    shown (cost_in), in eighths of a cell, as tall as any carrying the same and never under one
    carrying a smaller, and one with `-` on its top, no number, the least a bar can.  A choice
    is solid, the rest shaded `░`, each `why` under it led by `░`, so one too short to show its
    shade still says it is one; `used`, the row the role uses, is in the accent colour, `━`
    under its name.  No axis line: the numbers say what the heights measure, as a shaded bar on
    the right is dearer, not better.  On a narrow screen the two-cell gutters, then the indent,
    give way to the labels.  The tallest stands as tall as the rest leave of `room` lines, TALL
    cells at most and one at least; `marked` false leaves the `━` out, `why` false the whys,
    their columns as wide."""
    utf8, width = terminal.utf8(), terminal.layout_width()
    solid, shade, mark = GLYPHS[utf8]
    size, rows, labels, words, widths = models_standing(found, kept, unit)
    shaded = sum(fill == shade for _, fill in rows)
    chosen = len(rows) - shaded
    gap = 2 if sum(widths) + 2 * len(rows) <= width else 1
    lead = max(0, min(2, width - sum(widths) - gap * (len(rows) - 1)))
    lines = ["", *("  " + line for line in packed([
        matrix.CONFIG_ROLES[role], f"{COUNTS[chosen]} choice{'s' * (chosen != 1)}",
        *([f"{COUNTS[shaded]} more shaded"] if shaded else []),
        *([price] if price else [])], terminal.separator(), width - 2))]
    unders = [[[quality], columned(name, wide) + [mark * size] * (marked and row is used),
               [effort], [line for text in whys if why for line in columned(text, wide)]]
              for (row, _), (_, quality, effort), (name, *whys), wide
              in zip(rows, labels, words, widths)]
    # the heading, the tallest's number over it and what stands under the bars take their lines
    taken = len(lines) + 1 + sum(max(map(len, part)) for part in zip(*unders))
    tall = max(1, min(TALL, room - taken))
    numbers = [cost_in(found, row, unit) for row, _ in rows]
    largest = max(filter(None, numbers), default=0) or 1
    # an eighth of a cell; a whole one without UTF-8, and on a shaded bar, as no glyph shades a
    # part of a cell: its top would stand solid on its shade
    steps = [1 if utf8 and fill == solid else 8 for _, fill in rows]
    # each number in turn, smallest first, at the coarsest step of the bars carrying it, so it
    # stands as tall on each and never under a smaller one, which a whole shaded cell may overtake
    heights, below = {}, 0
    for number in sorted(set(numbers) - {None}):
        step = max(one for one, its in zip(steps, numbers) if its == number)
        below = heights[number] = max(step, step * round(8 * tall * number / largest / step),
                                      -(-below // step) * step)
    stands = [step if number is None else heights[number] for number, step in zip(numbers, steps)]
    kinds, columns = [], []
    for (row, fill), (cost, *_), under, eighths in zip(rows, labels, unders, stands):
        kinds.append("accent" if row is used else None)
        top = -(-eighths // 8)
        columns.append([[cost if level == top + 1 else "" if level > top else
                         (fill if eighths >= 8 * level else EIGHTHS[eighths % 8]) * size
                         for level in range(tall + 1, 0, -1)], *under])

    def cell(text, wide, kind):       # spaced after its colour, so no line keeps trailing space
        spaces = " " * (wide - terminal.cells(text))
        return (terminal.styled(text, kind) if kind else text) + spaces
    for parts in zip(*columns):       # chart, quality, name, effort, why: each on the same lines
        deep = max(map(len, parts))
        for texts in zip(*(part + [""] * (deep - len(part)) for part in parts)):
            lines.append((" " * lead + (" " * gap).join(
                map(cell, texts, widths, kinds))).rstrip())
    return lines


def models_read(compared, total, fetched):
    """How many of your companies' `total` models are `compared`, and when the boards were read."""
    read = time.localtime(fetched or 0)
    every = len(compared) == total
    parts = [f"comparing {'all' if every else f'{len(compared)} of'} {total} models",
             *(["boards read " + time.strftime("%H:%M" if read[:3] == time.localtime()[:3]
                                               else "%d %b %H:%M", read)] if fetched else [])]
    return ["  " + terminal.styled(part, "dim")
            for part in packed(parts, terminal.separator(), terminal.layout_width() - 2)]


def number(count):
    """`count` as a word under ten, else in digits."""
    return NUMBERS[count] if count < len(NUMBERS) else str(count)


def points(count):
    """`count` quality points in words: `a point`, `two points`."""
    return "a point" if count == 1 else f"{number(count)} points"


def scored(column, one):
    """A measure's evaluation, and how a row scored there where the score is not its own."""
    return MEASURES[column] + (f" carried from {one['from']}" if one["how"] == "carried" else
                               " no score, counted as its worst" if one["how"] == "missing"
                               else "")


def flowed(parts, room, hang=0):
    """`parts` three cells apart on lines of `room` cells, each going on at its words beside the
    one before it and the rest under the first, `hang` cells further in where that leaves a line
    a cell, a word too long for the line it starts split there (terminal.wrap), its pieces
    joined by nothing: a release's name split mid-version reads as that version."""
    lines, hang = [""], min(hang, room - 1)
    for part in parts:
        gap = "   " if lines[-1] else ""
        for word in terminal.plain(part).split():
            if lines[-1] and terminal.cells(lines[-1] + gap + word) > room:
                lines.append(" " * hang)
                gap = ""
            head, *rest = terminal.wrap(word, room - terminal.cells(lines[-1] + gap))
            lines[-1] += gap + head
            lines += [" " * hang + piece for piece in terminal.wrap("".join(rest), room - hang)]
            gap = " "
    return lines


def plans_checked(cfg, provider):
    """(plan, checks) of each plan of `provider`'s logins, in the order the config lists them,
    as a screen names it, and the days of its week usage.plan_checks checked: one plan once, as
    each of its logins is checked on the same week, of whichever the usage cache (usage.held)
    holds, none while it holds none of them; a login whose plan is not known names none."""
    held = usage.held(cfg)
    # the usual login by its name: the cache keys it None until the config lists accounts and
    # it next reads them, the config by name once it lists them, and either may be first
    checked = {account or config.DEFAULT_ACCOUNT: checks for account, checks in (
        usage.plan_checks(cfg, {provider: held[provider]}, time.time())[provider].items()
        if provider in held else ())}
    plans = {}
    for account in config.accounts(cfg, provider) or [config.DEFAULT_ACCOUNT]:
        plan = logins.whose(provider, account)[1]
        if plan:
            plan = harness_plugin(logins.harness(cfg, provider)).plan_name(plan)
            plans[plan] = plans.get(plan) or checked.get(account, [])
    return list(plans.items())


def week_checked(plan, checks):
    """How far off `plan`'s week foretold its meter on the days `checks` (usage.plan_checks): the
    points it foretold for them against those the meter rose, as a share of what it rose."""
    if not checks:
        return f"{plan}'s week: no day checked yet"
    rose, foretold = (sum(check[key] for check in checks) for key in ("rose", "predicted"))
    off = 100 * (foretold - rose) / rose
    return (f"{plan}'s week, checked on {len(checks)} day{'s' * (len(checks) != 1)}: it "
            f"foretold {foretold:.0f} points where its meter rose {rose:.0f}, {abs(off):.0f}% "
            f"{'high' if off >= 0 else 'low'}")


def models_why(found, role, row, kept, unit, weeks, runs):
    """The why of `row` of `role`'s answer `found` (matrix.answer), the owner's design of 5 Nov
    2026: a label column, each value going on at its words in its own (flowed), an other's lines
    after its first two cells further in, so each other's first line stands out.  Its quality,
    give or take 1.96 standard errors, the measures that scored it and how far below the role's
    best choice it is, else, with no choice, the best compared (`best`), none where the role
    rates no row of a release compared, and, where `runs`, the effort a step to it writes (None
    for a row no step is), is another than one it was rated at, both, the owner's choice of 20
    Nov 2026, its bars and the role lines keeping the one rated (left so 21 Nov 2026); its cost
    in `unit`, said as UNITS says it, where that comes from (SOURCES) and how far off each of
    `weeks` foretold (week_checked); the rule that makes the choices; and why each model is none (WHYS):
    under `shaded` each the bars of `kept` draw shaded at this width (models_standing), in their
    order, under `not shown` the rest of its `others`, in theirs, then each release it rates no
    row of by name (`unrated`), in its order, and why (UNRATED); a page leaving its values no
    cell beside it folds each under its label, two cells in.  The page's margin and that fold are
    two cells where that leaves a line a cell, else as many as do.  A model's name goes on at its
    words as any value does, never cut: releases of one name differ only at its end.  A row no
    board rates, the role line's own for a model no row is (models_said), has neither quality
    nor cost: its page is the rule and the whys."""
    margin = min(2, terminal.layout_width() - 1)
    room = terminal.layout_width() - margin
    width = terminal.cells("not shown")     # the design's label column: its widest label
    fold = room - width - 2 < 1
    indent = min(2, room - 1) if fold else width + 2       # the cells before a value
    values = room - indent
    # the best choice, else, with nothing compared to take, the best compared: never a row of a
    # company not added or turned off, the owner, 5 Nov 2026: "I dont want others to be shown"
    top = max(found["choices"], key=lambda one: one["quality"], default=found["best"])
    best = "the best of these choices" if found["choices"] else "the best of the models on"

    def below(one):       # of the qualities as shown: 98.46 and 94.04 read 98.5, 94.0 and 4.5
        return round(top["quality"], 1) - round(one["quality"], 1)

    def priced(one):      # a row with no cost, its quality alone
        return f"{named(one)}, {one['quality']:.1f}" + (
            f" for {cost_said(found, one, unit)}" if one["cost"] is not None else "")

    def why(one):
        word, by = found["whys"][id(one)]
        return f"{priced(one)}: " + WHYS[word].format(
            by=by and priced(by), apart=points(matrix.APART), below=f"{below(one):.1f}",
            places=number(matrix.PLACES))

    def rating():         # its quality and cost
        measures = {column: one for column, *_ in quality.ROLES[role]
                    for one in [row["measures"].get(column)] if one}
        counted = sum(one["how"] != "missing" for one in measures.values())
        behind, cost = top and below(row), cost_said(found, row, unit)
        return [{"quality": [[f"{row['quality']:.1f}", f"give or take {1.96 * row['se']:.1f}, "
                                                       f"from {number(counted)} benchmarks"],
                             [", ".join(scored(column, one) for column, one in measures.items())],
                             *([[best]] if row is top else [] if top is None else
                               [[f"{abs(behind):.1f} {'below' if behind >= 0 else 'above'} the "
                                 f"best, {named(top)}"]]),
                             *([[f"rated at {row['effort']}, runs at {runs}"]]
                               if row["effort"] and runs not in (None, row["effort"]) else [])]},
                {"cost": [[UNITS[unit].format(cost=cost, run=RUN[role]) if cost != "-" else cost,
                           SOURCES[row["cost_rule"]].format(runs=row["runs"], run=RUN[role])],
                          *([week_checked(*week)] for week in weeks)]
                         if row["cost"] is not None else [["no cost"]]}]
    # the bars with a why are the shaded ones; a kind with none goes unsaid
    bars = [one for one, _ in models_standing(found, kept, unit)[1]]
    drawn = {id(one) for one in bars}
    kinds = {label: whys for label, whys in [
        ("shaded", [[why(one)] for one in bars if id(one) in found["whys"]]),
        ("not shown", [[why(one)] for one in found["others"] if id(one) not in drawn] + [
            [f"{terminal.plain(name)}: " + UNRATED.format(fewest=number(quality.FEWEST))]
            for name in found["unrated"]])] if whys}
    said = [*(rating() if "quality" in row else []),
            {"choices": [[f"the best, then cheaper ones {points(matrix.APART)} apart, none more "
                          f"than {number(matrix.WINDOW)} below, {number(matrix.PLACES)} at most"]],
             **kinds}]
    lines = terminal.wrap(f"why {named(row)} {DOES[role]}", room)
    for block in said:
        lines.append("")
        for label, parts in block.items():
            hang = 2 * (label in kinds)
            flowing = [line for part in parts for line in flowed(part, values, hang)]
            if fold:
                lines += terminal.wrap(label, room) + [" " * indent + line for line in flowing]
            else:
                lines += [f"{terminal.pad(label if n == 0 else '', width)}  {line}"
                          for n, line in enumerate(flowing)]
    return [" " * margin + line if line else line for line in lines]


@terminal.clicks_its_own
def models_screen(cfg, session, selected, providers):
    """`r recommended` on `c`, `config · recommended · <seat>` or `· new seats`: what each role
    of `selected` uses (models_body), the bars of the highlighted role (models_bars) as tall as
    the page leaves room for, over models_read until Esc, the boards read as it opens
    (matrix.refresh), its first answer made under `c` as drawn, its header naming what that
    reads (terminal.doing); a page too short for one-cell bars sheds what gives way, then is cut
    from its bottom (matrix_key).  ↑/↓ move the highlight, and ← and → take the next cheaper or
    better choice for its role at once (next_choice, take_choice), keeping the price it stopped at
    (keep_price), which its bars' heading says while it holds (price_held), the owner's design
    of 5 Nov 2026, `no choice` up to a limit no choice costs as little as (price_fit), as the
    role then stays; the last row a role was shown using that is no choice staying one of its bars
    and steps; each answer made (opening, the boards landing, `p`) takes the best up to each
    price that holds (price_take), saying so under the rows.  ⏎ or a click opens the why
    (models_why) of the row the role uses, else of its first choice, else of its first other
    (matrix.answer: every release compared it rates is a choice or an other), else, where it
    rates no row of one (`unrated`), of its role line's (models_said), at once, drawn again
    with its plans' weeks (plans_checked) once they land off the drawing thread.  `p` lists
    companies (company_list), and `u` counts every cost in the next unit (next_unit), the screen
    opening in the last one (models_unit).  The why comes up as a page does."""
    fetch, answer = Fetch(lambda: matrix.refresh(cfg)), None
    here, top, note, kept, unit = ("row", "orchestrate"), 0, "", {}, models_unit()
    title = f"config · recommended · {session or NEW_SEATS}"
    clock, rows = motion.Clock(page=True), [("row", role) for role in quality.ROLES]
    if terminal.taken():      # seconds on a home with months of runs, no key read meanwhile
        terminal.doing("config · recommended · reading what your runs cost")
    while True:
        if fetch is not None and not fetch.is_alive():
            try:                      # a board that failed answers with its error, kept a day
                failed = "; ".join(f"{name} {board['error']}" for name, board
                                   in fetch.answer()[0].items() if board.get("error"))
            except Exception as exc:      # noqa: BLE001 -- what stands is shown, the fault said
                failed = " ".join(str(exc).split()) or type(exc).__name__
            note = f"the boards were not read: {failed}" if failed else note
            fetch, answer = None, None
        if answer is None:        # counted, answered and dated off one read of the boards
            reading, fetched = matrix.dated()
            compared, total = matrix.compared(cfg, reading), len(matrix.ours(cfg, reading))
            answer = matrix.answer(reading[0], compared, cfg=cfg)
            note = "\n".join(filter(None, [note, *(price_take(
                cfg, session, selected, providers, answer, role) for role in answer)]))
        # a take changes what each role uses, never the answer, which takes seconds to price
        used = matrix.uses(cfg, selected, answer)
        kept.update({role: one[:2] for role, one in used.items()
                     if stands(answer[role], one[2])})
        # the row each role kept, else the one it uses, of the answer as it stands: `p` and the
        # boards landing make it anew
        own = {**used, **{role: (name, effort, matrix.row_of(answer[role]["rated"],
                                                             cfg["models"][name], effort))
                          for role, (name, effort) in kept.items()}}
        said = models_said(cfg, answer, used, unit)
        cheaper, better = ("←", "→") if terminal.utf8() else ("<", ">")
        keys = terminal.keys(f"{cheaper} cheaper", f"better {better}", "p models", "u unit",
                             "esc back", enter="why", move=("role",))

        def laid(under, keys):    # (over, role lines, places) at this draw's size, `here` lit
            # the heading, the line that is no role's, wherever a role with no numbers leaves
            # it, stays over the role lines where a page too short for every role follows the
            # highlight (matrix_page), the screen's and a card's: its numbers never stand unnamed
            # while it leaves the page a line, else it scrolls with them, as the frame outgrowing
            # the terminal would scroll the header off
            lines, places = models_body(said, unit, None if terminal.away() else here[1])
            over = [line for number, line in enumerate(lines) if number not in places]
            if page_room(under, keys, over) < 1:
                return [], lines, places
            return over, [lines[number] for number in places], dict(enumerate(places.values()))
        over, body, places = laid(note_lines(note), keys)
        read = ["", *models_read(compared, total, fetched)]
        price = price_held(session, here[1], used[here[1]], answer[here[1]])
        # a limit leaving every choice out says so, as the role stays (price_take); none leaves
        # none out, keeping the best whatever runs
        price = price and (f"keeps {price_said(price, here[1])}" if price["limit"] is None
                           or price_fit(cfg, answer[here[1]], price)
                           else price_said(price, here[1], "no choice"))
        # where one-cell bars leave too little room these give way whole, in turn: the comparing
        # line, the `━` (the accent and the role's line still name the row in use), the whys
        for under, marked, why in ((read, True, True), ([], True, True), ([], False, True),
                                   ([], False, False)):
            room = page_room([*under, *note_lines(note)], keys, over) - len(body)
            bars = models_bars(answer[here[1]], here[1], used[here[1]][2], own[here[1]][2], unit,
                               room, marked, why, price)
            if len(bars) <= room:
                break
        act, here, _, top = matrix_key(title, body + bars, places, rows, here, top, note, keys,
                                       marks=0, under=under, over=over,
                                       clock=clock, began=fetch and fetch.began,
                                       going=fetch and fetch.is_alive)
        if act is None:
            continue                  # a resize, the pointer or the boards landing: drawn again
        note = ""

        def around(card, keys):   # the role lines the card leaves room for, the question under them
            over, lines, places = laid(card, keys)
            first, room = matrix_page(lines, places, here, top, card, keys, over)
            shown = [*over, *lines[first:first + room]]
            return framed(clock, title, [*shown, *card], len(shown), card, keys,
                          page_places(places, first, room, len(over)))
        ask = asking(clock, around, title=title)
        if act == "back":
            return
        if act in ("left", "right"):
            found = next_choice(cfg, answer[here[1]], used[here[1]][2], 1 if act == "right" else -1,
                                own[here[1]])
            if found:
                note = take_choice(cfg, session, selected, providers, here[1], *found, ask)
                if note == "":    # taken: `selected` may also hold another window's write since
                    note = keep_price(cfg, session, selected, answer, here[1], used[here[1]][2])
        elif act == "p":
            clock.forget()            # another screen: the models back from it are as they are
            note, answer = company_list(cfg, title), None
        elif act == "u":
            unit = next_unit(unit)
        elif act == "enter":
            role = here[1]
            # else, with releases it rates no row of to name, the role line's own of a model no
            # row is: never a page that would stay empty while the boards are first read
            row = used[role][2] or next(iter([*answer[role]["choices"], *answer[role]["others"], *(
                one for name, one, _ in said if name == role and answer[role]["unrated"])]), None)
            key, why, page = None, ("why",), 0    # every line one row: ↑/↓ turn its pages
            # its plans' weeks take seconds to read: the page is drawn without them till they land,
            # under a cost, which a row no board rates has none of
            weeks = []
            checking = Fetch(lambda name=row["provider"]: plans_checked(cfg, name)) if (
                row and "quality" in row) else None
            # the effort a step to it writes (take_choice), asked of it alone: None for a row no
            # step is, or one no take of which takes a model
            taken, level = (step_take(cfg, answer[role], own[role], row) if any(
                one is row for one in role_steps(answer[role], own[role])) else (None, None))
            runs = taken and _taken_at(cfg, taken, level)
            clock.forget()            # another screen: the models back from it are as they are
            opened = motion.Clock(page=True)      # the why comes up as a page of `c`'s does
            while row and key != "back":
                if checking and not checking.is_alive():
                    weeks, checking = checking.answer(), None
                lines = models_why(answer[role], role, row, own[role][2], unit, weeks, runs)
                key, _, _, page = matrix_key(title, lines, dict.fromkeys(range(len(lines)),
                                                                         (why, [])),
                                             [why], why, page, "", "esc back", clock=opened,
                                             began=checking and checking.began,
                                             going=checking and checking.is_alive)


ADD_COMPANY = ("row", "add")      # the company list's `+ add a company`, which a click opens
UNKNOWN = "unknown"     # the name the company lists give a maker the boards leave unnamed


def companies_listed(cfg):
    """Each company with a listed model (matrix.listed), strongest first as the lineup orders
    them, its listed models in that order, {maker: {slug: name}}; and your companies
    (matrix.companies) in their order (matrix.company_order)."""
    lineup, found = matrix.listed()
    makers, had = {}, matrix.companies(cfg, lineup)
    for row in lineup:
        if row["release"] in found:
            makers.setdefault(row["maker"], {})[row["release"]] = row["name"]
    return makers, [maker for maker in matrix.company_order(cfg, lineup) if maker in had]


def models_listed(cfg, yours, off):
    """`yours` saved as `companies` and the slugs `off` as `models_off` at once (_saved), so a
    first change writes the companies the config had.  What to say, or ""."""
    before = copy.deepcopy(cfg)
    cfg.update(companies=yours, models_off=sorted(off))
    if not off:
        del cfg["models_off"]
    return _saved(cfg, cfg, before)


def companies_body(makers, yours, off, at=None, column=0, moves=None):
    """The company list's lines and {line: (row, cells)}: each of `yours` with a listed model a
    line, its name, then each of those models (`makers`), `■` on in the accent, or `□` and dim
    where `off` holds it; where the width runs out they go on under the column where they
    began.  The keys' cell, `column` of the row `at` (its name 0), is lit (terminal.toggle).
    Last, `+ add a company`; each mark and its move (motion.toggled) goes on `moves`."""
    room, (on, out) = terminal.layout_width(), "■□" if terminal.utf8() else "#-"
    shown = [maker for maker in yours if maker in makers]
    label = max((terminal.cells(maker or UNKNOWN) for maker in shown), default=0)
    start = label + 4         # the models' first column: after a space, the name's cell and one
    lines, places = [], {}
    for maker in shown:
        row, parts = ("company", maker), [[" ", []]]
        texts = [(maker or UNKNOWN, None), *((f"{out if slug in off else on} "
                                              f"{terminal.cut(name, room - start - 2)}",
                                              "dim" if slug in off else "accent")
                                             for slug, name in makers[maker].items())]
        for number, (text, kind) in enumerate(texts):
            first, width = terminal.cells(parts[-1][0]) + 1, terminal.cells(text) + 2
            if number > 1 and first + width - 2 > room:      # its space after may go
                parts.append([" " * (start - 1), []])
                first = start
            parts[-1][0] += terminal.toggle(text, width, kind, row == at and number == column)
            parts[-1][0] += " " * (0 if number else label - terminal.cells(text))
            if number and moves is not None:      # its mark leads its text
                moves.append((len(lines) + len(parts) - 1, ("mark", maker, number), text[0],
                              motion.toggled(text[0], 3, kind, row == at, first)))
            parts[-1][1].append((first, first + width - 1, number))
        for number, (line, cells) in enumerate(parts):
            places[len(lines)] = (row, cells)
            lines.append(terminal.highlight(line.rstrip(), not number, band=False) if row == at
                         else line.rstrip())
    places[len(lines)] = (ADD_COMPANY, [])
    lines.append(terminal.highlight("  + add a company") if at == ADD_COMPANY
                 else "  + add a company")
    return lines, places


@terminal.clicks_its_own
def company_list(cfg, title):
    """`p` on the models screen, `<title> · models`: your companies (companies_body) over how
    many models are on (matrix.compared), from how many companies, and how many more have
    benchmark scores, until Esc.  ↑/↓ move between companies, ←/→ between a company's name and
    its models; Space or a click marks the model pointed at on or off, and on a name all its
    models on, or off where all are on, each change saved at once (models_listed).  `a`, or
    ⏎ or a click on `+ add a company`, adds one all on (company_add).  Esc drops each company
    left with none on from `companies`, and all its releases from `models_off`.  What to say,
    or "".  It comes up as a page does, its marks moving as `c`'s do (motion.Clock)."""
    title, here, column, top, note = f"{title} · models", None, 0, 0, ""
    clock = motion.Clock(page=True)
    while True:
        (makers, yours), room = companies_listed(cfg), terminal.layout_width()
        off, now = set(cfg.get("models_off") or ()), matrix.compared(cfg)
        rows = [*(("company", maker) for maker in yours if maker in makers), ADD_COMPANY]
        here = here if here in rows else rows[0]
        column = min(column, 0 if here == ADD_COMPANY else len(makers[here[1]]))
        giving = sum(bool(now & models.keys()) for models in makers.values())
        more = len(makers.keys() - set(yours))
        said = [f"{len(now)} model{'s' * (len(now) != 1)} on, from {giving} "
                f"{'company' if giving == 1 else 'companies'}",
                f"{more} more {'company has' if more == 1 else 'companies have'} "
                "benchmark scores"]
        moves, adding = [], here == ADD_COMPANY     # it opens a page: Enter's, not Space's
        body, places = companies_body(makers, yours, off, None if terminal.away() else here,
                                      column, moves)
        act, here, clicked, top = matrix_key(
            title, body, places, rows, here, top, note, terminal.keys(
                "a add a company", "esc back", space=None if adding else "mark",
                enter="add" if adding else None),
            marks=1 + max(map(len, makers.values()), default=0), keyed=column,
            clock=clock, moves=moves,
            over=[*("  " + part for part in terminal.wrap(
                "ak uses only the models that are on. Space marks one on or off, or, on a "
                "company's name, all of them. A company with none on leaves the list.",
                room - 2)), ""],
            under=["", *("  " + terminal.styled(part, "dim")
                         for part in packed(said, " · ", room - 2))])
        column = column if clicked is None else clicked
        if act is None:
            continue                  # a resize or the pointer: drawn again
        note, models = "", [] if here == ADD_COMPANY else list(makers[here[1]])
        if act == "back":
            # by the lineup's rows, so releases without a score go too, and a company it lacks stays
            lineup = matrix.listed()[0]
            gone = {row["maker"] for row in lineup
                    if row["maker"] in yours and not makers.get(row["maker"], {}).keys() - off}
            return models_listed(cfg, [maker for maker in yours if maker not in gone],
                                 off - {row["release"] for row in lineup if row["maker"] in gone}
                                 ) if gone else ""
        if act == "a" or act == "enter" and here == ADD_COMPANY:
            clock.forget()            # another screen: the list back from it is drawn as it is
            added = company_add(title, makers, yours)
            if added is not None:      # "", the maker the boards leave unnamed, is one
                note = models_listed(cfg, [*yours, added], off - makers[added].keys())
                here, column = ("company", added), 0
        elif act in ("left", "right"):
            column = max(0, min(column + (1 if act == "right" else -1), len(models)))
        elif act == "space" and models:
            # a model alone, or on a name all of its company's: all on turn off, else all on
            slugs = set(models if column == 0 else models[column - 1:column])
            note = models_listed(cfg, yours, off - slugs if off & slugs else off | slugs)


@terminal.clicks_its_own
def company_add(title, makers, yours):
    """`a` on the company list, `<title> · add a company`: each company of `makers` not among
    `yours`, strongest first, with how many listed models it has and its strongest, until ⏎ or
    a click picks one, or Esc goes back: that company, or None.  It comes up as a page does."""
    rows, here, top = [("row", maker) for maker in makers if maker not in yours], None, 0
    clock = motion.Clock(page=True)
    counts = {maker: f"{len(makers[maker])} model{'s' * (len(makers[maker]) != 1)}"
              for _, maker in rows}
    while True:
        here = here if here in rows else rows[0] if rows else None
        widths = [max(map(terminal.cells, texts), default=0)
                  for texts in ([maker or UNKNOWN for maker in counts], counts.values())]
        widths.append(max(1, terminal.layout_width() - 6 - sum(widths)))
        body = [terminal.table_row([maker or UNKNOWN, counts[maker],
                                    next(iter(makers[maker].values()))],
                                   widths, indent="  ") for _, maker in rows]
        body = [terminal.highlight(line) if row == here and not terminal.away() else line
                for row, line in zip(rows, body)]
        act, here, _, top = matrix_key(f"{title} · add a company", body, {
            line: (row, []) for line, row in enumerate(rows)}, rows, here, top, "",
            terminal.keys("esc back", enter="add", move=("company",)), marks=0, clock=clock)
        if act == "back" or act == "enter" and here:
            return None if act == "back" else here[1]


def config_columns(selected, name):
    """The cells the keys stop on along `name`'s row of `c`, in CONFIG_ORDER: each role's mark
    of `selected` and, where it is marked, that role's effort beside it; with no marks, the
    three efforts."""
    texts = orch.role_texts(selected, name, "●○■□") if selected else "●●●"
    return tuple(number for number in CONFIG_ORDER
                 if selected and number < 3 or number >= 3 and texts[number - 3] in "●■")


def config_body(cfg, at=None, column=0, selected=None, providers=None, moves=None, scope=None,
                rows=CONFIG_ROWS):
    """The `c` screen's lines, and where its rows sit on them: {line: (row, cells)}.

    Every offered model once, under its harness's name (model_heading), a line each: label,
    the three role marks of `selected` -- a session's record, whose missing reviewers are its
    workers -- each marked one followed by the effort the model runs that role at
    (config_columns): a cell for each level it offers, full up to it (terminal.effort_cells,
    effort_levels), then its word; a model with one effort is its word alone.  With no
    `selected`, only the three efforts.  `moves`, a list, is handed each mark's line, key,
    glyph and how it moves once flipped or refused (motion.toggled), and each effort's line,
    key, word and how its cells move once a step changed it (_effort_moves), for the clock.
    A model `providers` read as spent is dim.  Then `Models`,
    `Subscriptions`, `Discord`, `Done check`, `Machines`, `Limits` and `Money` with
    their values, unless `rows` is empty (a new session's screen).  A row is `("model", name)`
    or `("row", one of CONFIG_ROWS)`, so a model that
    happens to be called `Discord` is still a model; `at` is the highlighted one and `column`
    the cell on it the keys act on.  `cells` are a model row's (first, last, column), for a
    click, counted from 1 as the terminal counts: its marks and efforts, never its label, which
    a click acts on nothing of. Where the bars and fixed columns do not fit beside every whole
    name the bars give way, then the fixed columns, then the label, and where one cell of label
    still leaves the roles too little room each role folds onto a line of its own under the
    label, its head before it instead of over it.
    `scope`, whom the marks are for -- NEW_SEATS or a seat's name -- is the For line over the
    headings, and a seat's efforts are its record's (config.at_efforts).
    """
    cfg = config.at_efforts(cfg, selected)
    room, utf = terminal.layout_width(), terminal.utf8()
    marks = "●○■□" if utf else "*.x."
    names, models = config_models(cfg), cfg["models"]
    levels = {name: effort_levels(models[name], cfg) for name in names}
    efforts, levelled = {}, {}
    for name in names:
        entry, taken = models[name], levels[name]
        for number, key in enumerate(config.ROLE_EFFORTS.values(), 3):
            effort = efforts[name, number] = entry.get(key, entry.get("effort", "?"))
            levelled[name, number] = terminal.effort_cells(len(taken), taken.index(
                effort) + 1 if effort in taken else 0)
    shows = {name: config_columns(selected, name) for name in names}
    beside = [(name, number) for name in names for number in shows[name] if number >= 3]
    label = max(terminal.cells(config.model_name(cfg, name)) for name in names)
    word = max((terminal.cells(level) for taken in levels.values() for level in taken), default=0)

    def widths(tall, fixed):
        """Each role's mark (` ● `, a space before cells), then its effort column: `fixed`, as
        wide as the listed models' most cells and widest effort, so no mark or step moves it,
        else as wide as the efforts marked in it now; a shown one its model no longer takes
        widens it either way."""
        mark = (4 if tall else 3) if selected else 0
        lead = tall + 2 if tall else 0
        wide = {number: max([
            terminal.cells(head) - mark, lead + word if fixed else 0,
            *((lead if levelled[key] else 0) + terminal.cells(efforts[key])
              for key in beside if key[1] == number)])
            for number, head in enumerate(orch.ROLE_HEADS, 3)}
        return {**{number - 3: mark for number in wide if mark}, **wide}
    tall = max(map(len, levelled.values()), default=0)   # the cells, before every word
    # names win over places: the bars and fixed columns, else the fixed columns alone, else each
    # column only as wide as what is marked in it, the label cut to what is left
    for tall, fixed in ((tall, True), (0, True), (0, False)):
        width = widths(tall, fixed)
        if 2 + label + 6 + sum(width.values()) <= room:
            break
    # a barred model's word after the most cells any model has; one with no cells beside its mark
    leads = {key: "".join(cells) + " " * (tall + 2 - len(cells)) if tall and cells else ""
             for key, cells in levelled.items()}
    roles = 6 + sum(width.values())
    folded = 2 + 1 + roles > room
    label = min(label, max(1, room - 2 - (0 if folded else roles)))
    left = 2 + label                                        # the columns before the marks
    lines = [] if folded else [terminal.styled((" " * left + "".join(
        "  " + terminal.pad(head, width.get(number, 0) + width[number + 3])
        for number, head in enumerate(orch.ROLE_HEADS))).rstrip(), "dim")]
    head_width = max(1, min(max(map(terminal.cells, orch.ROLE_HEADS)), room - 4 - 2 - max(
        width.get(number, 0) + width[number + 3] for number in range(3))))   # a fold's heads
    places = {}
    if scope is not None:     # cut to the width, never `For`
        named = terminal.cut(scope, max(1, room - 7))
        lines.insert(0, "  " + terminal.styled("For  ", "dim") + terminal.styled(named, "bold"))
    for harness in dict.fromkeys(models[name]["harness"] for name in names):
        lines.append(model_heading(harness))
        for name in (name for name in names if models[name]["harness"] == harness):
            texts = orch.role_texts(selected, name, marks) if selected else ()
            note = orch.spent_note(cfg, name, providers) if providers else ""
            shown = model_label(cfg, name, label)
            line = "  " + (terminal.styled(shown, "dim") if note else shown) + " " * (
                label - terminal.cells(shown))
            cells, first, parts = [], left + 1, []
            for number in CONFIG_ORDER if selected else CONFIG_ORDER[1::2]:
                gap = 0 if selected and number >= 3 else 2      # a role's effort beside its mark
                if folded and gap:                              # a role starts its own line
                    parts.append((line, cells))
                    head = terminal.pad(orch.ROLE_HEADS[number % 3], head_width)
                    line, cells, first = "    " + terminal.styled(head, "dim"), [], 5 + head_width
                line, first = line + " " * gap, first + gap
                if number not in shows[name]:      # an open mark has no effort beside it
                    line, first = line + " " * width[number], first + width[number]
                    continue
                text = texts[number] if number < 3 else efforts[name, number]
                keyed = at == ("model", name) and number == column
                kind = ("dim" if note or text in (marks[1], marks[3])
                        else "accent" if number < 3 else None)
                if number >= 3:   # an effort is its cells and then its word, the keys' lit whole
                    lead = leads[name, number]
                    lead = terminal.styled(terminal.plain(lead, True), kind) if (
                        kind == "dim" and lead) else lead
                    text = lead + (terminal.styled(text, kind) if kind else text)
                    text = terminal.selected(text, 1, terminal.cells(text)) if keyed else text
                line += (terminal.toggle(text, width[number], kind, keyed) if number < 3 else
                         text + " " * (width[number] - terminal.cells(text)))
                if number < 3 and moves is not None:
                    moves.append((len(lines) + len(parts), ("mark", name, number), text,
                                  motion.toggled(text, width[number], kind,
                                                 at == ("model", name), first)))
                # a mark is its whole column; an effort is its own text, cells and all
                cells.append((first, first - 1 + (width[number] if number < 3
                                                  else terminal.cells(text)), number))
                if number >= 3 and moves is not None and len(levels[name]) > 1:
                    moves.append((len(lines) + len(parts), ("effort", name, number),
                                  efforts[name, number],
                                  _effort_moves(levels[name], efforts[name, number], kind,
                                                at == ("model", name),
                                                first + terminal.cells(leads[name, number]),
                                                first if leads[name, number] and not note
                                                else None)))
                first += width[number]
            for number, (part, cells) in enumerate([*parts, (line, cells)]):
                places[len(lines)] = (("model", name), cells)
                lines.append(terminal.highlight(part.rstrip(), number == 0, band=False)
                             if at == ("model", name) else part.rstrip())
    if not rows:
        return lines, places
    lines.append("")
    values = ("", "", discord_value(), done_check_value(cfg), machines_value(), limits_value(cfg),
              money_value(cfg))
    # the values line up past the widest row that has one
    wide = max(terminal.cells(row) for row in CONFIG_ROWS[2:])
    for row, value in zip(CONFIG_ROWS, values):
        # the value wraps at a word under itself, never cut
        for number, part in enumerate(terminal.wrap(value, room - 2 - wide - 2) or [""]):
            line = terminal.table_row([row if number == 0 else "", part],
                                      [wide, room - 2 - wide - 2], indent="  ",
                                      kinds=(None, "muted")) if value else (
                "  " + terminal.cut(row, room - 2))
            places[len(lines)] = (("row", row), [])
            lines.append(terminal.highlight(line, number == 0) if at == ("row", row) else line)
    return lines, places


def effort_levels(entry, cfg):
    """The efforts a model's bars count: config.efforts off the catalog `cfg`'s logins on its
    harness last listed (config.catalog_held), the one list a step on it walks (config_effort).  None where they
    cannot be read."""
    try:
        return config.efforts(entry.get("harness"), entry.get("model"),
                              lambda harness: config.catalog_held(harness, cfg))
    except config.Error:
        return []


def _effort_moves(levels, effort, kind, bright, word, cells):
    """How an effort's cells move on the `c` screen's clock once a step changed it to `effort`:
    each cell the step filled or emptied, where they stand from column `cells` (or None), takes
    its turn STAGGER seconds after the one nearer the effort before it (motion.filling); and a
    step onto the model's highest sends one light through the word from column `word`
    (motion.shimmering), `kind` and `bright` as the draw styled it.  A function of the clock,
    the screen row, when the step was and the effort before it."""
    def start(clock, row, since, before):
        was, filled = (levels.index(value) + 1 if value in levels else 0
                       for value in (before, effort))
        changed = range(min(was, filled), max(was, filled))
        for turn, n in enumerate((changed if filled > was else reversed(changed)) if cells
                                 else ()):
            clock.start([(row, cells + n)], *motion.filling(
                n < filled, since + turn * motion.STAGGER, bright))
        if effort == levels[-1]:
            clock.start([(row, word)], *motion.shimmering(effort, since, kind, bright))
    return start


def _saved(cfg, table, before, defaults=None):
    """config.save, `defaults` with it; "" when it held.  One that fails puts `table` back as
    `before`, so the screen, and the menu after it, go on with what the file holds, and says
    why.  The config `c` holds (_held) is written only over the file `c` last read or saved,
    under the config lock so no write lands between: over one another process changed since,
    whose change a whole write would take out, nothing is written, `table` goes back as it
    does for a save that fails, and Changed is raised."""
    global _held
    mine = _held[0] is cfg
    try:
        with config._config_lock():
            if mine and config_mark() != _held[1]:
                table.clear()
                table.update(before)
                raise Changed
            config.save(cfg, defaults)
            if mine:
                _held = cfg, config_mark()
    except (config.Error, OSError) as exc:
        table.clear()
        table.update(before)
        return f"config: {exc}"
    return ""


def config_effort(cfg, name, step, wrap=False, role="orchestrator", to=None, seat=None,
                  hold=()):
    """`name`'s effort in `role` (config.role_effort: a worker's is the effort while its own
    key is unset) one step along that model's own efforts (config.efforts), never past either
    end unless `wrap` takes it round to the other, or onto the `to`-th of them, and saved, a
    `seat`'s (record, held) to what its page holds (held_over), else to new seats' entry; one
    set to an effort it does not take lands on its first, and a worker's stepped onto the
    effort itself is unset again (_follows), while the effort's own step moves no other key;
    `hold`'s keys stay at the efforts they stand at, one that followed the effort keeping it.
    The efforts are read `now`, off the catalog already in hand (config.catalog_now): a listing
    never stands between the key and its frame.  What to say under the matrix, or ""."""
    if seat and seat[0] is None:    # no record to hold a step over (for_selected)
        return "session: the seat's record will not read"
    entry, key = cfg["models"][name], config.ROLE_EFFORTS[role]
    try:
        levels = config.efforts(entry.get("harness"), entry.get("model"),
                                lambda harness: config.catalog_now(harness, cfg))
    except config.Error as exc:
        return f"config: {exc}"
    shown = config.at_efforts(cfg, held_over(cfg, *seat))["models"][name] if seat else entry
    current = shown.get(key, shown.get("effort"))
    at = to if to is not None else levels.index(current) + step if current in levels else 0
    at = at % len(levels) if wrap else at
    if not 0 <= at < len(levels) or levels[at] == current:
        return ""
    if seat:
        held = seat[1]
        was = held.pop((name, key), (current,))[0]
        if levels[at] != was:       # back where it began: the record's again, whatever it holds
            held[name, key] = was, levels[at]
        return ""
    before = dict(entry)
    _set_effort(entry, key, levels[at], hold)
    return _saved(cfg, entry, before)


def held_over(cfg, record, held):
    """Seat `record` as its page draws it, `held`, {(model, key): (the record's effort when that
    cell was first stepped, the one held)}, over it (_stepped)."""
    steps = _held_steps(cfg, held)
    return {**record, "efforts": _stepped(cfg, record, steps)} if steps else record


def _held_steps(cfg, held):
    return [(model, key, now) for (model, key), (_, now) in held.items() if model in cfg["models"]]


def apply_held(cfg, seat, held, ask, providers=None):
    """What a seat's page holds (held_over) applied once, then held no more, `seat` (name, record):
    the effort of the orchestrator its record names now as one move, asked first where that
    restarts it by `ask` (seat_effort), every other written at once (efforts_saved)."""
    name, record = seat
    steps = _held_steps(cfg, held) if name else []
    if name is None:    # a seat not made yet takes what its page draws (born_models)
        record.update(held_over(cfg, record, held))
    elif steps:         # a model another window picked since keeps its pick: no effort moves it
        seat_read(cfg, name, record)
    lead = [step for step in steps if step[:2] == (record["orchestrator"], "effort")]
    rest = [step for step in steps if step not in lead]
    said = [efforts_saved(cfg, name, record, rest)] if rest else []
    for model, _, effort in lead:
        said.append(seat_effort(cfg, name, record, model, effort, ask, providers=providers))
    held.clear()
    return "\n".join(filter(None, said))


def restart_asked(cfg, name, model, ask, effort=None):
    """What a seat's orchestrator move asks before restarting it: `ask` on the card, naming
    `restarting` in the header once `Restart` is picked."""
    return ask and (lambda kept: ask(
        (RESTART_ASK if effort else MOVE_ASK).format(
            name, config.model_name(cfg, model), effort),
        MOVE_MEANS[kept], "Restart", "restarting"))


def seat_effort(cfg, name, selected, model, effort, ask, providers=None):
    """Seat `name` moved to `model` with its orchestrator at `effort`, or at the one it runs
    `model` at for None, a restart once `Restart` is picked on the card `ask` asks on
    (asking), the owner's 24 Oct words about the orchestrator: "it should ask me to
    confirm. As this restarts the session."  The move alone writes the record
    (orch.switch_orchestrator), and `selected` then holds it as it is.  What to say under the
    rows, or ""; None where Restart was not picked."""
    note = orch.switch_orchestrator(cfg, name, model, providers=providers, effort=effort,
                                    asked=restart_asked(cfg, name, model, ask, effort))
    try:
        selected.update(config.load_session(cfg, name, required=False) or {})
    except (config.Error, OSError) as exc:
        return note or f"session: {exc}"
    return note


def _set_effort(entry, key, effort, hold=()):
    """`entry`'s `key` at `effort`, None being its own effort, a role's key that lands on the
    effort unset again (_follows); each key of `hold` that follows the effort keeps the one it
    followed, read off `entry` as it stands."""
    if "effort" in entry:
        entry.update(config.held_efforts(entry, hold))
    entry[key] = entry["effort"] if effort is None else effort
    _follows(entry, [key, *hold])


def _follows(entry, keys):
    """Each of `keys`, a role's effort key (config.ROLE_EFFORTS), that sits on the effort
    itself, or on no word (a catalog's `""`), is unset: `same`, it follows the effort again."""
    for key in keys:
        if key != "effort" and entry.get(key) in ("", entry.get("effort")):
            del entry[key]


def _nearest(effort, levels):
    """`effort` where `levels` hold it, else the one of them nearest it in EFFORT_RANK, the
    weaker of two as near; the first of them for a word the ranking does not know."""
    if effort in levels:
        return effort
    if effort not in EFFORT_RANK:
        return levels[0]
    return min(levels, key=lambda word: abs(EFFORT_RANK.index(word) - EFFORT_RANK.index(effort))
               if word in EFFORT_RANK else len(EFFORT_RANK))


def _offered(harness, *screen, provider=None, cfg=None):
    """Every model that harness's catalog lists for `provider`, its logins `cfg`'s
    subscriptions' there, asked while `screen` waits on it (`waited`), each with the efforts
    it is offered at (config.efforts), read off that listing without asking the catalog a
    second time.  A `<provider>/<model>` id is that provider's, the way OpenCode names every
    provider's models, and any other id is every provider's the harness runs."""
    listed = waited(lambda: config.catalog(harness, cfg), *screen,
                    doing=f"reading the models {harness} offers")
    return [dict(model, efforts=config.efforts(harness, model["id"], lambda _harness: listed))
            for model in listed
            if provider is None or model["id"].partition("/")[0] in (provider, model["id"])]


def config_meters(cfg, at=None, rows=None, moves=None):
    """The lines over the `c` screen's page, on every page, and where its meters are on them
    (meter_spots): each subscription's meter as the main screen draws it (`usage_lines`, of
    `rows` where read already), and under them a line that, while `at`, from 1, has the
    highlight, says what its cell has no room for (`usage_detail`), its meter lit as the pointer
    lights it there; none without a grid.  Each meter is one of `moves` where given, gliding to
    a new reading (`meter_moves`), the lines counted back from the page's first (matrix_key)."""
    rows, width = usage_rows(cfg) if rows is None else rows, terminal.layout_width()
    # one reading of the wall clock, so the meters at rest and each frame are of these cells
    now = time.time()
    ending, cells = login_notes(rows, now), usage_cells(cfg, now, rows)

    def drawn(cells):
        return usage_lines(cfg, width, lit=at, rows=rows, ending=ending, cells=cells)
    meters = drawn(cells)
    if not meters:
        return [], {}
    detail = "  " + usage_detail(cfg, at, width, now, rows, ending) if at else ""
    spots, first = meter_spots(width, len(rows), 0), -1 - len(meters)
    if moves is not None:
        moves += meter_moves(rows, cells, [first + line for line, (_, on) in spots.items()
                                           for _ in on],
                             lambda cells: dict(enumerate(drawn(cells), first)))
    return [*meters, detail], spots


def meters_led(meters, body, places, under, keys, moves=()):
    """The lines over the `c` screen's page and their places, its `body`, `places` and `moves`,
    as it draws them with `under` under the page: the meters (config_meters: their lines and
    places) over the page while they leave it LEAST rows, else its first lines, which scroll
    with it, so a short screen keeps its room for what is under the page."""
    over, spots = meters
    if matrix_page([], {}, None, 0, under, keys, over)[1] >= LEAST:
        return over, spots, body, places, list(moves)
    return [], {}, [*over, *body], {**spots, **{line + len(over): place for line, place
                                                in places.items()}}, [
        (line + len(over), *rest) for line, *rest in moves]


def page_room(under, keys, over=(), lead=None):
    """The lines a matrix screen has for its rows between `over` and `under`, lines of its own
    above and below them, and its key line: under 1 where those leave none."""
    return terminal.height() - 5 - len(terminal.key_line(keys, first=lead)) - len(under) - len(over)


def matrix_page(body, places, here, top, under, keys, over=(), lead=None, keyed=None):
    """The page of a matrix screen's rows that fits between `over` and `under` (page_room): (top,
    room), the first line of `body` shown and how many are.  `top` stays where it was while the
    page holds every line of `here`, or for a row taller than the page the line of its cell in
    column `keyed`, or with none any of its lines, else moves the least that makes it so, and
    never past the last page; a cell that is a row of its own (terminal.under) is on its line."""
    room = max(1, page_room(under, keys, over, lead))
    # A page too short for every row follows `here` rather than keep its top, which a review of
    # 7 Nov 2026 asked for: on 40×12 no layout of the models screen shows every role's line, so
    # a page kept at its top would hide the role the highlight moves to.
    drawn = [number for number, (row, cells) in places.items()
             if row == here or any(here in cell[3:] for cell in cells)] or [0]
    lo, hi = drawn[-1] - room + 1, drawn[0]       # the tops holding every line of the row
    if lo > hi:                                   # taller than the page: Space acts on `keyed`
        held = [number for number in drawn
                if any(cell[2] == keyed for cell in places[number][1])] or drawn
        lo, hi = held[0] - room + 1, held[-1]
    return max(0, min(max(top, lo), hi, len(body) - room)), room


def page_places(places, top, room, over=0):
    """A matrix screen's `places` on the `room` lines of its page from `top`, `over` lines above
    them, as terminal.frame takes them: each with which of its row's lines it is, counted from
    the row's first though the page starts past it, so a row taller than its page is known
    line by line wherever it is turned to (terminal.held).  A line of a row whose cells are on
    its others -- a model's name folded over its marks -- is on nothing, though they be off the
    page: a cell of the row over no column, so it is no band (terminal.under) and still the
    row's, the pointer's light going out as it comes under a still pointer (terminal.lit)."""
    celled = {row for row, cells in places.values() if cells}
    first = {places[line][0]: line for line in sorted(places, reverse=True)}
    return {over + line - top: (row, cells if cells or row not in celled else [(1, 0, None)],
                                0 if row is None else line - first[row])
            for line, (row, cells) in places.items() if top <= line < top + room}


def note_lines(note):
    """A matrix screen's `note`, dim lines of its own under a blank one; none for no note."""
    return ["", *(terminal.styled("  " + part, "dim") for line in note.splitlines()
                  for part in terminal.wrap(line, terminal.layout_width() - 2))] if note else []


def matrix_key(title, body, places, rows, here, top, note, keys, timeout=None, marks=2,
               began=None, going=None, clock=None, moves=(), under=(), over=(),
               over_places=None, lead=None, keyed=None):
    """One draw of a matrix screen and the key read on it: (act, here, column, top).

    The `c` screen and a project's feature switches are read this way: rows the highlight moves
    through, and on a row cells, one a column.  `places` is {line: (row, cells)}, each cell
    (first, last, column) counted from 1 as the terminal counts.  On a screen too short for
    every row the part the highlight is on is shown, `over` has lines of its own above it and
    `under`, then `note`, under it, whatever the height; `moves` counts `under`'s on after
    `body`'s, and `over_places` are `over`'s, each cell on a line a row of its own (a meter on
    `c`).  ↑/↓, k/j and the wheel move `here` through `rows`, turning the pages of a row
    taller than the page, as far as its cell in column `keyed` stays shown (matrix_page), before
    they leave it.  A click on a row
    makes it `here`, and one on a cell makes that the column, acting `space` on the first
    `marks` columns and, on another's, the cell of it clicked, from 0; `column` is None where
    no cell was clicked; a cell that only explains is none.  The pointer does the same and acts
    on nothing, the cell it is on lit.  `act` is `back` for Esc or a click on `esc back`, None when the screen wants drawing again -- a
    resize, the pointer, or `timeout` seconds with no key -- a character key's character, its
    key-line item's too (`r recommended`), and any other key's name, `enter` a click on `⏎`'s
    and `space` one on `␣`'s, `left` and `right` one on an arrow of `lead`, a page mark, or on
    a cell that is `left` or `right`.
    `began` says since when what `body` was read from was being fetched, or None, looked at
    before reading it, so one landing since is never missed; while `going()`, the rule under the
    header glides (`motion.fetching`) and the read ends, None, once it lands.
    `clock` moves what `moves` -- (line, key, value, start) -- says is news (`motion.Clock.look`)
    on the lines shown, `over`'s counted back from the page's first, -1 its last, each by `start(clock, row, since, before)`, its frames drawn while the
    key is waited for; a key, not the pointer, ends them on their last frames.
    """
    said = note_lines(note)
    below = [*under, *said]
    top, room = matrix_page(body, places, here, top, below, keys, over, lead, keyed)
    shown, first = body[top:top + room], 3 + len(over)     # the screen row of the page's first
    spots = terminal.frame(title, [*over, *shown, *under, *said], keys, first=lead, places={
        **(over_places or {}), **page_places(places, top, room, len(over))},
        drawn=clock and (lambda: clock.drawn(moves, lambda line: first + line if line < 0
                                             else first + line - top
                                             if top <= line < top + room else
                                             first + len(shown) + line - len(body)
                                             if line >= len(body) else None)))
    if began is not None:     # on the screen's own clock, so what else moves goes on with it
        clock = motion.fetching(clock or motion.Clock(), began)
    if clock is None or clock.wait() is None and began is None:    # nothing moves or lands
        key = terminal.read_key(timeout)
    else:
        key = moving(clock, timeout=timeout or TICK, going=going)
    if key is None:
        return None, here, None, top
    if clock is not None and key.name != "point":
        clock.settle()                # a key ends what moves on its last frame
    act, column = key.char if key.name == "char" else key.name, None
    if act in ("click", "point"):
        spot = terminal.under(key, spots)
        if spot.what is not None:
            here, column = spot.what, None if isinstance(spot.cell, tuple) else spot.cell
        if act == "point":
            return None, here, column, top
        if spot.what is None:         # a key-line item does what its key does
            item = {"esc": "back", "⏎": "enter", "␣": "space", "←": "left", "<": "left",
                    "→": "right", ">": "right"}.get(spot.cell, spot.cell or "")
            return (item if item in ("back", "enter", "space", "left", "right")
                    or len(item) == 1 and item.isalpha()
                    else ""), here, None, top
        act = "enter" if here[0] in ("row", "usage") else ""      # a row runs its step
        if column in ("left", "right"):
            act = column          # an arrow drawn on a row (config_page's step)
        elif column is not None:
            act = "space" if column < marks else key.col - spot.first
    if act in ("esc", "eof"):
        return "back", here, column, top
    step = terminal.step(key)
    if step and rows:
        mine = [line for line, (row, _) in places.items() if row == here]
        turned = matrix_page(body, places, here, top + step * room, below, keys, over, lead,
                             keyed)[0]
        if mine and (mine[-1] >= top + room if step > 0 else mine[0] < top) and turned != top:
            top = turned          # a row taller than the page: its next page before the next row
        else:
            here = rows[min(max(rows.index(here) + step, 0), len(rows) - 1)]
    return act, here, column, top


@terminal.clicks_its_own
def config_matrix(cfg, keyboard, version, session=None, selected=None, providers=None, note="",
                  fresh=False, born=False):
    """The `c` screen read with the keys until Esc; the config as it left it, each
    subscription's meter over its page (config_meters).  `born`, it is a new session's models
    screen instead (born_models): `selected` is the born row's own, each mark and effort changed
    there alone, for a seat not made yet; no row under the models, no `r` and no `a`; Enter on a
    mark or an effort starts the session, true, and Esc goes back to the row, false.

    `cfg` follows config.toml, whoever saves it (configured), and `selected` `session`'s record
    over it, both read again before each draw -- every second while waiting for a key -- on this
    thread so a read cannot land over a save; the highlight and column stay where they are while
    their row is.  The born row's screen keeps the row's config, its seat's to be made of.  A
    key whose save is refused over a file changed since (_saved) brings the owner back here from
    the page it was on, and says so under the rows (CHANGED); a page that cannot read the file,
    `Machines` reading it itself, brings them back saying why.
    Its role marks are that seat's models: Space or a
    click flips one (session_mark), the orchestrator moving the seat once asked, the roles saved
    to the record for the runs it launches next, the mark filling or emptying over two frames
    and one refused shaking (motion.toggled).  With no `session` the marks are new seats',
    [defaults], what the next `n` starts from (defaults_mark), no open seat changing till a
    `fresh` window's -- one over no seat -- `a` gives them to every one, once asked
    (apply_defaults).
    ↑/↓, k/j and the wheel move between rows and ←/→ between each mark and the effort beside a
    marked one (config_columns).  Space on an effort steps that role's alone up,
    from its highest round to its lowest, as a click on its
    word or the blank before it does, and a click on one of its cells takes that level: each
    change is saved where it is new seats' (config_effort), a seat's page holding it till it
    closes or a model is picked on it, which apply it first (apply_held), and drawn at
    once, each cell it fills lighting and each it empties dimming in turn, and a step onto
    the model's highest sends a light through its word (config_body, on the clock); nothing
    replays after another screen.
    A model's label takes no click: only its marks and efforts do.  `r`, or a click
    on `r recommended`, opens the models screen (models_screen), what each role uses for whom the
    marks are, where ← and → take a role's next cheaper or better choice for them.  Enter or a
    click on `Models` opens its page (models_page), and on `Subscriptions` its page
    (config_subscriptions), and on `Limits` its page (config_limits).
    ↑ past the first model, and the pointer, reach
    the meters over the page: one is lit as the main screen lights it, and Enter or a click
    opens its row on `Subscriptions` (config_subscriptions); on `Discord` its two
    secrets are typed on the same keys (config_discord).  agentkit's build, `version`, is read
    under the rows, dim, on every page.
    On a screen too short for every row the part the highlight is on is shown, and what the
    last key could not do -- a pair that cannot run, a switch, a save or a failed catalog -- has
    lines of its own under it, whatever the height, until the next key; `note` is said so
    before the first.  The worker token's date stands under the rows from TOKEN_WARN_DAYS out.
    """
    from . import watch   # here, not at the top: the menu draws without the tick
    standing = watch.token_standing() or ""     # a file's date, read once a visit
    title, scope, under, advice = ("new session", None, (), False) if born else (
        "config", session or NEW_SEATS, CONFIG_ROWS, bool(selected))
    seat = (session, selected) if session or born else None     # whose efforts a step changes
    held = {}         # what it holds of them till it closes (held_over)
    here, column, top, clock = None, 0, 0, motion.Clock(page=True)
    refused = {}      # what the last `a` said (apply_defaults), fitted under the rows each draw
    subs = []         # the subscriptions the meters were last drawn from
    global _held
    if not born:
        _held = cfg, NOT_READ
    while True:
        if not born:        # a file that will not load is tried each pass (holding)
            cfg = holding(cfg)
        if session and selected is not None:
            seat_read(cfg, session, selected)
        if not session and not born and selected is not None:   # a page or a save that took a
            selected.clear()                                     # model out moved them, and a
            selected.update(copy.deepcopy(cfg["defaults"]))      # role they dropped goes
        drawn, subs = subs, usage_rows(cfg)
        if here and here[0] == "usage":
            here = followed(here, drawn, subs)
        # the meter the highlight or the pointer is on, lit as the main screen lights one
        lit = here[1] if here and here[0] == "usage" and not terminal.away() else None
        moves = []
        over, meters = config_meters(cfg, lit, subs, moves)
        models = [*(("model", name) for name in config_models(cfg)),
                  *(("row", row) for row in under)]
        rows = [cell for _, cells in meters.values() for *_, cell in cells] + models
        here = here if here in rows else models[0]    # the highlight is the row itself
        columns = config_columns(selected, here[1]) if here[0] == "model" else ()
        if here[0] == "model" and column not in columns:      # no effort here: onto its mark
            column = column - 3 if column - 3 in columns else columns[0]
        opens = here[0] in ("row", "usage")     # else changed in place
        keys = terminal.keys(*([ADVICE_KEY] if advice else []),
                             *([APPLY_KEY] if fresh else []), "esc back",
                             space=None if opens else "mark" if column < 3 else "step",
                             enter="open" if opens else "start" if born else None)
        as_drawn = held_over(cfg, selected, held)
        body, places = config_body(cfg, None if terminal.away() else here, column,
                                   as_drawn, providers, moves, scope, under)
        # agentkit's build, read under the page so every page shows it, and what was said under it
        told = said_once("\n".join(filter(None, (f"Version {version or '?'}", note or standing))),
                         refused, page_room((), keys, over) - len(body))
        over, meters, body, places, moves = meters_led((over, meters), body, places,
                                                       note_lines(told), keys, moves)
        act, here, clicked, top = matrix_key(title, body, places, rows, here, top,
                                            told, keys, marks=3,
                                            timeout=None if born else STIR,
                                            clock=clock, moves=moves,
                                            over=over, over_places=meters, keyed=column)
        column = column if clicked is None else clicked
        if act is None:
            continue                  # a tick, a resize or the pointer: drawn again
        note, refused = "", {}

        def around(card, keys):   # the matrix laid out at this draw's size, the question under it
            over, meters, body, places, _ = meters_led(config_meters(cfg), *config_body(
                cfg, None if terminal.away() else here, column, as_drawn, providers, scope=scope,
                rows=under), card, keys)
            first, room = matrix_page(body, places, here, top, card, keys, over, keyed=column)
            shown = [*over, *body[first:first + room]]
            return framed(clock, title, [*shown, *card], len(shown), card, keys,
                          {**meters, **page_places(places, first, room, len(over))})
        ask = asking(clock, around, title=title)
        if act == "back" or born and act == "enter" and here[0] == "model":   # a meter opens
            # closing applies what the page holds; what that could not do keeps it open, said
            if not (note := seat and apply_held(cfg, seat, held, ask, providers)):
                return act == "enter" if born else cfg
            continue
        try:
            if act == "a" and fresh:
                refused = apply_defaults(cfg, ask, clock)
                continue
            if act == "r" and advice:     # a record that will not read has nobody to take it
                clock.forget()            # another screen: the matrix back from it replays nothing
                models_screen(cfg, session, selected, providers)
                continue
            if act == "enter" and opens:
                clock.forget()            # another screen: the matrix back from it replays nothing
            if here == ("row", CONFIG_ROWS[0]):
                if act == "enter":
                    models_page(cfg, keyboard)
            elif here[0] == "usage":
                if act == "enter":
                    note = config_subscriptions(cfg, keyboard, here[1])
            elif here == ("row", CONFIG_ROWS[1]):
                if act == "enter":
                    note = config_subscriptions(cfg, keyboard)
            elif here[0] == "row":
                if act == "enter":
                    if here == AUDIT:
                        config_audit(cfg)
                    elif here == DONE_CHECK:
                        config_done_check(cfg)
                    elif here == MACHINES:
                        config_machines(cfg)
                    elif here == LIMITS:
                        config_limits(cfg)
                    elif here == MONEY:
                        config_money(cfg)
                    else:
                        config_discord()
            elif act in ("left", "right"):
                at = columns.index(column) + (1 if act == "right" else -1)
                column = columns[min(max(at, 0), len(columns) - 1)]
            elif act == "space" and column < 3:
                # a pick applies what the page holds first, as closing does, what that could not
                # do refusing it; it flips the marks as drawn, and the orchestrator's own picks none
                # A mark is made at once and never held for the close: holding one failed review
                # four times over a config, login or record changing under the page, and the
                # owner, 21 Nov 2026, asked whether to drop it: "Keep marks instant".
                note = (held and (column or here[1] != selected["orchestrator"])
                        and apply_held(cfg, seat, held, ask, providers)) or (
                    session_mark(cfg, session, as_drawn, here[1], column, providers, ask)
                    if session else born_mark(cfg, selected, here[1], column, providers) if born
                    else defaults_mark(cfg, selected, here[1], column))
                if note:
                    clock.touch(("mark", here[1], column))    # refused: the mark shakes
            elif act == "space" or isinstance(act, int):     # a role's effort
                # a click on one of its cells takes that level, and one on its word, or the blank
                # before it, steps it on as Space does; the row's other efforts stay as they
                # are shown
                role, key = list(config.ROLE_EFFORTS.items())[column - 3]
                entry = config.at_efforts(cfg, as_drawn)["models"][here[1]]
                hold = [list(config.ROLE_EFFORTS.values())[number - 3] for number in
                        config_columns(selected, here[1]) if number >= 3 and number != column]
                lead = next((last - first + 1 for row, cells in places.values() if row == here
                             for first, last, at in cells if at == column), 0) - terminal.cells(
                    entry.get(key, entry.get("effort", "?")))
                page = seat and (selected, held)
                note = (config_effort(cfg, here[1], 0, to=act, role=role, seat=page, hold=hold)
                        if isinstance(act, int) and act < min(lead, len(effort_levels(entry, cfg)))
                        else config_effort(cfg, here[1], 1, wrap=True, role=role, seat=page,
                                           hold=hold))
        except Changed:     # the page it was made on closed; the next pass reads the file
            note = CHANGED
        except config.Error as exc:     # a page reading config.toml mid-edit closed, and why
            note = str(exc)


def _runs(cfg, harness, model, effort=None):
    """The names the config runs that harness's `model` under, at `effort` if one is given."""
    return [name for name, entry in cfg["models"].items() if isinstance(entry, dict)
            and (entry.get("harness"), entry.get("model")) == (harness, model)
            and effort in (None, entry.get("effort"))]


def _marked(names):    # the names a model or effort runs under already, after a tick
    return f"{terminal.glyph('done')} {', '.join(names)}" if names else ""


def _logs_in(takes):
    """What a provider with no login reads on a list: `sign in` where its harness says it
    `takes` an account's own, `API key` where a key, else `log in`."""
    return {"sign-in": "sign in", "key": "API key"}.get(takes, "log in")


def _through_choices(cfg, harness, listed, screen, offered=None):
    """`add a subscription`'s first list for `harness`, as OpenCode's own `/models` lists them:
    every model its catalog lists (_offered, or `offered` where read already) of a provider in
    `listed` with a mode, which it runs now, beside that provider's name; then each provider it
    lists with none, to log in to, by what it takes (_logs_in).  Each is ((harness, provider),
    the model, or None for a login) and the columns it shows, so typing a model's name after `/`
    finds it before a provider that shares it."""
    ready = {provider: name for provider, name, mode, _ in listed if mode}
    choices = []
    for model in (_offered(harness, *screen, cfg=cfg) if offered is None else offered):
        provider = model["id"].partition("/")[0]
        if provider in ready:
            choices.append((((harness, provider), model),
                            [model["label"], ready[provider],
                             _marked(_runs(cfg, harness, model["id"]))]))
    return choices + [(((harness, provider), None),
                       [name, "" if name == provider else provider, _logs_in(takes)])
                      for provider, name, mode, takes in listed if not mode]


def add_body(picked, choices, at, finding=None):
    """`add a subscription`'s lines, and the choice each list row is: {line: index}.

    Each step chosen so far on a line of its own -- `model  DeepSeek V4.1 · OpenCode` -- and under
    them the step being chosen, its name -- and `/` with what is being found in it, while
    `finding` -- then its choices in columns with `at` highlighted: the steps stack up as they
    are chosen.  On a phone a model's id gives way first, then its
    label, and its mark keeps up to half the row.
    """
    room = terminal.layout_width()
    wide = max(terminal.cells(step) for step in ADD_STEPS)
    lines = [f"  {terminal.pad(step, wide)}  "
             + terminal.cut(" · ".join(filter(None, texts[:2])), room - 4 - wide)
             for step, (_, texts) in zip(ADD_STEPS, picked)]
    lines.append(f"  {ADD_STEPS[len(picked)]}" + ("" if finding is None else f"  /{finding}"))
    columns = list(zip(*(texts for _, texts in choices)))
    widths = [max(map(terminal.cells, column)) for column in columns]
    left = room - 4 - 2 * max(0, len(columns) - 1)
    if len(columns) > 1:
        widths[-1] = min(widths[-1], left // 2)       # the mark keeps up to half the row
        left -= widths[-1]
    for number in range(len(columns) - (len(columns) > 1)):   # the label, then the id
        widths[number] = min(widths[number], max(0, left))
        left -= widths[number]
    places = {}
    for number, (_, texts) in enumerate(choices):
        line = terminal.table_row(texts, widths, indent="    ", kinds=(None, "dim", "dim"))
        places[len(lines)] = number
        lines.append(terminal.highlight(line) if number == at else line)
    return lines, places


@terminal.clicks_its_own
def config_add(cfg, keyboard, through):
    """`config · add a subscription · <through>`, for a harness that runs any provider it can
    log in to (config.provider_hosts): its first list is every model it runs now, then every
    provider it lists with no login (_through_choices).  One of those picked is logged in on
    `keyboard`'s terminal, given back for it, then asked for again, its first model
    highlighted once it has a mode.  The
    model goes in with its provider's table where the config has none: the shipped one where
    the shipped default has it, else that mode, read off what the harness prices its models;
    the model takes that mode as its own where its provider's table says another.

    ↑/↓, k/j and the wheel move, and Enter or a click picks
    a choice -- logs in to a provider, or opens the next step under it -- the key line naming
    which; Space does nothing but after `/`; Enter on an effort adds the model, named from
    its label (config.short_name), and saves.  A model the config runs already is marked, and
    can be added at another effort, never at one it runs it at.  Esc steps back one level, and
    out from the models raises Back.  Nothing is typed, so no model or effort the catalog does
    not offer is ever written.  The new model is offered as orchestrator and as worker at
    once, and holds no seat's role until it is marked there.  The name it was added under, or
    None.  It comes up as a page does.
    """
    picked, ats, top, note = [], [0], 0, ""   # (value, texts) of each step chosen; its highlight
    clock = motion.Clock(page=True)
    finding = None                    # typed after `/`: the open list shows only what holds it
    title = f"config · add a subscription · {config.provider_hosts().get(through, through)}"
    screen = (title, lambda: add_body(picked, [], 0)[0])
    listed = pending = None           # `through`'s providers, as (id, name, mode); one logged in
    while True:
        values = [*picked[0][0]] if picked else []    # (harness, provider), then the model
        try:
            if listed is None:
                listed = waited(lambda: config.listed_providers(through), *screen,
                                doing=f"asking {config.provider_hosts().get(through, through)} "
                                      "which providers it has")
            choices = (_through_choices(cfg, through, listed, screen) if not picked else [
                (effort, [effort, _marked(_runs(cfg, through, values[1]["id"], effort))])
                for effort in values[1]["efforts"]])
        except config.Error as exc:
            choices, note, listed = [], f"config: {exc}", listed or []
        except Back:                  # Esc while a list was asked: back one list
            if not picked:
                raise
            picked.pop()
            ats.pop()
            continue
        if pending and not picked:    # just logged in to: its first model, once it has a mode
            found = [number for number, (((_, provider), model), _) in enumerate(choices)
                     if provider == pending[0] and model]
            if found:
                ats[-1], finding = found[0], None
            else:
                ready = any(row[0] == pending[0] and row[2] for row in listed)
                note = (f"{pending[1]} {'lists no model' if ready else 'is not logged in'};"
                        " nothing added")
            pending = None
        if finding:
            choices = [choice for choice in choices
                       if finding.lower() in " ".join(choice[1]).lower()]
        if not choices and not note:
            note = (f"nothing here holds {finding}" if finding
                    else f"the {through} catalog names no model" if picked
                    else f"{through} lists no model or provider")
        adding = len(picked) == len(ADD_STEPS) - 1
        at = min(ats[-1], max(0, len(choices) - 1))
        keys = terminal.keys("esc back", enter=None if not choices else "add" if adding
                             else "log in" if choices[at][0][1] is None else "open")
        body, places = add_body(picked, choices, None if terminal.away() else at,
                                finding=finding)
        said = ["", *(terminal.styled("  " + part, "dim")
                      for part in terminal.wrap(note, terminal.layout_width() - 2))] if note else []
        room = max(1, terminal.height() - 5 - len(terminal.key_line(keys)) - len(said))
        if finding is None and len(body) > room:      # a list past the screen: find in it
            keys = keys.replace("   esc back", "   / find   esc back")
            room = max(1, terminal.height() - 5 - len(terminal.key_line(keys)) - len(said))
        drawn = next((line for line, number in places.items() if number == at), len(body) - 1)
        top = max(0, min(max(top, drawn - room + 1), drawn, len(body) - room))
        shown = body[top:top + room]
        spots = terminal.frame(title, shown + said, keys, places={
            line - top: (number, []) for line, number in places.items()
            if top <= line < top + room}, drawn=lambda: clock.drawn((), None))
        key = terminal.read_key() if clock.wait() is None else moving(clock)
        if key is None:
            continue                  # a resize, or a while with no key: drawn again
        spot = terminal.under(key, spots)
        if key.name == "point":
            ats[-1] = at if spot.what is None else spot.what     # the highlight on its choice
            continue
        clock.settle()                # a key ends its coming up on its last frame
        act, note = key.name, ""
        if act == "click":
            if spot.what is not None:
                at, act = spot.what, "enter"
            elif spot.cell == "esc":
                act = "esc"
        if act == "eof":
            return None
        if finding is not None and act in ("esc", "backspace", "char", "space"):
            # what is typed after `/` finds; Esc lets the whole list back
            finding = (None if act == "esc" else finding[:-1] if act == "backspace"
                       else finding + (key.char or " "))
            ats[-1] = 0
        elif act == "char" and key.char == "/" or spot.cell == "/":     # the key or `/ find`
            finding, ats[-1] = "", 0
        elif act == "esc":
            if not picked:
                raise Back
            picked.pop()
            ats.pop()
            finding = None
        elif terminal.step(key):
            ats[-1] = min(max(at + terminal.step(key), 0), max(0, len(choices) - 1))
        elif act == "enter" and choices:
            ats[-1] = at
            if not picked and choices[at][0][1] is None:     # a provider to log in to
                row = next(row for row in listed if row[0] == choices[at][0][0][1])
                clock.forget()        # the login's screen: the list back from it is as it is
                note = _adapter_verbs(keyboard, through, ("login",), row[1], provider=row[0])
                if not note:
                    config.forget_catalog(through)       # its models are listed now
                    listed, pending = None, row          # asked again, for its mode
                continue
            if not adding:
                picked.append(choices[at])
                ats.append(0)
                finding = None
                continue
            (harness, provider), model = values
            effort, taken = choices[at][0], _runs(cfg, harness, model["id"], choices[at][0])
            if taken:
                note = f"{', '.join(taken)} runs {model['id']} at {effort} already"
                continue
            name, before = config.short_name(cfg, model["label"]), copy.deepcopy(cfg)
            cfg["models"][name] = entry = config.model_entry(
                harness, model["id"], model["label"], effort=effort, provider=provider)
            config.take_in(cfg, entry, next(row for row in listed if row[0] == provider))
            note = _saved(cfg, cfg, before)
            if not note:
                return name


def _adapter_verbs(keyboard, harness, verbs, picked, account=None, provider=None, new=False):
    """Each of `verbs` of `harness`'s adapter (one with its words, `login again`), run as
    install.sh runs them, for `account`'s
    login when one is named and of `provider` when one is (config.provider_env), with the
    terminal given back for them, each said in one line as it starts, and taken again after.  The
    first that fails ends them, and waits until what it said has been read: what to say about
    it under the matrix, or "".  With `new`, `account` is a name no subscription lists yet, and
    one that fails first takes what the harness made for it with it (its adapter's `forget`):
    a login nobody lists is one nobody signs out, and ^C or a closed terminal can end that
    wait.  No verbs is nothing to run, and the terminal stays."""
    if not verbs:
        return ""
    keyboard.give()
    if sys.stdout.isatty() and os.environ.get("TERM", "dumb") != "dumb":
        # a screen of their own: the screen given back still shows the last sign-in's lines
        print("\033[2J\033[H", end="", flush=True)
    failed = ""
    for verb in verbs:
        # a harness can take seconds to draw its own screen, and a blank one reads as hung
        print(f"Installing {config.harness_name(harness)}…" if verb == "install"
              else f"Opening {config.harness_name(harness)} to log in…", flush=True)
        # ^C at a sign-in that waits on a code without taking the keys (codex's, grok's) reaches
        # the whole foreground group: it ends that sign-in, not the menu.  A handler, unlike
        # SIG_IGN, is not inherited by the harness.
        interrupt = signal.signal(signal.SIGINT, lambda *_: None)
        try:
            # an install is the menu's own and ends with it; a browser a sign-in opens is the
            # owner's, and outlives it (`owner`)
            env = config.child_env()
            code = subprocess.run([str(config.adapter(harness)), *verb.split()],
                                  env={**(owner.unmarked(env) if verb.startswith("login") else env),
                                       **config.account_env(account),
                                       **config.provider_env([provider] if provider else [])}
                                  ).returncode
            # a sign-in cut short can still exit 0 (codex 0.163's on ^C): it finished unless the
            # harness says it has no login for it now -- no answer lets it stand
            if not code and verb.startswith("login") and worker.auth_ok(
                    harness, seat=True, account=account, provider=provider)[0] is False:
                code = 1
        except (config.Error, OSError) as exc:
            print(f"{harness}: {exc}")
            code = 1
        finally:
            signal.signal(signal.SIGINT, interrupt)
        if code:
            failed = f"{config.harness_name(harness)} {verb} did not finish; {picked} is not added"
            if new:
                try:
                    subprocess.run([str(config.adapter(harness)), "forget"],
                                   env={**config.child_env(), **config.account_env(account)},
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
                except (config.Error, OSError):
                    pass              # no adapter to run: nothing ran to make anything either
            pause()
            break
    keyboard.take()
    return failed


def sign_in(cfg, keyboard, picked):
    """`picked`'s login, its subscription as (provider, account, label), made afresh on the
    terminal, its `→ log in again` (`subscription_acts`): its harness's `login again`
    (`logins.harness`), and the menu back as soon as that ends, one that failed once what it
    said has been read.  One that finished is asked its end at once (`logins.renewed`), so the
    menu comes back with its meter grey.  What to say under the screen, or ""."""
    provider, account, label = picked
    if _adapter_verbs(keyboard, logins.harness(cfg, provider), ("login again",), label, account,
                      provider):
        return f"{label}'s sign-in did not finish"
    logins.renewed(cfg, provider, account or config.DEFAULT_ACCOUNT)
    return ""


def _add_subscription(cfg, keyboard, provider, listed, picked):
    """Another subscription of `provider`, `picked` being the name it will get: its harness's
    login, run on the terminal under the account name last in `listed`, new (_adapter_verbs),
    then `listed` as the provider's `accounts` -- the ones it had, `default` when it had none,
    and that name.  Its harness is its models' or, with none left, the shipped default's
    (config.provider_harnesses).  A login that fails adds nothing.  What to say under the
    matrix, or ""."""
    harnesses = config.provider_harnesses(cfg, provider)
    if not harnesses:
        return f"config: no model names a harness for [providers.{provider}]"
    failed = _adapter_verbs(keyboard, harnesses[0], ("login",), picked, listed[-1], provider,
                            new=True)
    if failed:
        return failed
    before = copy.deepcopy(cfg)
    cfg["providers"][provider]["accounts"] = listed
    return _saved(cfg, cfg, before)


@terminal.clicks_its_own
def config_add_provider(cfg, keyboard):
    """`+ add a subscription` on `c`, read as `Subscriptions` is: each company's name bold over
    what it adds (company_name), each row named as `Subscriptions` will name it once added, and
    Enter or a click adding it.  First one more subscription of each provider the config has, in
    the order `Subscriptions` lists them (`ChatGPT II`, config.account_label), which is only
    logged in and listed (_add_subscription), where its harness keeps more than one login
    (config.one_login); then each provider the shipped default has and the config has not, put
    in the way it ships, so nothing is typed; then `another provider` under each harness that
    runs any provider it can log in to (config.provider_hosts), standing in for those shipped on
    it: picked, it is installed where its program is missing, then `config_add` through it
    picks the provider, logs it in, and adds the model, Esc there coming back here.  Each is
    signed in under a new random account name (`fresh`), so its login starts empty and the
    owner picks the account signed in to; one that does not finish leaves nothing of it
    (_adapter_verbs).

    A new provider's harness, the shipped default's for it, is installed when its program is
    nowhere to be found, then logged in: each its adapter's own verb, run as install.sh runs
    them, with the terminal given back for it and taken again after.  Then its shipped
    [providers.*] table goes in, listing that one account,
    with the first model its harness's catalog lists (_offered),
    under the name and at the effort the shipped default gives that provider's first model --
    `spark`, and the effort or the nearest one it takes -- so a `usage_model` in that table
    names it.  It holds no seat's role until it is marked there.  Where a model of that name
    is here already nothing is installed or added, since the table would name that model
    instead.  A verb that fails adds nothing, and waits until what it said has been read.  Esc
    goes back with nothing done.  What to say under the matrix, or "".
    """
    shipped, hosts = config.shipped(), config.provider_hosts()
    # Random, never `default` nor the next free name: a login once on disk under either would
    # call the new subscription logged in, on an account nobody chose.
    fresh = os.urandom(3).hex()
    offers = []       # (company, row, what it adds), one row a company, as the page lists them
    for name in cfg["providers"]:
        harnesses = config.provider_harnesses(cfg, name)
        if harnesses and config.one_login(harnesses[0]):
            continue                  # _add_subscription's login would be refused
        listed = [*(config.accounts(cfg, name) or [config.DEFAULT_ACCOUNT]), fresh]
        offers.append((company_name(cfg, name), config.account_label({"providers": {name: {
            "name": config.provider_name(cfg, name), "accounts": listed}}}, name, fresh),
            ("more", name, listed)))
    offers += [(company_name(shipped, name), config.provider_name(shipped, name),
                ("new", name, None)) for name in shipped.get("providers") or {}
               if name not in cfg["providers"]
               and hosts.keys().isdisjoint(config.provider_harnesses(shipped, name))]
    offers += [(label, "another provider", ("through", harness, None))
               for harness, label in hosts.items()]
    rows, here, top = [("row", number) for number in range(len(offers))], ("row", 0), 0
    while True:       # Esc in a harness's list comes back here, that harness highlighted
        body, places, at = [], {}, None if terminal.away() else here
        room = terminal.layout_width()
        # wrapped, so a line the terminal would wrap never moves the next under another's place
        for number, (company, row, _) in enumerate(offers):
            body += [terminal.styled(part, "bold") for part in terminal.wrap(company, room)]
            for line, part in enumerate(terminal.wrap(row, room - 2)):
                places[len(body)] = (("row", number), [])
                body.append(terminal.highlight(f"  {part}", mark=not line)
                            if at == ("row", number) else f"  {part}")
        act, here, _, top = matrix_key("config · add a subscription", body, places, rows, here,
                                       top, "", terminal.keys("esc back", enter="add"))
        if act == "back":
            return ""
        if act != "enter" or not offers:
            continue
        _, picked, (kind, name, listed) = offers[here[1]]
        if kind != "through":
            break
        failed = _adapter_verbs(keyboard, name, () if config.harness_present(name)
                                else ("install",), picked)
        if not failed:
            try:
                config_add(cfg, keyboard, through=name)
            except Back:
                continue
        return failed
    if kind == "more":
        return _add_subscription(cfg, keyboard, name, listed, picked)
    try:
        harness, first = config.provider_harness(shipped, name)
    except config.Error as exc:
        return f"config: {exc}"
    if first in cfg["models"]:
        return f"{picked} adds its model as {first}, and a model has that name; nothing added"
    verbs = () if config.harness_present(harness) else ("install",)
    failed = _adapter_verbs(keyboard, harness, (*verbs, "login"), picked, fresh, name, new=True)
    if failed:
        return failed
    table = {**shipped["providers"][name], "accounts": [fresh]}
    try:              # its models are the ones its new login lists
        models = _offered(harness, "config · add a subscription", provider=name,
                          cfg={**cfg, "providers": {**cfg["providers"], name: table}})
    except Back:
        return ""                     # Esc while its catalog was asked: nothing added
    if not models:
        return f"the {harness} catalog names no model; {picked} is not added"
    model, before = models[0], copy.deepcopy(cfg)
    cfg["providers"][name] = table
    cfg["models"][first] = config.model_entry(
        harness, model["id"], model["label"],
        effort=_nearest(shipped["models"][first].get("effort"), model["efforts"]), provider=name)
    return _saved(cfg, cfg, before)


@terminal.clicks_its_own
def config_remove_provider(cfg, picked):
    """`− remove` under a row of `Subscriptions` (subscription_acts): `picked`, its subscription as
    (provider, account, label), `Remove <provider> and its models?` for its provider's last
    one, `Remove <subscription>?` for any other, the usual login too, asked under its name,
    `Keep` picked and Esc keeping it, `Remove` fading the card out (fade_out) before it goes.
    config.remove_provider takes a provider's table, its models and their places in
    [defaults], and with its table goes its meter; a subscription leaves only the provider's
    `accounts`.  Once saved, the subscription that went is signed out on this machine
    (_signed_out).  The last provider is refused without asking.  What to say under the
    screen, or "".
    """
    (name, account, label), title = picked, f"config · {picked[2]}"
    # a provider listing no subscription has its usual login alone
    last = len(config.accounts(cfg, name)) < 2
    if last and len(cfg["providers"]) < 2:
        return "the config needs one provider"
    shown = config.provider_name(cfg, name) if last else label
    question, means = REMOVE_PROVIDER_ASK if last else REMOVE_SUBSCRIPTION_ASK
    clock, leaving = motion.Clock(), []     # the page's own: the card on it comes up

    def asked(card, keys):
        top = framed(clock, title, card, 0, card, keys)
        leaving[:] = range(top, top + len(card))
        return top
    if not asking(clock, asked)(question.format(shown), means, "Remove"):
        return ""
    fade_out(clock, leaving)
    before, harness = copy.deepcopy(cfg), logins.harness(cfg, name)
    try:
        if last:
            config.remove_provider(cfg, name)
        else:
            cfg["providers"][name]["accounts"].remove(account)
    except (config.Error, OSError) as exc:
        return str(exc)
    # no `waited`: its Esc would drop what a sign-out that failed says
    return _saved(cfg, cfg, before) or _signed_out(harness, name, account, label)


def _signed_out(harness, provider, account, label):
    """`provider`'s subscription `account`, read `label`, signed out on this machine by
    `harness`'s adapter's `logout`.  What to say under the screen while it is still on it: the
    last line its adapter said, and the command that signs it out by hand, which names its
    account even when empty, as a seat's shell has one of its own; or ""."""
    env = {**config.account_env(account), **config.provider_env([provider])}
    try:
        done = subprocess.run([str(config.adapter(harness)), "logout"],
                              env={**config.child_env(), **env}, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if not done.returncode:
            return ""
        said = (done.stderr.strip().splitlines() or [""])[-1]
    except (config.Error, OSError) as exc:
        said = str(exc)
    by_hand = " ".join([*(f"{key}={shlex.quote(value)}" for key, value in env.items()),
                        shlex.quote(str(config.adapter_path(harness))), "logout"])
    return (f"{label}'s login is still on this machine{f' ({said})' if said else ''};"
            f" sign it out with {by_hand}")


@terminal.clicks_its_own
def config_spend_reset(cfg, picked, kind=None):
    """`→ spend a reset` on a subscription's row: one usage-limit reset spent,
    by hand, on `picked`, its subscription as (provider, account, label), of `kind` where its
    reading names kinds.  usage.replenish spends it where it still holds one and reads the
    meters back into the cache, so its meter shows the week that came back; Esc while it is
    spent lets it finish.  What to say under the matrix: its name, what its cell on the `ak`
    screen says now (`usage_cells`), what each cap its provider names has left (`scoped_notes`:
    a Fable reset leaves the week's cell as it was) and the resets still in hand (`in_hand`),
    `Acme · 60% left · Fable 100% left · 1 weekly, 2 Fable resets in hand`."""
    title = f"config · {picked[2]}"
    name, account, label = picked
    try:
        spent, _ = waited(lambda: usage.replenish(cfg, name, account=account, kind=kind), title,
                          doing=f"spending a {kind + ' ' if kind else ''}reset of {label}")
    except Back:
        return ""
    if not spent:
        return f"{label}: no reset was spent"
    rows = usage_rows(cfg)
    prov, said = next((row[2], cell[3]) for row, cell in zip(rows, usage_cells(cfg, rows=rows))
                      if cell[:2] == (name, label))
    week, _, readable = reading(cfg, name, prov, time.time())
    return " · ".join(filter(None, (label, said, *scoped_notes(cfg, name, readable, week)[0],
                                    in_hand(prov))))


def subscription_acts(cfg, keyboard, row, ends):
    """What subscription `row`, one of usage_rows', offers, as (text, act) each, an act what to
    say under the screen or "": `log in again` while its own login ends soon or has ended
    (`ends`, login_notes' as drawn), where its harness signs it in afresh (sign_in,
    config.signs_in_again), `spend a reset` while it holds one (config_spend_reset) -- where its reading names kinds,
    `spend a Fable reset` for each it can spend now, in its order -- and `remove`
    (config_remove_provider).  A login the tick finds logged out with no end recorded is told
    by its alert alone: that record is its harness's, which can carry several subscriptions."""
    name, label, prov, account = row
    # its label as usage_cells has it, which config_spend_reset reads its week back by
    picked = (name, account, label)
    harness = logins.harness(cfg, name)
    kinds = prov.get("reset_kinds")
    spends = [] if not in_hand(prov) else [None] if not kinds else [
        kind["kind"] for kind in kinds if kind.get("usable")]
    return [(act_text(text, kind), act) for text, kind, act, offers in (
        (SUBSCRIPTION_ACTS[0], None, lambda: sign_in(cfg, keyboard, picked),
         ends and harness and config.signs_in_again(harness, account)),
        *((SUBSCRIPTION_ACTS[1], kind, lambda kind=kind: config_spend_reset(cfg, picked, kind),
           True) for kind in spends),
        (SUBSCRIPTION_ACTS[2], None, lambda: config_remove_provider(cfg, picked), True))
        if offers]


# The owner chose this layout on 26 Oct 2026, so the details stay calm until pointed at.
@terminal.clicks_its_own
def config_subscriptions(cfg, keyboard, number=None):
    """`Subscriptions` on `c`: each subscription under its company (company_name), named bold as
    `c` names a harness, as the main screen draws it (usage_lines), then `+ add a subscription`
    (config_add_provider), opened on the row of subscription `number`, from 1 in `cfg`'s
    usage_rows order, as Enter or a click on its meter opens it, on the ak screen, `c` and a
    new seat's models alike, else on the first.  The row the keys or the pointer are on
    says its resets in hand beside its meter where there is room, and opens a dim line of its
    limit_notes but the resets in hand, where it has any, given way to its width as the line
    under its meter on the ak screen gives them (`fitting`), then a line: whose login it is and
    its plan (login_notes; one ending as ending_note says it, amber), resets with no room beside
    its meter, then its acts (subscription_acts), ←/→ or the pointer moving, Enter or a click
    running one, the key line naming it.  One an act adds is asked whose it is (logins.renewed),
    then pointed at.  It comes up as `c` does as it opens, and the pointed row's lines come up
    under it as the line under the menu's highlighted row does; back from what an act or an add
    drew, it is drawn as it is.  The act lit (`on`) is kept by what it is, so one going from under
    it lights nothing in its place, and is at rest while the pointer lights its row's own cell,
    the label, meter and share.  A meter glides to a new reading on its line as drawn here
    (`meter_moves`).

    Whichever screen opens it, it is made of config.toml read as it opens, `cfg` where that will
    not load, held as `c` holds it (holding), so a save over the file changed since writes nothing
    and closes the page; what was held before is held again after.  What to say under the
    screen back: CHANGED, or ""."""
    global _held
    # found by company and account, so a subscription added meanwhile moves it to no other's row
    whose = number and subscription(usage_rows(cfg)[number - 1])
    outer, _held = _held, (cfg, NOT_READ)
    try:
        return _subscriptions(holding(cfg), keyboard, whose)
    except Changed:
        return CHANGED
    finally:
        _held = outer


def _subscriptions(cfg, keyboard, whose):
    """config_subscriptions' page over `cfg`, read until Esc."""
    here = ("sub", next((number for number, sub in enumerate(usage_rows(cfg), 1)
                         if subscription(sub) == whose), 1))
    opened, on, top, said = None, None, 0, ""
    clock = motion.Clock(page=True)
    while True:
        subs, width = usage_rows(cfg), terminal.layout_width()
        ids = [*(("sub", number) for number in range(1, len(subs) + 1)), ("row", "add")]
        here = here if here in ids else ids[-1]      # its row removed: onto the last
        # a subscription's line, whichever row it is on now, opens lit as SUBSCRIPTION_ACTS says
        whose = subscription(subs[here[1] - 1]) if here[0] == "sub" else None
        if whose != opened:
            opened, on = whose, act_text(SUBSCRIPTION_ACTS[0])
        at = None if terminal.away() else here
        lit = at[1] if at and at[0] == "sub" else None
        # one reading of the wall clock, so the lines at rest and each frame are of these cells
        now = time.time()
        ending, cells = login_notes(subs, now), usage_cells(cfg, now, subs)

        def meters_at(cells):
            return usage_lines(cfg, width, rows=subs, ending=ending, columns=1, cells=cells)
        meters = meters_at(cells)
        drawn = meters or ["  " + label for _, label, _, _ in subs]
        # the lit row says its resets in hand beside its meter where its line at rest has room,
        # and in every other frame of a glide, one too wide for them the line at rest
        # (meter_moves)
        held = lit and in_hand(subs[lit - 1][2])
        beside = held and terminal.cells(f"{drawn[lit - 1]} · {held}") <= width

        def lined(number, line, said=beside):
            # login `number`'s line: lit, it has no band, Enter acting on its act, never the row
            tail = terminal.styled(" · ", "dim") + terminal.styled(held, "info") if said else ""
            return terminal.highlight(line + tail, band=False) if number == lit else line
        # its whole cell, a cell of its row, the pointer lights as any cell (-1, no act)
        own = [(*usage_cell(width, 0), -1)] if meters else []
        owned = terminal.pointer_spot().cell == -1      # the pointer on one, as last drawn
        body, places, acts, moves, spots = [], {}, {}, [], []
        for number, (sub, line) in enumerate(zip(subs, drawn), 1):
            name, _, prov, _ = sub
            if number == 1 or subs[number - 2][0] != name:
                body.append(terminal.styled(company_name(cfg, name), "bold"))
            # the row, all its line its own cell leaves, comes under the pointer to open its acts;
            # it has no band, its acts being what Enter and a click act on (terminal.under)
            row = [(1, width, None)]
            places[len(body)] = (("sub", number), [*own, *row])
            spots.append(len(body))
            body.append(lined(number, line))
            if number != lit:
                continue
            # its limits but the resets in hand, its row's to say, or with no room its login's line
            limits = fitting([(worth, note) for worth, note in
                              limit_notes(cfg, name, prov, now) if note != held],
                             width - 4)
            if limits:
                shown = "    " + terminal.styled(" · ".join(limits), "dim")
                places[len(body)] = (("sub", number), row)
                moves.append((len(body), ("opened",), lit, motion.fading(shown)))
                body.append(shown)
            # its acts, email and plan from the one read of the logins its meter was drawn by
            ends, email, plan = ending[number - 1]
            acts = dict(subscription_acts(cfg, keyboard, sub, ends))
            on = on if on in acts else None
            plan = harness_plugin(logins.harness(cfg, name)).plan_name(plan)
            kind = "amber" if ends else "dim"
            told = [(ending_note(email, ends) if ends else email, kind), (plan, kind),
                    (not beside and held, "info")]
            # the pointer on its own cell lights that, so its act is at rest: one thing lit
            for shown, spans in opened_line(told, list(acts), None if owned else on, width - 4):
                places[len(body)] = (("sub", number), [*spans, *row])
                moves.append((len(body), ("opened",), lit, motion.fading(shown)))
                body.append(shown)
        # seen with no line too, so the pointer coming back onto a row is news
        moves.append((0, ("opened",), lit, lambda *_: None))
        if meters:      # each gliding to a new reading on its line as drawn here
            moves += meter_moves(subs, cells, spots, lambda shown: {
                spot: lined(number, line, held if shown != cells else beside)
                for number, (spot, line) in enumerate(zip(spots, meters_at(shown)), 1)})
        body.append("")
        places[len(body)] = (("row", "add"), [])
        add = "  + add a subscription"
        body.append(terminal.highlight(add) if at == ("row", "add") else add)
        keys = terminal.keys("esc back", enter="open" if here[0] == "row" else act_word(on)
                             if on in acts else None)
        # every STIR as the main screen and `c`, so a reading that lands -- one just added --
        # shows, gliding there
        act, moved, clicked, top = matrix_key("config · subscriptions", body, places, ids, here,
                                              top, said, keys, timeout=STIR, marks=0,
                                              clock=clock, moves=moves)
        if clicked == -1:             # a subscription's own cell, lit by the pointer: no act
            clicked = None
        elif clicked is not None:
            on = list(acts)[clicked]
        here = moved
        if act is None:
            continue                  # a resize or the pointer: drawn again
        said = ""
        if act == "back":
            return ""
        if act in ("left", "right") and acts:
            texts, step = list(acts), 1 if act == "right" else -1
            on = texts[min(max(texts.index(on) + step, 0), len(texts) - 1) if on in acts else 0]
        elif (act == "enter" or clicked is not None) and (on in acts or here[0] == "row"):
            def signed(rows):     # a provider's only login is its usual one, listed or not
                return [(name, account or config.DEFAULT_ACCOUNT) for name, _, _, account in rows]
            before = signed(subs)
            clock.forget()            # a card or a sign-in: the page back is drawn as it is
            said = (acts[on]() if here[0] == "sub"
                    else config_add_provider(cfg, keyboard)) or ""
            after = signed(usage_rows(cfg))
            added = [number for number, login in enumerate(after, 1) if login not in before]
            for number in added:      # whose login it is, for its line
                logins.renewed(cfg, *after[number - 1])
            if added:
                here = ("sub", added[0])


def opened_line(told, texts, on, room):
    """The line a pointed row of `Subscriptions` opens: `told`'s parts, (text, kind) each, ` · `
    apart in dim whatever their kind, as the eye skips it, then `texts` three spaces apart, the one
    that is `on` lit with a cell before and after it (terminal.selected, bracketed with no colour),
    wrapped in `room` cells, never cut; each line with its texts' places, (first, last, index),
    from 1, as wide as one is lit."""
    room = max(1, room)
    said = []
    for text, ink in told:
        said += [(" · ", "dim")] * bool(said and text) + [(text, ink)] * bool(text)
    # wrapping keeps every other character in order: each in its part's colour, a space in the
    # colour before it
    inks, pieces = iter([ink for text, ink in said for char in text if not char.isspace()]), []
    for part in terminal.wrap("".join(text for text, _ in said), room):
        runs = [["dim", ""]]
        for char in part:
            ink = runs[-1][0] if char.isspace() else next(inks, "dim")
            runs += [[ink, ""]] * (runs[-1][0] != ink)
            runs[-1][1] += char
        pieces.append(("".join(terminal.styled(text, ink) for ink, text in runs), None))
    for index, text in enumerate(texts):
        pieces.append((f"[{text}]" if text == on and not terminal.colour_depth() else text,
                       index))
    lines, used = [("    ", [])], 0
    for shown, index in pieces:
        whole = terminal.cells(terminal.plain(shown))
        for part in (terminal.wrap(shown, room) if whole > room else [shown]):
            if used and used + 3 + whole + (index is not None) > room:  # an act's cell after it
                lines, used = [*lines, ("    ", [])], 0
            gap, wide = 3 if used else 0, terminal.cells(terminal.plain(part))
            if index is not None:   # its cell after it never past the line's end: lit there,
                # it would wrap and push every row under it off the place recorded for it
                lines[-1][1].append((4 + used + gap, min(5 + used + gap + wide, 4 + room), index))
            lines[-1] = (lines[-1][0] + " " * gap + part, lines[-1][1])
            used += gap + wide
    return [(next((terminal.selected(line, first, last) for first, last, index in cells
                   if texts[index] == on), line), cells) for line, cells in lines]


def page_body(rows, at=None, moves=None):
    """The lines of a page `c` opens and the row each is, {line: (row, cells)}: of `rows`,
    (row, label, value) each, its label and then its value, lined up past the widest label
    beside a value as `c`'s own rows are, or with no label a choice of a list opened under the
    row above it, indented as `add a subscription`'s are.  A value is
    text, or parts: (text, kind) each -- or (text, kind, cell), its columns one of the line's
    cells, as matrix_key reads them -- a space apart, or a list of (text, kind) kept whole as one
    unit with a two-space gutter after it, wrapped at a word under itself as `c`'s
    own values are, never cut: one with a word too wide beside its label folds under it,
    indented as a choice, and so does one with a cell, kept whole, as `◂ 300 ▸` steps; `at` is
    the row lit, on the selection unless its cell is what is lit, and `moves` is handed each
    mark leading a value (`■`, `□`, `●`, `○`) as config_body hands its own."""
    room = terminal.layout_width()
    # a label may be a name read from a file, a provider's or a plan kept, holding a line break;
    # its spacing kept, as two names may differ only in it
    rows = [(row, label if label is None else terminal.plain(label, spaced=True), value)
            for row, label, value in rows]
    wide = max((terminal.cells(label) for _, label, value in rows if label is not None and value),
               default=0)
    lines, places = [], {}
    for row, label, value in rows:
        # a label beside a value is never wider than `wide`, so padding it keeps its colour
        lead = "    " if label is None else f"  {label}{' ' * (wide - terminal.cells(label))}  "
        # the room beside the padded label, none or less where the widest label fills the line
        left, wrapped, used = room - terminal.cells(lead), [[]], 0
        parts, folded = [(value, None)] if isinstance(value, str) else value, False
        # what never parts across lines: each word, a mark-and-word list, and a value with a cell
        # whole, so an arrow stays beside what it steps
        celled = any(isinstance(part, tuple) and len(part) > 2 for part in parts)
        # such a row is still the row around its cells, on every line of it (terminal.under)
        around = [(1, room, None)] if celled else []
        whole = ([" ".join(text for text, *_ in parts)] if celled
                 else [word for part in parts for word in (
                     ["".join(text for text, _ in part)] if isinstance(part, list)
                     else part[0].split())])
        if label is not None and any(terminal.cells(word) > left for word in whole):
            # too wide beside the label: the value folds under it, never cut in a word, and so
            # does a label too wide for its line, wrapped at its words
            for number, part in enumerate(terminal.wrap(label, room - 2, spaced=True)):
                places[len(lines)] = (row, around)
                lines.append(terminal.highlight(f"  {part}", number == 0, band=not celled)
                             if row == at else f"  {part}")
            lead, left, folded = "    ", max(1, room - 4), True
        if (moves is not None and not isinstance(value, str) and value
                and isinstance(value[0], tuple) and value[0][0] in motion.HALF):
            moves.append((len(lines), ("mark", row), value[0][0], motion.toggled(
                value[0][0], 3, value[0][1], row == at, terminal.cells(lead))))
        indent, gap = terminal.cells(lead), 0
        for part in parts:
            if isinstance(part, list):
                piece = "".join(terminal.styled(text, kind) if kind else text
                                for text, kind in part)
                span = terminal.cells(piece)
                if used and used + gap + span > left:
                    wrapped, used, gap = [*wrapped, []], 0, 0
                wrapped[-1].append((" " * gap + piece, []))
                used, gap = used + gap + span, 2
                continue
            text, kind, *cell = part
            for piece in terminal.wrap(text, left):
                span = terminal.cells(piece)
                if used and used + gap + span > left:
                    wrapped, used, gap = [*wrapped, []], 0, 0
                used += gap + span
                first = indent + used - span + 1
                wrapped[-1].append((" " * gap + (terminal.styled(piece, kind) if kind else piece),
                                    [(first, indent + used, *cell)] if cell else []))
                gap = 1
        for number, parts in enumerate(wrapped):
            line = ((lead if number == 0 else " " * indent)
                    + "".join(piece for piece, _ in parts)).rstrip()
            places[len(lines)] = (row, [*(spot for _, cells in parts for spot in cells), *around])
            lines.append(terminal.highlight(line, number == 0 and not folded, band=not celled)
                         if row == at else line)
    return lines, places


@terminal.clicks_its_own
def config_page(name, page, move=True):
    """`config · <name>`, a page `c` opens: `page()` gives its rows -- (label, value, act) each,
    or with a note of the row's own after, said instead of the page's while the row is pointed,
    and lines of its own after that, drawn under the rows, ↓ and ↑ paging them as a tall row's
    -- and the note under them, asked again for every draw, drawn as page_body draws them and
    read with `c`'s keys until Esc, the key line saying what the arrows `move` (terminal.keys).
    It comes up as `c` does as it opens, its name writing itself out in the header
    (motion.Clock), and a mark leading a value fills or empties as it flips (motion.toggled);
    one gone back to from a list or a field is drawn as it is.

    A row's act is None for a row that only shows; a mark, ("mark", flip), Space or a click
    flipping it, optionally a third item, a field Enter opens; a step, ("step", near, take), ←
    and → calling `take(near(-1))` and `take(near(1))`, nothing where `near` gives None, an
    end, and the lit row's value drawn `◂ value ▸`, each arrow where it moves; a list,
    (choices, several), Enter or a click opening it under the row, coming up there
    (motion.fading), the highlight on the first choice marked; or a field, Enter or a click
    calling it with `draw`,
    which draws the page with lines under the row and returns the screen row of the first, as
    terminal.field takes it.  `choices()` gives (value, pick, mark) each, asked as the list
    opens and again after each pick, so a reading that moves underneath never moves the
    highlight onto another choice.
    `mark` is a mark's state, Space or a click calling `pick()` and the list staying open,
    Enter closing it, first picking the highlighted choice unless `several`; or an act's word,
    Enter or a click calling `pick()`, "" doing nothing.  Esc closes the list.  What a call
    returns is said under the rows, over the note, until the next key."""
    here, top, said, opened, title, pointed = ("row", 0), 0, "", None, f"config · {name}", None
    rows, listed = [], []              # the page and open list's choices, as last asked
    clock = motion.Clock(page=True)   # it comes up as `c` does, and its marks move as `c`'s

    def kind(act):                    # a mark's or a step's word, else None
        return act[0] if isinstance(act, tuple) and isinstance(act[0], str) else None

    def does(row):                    # what Space and Enter do on `row` (terminal.keys)
        if len(row) == 3:
            mark = listed[row[2]][2]
            return ((None, mark) if isinstance(mark, str)
                    else ("mark", "close" if opened[2] else "pick"))
        act = rows[row[1]][2]
        if act is None or kind(act) == "step":
            return None, None
        return (("mark", "open" if len(act) == 3 else None) if kind(act) == "mark"
                else (None, "open"))

    def stepping(value, near):        # a lit step's value, an arrow each side it moves to
        left, right = ("◂", "▸") if terminal.utf8() else ("<", ">")
        first, *rest = [(value, None)] if isinstance(value, str) else value
        return [*([(left, "dim", "left")] if near(-1) is not None else []), first,
                *([(right, "dim", "right")] if near(1) is not None else []), *rest]
    # Each row as each draw knows it again: its label, whether it only shows, and how many rows
    # above share both, as a machine ak uses may share its name with one that stands in, whose
    # row only shows, and two harnesses the name their manifests give.
    def who(rows):
        keys = [(label, act is None) for label, _, act, *_ in rows]
        return [(key, keys[:number].count(key)) for number, key in enumerate(keys)]
    while True:
        was = who(rows)[here[1]] if rows else None
        rows, note = page()
        if not opened:                # a pick removed the last row: the highlight on the new last
            here = ("row", next((number for number, row in enumerate(who(rows)) if row == was),
                                 min(here[1], len(rows) - 1)))
        drawn = [(("row", number), label,
                  stepping(value, act[1]) if kind(act) == "step" and here == ("row", number)
                  and not terminal.away() else value)
                 for number, (label, value, act, *_) in enumerate(rows)]
        # the pointed row's own note and lines, none while the pointer is off every row
        note, under = ((*rows[here[1]][3:], ())[:2] if len(rows[here[1]]) > 3
                       and not terminal.away() else (note, ()))
        if opened:
            drawn[opened[0] + 1:opened[0] + 1] = [(("row", opened[0], number), None, value)
                                                  for number, (value, _, _) in enumerate(listed)]
        # with a list open its choices are what the keys move through, else the rows
        ids = [row for row, label, _ in drawn if (label is None) == bool(opened)]
        moves = []
        body, places = page_body(drawn, None if terminal.away() else here, moves)
        # an open list comes up under its row as the line under the menu's highlighted row does
        moves += [(line, ("opened",), opened[0], motion.fading(body[line]))
                  for line, (row, _) in places.items() if len(row) == 3]
        # a click on what a mark's line draws acts as Space does (matrix_key's `marks`)
        places = {line: (row, [(1, terminal.layout_width(), 0)] if does(row)[0] else cells)
                  for line, (row, cells) in places.items()}
        # the pointed row's lines under the rows, its own: ↓ and ↑ turn their pages before they
        # leave it, as a tall row's (matrix_key), from the row each time the pointer comes to it
        top = min(top, next(line for line, (row, _) in places.items() if row[:2] == here[:2])
                  ) if here[1] != pointed else top
        places.update((len(body) + number, (here[:2], [(1, terminal.layout_width(), None)]))
                      for number in range(len(under)))
        body, pointed = [*body, *under], here[1]
        space, enter = does(here)
        keys = terminal.keys("esc back", space=space, enter=enter, move=move)
        below = note_lines("\n".join(filter(None, (said, note))))
        act, moved, _, top = matrix_key(title, body, places, ids, here, top, "", keys, marks=1,
                                        clock=clock, moves=moves, under=below)
        # the pointer on a row off-list, unless it clicked it, which closes an open list
        here = moved if moved in ids or act in ("enter", "space") else here
        opened = opened if len(here) == 3 else None
        if act is None:
            continue                  # a resize or the pointer: drawn again
        said, (space, enter) = "", does(here)
        if act == "back":
            if not opened:
                return
            here, opened = ("row", opened[0]), None
        elif (act in ("left", "right") and len(here) == 2 and kind(rows[here[1]][2]) == "step"
              and not terminal.unseen()):      # unseen, it only brings the highlight back
            _, near, take = rows[here[1]][2]
            value = near(1 if act == "right" else -1)
            said = "" if value is None else take(value) or ""
        elif not (act == "space" and space or act == "enter" and enter):
            continue
        elif len(here) == 3:
            if act == "space" or enter != "close":
                said = listed[here[2]][1]() or ""
            if act == "enter" and space:
                here, opened = here[:2], None
            else:
                listed = opened[1]()
                # a login's list asked again can be shorter: the highlight stays on a choice
                here = (*here[:2], min(here[2], max(0, len(listed) - 1)))
        elif act == "space":         # a mark of the page's own
            said = rows[here[1]][2][1]() or ""
        elif isinstance(rows[here[1]][2], tuple) and not space:
            opened = (here[1], *rows[here[1]][2])
            clock.forget()            # what it asks may draw a screen: the page back is up
            listed = opened[1]()
            clock.touch(("opened",))  # news: the list comes up
            here = (*here, next((number for number, (_, _, mark) in enumerate(listed)
                                 if mark is True), 0))
        else:
            # typed in, the arrows move nothing: Enter saves what was typed
            opened, at = None, here[1]
            field_row = who(rows)[at]
            clock.forget()            # drawn off the clock: the page back is drawn as it is
            keys = terminal.keys("esc back", enter="save", move=False)

            def draw(lines):          # the page of matrix_key's height that holds the lines
                rows, note = page()
                at = who(rows).index(field_row)
                body, places = page_body([(("row", number), label, value)
                                          for number, (label, value, *_) in enumerate(rows)])
                # under the row's last line, a value that wrapped included
                end = 1 + max(line for line, (row, _) in places.items() if row == ("row", at))
                body[end:end], said = lines, note_lines(note)
                first, room = matrix_page(body, {end: ("lines", [])}, "lines", top, said, keys)
                terminal.frame(title, [*body[first:first + room], *said], keys)
                return 3 + end - first
            field = rows[at][2][2] if space else rows[at][2]
            said = field(draw) or ""


# What `Models`, `Discord`, `Weekly audit` and `Done check` say under their rows.
TICKS_NOTE = "Space on a model under its harness takes it in or out of the config."
DISCORD_NOTE = "A card reads only Needs you · <seat> or Done · <seat>, and mentions you."
AUDIT_NOTE = "Once a week ak opens a seat named audit with the week's largest loss."
DONE_CHECK_NOTE = "A model reads what you asked a seat and names what its work does not hold."


def models_page(cfg, keyboard):
    """`Models`: a row per harness the config's providers run on (config.provider_harnesses),
    opening `■` each model the config runs there and `□` only the newest release of each line its
    catalog offers (_offered, releases.newest), or for a harness that logs in to providers
    (config.provider_hosts) each newest it runs now, then each of the config's providers it lists
    with no login (_through_choices).  Space
    takes one out (remove_model), the last model kept, or in: one taken out here as it was, its
    provider's table as the page opened; any other named from its label (config.short_name), at
    its harness's first model's effort, else `high`, as near as it goes (_nearest), under that
    model's provider, else one shipped to run there, or the one it is listed under, taken in
    as `add a subscription` takes it (config.take_in).  Enter on a provider logs in to it on
    `keyboard`'s terminal, and its models are listed.  Saved at once."""
    full, empty = ("■", "□") if terminal.utf8() else ("#", "-")
    tables = copy.deepcopy(cfg["providers"])
    gone = {}                 # (harness, model id): [(name, entry)] each taken out here
    harnesses = list(dict.fromkeys(harness for provider in cfg["providers"]
                                   for harness in config.provider_harnesses(cfg, provider)))
    runs = {}                 # harness: what a model coming in where none is left takes
    shipped = config.shipped().get("models")
    for entry in shipped.values() if isinstance(shipped, dict) else ():
        if isinstance(entry, dict) and entry.get("provider") in cfg["providers"]:
            runs.setdefault(entry.get("harness"), entry["provider"])
    for provider in cfg["providers"]:     # a harness the shipped default runs on none of them
        for harness in config.provider_harnesses(cfg, provider):
            runs.setdefault(harness, provider)

    def on(harness, model=None):      # the names the config runs on that harness, `model`'s
        return [name for name in config.offered(cfg) if cfg["models"][name]["harness"] == harness
                and model in (None, cfg["models"][name]["model"])]

    def tick(harness, model, row=None):     # `row`: the provider it is listed under
        key, names, before = (harness, model["id"]), on(harness, model["id"]), copy.deepcopy(cfg)
        if names and len(names) == len(config.offered(cfg)):
            return "the config needs one model"
        if names:
            gone[key] = [(name, cfg["models"][name]) for name in names]
            ran[harness][model["id"]] = model["label"]
            for name in names:
                config.remove_model(cfg, name)
            return _saved(cfg, cfg, before)
        first = next((cfg["models"][name] for name in on(harness)), {})
        # never a name one taken out here comes back under
        taken = {"models": [*cfg["models"], *(name for kept in gone.values() for name, _ in kept)]}
        entries = gone.get(key) or [(config.short_name(taken, model["label"]), config.model_entry(
            harness, model["id"], model["label"],
            effort=_nearest(first.get("effort", "high"), model["efforts"]),
            provider=row[0] if row else first.get("provider", runs[harness])))]
        if row and key not in gone:
            config.take_in(cfg, entries[0][1], row)
            tables.setdefault(row[0], copy.deepcopy(cfg["providers"][row[0]]))
        for name, entry in entries:
            cfg["models"][name] = entry
            cfg["providers"].setdefault(entry["provider"], copy.deepcopy(tables[entry["provider"]]))
        return _saved(cfg, cfg, before)

    # harness: {id: name} each model it ran as its list was read here, or taken out here: one
    # its catalog does not list keeps a row of its own while the page is open, taken out here or
    # not, and one taken in or out here that a login leaves out of the listing read again
    ran = {}

    def listing(harness):     # what a harness's row opens onto: (model, the provider it is
        said, catalog = "", []  # listed under) each, (None, one to log in), offered ids, and note
        try:
            if harness not in config.provider_hosts():
                catalog = _offered(harness, "config · models", cfg=cfg)
                rows = [(model, None) for model in catalog]
            else:
                listed = waited(lambda: config.listed_providers(harness), "config · models",
                                doing=f"asking {config.provider_hosts()[harness]} "
                                      "which providers it has")
                catalog = _offered(harness, "config · models", cfg=cfg)
                by = {row[0]: row for row in listed}
                rows = [(model, by[provider]) for (((_, provider), model), _)
                        in _through_choices(cfg, harness, listed, ("config · models",),
                                            offered=catalog)
                        if model or provider in cfg["providers"]]
        except config.Error as exc:     # what the config runs there comes out with no listing
            rows, said = [], f"config: {exc}"
        except Back:
            rows, said = [], "not read: esc and open it again"
        ran.setdefault(harness, {}).update((cfg["models"][name]["model"],
                                            config.model_name(cfg, name)) for name in on(harness))
        ids = {model["id"] for model, _ in rows if model}
        rows += [({"id": model, "label": label}, None)
                 for model, label in ran[harness].items() if model not in ids]
        # catalog models compete only among what the harness lists; unlisted history rows are
        # offered `□` only for lines the catalog does not list, so they never hide a listed release
        catalog_ids = {model["id"] for model in catalog}
        extras = [model for model, _ in rows if model and model["id"] not in catalog_ids]
        offered = {model["id"] for model in releases.newest(catalog, extras=extras)}
        return rows, offered, bool(catalog), said

    def ticks(harness):       # the list a harness's row opens
        got = []

        def log_in(row):
            said = _adapter_verbs(keyboard, harness, ("login",), row[1], provider=row[0])
            if not said:
                config.forget_catalog(harness)       # its models are listed now
                got.clear()
            return said

        def choices():
            if not got:
                got.append(listing(harness))
            rows, offered, has_catalog, said = got[0]
            shown = [(model, row) for model, row in rows
                     if not model or on(harness, model["id"]) or model["id"] in offered]
            note = said or ("" if shown else
                            "no model to offer" if has_catalog else "its catalog lists no model")
            return [([(full, "accent") if on(harness, model["id"]) else (empty, "dim"),
                      (model["label"], None)],
                     lambda model=model, row=row: tick(harness, model, row),
                     bool(on(harness, model["id"]))) if model else
                    ([(row[1], None), (_logs_in(row[3]), "dim")], lambda row=row: log_in(row),
                     "log in")
                    for model, row in shown] + ([([(note, "dim")], lambda: "", "")] if note else [])
        return choices, True

    def page():
        return [(config.harness_name(harness), ", ".join(config.model_name(cfg, name)
                                                   for name in on(harness)) or "none",
                 ticks(harness)) for harness in harnesses], TICKS_NOTE
    config_page("models", page)


def config_discord():
    """`Discord`: who a card mentions and the webhook it goes to, a row each (config_page),
    each typed anew under its row (discord_secret)."""
    def page():
        who, hook = discord_shown()
        return [("Mention", who or "nobody", lambda draw: discord_secret(
                    draw, "discord_user_id", "your Discord user id")),
                ("Webhook", hook or "not connected", lambda draw: discord_secret(
                    draw, "discord_webhook", "your channel's webhook URL"))], DISCORD_NOTE
    config_page("discord", page)


def discord_secret(draw, name, hint):
    """One of `Discord`'s secrets typed under its row (terminal.field) and written the way
    install.sh writes it; Enter with nothing typed, or Esc, keeps what is there, and a user id
    that is not digits is refused.  What to say under the rows, or ""."""
    value = terminal.field("    ", hint, around=lambda line: draw([line]))
    value = "" if value is None or terminal.is_esc(value) else value.strip()
    if not value:
        return ""
    if name == "discord_user_id" and not re.fullmatch(r"[0-9]+", value):
        return "a user id is only digits: Discord's Copy User ID gives it"
    try:
        config.ensure_dirs()
        path = config.SECRETS / name
        path.write_text(value + "\n")
        os.chmod(path, 0o600)
    except OSError as exc:
        return f"discord: {exc}"
    return ""


def audit_value(cfg):
    """`Weekly audit`'s value: on or off, and who orchestrates, executes and reviews it, under
    the matrix's own column words, each model by its full name, `on · orch Opus 5.5 · builds
    Opus 5.5, 6 Astra · reviews 6 Astra`; a setting the config cannot read is shown as
    the error that says why."""
    try:
        setting = config.audit(cfg)
    except config.Error as exc:
        return str(exc)
    heads = orch.ROLE_HEADS
    return " · ".join(("on" if setting["on"] else "off",
                       f"{heads[0]} {config.model_name(cfg, setting['orchestrator'])}",
                       f"{heads[1]} " + (audit_names(cfg, setting["workers"]) or "nobody"),
                       f"{heads[2]} " + audit_names(cfg, setting["reviewers"])))


def audit_names(cfg, names):
    """The models `names` are, by their full names, as `Weekly audit` shows a role's."""
    return ", ".join(config.model_name(cfg, name) for name in names)


def setting(cfg, page, table, read):
    """What `c`'s page `page` shows of `[table]` in config.toml and how it writes it, as `read`
    (config.audit, done_check.setting, money.currency) takes the table: the setting, else the
    one left once each key `read` cannot take on its own is dropped, so the first change mends a
    table nothing reads, and one that is not a table keeps nothing; why `read` takes none, or "";
    and `write(key, value)`, which sets `key` to `value`, or takes it out for None, beside the
    keys kept and saves it, `cfg` with it (_saved), once `read` takes it, else writes nothing and
    returns why, else ""."""
    held, kept = cfg.get(table), {}
    for key, value in held.items() if isinstance(held, dict) else ():
        try:
            read({**cfg, table: {key: value}})
        except config.Error:
            continue
        kept[key] = value

    def write(key, value):
        changed = {**kept, key: value}
        if value is None:
            del changed[key]
        try:
            read({**cfg, table: changed})
        except config.Error as exc:
            return f"{page}: {exc}"
        before = copy.deepcopy(cfg)
        if changed:
            cfg[table] = changed
        else:
            cfg.pop(table, None)
        return _saved(cfg, cfg, before)
    try:
        return read(cfg), "", write
    except config.Error as exc:
        return read({**cfg, table: kept}), str(exc), write


def on_row(held, write):
    """A page's `On` row, its setting's `on`, Space turning it the other way at once (write)."""
    on, off = ("●", "○") if terminal.utf8() else ("*", ".")
    return ("On", [(on, "accent"), ("on", None)] if held["on"] else [(off, "dim"), ("off", None)],
            ("mark", lambda: write("on", not held["on"])))


def config_audit(cfg):
    """`Weekly audit`: whether it runs and the models its seat takes, a row each (config_page),
    each change written to `[audit]` in config.toml at once (setting).  Space on `On` turns it
    the other way (on_row); Enter on `Orchestrator` opens every model under it, `●` the one it
    is, Space moving the ● and Enter taking the highlighted one; on `Builds` and `Reviews` every
    model `■` in that role or `□` not, Space taking one in or out."""
    on, off, full, empty = ("●", "○", "■", "□") if terminal.utf8() else ("*", ".", "#", "-")

    def shown():
        return setting(cfg, "weekly audit", "audit", config.audit)

    def models(key):          # the list a role's row opens
        one = key == "orchestrator"

        def choices():
            held, _, write = shown()
            held = [held[key]] if one else held[key]
            return [([(on if one else full, "accent") if name in held
                      else (off if one else empty, "dim"), (config.model_name(cfg, name), None)],
                     lambda name=name: write(key, name if one else [
                         other for other in held if other != name] if name in held
                         else [*held, name]),
                     name in held)
                    for name in config.offered(cfg)]
        return choices, not one

    def page():
        held, why, write = shown()
        return [on_row(held, write),
                ("Orchestrator", config.model_name(cfg, held["orchestrator"]),
                 models("orchestrator")),
                ("Builds", audit_names(cfg, held["workers"]) or "nobody", models("workers")),
                ("Reviews", audit_names(cfg, held["reviewers"]), models("reviewers"))], \
            "\n".join(filter(None, (why, AUDIT_NOTE)))
    config_page("weekly audit", page)


def checker_name(cfg, name):
    """The model that makes the done check, `name`, by its full name, else the seat's reviewer."""
    return config.model_name(cfg, name) if name else "the seat's reviewer"


def done_check_value(cfg):
    """`Done check`'s value: on or off and the model that makes it, `on · the seat's reviewer`;
    a setting the config cannot read is shown as the error that says why."""
    try:
        held = done_check.setting(cfg)
    except config.Error as exc:
        return str(exc)
    return f"{'on' if held['on'] else 'off'} · {checker_name(cfg, held['model'])}"


def config_done_check(cfg):
    """`Done check`: whether it is on and the model that makes it, a row each (config_page),
    each change written to `[done_check]` in config.toml at once (setting).  Space on `On`
    turns it the other way (on_row); Enter on `Model` opens the seat's reviewer and every
    model, `●` the one in use, Space moving the ● and Enter taking the highlighted one, the
    seat's reviewer by taking `model` out."""
    on, off = ("●", "○") if terminal.utf8() else ("*", ".")

    def shown():
        return setting(cfg, "done check", "done_check", done_check.setting)

    def choices():
        held, _, write = shown()
        return [([(on, "accent") if name == held["model"] else (off, "dim"),
                  (checker_name(cfg, name), None)],
                 lambda name=name: write("model", name), name == held["model"])
                for name in (None, *config.offered(cfg))]

    def page():
        held, why, write = shown()
        return [on_row(held, write),
                ("Model", checker_name(cfg, held["model"]), (choices, False))], \
            "\n".join(filter(None, (why, DONE_CHECK_NOTE)))
    config_page("done check", page)


# What each currency `[money] currency` may name (money.TABLES) is called, after its sign.
CURRENCY_NAMES = {"USD": "US dollars", "EUR": "euros"}


def money_value(cfg):
    """`Money`'s value, and its page's `Currency`'s: the currency prices are in (money.currency)
    after its sign, `$ US dollars`, or without UTF-8 after its ISO code, `USD US dollars`."""
    code = money.currency(cfg)
    return f"{usage.SIGNS[code] if terminal.utf8() else code} {CURRENCY_NAMES[code]}"


def vat_value(cfg):
    """`VAT`'s value: `none` where `[money] vat` names none or 0, else the percent money.price
    adds, `19% · added to list prices`, exactly: never rounded, so it never reads as another
    rate, but its first 20 digits and `…` where it has more, and `under 0.01%`, the least the
    field takes, for a rate below it, so no long one fills the page.  In whole numbers
    (config.parse_decimal), as a float of a tiny rate is 0 and decimal's exponents end."""
    rate = money.vat(cfg)
    _, digits, places, exp = config.parse_decimal(0 if rate is None else rate)
    if not digits:
        return "none"
    cut = max(0, places - 20)
    shown = ("under 0.01" if places + exp < -1          # 0.00…: two zeros after the point
             else f"{decimal.Decimal(digits // 10 ** cut).scaleb(exp + cut):f}" + "…" * bool(cut))
    return f"{shown}% · added to list prices"


def config_money(cfg):
    """`Money`: `Currency`, the currency prices are in (config_page), Space switching it to the
    next of money.TABLES, written to `[money]` in config.toml at once (setting); under it `VAT`,
    the percent money.price adds to list prices (vat_value), Enter opening a field for it
    written at once, empty taking it out; under that the plans the logins were on when
    the page opened (usage_rows, usage.plan), their prices read at each draw (plan_rows)."""
    counts = {}
    for provider, _, _, account in usage_rows(cfg):
        on = provider, usage.plan(provider, account)
        counts[on] = counts.get(on, 0) + 1

    def vat(write):
        def field(draw):
            typed = terminal.field("    ", "percent · empty: none, as for a business",
                                   around=lambda line: draw([line]), tabs=True)
            if typed is None or terminal.is_esc(typed):
                return ""
            value = money.parse(typed, 100) if typed else None
            if typed and value is None:
                return "a VAT is a percent like 19 or 8.1"
            if value is None and money.vat(cfg) is None:
                return ""       # nothing to take out: config.toml stays as written
            return write("vat", value)
        return field

    def page():
        held, _, write = setting(cfg, "money", "money", money.currency)
        codes = list(money.TABLES)
        return [("Currency", money_value(cfg), ("mark", lambda: write(
            "currency", codes[(codes.index(held) + 1) % len(codes)]))),
            ("VAT", vat_value(cfg), vat(write)),
            *plan_rows(cfg, counts, write)], ""
    config_page("money", page)


def plan_rows(cfg, counts, write):
    """One row per `(provider, plan)` in `counts`, named as `config · subscriptions` names the
    provider (company_name), then the plan, or alone, `plan not read yet`, where the plan is not
    known; its price a month in the config's currency (money.price, `amount`), with `your price`
    when kept under `[money.paid]` (money.typed), else `no price in` the currency, its logins
    counted where more than one.  Enter on a plan's row opens a field for what you pay a month
    in that currency, written to `[money.paid.<currency>.<provider>]` at once through `write`,
    or empty takes it out; a row with no plan stays one that only shows.  Then `In all`, each
    price times its logins, the logins of a row with no price `not counted`.  None where
    `counts` is empty."""
    code, rows, total, missed = money.currency(cfg), [], 0, 0

    def take(provider, plan):
        def field(draw):
            typed = terminal.field("    ", "a month · empty: the list price",
                                   around=lambda line: draw([line]), tabs=True)
            if typed is None or terminal.is_esc(typed):
                return ""
            value = money.parse(typed) if typed else None
            if typed and value is None:
                return "a price is a number like 180 or 180.50"
            held = cfg.get("money", {}).get("paid") if isinstance(cfg.get("money"), dict) else None
            if value is None:
                if money.typed(cfg, provider, plan, code) is None:
                    return ""
                updated = copy.deepcopy(held)
                del updated[code][provider][plan]
                if not updated[code][provider]:
                    del updated[code][provider]
                if not updated[code]:
                    del updated[code]
                return write("paid", updated or None)
            if held is not None and not isinstance(held, dict):
                return "money: [money.paid] must be a table"
            updated = copy.deepcopy(held) if isinstance(held, dict) else {}
            table = updated
            for depth, key in enumerate((code, provider)):
                if key in table and not isinstance(table[key], dict):
                    where = ".".join(("money", "paid", *(code, provider)[:depth + 1]))
                    return f"money: [{where}] must be a table"
                table = table.setdefault(key, {})
            if isinstance(table.get(plan), dict):
                return f"money: [money.paid.{code}.{provider}] {plan} is a table"
            table[plan] = value
            return write("paid", updated)
        return field

    for (provider, on), count in counts.items():
        yours = None if on is None else money.typed(cfg, provider, on, code)
        price = (None if on is None
                 else yours if yours is not None
                 else money.price(cfg, provider, on, code))
        if price is None:
            missed += count
        else:
            total += decimal.Decimal(str(price)) * count    # exact, as cents written add up
        said = ("plan not read yet" if on is None
                else f"no price in {CURRENCY_NAMES[code]}" if price is None
                else amount(code, price))
        parts = [said, *(["your price"] if yours is not None else []),
                 *([f"{count} logins"] if count > 1 else [])]
        rows.append((company_name(cfg, provider) + ("" if on is None else f" · {on}"),
                     " · ".join(parts), None if on is None else take(provider, on)))
    if rows:
        rows.append(("In all", amount(code, total) + (
            f" · {missed} login{'s' if missed > 1 else ''} not counted" if missed else ""), None))
    return rows


def amount(code, value):
    """`$200 a month`, `$19.99 a month`: `value` after the sign of currency `code`, or without
    UTF-8 after its ISO code as money_value's, `EUR 18 a month`; whole where it is whole, else
    to the cent."""
    value = decimal.Decimal(str(value))
    digits = f"{value:,.{0 if value == value.to_integral_value() else 2}f}"
    return (f"{usage.SIGNS[code]}{digits}" if terminal.utf8() else f"{code} {digits}") + " a month"


def machines_value():
    """`Machines`' count, with no probe; it loads config.toml as it is now, so one that will not
    load is shown as the error that says why, `c` drawn over it while it goes on with the config
    it read last."""
    try:
        config.load()
        count = len(machines.known())
    except config.Error as exc:
        return str(exc)
    return f"{count} machine{'' if count == 1 else 's'}"


def machine_value(machine, stand_in=None):
    """What the tick last found, then `stand_in`, its words as the stand-in where it is one;
    another machine that answered on battery takes no work now (machines.helpers), its row
    ending `on battery · no work until on power`."""
    here, said = machine.name == machines.HERE, machine.said
    also = [stand_in] if stand_in else []
    words = ["home" if here else machine.kind]
    if said:
        total, free = said["memory_mb"], said["free_mb"]
        words += [f"{said['cores']} cores · {machines._gb(total)}"]
    if machine.checks and not machine.checks[-1][1]:
        since = machine.checks[-1][0]
        for at, answered in reversed(machine.checks):
            if answered:
                break
            since = at
        words += [f"not answering since {machines._when(since)}"]
    elif said:
        busy = min(100, max(0, round(100 * said["load"] / max(1, said["cores"]))))
        used = machines._gb(total - free).removesuffix(" GB")
        words += [f"{busy}% busy · {used} of {machines._gb(total)} used"]
        if not here and machines.on_battery(said):
            return " · ".join([*words, *also, "on battery · no work until on power"])
    else:
        words += ["never answered"]
    return " · ".join([*words, *also])


def stand_in_value(age, takes, own=True):
    """A machine that copies this one, from its record (standby.copies): its copy's age, or why
    that cannot be said, and on a row of its `own` whether it takes over and home goes back to
    it: on a listed machine's row, `this one` and `it` would read as that machine."""
    return " · ".join(["stand-in", f"copy {age}" if takes else age,
                       *["takes over when this one stops"] * (own and takes in standby.OVER),
                       *["home goes back to it once it is steady"] * (own and takes == "back")])


def machine_hours(name):
    """`name`'s last 24 hours of processors as 24 marks (EIGHTHS and GLYPHS's full cell, 1 or
    more full, `·` with no reading) and what those 24 hours ran short of, or `no readings yet`
    when none of the 24 has one."""
    series = readings.hours(name, time.time(), 24, home=False)
    if not any(hour.processors is not None for hour in series):
        return "no readings yet"
    marks, empty = (EIGHTHS[1:] + GLYPHS[True][0], "·") if terminal.utf8() else ("_,-:=+*#", ".")
    bars = "".join(empty if h.processors is None
                   else marks[7 if h.processors >= 1 else min(6, max(0, round(8 * h.processors) - 1))]
                   for h in series)
    short = [f"short of {what} in {n} of {len(series)} hours"
             for what in ("processors", "memory")
             if (n := sum(what in hour.short_of for hour in series))]
    return f"{bars} {' · '.join(short) if short else 'never short'}"


def config_machines(cfg):
    """Recorded machines; Enter opens each one's cap on runs at once (runs_row), the home's with
    how many sessions it carries at once under it (carried.value), another's under its work
    marks.  Each machine that copies this one (standby.copies) is said on the row of the first
    listed machine but the home whose last reading names its host (machine_value), one machine one
    row, else under them on a row that opens nothing; why they cannot be read under the rows.
    Last, `+ add a machine` takes an ssh address, or with none typed finds those that ran the
    line making a new machine one it adds (machines.join_line, under its field; machines.found),
    and writes each to config.toml once it answers (machines.add), else says why not."""
    on, off = ("●", "○") if terminal.utf8() else ("*", ".")

    def add_field(draw):
        join = machines.join_line()

        def around(line):             # under the field, the line a new machine is added by
            said = terminal.wrap("Run this on a new Linux machine, then press Enter for ak to "
                                 "find it on your Tailscale network, or type above the address "
                                 "it prints:", terminal.layout_width() - 4)
            return draw([line, "", *(terminal.styled(f"    {part}", "dim") for part in said),
                         *terminal.unbroken(f"    {join}")])
        name = terminal.field("    ", "its ssh address: a Host of ~/.ssh/config, a host name or "
                              "user@host", around=around)
        if name is None or terminal.is_esc(name):
            return ""
        name = name.strip()
        try:
            if name:
                names, why = [name], waited(lambda: machines.add(name), "config · machines",
                                            doing=f"asking {name}")
            else:
                names, why = waited(machines.found, "config · machines",
                                    doing="asking your Tailscale network")
        except Back:
            return ""
        if why:
            return why
        before = copy.deepcopy(cfg)
        cfg.setdefault("machines", {}).update({name: {} for name in names})
        return _saved(cfg, cfg, before)

    def runs_row(where, held, *said):
        """`runs at once` (the owner, 25 Nov 2026: "one number per machine"), `max_runs` in the
        table of cfg at the keys `where` names as the field saves, its top for none: `held`, the
        number in force, or `no limit`, then `said`, dim.  Enter opens a field: a whole number
        of 1 or more is saved there, 0 or nothing typed takes it off, anything else is refused
        in a sentence."""
        def field(draw):
            typed = terminal.field("    ", "a whole number, or 0 for no limit",
                                   around=lambda line: draw([line]))
            if typed is None or terminal.is_esc(typed):
                return ""
            if typed and not re.fullmatch(r"[0-9]+", typed.strip()):
                return "runs at once must be a whole number, or 0 for no limit"
            number = config.read_whole(typed.strip())
            before, table = copy.deepcopy(cfg), cfg
            for depth, key in enumerate(where):
                if not isinstance(table.get(key, {}), dict):
                    return (f"config: [{'.'.join(where[:depth + 1])}] must be a table"
                            if number else "")
                table = table.setdefault(key, {}) if number else table.get(key, {})
            if number:
                table["max_runs"] = number
            elif "max_runs" in table:
                del table["max_runs"]
            else:
                return ""
            return _saved(cfg, cfg, before)
        return ("runs at once", [(config.whole(held) if held else "no limit", None),
                                 *((words, "dim") for words in said)], field)

    # the keys of the table whose number this one's row last drew, where its field saves: a
    # tick may find this host a listed machine, or no longer one, while the field is open
    here = []

    def home_page(sessions):
        def page():
            where, held = config.max_runs_at()
            here[:] = where
            config.load()       # as on Machines' own page
            return [runs_row(here, held, *["set by AK_MAX_RUNS"] * ("AK_MAX_RUNS" in os.environ)),
                    ("sessions at once", sessions, None)], ""
        return page

    def work_page(name):
        def flip(word):
            before = copy.deepcopy(cfg)
            work = machines.work(name, cfg)
            table = cfg.setdefault("machines", {}).setdefault(name, {})
            table["work"] = [item for item in ("turns", "tests")
                             if (item in work) != (item == word)]
            if table["work"] != machines.work(name, cfg):
                cfg.clear()
                cfg.update(before)
                return "this machine cannot build or review"
            return _saved(cfg, cfg, before)

        def page():
            work = machines.work(name, cfg)
            cap = machines.max_runs(name, cfg)
            config.load()       # as on Machines' own page
            return [*((label, [(on, "accent") if word in work else (off, "dim"),
                               ("on" if word in work else "off", None)],
                       ("mark", lambda word=word: flip(word)))
                      for word, label in (("turns", "builds and reviews"), ("tests", "tests"))),
                    runs_row(("machines", name), cap),
                    ("last 24 hours", machine_hours(name), None)], ""
        return page

    def opens(name):
        def open_page(draw):
            # the history read once as the page opens, as `Limits` reads it
            config_page(f"machines · {name}", home_page(carried.value(time.time()))
                        if name == machines.HERE else work_page(name))
            return ""
        return open_page

    def page():
        known = machines.known()
        try:
            stand_ins, why = standby.copies(), ""
        except config.Error as exc:
            stand_ins, why = [], str(exc)
        joined, apart = {}, []
        for host, age, takes in stand_ins:
            same = next((machine.name for machine in known if machine.name != machines.HERE
                         and (machine.said or {}).get("name") == host), None)
            if same:
                joined[same] = stand_in_value(age, takes, own=False)
            else:
                apart.append((host, stand_in_value(age, takes), None))
        def row_value(machine):
            work = machines.work(machine.name, cfg)
            # kept as one unit so runs and tests stay on one line and fold together on narrow rows
            marks = []
            for word, label in (("turns", "runs"), ("tests", "tests")):
                marks += [("  ", None)] * bool(marks) + [
                    (on, "accent") if word in work else (off, "dim"), (f" {label}", None)]
            return [marks, (machine_value(machine, joined.get(machine.name)), None)]
        rows = [(machine.name, row_value(machine), opens(machine.name))
                for machine in known] + apart
        # a file that will not load closes the page, saying why on `c`; read last, so one
        # breaking under the reads above does too
        config.load()
        return [*rows, ("+ add a machine", "", add_field)], why
    config_page("machines", page)


def limit_shown(value):
    """One of config.POLICY's numbers as `Limits` says it, as config.toml writes a number
    (config.whole): 0, the limit off, as `off`."""
    return config.whole(value) if value else "off"


def limits_value(cfg):
    """`Limits`' value on `c`: each of config.POLICY's numbers in force (config.host_policy) with
    a short name (LIMIT_NAMES) under it, `review 3 rounds · executor 300 lines · orchestrator
    off`."""
    numbers = config.host_policy(cfg)
    return " · ".join(f"{short} {limit_shown(numbers[key])}" + (
        f" {unit[:-1] if numbers[key] == 1 else unit}" if type(numbers[key]) is int and numbers[key] else "")
        for key, (_, short, unit, _) in LIMIT_NAMES.items() if short)


def limit_step(key, held, step):
    """`key`'s step (LIMIT_NAMES) next from `held` up, `step` 1, or down, -1, `no limit` over
    every number: one between steps, as typed by hand, moves onto the next; None past an end.
    A number with no steps moves onto the whole number beside `held`, none under 0."""
    if LIMIT_NAMES[key][3] is None:
        return held + step if held + step >= 0 else None
    rank = lambda value: (value == "no limit", value)
    return next((value for value in LIMIT_NAMES[key][3][::step]
                 if (rank(held) < rank(value) if step > 0 else rank(value) < rank(held))), None)


def rounds_said(runs, held):
    """What `runs` (history.round_endings) would have done at `held` review rounds, said under
    size_table.rounds, M the last round one merged in and F the number that failed.  Off, how
    many went that way; under M, those merged after `held`, and F, back to their orchestrator
    sooner; at M, F back; one past M, a guess that F merge at the share round M merged of its
    merges and F; further, nothing they can say.  None with no run, unless off."""
    merged = [ending for *_, ending in runs if ending is not None]
    if held == 0:
        bare = merged.count(0)
        return "Off: no reviewer, so a change lands when its checks pass. " + (
            f"{bare} of your runs went that way." if bare
            else "None of your runs went that way, so they can't say how it would go.")
    if not runs:
        return None
    failed, last = len(runs) - len(merged), max([*merged, 0])
    nth = lambda n: f"{n}" + ("th" if n % 100 in (11, 12, 13)
                              else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))
    if held < last:
        later = sum(ending > held for ending in merged)
        return (f"The {later} change{'s' * (later != 1)} that merged after round {held} would have "
                "gone back to their orchestrator instead" + (
                    f", and the {failed} that failed would have gone back after round {held}"
                    if failed else "") + ".")
    if held == last:
        return (f"{failed} change{'s' * (failed != 1)} ({round(100 * failed / len(runs))}%) went "
                f"back to their orchestrator after {held} round{'s' * (held != 1)}.")
    if held == last + 1 and last and failed:
        kept = merged.count(last)
        return (f"If a {nth(held)} round went like the {nth(last)}, where "
                f"{round(100 * kept / (kept + failed))}% merged, about "
                f"{round(failed * kept / (kept + failed))} of those {failed} would have merged. "
                "No run has had one, so this is a guess.")
    return f"No run has gone past {last} round{'s' * (last != 1)}, so your runs can't say."


def lines_said(key, sizes, held, *, executors_off=False):
    """What `key`'s changes would have done at `held` lines, `sizes` its kind's of
    history.first_review_sizes: those of more than `held` lines, as the first review's gates
    (transitions.first_review_refusal, seat_lines) refuse them, split, for builds under
    `executor_lines` and for orchestrators' own pull requests when `executors_off`, or made
    tasks, for orchestrators' own pull requests under `orchestrator_lines` -- the owner's design
    of 5 Nov 2026 -- and how often their first review passed, or round 1 merged them, beside the
    rest; off, or past the largest, what they can't say.  None with none, unless off."""
    own = key == "orchestrator_lines"
    if held == 0:
        return ("Off: orchestrators build nothing themselves" + (
                    f", so every one of their {len(sizes)} own pull request"
                    f"{'s' * (len(sizes) != 1)} would have been a task." if sizes else ".")
                if own else
                "Off: executors build nothing, so your runs can't say how that would go.")
    if not sizes:
        return None
    over = [passed for lines, passed in sizes if held != "no limit" and lines > held]
    if not over:
        return (f"Your largest {'own pull request' if own else 'build'} was "
                f"{max(lines for lines, _ in sizes)} lines, so your runs can't say how bigger "
                "ones would go.")
    under = [passed for lines, passed in sizes if lines <= held]
    rate = lambda each: f"{round(100 * sum(each) / len(each))}%"
    were, rest = "was" if len(over) == 1 else "were", (
        f", and {rate(under)} at {held} lines or fewer" if under else "")
    if own:
        fate = "split" if executors_off else ("a task" if len(over) == 1 else "tasks")
        return (f"{len(over)} of your orchestrators' {len(sizes)} own pull requests {were} "
                f"more than {held} lines and would have been {fate}. "
                f"Round 1 merged {rate(over)} of them{rest}.")
    return (f"{len(over)} of your {len(sizes)} builds ({round(100 * len(over) / len(sizes))}%) "
            f"{were} more than {held} lines and would have been split. Their first review passed "
            f"{rate(over)} of the time{rest}.")


def config_limits(cfg):
    """`Limits`: each of LIMIT_NAMES' numbers a row (config_page) under its name there,
    its value and `default N` where that is not ak's default, then under each
    what it means and, where it has them, how its runs did (size_table)
    and what they would have done at its value (rounds_said, lines_said), read as the page opens
    and said again as the value moves: each explanation before its evidence.  ← and → move the
    pointed one a step (limit_step), saved to config.toml at once where config.host_policy takes
    it.  The owner's design of 5 Nov 2026."""
    ended = history.round_endings()
    builds, own = history.first_review_sizes()
    runs, _, paid = matrix.counted(cfg)
    # each number's chart and what its runs would have done at `held`; one no run records how
    # it did yet has neither
    evidence = {"review_rounds": lambda held, numbers: (
                    size_table.rounds(runs["rounds"], held, terminal.layout_width(), paid),
                    rounds_said(ended, held)),
                "executor_lines": lambda held, numbers: (
                    size_table.lines(runs["sizes"], held, terminal.layout_width(), paid),
                    lines_said("executor_lines", builds, held)),
                "orchestrator_lines": lambda held, numbers: (
                    size_table.own_lines(runs["own_sizes"], held, terminal.layout_width(), paid),
                    lines_said("orchestrator_lines", own, held,
                               executors_off=numbers["executor_lines"] == 0)),
                "rescope_findings": lambda held, numbers: (
                    size_table.issues(runs["first_issues"], held, terminal.layout_width(), paid),
                    None)}

    def under(key, numbers):      # what the row means, its chart, what its runs would have done
        meaning = config.POLICY[key][2]
        chart, said = evidence.get(key, lambda *_: ([], None))(numbers[key], numbers)
        room = terminal.layout_width() - 2
        told = lambda text: (["", *("  " + part for part in terminal.wrap(text, room))]
                             if text else [])
        return [*told(f"{meaning[0].upper()}{meaning[1:]}."), *chart, *told(said)]

    def take(key, value):
        try:
            config.host_policy({**cfg, key: value})
        except config.Error as exc:
            return f"config: {exc}"
        before = copy.deepcopy(cfg)
        cfg[key] = value
        return _saved(cfg, cfg, before)

    def page():
        numbers = config.host_policy(cfg)
        return [(LIMIT_NAMES[key][0],
                 [(limit_shown(numbers[key]), None),
                  *([] if numbers[key] == default else [(f"default {default}", "dim")])],
                 ("step", lambda step, key=key: limit_step(key, numbers[key], step),
                  lambda value, key=key: take(key, value)),
                 "", under(key, numbers))
                for key, (default, *_) in config.POLICY.items()], ""
    config_page("limits", page, move=("limit", "value"))


def show_config(dry_run=False, keyboard=None, session=None):
    """`c`: every model in one matrix of `session`'s roles -- the seat the popup is over, read
    from its own record -- and the efforts, under each subscription's meter, then
    CONFIG_ROWS, agentkit's build under them, read with the menu's keyboard (config_matrix),
    so nothing is typed.
    With no seat, or for a seat with no record, the marks are new seats' ([defaults]); a
    record that will not read has the efforts alone, saying so under the rows: the screen that
    changes the models still opens.

    Providers, models, efforts and the two Discord secrets live here, the way they live in
    ~/.agentkit/config.toml and ~/.agentkit/secrets, so nobody opens either file; a seat's
    models live in its record, the one place its row and its runs read them from too.  A dry
    run, and a menu with no keyboard to read -- a pipe -- draw it once and read nothing.
    Returns the config as the screen left it; None when there was nothing to show.
    """
    try:
        cfg = config.load()
    except config.Error as exc:
        if keyboard is not None:
            keyboard.give()
        pause(f"config: {exc}")
        return None
    scope, selected, note = for_selected(cfg, session or NEW_SEATS)
    fresh = not session       # a seat with no record shows new seats' marks, yet is no fresh window
    session = None if scope == NEW_SEATS else session
    providers = usage.held(cfg) if session and selected else {}     # what a flip is refused on
    # git asked once a visit, not each draw; nothing about a harness and nothing over the network
    version = update.agentkit_version()
    if dry_run or keyboard is None or not keyboard.take():
        terminal.frame("config",
                       [*config_meters(cfg)[0],
                        *config_body(cfg, selected=selected, providers=providers,
                                     scope=session or NEW_SEATS)[0],
                        *note_lines(f"Version {version or '?'}")],
                       "esc back")
        return cfg
    return config_matrix(cfg, keyboard, version, session, selected, providers, note,
                         fresh=fresh)


def for_selected(cfg, scope):
    """Whom `c`'s marks are for when it opens for `scope`, the marks, and what to say about
    them: a seat's record, None for one that will not read, said so; and [defaults] for
    NEW_SEATS and for a seat with no record, which has no models to give."""
    try:
        selected = None if scope == NEW_SEATS else config.load_session(cfg, scope,
                                                                       required=False)
    except config.Error as exc:
        return scope, None, f"{scope}'s roles are not shown: {exc}"
    return ((scope, selected, "") if selected is not None
            else (NEW_SEATS, copy.deepcopy(cfg["defaults"]), ""))


def defaults_mark(cfg, selected, model, column):
    """Act on one of new seats' marks, `selected` being [defaults]: saved at once
    (defaults_saved) and into `cfg` and `selected`, no open seat changing.  What to
    say under the rows, or ""."""
    # a new seat's crew is read as it is made (orch.default_crew), so no meter refuses one now
    changed, note = orch.role_mark(cfg, selected, model, column, {})
    if note or changed == selected:
        return note
    return defaults_saved(cfg, selected, changed, copy.deepcopy(cfg))


def defaults_saved(cfg, selected, changed, before):
    """New seats' role groups as `changed` has them, saved at once with the models `cfg`
    changed from `before` (_saved), and then into `cfg` and `selected`; a save not taken leaves
    `selected` alone and says why.  What to say under the rows, or ""."""
    note = _saved(cfg, cfg, before, changed)
    if not note:
        cfg["defaults"] = copy.deepcopy(changed)
        selected.update(changed)
    return note


def apply_defaults(cfg, ask, clock=None):
    """`a` on a fresh window's `c`: every listed seat with a record but the weekly audit's takes
    [defaults]'s executors and reviewers and the entries' efforts for the models it then runs,
    once `Apply` is picked on the card `ask` asks on (asking), which names each seat
    that restarts; one not running [defaults]'s orchestrator at its entry's effort then moves to
    it at that effort (orch.switch_orchestrator), the only way a seat's orchestrator effort
    changes, so a move refused or failed leaves its record on the one its harness runs, its
    other changes kept.  Listed: it has a row on the main screen, gone from tmux
    too.  Each one's bar names what it took at once (handback.redress_seat).  Before each is
    changed, the header counts it and the rule fills by those done (terminal.counting), and once
    the count has gone through the last session, `clock` sweeps the header's rule once
    (motion.Clock.sweep).  config.toml is not written.  What to say under the rows (said_once):
    {each reason a seat was refused for: the seats it held}, in the order the seats are listed,
    a reason no seat holds said alone."""
    from . import audit     # here, not at the top: audit imports this module
    if clock is not None:
        clock.swept = None
    defaults, records = cfg["defaults"], config.session_records()
    skip = config.resolve_session(audit.NAME)
    seats = {s["name"]: records[s["name"]] for s in orch.listing(reconcile=False)
             if not s.get("closed") and s["name"] in records and s["name"] != skip}
    if not seats:
        return {"no session to apply them to": []}
    lead = defaults["orchestrator"]
    effort = config.efforts_of(cfg["models"][lead])["effort"]
    moving = [name for name, record in seats.items() if record.get("orchestrator") != lead
              or config.at_efforts(cfg, record)["models"][lead]["effort"] != effort]
    count = f"{len(seats)} session{'s' * (len(seats) > 1)}"
    restarts = [name for name in moving if not orch.switch_lines(cfg, name, lead, effort)]
    means = (f"{', '.join(restarts)} restart{'s' * (len(restarts) == 1)} on "
             f"{config.model_name(cfg, lead)} at {effort}." if restarts
             else "No session restarts.")
    if not ask(APPLY_ASK.format(count), means, APPLY_ANSWER):
        return {}
    runs = [lead, *defaults["workers"], *defaults.get("reviewers", defaults["workers"])]
    taken = {model: config.efforts_of(cfg["models"][model]) for model in runs}
    providers = usage.held(cfg)       # what orders a move's logins, as `c` reads them

    def given(held):
        """`held`'s efforts at the entries', its orchestrator's own effort where it stands."""
        own = held.get("orchestrator")
        # its orchestrator's entry too, as before, but for the effort it runs at, which only a
        # move at another changes
        efforts = {**(held.get("efforts") or {}), **{
            model: config.efforts_of(cfg["models"][model])
            for model in (own,) if model in cfg["models"]}, **taken}
        if own not in cfg["models"]:
            return efforts
        at = config.at_efforts(cfg, held)["models"][own]["effort"]
        return config.orchestrating_at(cfg["models"], {"efforts": efforts}, own, at)

    held = {}
    for done, name in enumerate(seats):
        terminal.counting("applying", done, len(seats))
        try:
            config.change_efforts(name, given)
            # reviewers [defaults] does not name follow the executors there and here alike
            config.update_session(name, workers=defaults["workers"],
                                  reviewers=defaults.get("reviewers"))
        except (config.Error, OSError) as exc:
            note = str(exc)
        else:
            note = name in moving and orch.switch_orchestrator(cfg, name, lead, providers,
                                                               effort=effort)
            # after the move, a restart's launch dressing a bar with no roles yet
            handback.redress_seat(name)
        if note:
            held.setdefault(terminal.plain(note), []).append(name)
    if clock is not None:
        clock.sweep()
    return held


def said_once(told, held, room):
    """`told`, then what `a` said (apply_defaults), `held`, in the `room` lines the rows leave a
    note (note_lines) and no more, at this draw's width: each reason once, led by the seats it
    held, every name where they fit its line, else the first ones and how many more; where the
    reasons do not fit, the most of the first that do, at least the first, and a last line saying
    how many more there are, before which `told`'s own lines give way, and then that count; a
    first reason taller than the lines left names fewer seats until it fits them, so what was
    refused is read whole, and one no fewer names fit is cut to them, ending in `…`."""
    if not held:
        return told
    width = terminal.layout_width() - 2       # a note's line (note_lines)

    def led(why, names, lines=None):
        for count in range(len(names), 0, -1):
            lead = ", ".join(names[:count]) + (f" and {len(names) - count} more"
                                               if count < len(names) else "")
            if count == 1 or terminal.cells(lead) < width and (     # and its colon
                    lines is None or len(terminal.wrap(f"{lead}: {why}", width)) <= lines):
                return f"{lead}: {why}"
        return why

    def tall(lines):
        return sum(len(terminal.wrap(line, width)) for line in lines)

    head = told.splitlines()
    reasons = [led(why, names) for why, names in held.items()]
    shown = len(reasons)
    while shown > 1 and tall(head + reasons[:shown]) + (shown < len(reasons)) >= room:
        shown -= 1
    if tall(reasons[shown:]) == 1:
        shown = len(reasons)        # its count would take its line and say less
    more = len(reasons) - shown
    said = [*reasons[:shown], *([f"{more} more reason{'s' * (more > 1)}"] if more else [])]
    while head and tall(head + said) >= room:
        head.pop()
    if tall(said) >= room:      # no line for more: the first reason, under the note's blank line
        keep = max(1, room - 1)
        lines = terminal.wrap(led(*next(iter(held.items())), keep), width)
        said = lines if len(lines) <= keep else [
            *lines[:keep - 1], terminal.cut(" ".join(lines[keep - 1:]), width)]
    return "\n".join(head + said)


def born_mark(cfg, selected, model, column, providers):
    """Act on one of the born row's marks (born_models), in `selected` alone: the seat is not
    made yet.  What to say under the rows, or ""."""
    changed, note = orch.role_mark(cfg, selected, model, column, providers)
    selected.update(changed)
    return note


def session_mark(cfg, name, selected, model, column, providers, ask=None):
    """Act on one of a session's marks, saving it to the session's record at once.

    `column` is 0 for the orchestrator and 1 for executes and 2 for reviews, as
    `orch.role_mark` numbers them. The orchestrator moves the seat to that model under the
    same name, inside its running harness asking nothing where that harness takes the move
    (orch.switch_lines), else by a restart once `Restart` is picked on the card `ask` asks on
    (asking), the owner's 24 Oct words: "when pressing a different orch, it should
    ask me to confirm. As this restarts the session. for exec and review should be instant."
    A harness that is not installed or not logged in is refused in one line before any
    question with the seat as it was, and so is a record naming a model removed on this
    screen; a spent model is not (orch._switch_plan). An executor or reviewer mark flips
    on the record as it stands (roles_saved): the role gains the model `selected` shows
    unmarked, or loses it. Either role may be left empty, and a flip leaving no
    allowed pair is refused. A run launched afterwards reads the record as left
    here; one already going keeps the groups its receipt saved. A refusal or a save that
    fails leaves the record, and `selected`, alone. What to say under the rows, or "".
    """
    if column == 0:
        note = orch.switch_orchestrator(cfg, name, model, providers,
                                        asked=restart_asked(cfg, name, model, ask))
        if note == "":
            selected["orchestrator"] = model
        return note or ""
    return roles_saved(cfg, name, selected, lambda record, now: orch.role_mark(
        now, record, model, column, providers, shown=selected))


# A production project's feature switches are live data in the project, reached through the one
# command its AGENTS.md names under `features:`: `list`, and `set <id> you|everyone on|off`.
FEATURES_EVERY = 60     # how old a project's last `list` grows before the menu asks again
FEATURES_WAIT = 20      # the longest `list` or `set` is waited for
FEATURES_HEADS = ("you", "everyone")
_SWITCHES = {}          # checkout -> its last answer: rows, why there are none, when asked
_SWITCHES_LOCK = threading.Lock()


def switches_command(checkout):
    """The command a checkout's AGENTS.md names for its feature switches, or None."""
    return gitcall.declared(checkout, "features")


def features_run(checkout, *words):
    """The project's features command with `words` after it, as `gitcall.project_answer` runs a
    project's own command: (its JSON answer, "") or (None, the one line saying why)."""
    command = switches_command(checkout)
    if not command:
        return None, "AGENTS.md names no features command"
    return gitcall.project_answer(f"{command} {shlex.join(map(str, words))}", checkout,
                                  FEATURES_WAIT, words[0])


def switches(checkout, every=FEATURES_EVERY):
    """The checkout's feature rows as its `list` last answered, or None before any; never waits.

    Once the last `list` was asked `every` seconds ago and none is going, it is asked again in
    a thread of its own, and the draw after its answer lands shows it (`Live.watch`).
    """
    with _SWITCHES_LOCK:
        entry = _SWITCHES.setdefault(str(checkout), {"rows": None, "error": "", "asked": None,
                                                     "going": False, "set": 0, "flips": {}})
        if not entry["going"] and (entry["asked"] is None
                                   or motion.moment() - entry["asked"] >= every):
            entry["asked"], entry["going"] = motion.moment(), True     # the rule glides from it
            threading.Thread(target=_list_switches, args=(checkout, entry), daemon=True).start()
        return entry["rows"]


def switch_rows(answer):
    """The switches a features `list` answered, each a row with an id; None for no list."""
    return ([row for row in answer if isinstance(row, dict) and "id" in row]
            if isinstance(answer, list) else None)


def _list_switches(checkout, entry):
    asked = time.monotonic()
    answer, why = features_run(checkout, "list")
    rows = switch_rows(answer)
    with _SWITCHES_LOCK:
        entry["going"] = False
        if entry["set"] > asked:
            return          # a flip answered while this was asked: this list is older than it
        if rows is not None:
            entry["rows"] = rows      # a new list, never the old one changed: Live.watch compares
        entry["error"] = "" if rows is not None else why or "list answered no list"


def features_body(rows, at=None, column=0, moves=None):
    """A project's switches' lines, and where its features sit on them: {line: (row, cells)}.

    Every feature once, its name, then a mark under `you` and under `everyone`: `●` on, in
    working's blue under `you` and done's green under `everyone`, and `○` (dim) off -- the
    owner's pick of 18 Oct 2026.  One on for everyone is on for you too, and one the project does not let you
    switch for yourself has `—` under `you`.  `at` is the highlighted feature's id and `column`
    its cell the keys act on; `cells` are config_body's, for a click, and `moves` is handed its
    marks as config_body hands its own.
    """
    room, utf = terminal.layout_width(), terminal.utf8()
    on, off, fixed = ("●", "○", "—") if utf else ("*", ".", "-")
    widths = [terminal.cells(head) for head in FEATURES_HEADS]
    names = {row["id"]: str(row.get("name") or row["id"]) for row in rows}
    label = min(max(terminal.cells(name) for name in names.values()),
                max(1, room - 2 - sum(2 + width for width in widths)))
    lines = [terminal.styled((" " * (2 + label) + "".join(
        "  " + terminal.pad(head, width) for head, width in zip(FEATURES_HEADS, widths))).rstrip(),
        "dim")]
    places = {}
    for row in rows:
        everyone = bool(row.get("everyone"))
        texts = (fixed if row.get("you_switchable") is False
                 else on if everyone or row.get("you") else off, on if everyone else off)
        shown = terminal.cut(names[row["id"]], label)
        line = "  " + shown + " " * (label - terminal.cells(shown))
        cells, first = [], 2 + label + 1
        for number, (text, width) in enumerate(zip(texts, widths)):
            kind = "dim" if text in (off, fixed) else ("accent", "ok")[number]
            line += "  " + terminal.toggle(text, width, kind, at == row["id"] and number == column)
            if moves is not None:
                moves.append((len(lines), ("mark", row["id"], number), text, motion.toggled(
                    text, width, kind, at == row["id"], first + 2)))
            cells.append((first + 2, first + 1 + width, number))
            first += 2 + width
        places[len(lines)] = (("feature", row["id"]), cells)
        line = line.rstrip()
        lines.append(terminal.highlight(line, band=False) if at == row["id"] else line)
    return lines, places


def features_flip(checkout, feature, column):
    """One mark flipped by the project's own `set`, and the row it answers with drawn; what to
    say under the rows, or "".  A failed `set` changes no mark and says why in one line, and
    one of a feature asked again before it answered -- from the screen opened again after Esc
    -- is not drawn: the later one is."""
    with _SWITCHES_LOCK:
        entry = _SWITCHES[str(checkout)]
        row = next((row for row in entry["rows"] or () if row["id"] == feature), None)
    if row is None or column == 0 and row.get("you_switchable") is False:
        return ""
    on = not (row.get("everyone") or column == 0 and row.get("you"))
    with _SWITCHES_LOCK:
        asked = entry["flips"][feature] = time.monotonic()
    answer, why = features_run(checkout, "set", feature, FEATURES_HEADS[column],
                               "on" if on else "off")
    if not isinstance(answer, dict) or answer.get("id") != feature:
        return why or "set answered no row"
    with _SWITCHES_LOCK:
        if entry["flips"][feature] != asked:
            return ""
        entry["rows"] = [answer if row["id"] == feature else row for row in entry["rows"]]
        entry["set"] = time.monotonic()
    return ""


@terminal.clicks_its_own
def show_features(checkout, dry_run=False):
    """`agentkit · <project>`: its feature switches, flipped with the matrix's keys until Esc.

    The rows are the project's `list` as last answered (`switches`), asked again every TICK
    while the screen is open and drawn within STIR of landing, so the screen never waits on
    it; while it is asked the rule glides, where colour moves, and it is drawn within a frame
    of landing.  ↑/↓ move between features and ←/→ between `you` and `everyone`; Space or a
    click flips a mark by calling the project's `set` at once, off the drawing thread, the
    rule gliding the same way, and draws the row it answers with, a mark it changed filling or
    emptying; a flip before that is let go.  What a `set` could not do is one dim line under the
    rows, the mark as it was and shaking, until the next key; a `list` that failed is one too,
    for as long as the rows drawn are older than it.  A dry run draws it once.
    """
    here, column, top, note, clock = None, 0, 0, "", motion.Clock(page=True)
    keys = terminal.keys("esc back", space="mark", enter=None)

    flip = flipped = None   # the `set` asked from here, till its answer is drawn, and its mark

    def fetched():      # when the `set` or else the list now going was asked, till it lands
        entry = _SWITCHES[str(checkout)]
        return (flip.began if flip and flip.is_alive() else entry["asked"] if entry["going"]
                else None)

    while True:
        switches(checkout, TICK)
        began = fetched()       # looked at before what it lands in is read
        if flip and not flip.is_alive():
            note, flip = flip.answer(), None
            if note:
                clock.touch(flipped)  # refused: the mark shakes
        features = _SWITCHES[str(checkout)]["rows"]
        rows = [("feature", row["id"]) for row in features or ()]
        here = here if here in rows else rows[0] if rows else None
        moves = []
        body, places = (features_body(features, None if terminal.away() else here[1], column,
                                      moves) if features else ([], {}))
        # under the rows, not after them: scrolled to the last feature, a stale list still says
        # so; each one line whatever it says, so the rows stay where a click is read against them
        said = [terminal.cut(line, terminal.layout_width() - 2) for line in (
            _SWITCHES[str(checkout)]["error"] or ("" if features else "no features"
                                                  if features == [] else "asking for its features"),
            note) if line]
        if dry_run:
            terminal.frame(checkout.name, body + [terminal.styled("  " + line, "dim")
                                                  for line in said], "esc back")
            return
        act, here, clicked, top = matrix_key(checkout.name, body, places, rows, here, top,
                                             "\n".join(said), keys, STIR, began=began,
                                             going=lambda: fetched() == began,
                                             clock=clock, moves=moves)
        column = column if clicked is None else clicked
        if act is None:
            continue                  # a resize, the pointer, or a look at whether it landed
        note = ""
        if act == "back":
            return
        if act in ("left", "right"):
            column = 1 if act == "right" else 0
        elif act == "space" and here and flip is None:
            flipped = ("mark", here[1], column)
            flip = Fetch(lambda feature=here[1], column=column:
                         features_flip(checkout, feature, column))


def past_offered(found):
    """Whether the past screen has a row, so `p` is a key and the key line offers it: a seat
    the owner stopped is among `found` (`closed`, `orch.ghost`)."""
    return any(session.get("closed") for session in found)


def closed_when(closed, now=None):
    """`closed`'s day and time: `today` `10:24`, `this week` `Sat 12:31`, `earlier` `20 Oct`."""
    at = time.localtime(closed)
    days = max(0, (datetime.date.fromtimestamp(time.time() if now is None else now)
                   - datetime.date.fromtimestamp(closed)).days)
    if days > 6:
        return "earlier", f"{at.tm_mday} {time.strftime('%b', at)}"
    return ("today", "yesterday", "this week")[min(days, 2)], time.strftime(
        "%a %H:%M" if days > 1 else "%H:%M", at)


def past_said(session):
    """What a past row opens: its first done line's first sentence, and its restart note."""
    done = (plan.first_done(session["name"]) or "").strip()
    return re.match(r".*?[.!?](?=\s|$)|.*", done)[0], session.get("restart") or ""


def past_body(past, at=None, room=None, said=None, now=None):
    """The past screen's (lines, places, moves, page, turns): `past` under the day each closed,
    `at` lit and opening its `said`, on its page of `room` lines; every row's `said` from a pipe."""
    width, stands = terminal.content_width(), orch.listed()
    rows = [(str(number), session["name"], orch.project_name(orch.checkout_of(
        session.get("repo"), stands=stands), ""), *closed_when(session["closed"], now),
        seat_progress(session["name"])) for number, session in past]
    num, name, project, clock = (max(terminal.cells(row[n]) for row in rows) for n in (0, 1, 2, 4))
    name, project = min(name, 24, width - (2 + num + 2)), min(project, width - 4)
    free = width - (2 + num + 2 + name + 2 + project + 6 + clock)
    # no room for a row on one line: what follows its name goes under it
    fold = free < max(len(f"{done} of {total}") if total else 7 for *_, (done, total) in rows)
    indent, under = " " * (2 + num + 2), width - (2 + num + 2)
    opened = {seat: terminal.wrap(sentence, under) + [
        terminal.styled(line, "dim") for line in terminal.wrap(restart, under)]
        for seat, (sentence, restart) in (said or {}).items()}
    lit, days, spans = not terminal.away(), {}, {}
    for number, seat, home, day, closed, (done, total) in rows:
        bar = (terminal.plan_bar(done, total, 0 if fold else free, 0, "done" if done == total
                                 else "idle") if total else terminal.styled("no plan", "dim"))
        head = "  " + _styled_cell(number, num, "dim", right=True) + "  " + _styled_cell(seat, name)
        tail = [_styled_cell(home, project, "dim"), bar + " " * max(0, free - terminal.cells(bar)),
                closed.rjust(clock)]
        block = ([head + "  " + "  ".join(tail)] if not fold else [head, *(
            "    " + line for line in packed([part.strip() for part in tail if part.strip()],
                                             "  ", width - 4))])
        block += [indent + line for line in opened.get(seat, [])] if at is None else []
        spans[seat] = line_at(block[0])
        days.setdefault(day, []).append([(terminal.highlight(line, mark=n == 0)
                                          if lit and seat == at else line, seat)
                                         for n, line in enumerate(block)])
    pages = project_pages([((terminal.styled(day, "bold"), None), blocks)
                           for day, blocks in days.items()],
                          # a page holds a heading and its row whatever the row opens
                          max(1 + max(len(block) for blocks in days.values() for block in blocks),
                              (room or sys.maxsize) - max(map(len, opened.values()), default=0)),
                          apart=False)
    page = next((n for n, lines in enumerate(pages) if any(seat == at for _, seat in lines)), 0)
    shown = pages[page]
    where = max((n for n, (_, seat) in enumerate(shown, 1) if seat == at), default=0)
    # under a card the row stays open, unlit: the card and its answers where they were
    told = opened.get(at, []) if where and not terminal.off_rows() else []
    shown = shown[:where] + [(terminal.highlight(indent + line, mark=False) if lit
                              else indent + line, at) for line in told] + shown[where:]
    moves = [(n, ("page",), page, motion.fading(line))
             for n, (line, _) in enumerate(shown)]
    moves += [(n, ("opened",), at, motion.fading(shown[n][0]))
              for n in range(where, where + len(told))]
    rowed = [n for n, (_, seat) in enumerate(shown) if seat and spans[seat]
             and (n == 0 or shown[n - 1][1] != seat)]
    moves += [(n, ("bar", shown[n][1]), None, lambda clock, row, since, _, line=shown[n][0],
               span=spans[shown[n][1]], began=after * motion.STAGGER: grow_line(
                   clock, row, line, span, lambda cells: motion.growing(cells, since + began),
                   (0, since + began, motion.GROW))) for after, n in enumerate(rowed)]
    return ([line for line, _ in shown],
            {n: (("row", seat), []) for n, (_, seat) in enumerate(shown) if seat},
            moves, page, [next((seat for _, seat in lines if seat), None) for lines in pages])


@terminal.clicks_its_own
def show_past(cfg, found, dry_run=False, keyboard=None):
    """`past sessions`, `p` (`past_body`): a digit, Enter or a click reopens one (`open_session`),
    True said; `x` asks (`terminal.confirm`) before `remove_seat`.  A dry run draws it once."""
    here, clock, said, top = None, motion.Clock(page=True), {}, 0
    for session in found:
        clock.touch(("bar", session["name"]))     # news once, as the screen opens
    while True:
        past = list(enumerate(sorted((session for session in found if session.get("closed")),
                                     key=lambda session: -session["closed"]), 1))
        if not past:
            return
        names = [session["name"] for _, session in past]
        if not terminal.taken():
            keys = "x remove   esc back"
            terminal.frame("past sessions", past_body(past, said={
                session["name"]: past_said(session) for _, session in past})[0], keys)
            if dry_run:
                return
            line = read("> ", "")
            if not line or terminal.is_esc(line):
                return
            if line.isdecimal() and line.isascii() and 1 <= int(line) <= len(past):
                open_session(cfg, past[int(line) - 1][1], dry_run)
                return True
            elif line.lower() == "x":
                choice = terminal.ask("Remove", names[0], names, read=read,
                                      numbers=[number for number, _ in past])
                if choice:
                    remove_seat(choice, dry_run)
                    found = [session for session in found if session["name"] != choice]
            else:
                pause(f"not a key: {line!r}", keys)
            continue
        keys = terminal.keys("x remove", "esc back", enter="reopen")
        here = here if here in names else names[0]
        said.update((session["name"], past_said(session)) for _, session in past
                    if session["name"] not in said)

        def laid():
            """The rows at the terminal's size now, `here` lit on its page."""
            room = matrix_page([], {}, None, 0, [], keys, lead=page_mark(98, 99))[1]
            return past_body(past, here, room, said)
        body, places, moves, page, turns = laid()
        first = page_mark(page, len(turns)) if len(turns) > 1 else None
        act, row, _column, top = matrix_key("past sessions", body, places,
                                            [("row", name) for name in names], ("row", here),
                                            top, "", keys, clock=clock, moves=moves, lead=first)
        top = top if row[1] == here else 0      # another row is another body, from its start
        here = row[1]
        if act is None:
            continue              # a resize or the pointer: drawn again
        if act == "back":
            return
        if act in ("left", "right"):
            here = turned(turns, page, here, 1 if act == "right" else -1)
            continue
        if act.isdecimal() and act.isascii() and 0 < int(act) * 10 <= len(past):
            more = terminal.read_key(0.5)      # 1 then 2 within half a second is row 12
            act += more.char if more and more.name == "char" and more.char.isdecimal() else ""
        if act == "enter" or act.isdecimal() and act.isascii() and 1 <= int(act) <= len(past):
            open_session(cfg, past[names.index(here) if act == "enter" else int(act) - 1][1],
                         dry_run, keyboard=keyboard,
                         starting=lambda: terminal.doing("past sessions · starting"))
            return True
        if act == "x" and not terminal.unseen():     # unseen, it only brings the highlight back
            leaving = []

            def around(card, keys):
                # the rows laid out anew, a resize's; in what a frame holds unscrolled at this
                # height (`terminal.written` ends in a newline), the card to its answers, its top
                # giving way where that is too little, then the rows round it in what is left;
                # none where the answers are not
                holds = terminal.height() - 4 - len(terminal.key_line(keys))
                if holds < 2:
                    return None
                body, places = laid()[:2]
                mine = [line for line, (row, _) in places.items() if row == ("row", here)]
                at = max(mine) + 1
                lines, skip = body[:at] + card + body[at:], max(0, at + len(card) - 1 - holds)
                leaving[:] = range(3 + max(0, min(mine) - skip),
                                   3 + min(holds, at + len(card) - skip))
                return framed(clock, "past sessions", lines[skip:skip + holds], at - skip, card,
                              keys, page_places(places, skip, at - skip))
            if asking(clock, around)(f"Remove {here} from past sessions?",
                                     "It can no longer be reopened.", "Remove"):
                fade_out(clock, leaving)
                keyboard.give()       # the stop says what it did where it can be read
                clock.forget()        # another screen: the page back from it is drawn as it is
                remove_seat(here, dry_run)
                keyboard.take()
                found = [session for session in found if session["name"] != here]


def remove_seat(name, dry_run):
    """The past screen's `x`: the owner's, as `x` on the main screen is (`Live.stop`), so a seat
    the menu is over refuses no other seat's removal; a refusal waits there as a notice."""
    subprocess.run(teardown(name, dry_run), cwd=config.REPO, env=config.owner_env(),
                   stdin=subprocess.DEVNULL)


def page_mark(page, pages, arrows=True, needs=(False, False)):
    """Where the owner is, `←  2 / 3  →`, for the key line to lead the keys with, wrapped with
    them as one more item: each arrow a key a click turns the page with, amber where a seat that
    needs the owner is that way (`needs`, back and on), the place between them none.  From a
    pipe, which turns pages with `j` and `k`, the place alone, `2 / 3`."""
    arrow, ahead = ("←", "→") if terminal.utf8() else ("<", ">")
    tone = ["amber" if need else "dim" for need in needs]
    return (
        f"{terminal.styled(arrow, tone[0])}  {page + 1} / {pages}  "
        f"{terminal.styled(ahead, tone[1])}" if arrows else f"{page + 1} / {pages}")


def turned(turns, page, cursor, step):
    """Where ← (`step` -1) or → (1) takes the highlight from `page`: to the first thing it can
    rest on (`turns`, each page's) of the nearest page that way holding one, passing a page
    with none -- only a heading, or the rest of a tall seat; else it stays on `cursor`."""
    ahead = range(page + step, len(turns) if step > 0 else -1, step)
    return next((turns[n] for n in ahead if turns[n] is not None), cursor)


def pressed(key, drawn, found):
    """What one `terminal.Key` asks of the main screen, in the line menu's own words.

    Enter is the highlighted seat's number, and a click on any line of a seat is that seat's;
    on a project's heading either is that project's checkout, whose switches it opens, and on a
    meter that meter, ("usage", number).
    A click on the key line is the key of the item under it, `⏎ open` being Enter; Esc, a click
    on `esc leave` and a keyboard that is gone are ESC, which leaves; a character is itself;
    anything else is "", which asks for nothing.  `drawn` is the layout on the screen when the
    key was read, so a click lands where he saw, and `found` the seats now, so a seat is
    opened by the number it has now.
    """
    numbers = {session["name"]: str(number) for number, session in enumerate(found, 1)}

    def opens(name):
        return name if isinstance(name, (Path, tuple)) else numbers.get(name, "")
    if key.name == "click":
        spot = terminal.under(key, drawn["spots"])
        if spot.what is not None:
            return opens(spot.what)
        item = spot.cell or ""
        if item not in ("⏎", "enter", "esc"):
            return item if len(item) == 1 else ""
        key = terminal.Key({"⏎": "enter"}.get(item, item))
    if key.name == "enter":
        return opens(drawn["cursor"])
    if key.name in ("esc", "eof"):
        return terminal.ESC
    return key.char if key.name == "char" else ""


def loop(cfg, client=False, dry_run=False, overlay=False, tidy=None, said=()):
    """The menu until Esc, or from a pipe until an empty line or the end of input.

    `overlay` is the menu as a tmux popup over a running seat, the same menu with its highlight
    starting on that seat.  A number, `n` and a past session reopened hand this client to a
    session, and the popup has to come down for it to be seen, so those return, as `x`, which
    stops the popup's own seat alone, does before the stop ends.  Read a line at a time, `j` and `k` turn the pages of a list
    longer than the screen, and a number is answered from whichever page is up.

    The main screen is live: the read waits at most TICK seconds, and a wait that ends with
    nothing typed draws again, so the clock, the seat rows, the counts on the top line and the
    usage stay true in front of whoever left it open -- and it ends within STIR of any seat's
    record, the usage cache or config.toml changing, so a row never says for longer what its bar
    or the config no longer does, a run at rest aside (`Live.watch`, `Live.configure`).  Nothing
    is read between a key and its frame: the seats, their runs and their rows are read once
    before the first draw, then in `Live`'s thread -- on the clock, after a key
    that did more than move the highlight, and within STIR of a record changing -- and every
    draw is what the last read left, drawn again when the next one lands.  While the owner is in
    a seat it opened, or on the screen that opens one, nothing is read but by the pass a seat
    listed was still owed (`Live.away`), and back, the menu is drawn at once as it was and read
    again behind it, what changed meanwhile coming in as news (`Live.back`).  The clock and those
    keys have every seat looked at again as well, in a thread of its own (`Live.look`), so no
    seat's capture holds up a read or a draw: the first draw is the records as they stand, and
    a look landing has them read and drawn again.  The first draw's meters are the cache's, and
    the probe that follows it runs in a thread and asks for one more draw when it lands.  So
    does `tidy`, `main`'s maintenance (`Live.tidy`): a warning it gives is a notice as it lands;
    `said`, what `main` had to say before, is the first.
    Nothing here waits on an adapter, and a key typed during a draw is read by the next wait.
    Between draws the working seats' dots breathe, and what changed since the draw before moves
    once, a frame whenever the clock says one is due and no key is waiting (`moving`), so a key
    is read within a frame of being pressed.  A key that opens another screen, a notice and a
    resize have the clock forget what it saw, so the menu after them replays nothing.  The
    popup's content fades in on that clock, and a key pressed while it does is answered as at
    any other time, its draw coming up with the rest; the popup closes the moment its menu ends.

    On a terminal the menu has the keyboard (`terminal.Keyboard`) and there are no lines: a
    key acts the moment it is pressed.  One seat row is highlighted; ↑/↓, k/j and the wheel
    move it and the page up follows it; Enter opens it.  A click on a row opens that seat and
    a click on the key line does what its key does, each once the button is up; the pointer
    on a row moves the highlight there, and on a key-line item lights it (`draw`).  ↑ past the
    first seat, or from under the grid with none, reaches the meters, and Enter or a click on
    one opens its row on `Subscriptions` (config_subscriptions), the highlight on it back from
    there.  A digit waits half a second for a second one, a resize or not, and a key read while
    it waits is kept for after, with the screen it was read on.  The highlight is the seat's
    name, so it stays on its seat whatever comes or goes above it, and a meter's its
    subscription's.  A key that does nothing here is let go without a word, `i` among them, and
    every key that does something gives the terminal back
    before it does it -- but `c`, `n` and `x`'s question, which are read with the keys on
    the screen the menu has: `x`, in a popup only, closes its own seat at once when done and
    otherwise asks `Keep` or `Stop` under that seat's row, Enter or a click answering and Esc keeping it; `p` opens the past
    screen (`show_past`) on the same keys, and is a key only while the key line offers it
    (`past_offered`).  Esc, and a click
    on `esc leave`, leaves at once, whatever a thread is doing (`Live.close`); `q` is no key.

    A test driving this mocks `wait_key` beside `read`: the real wait selects on stdin, and a
    stdin that never delivers EOF redraws forever instead of finishing.  It leaves `Live`'s
    probe unstarted: its thread calls `usage.collect` after the test's mock is gone.
    """
    own = config.current_session() if overlay else None     # the seat the popup is over
    restarted = "AK_MENU_CURSOR" in os.environ    # by the exec below: the same screen, on new code
    cursor = restored(os.environ.pop("AK_MENU_CURSOR", ""), os.environ.pop("AK_MENU_METER", ""),
                      cfg) or own
    page, ahead, look, updating, updated = 0, None, False, None, False
    pointing = False                      # the highlight is where the owner points (`draw`)
    updates = []                         # this loop's inbox, independent of the usage/read worker
    start_update = not (dry_run or overlay)
    last = [[], None]                     # what the last read left: the seats and their groups
    clock = motion.Clock(fade=overlay)    # what moves between draws: the dots, news, and
                                          # the popup's first draw coming up
    clock.grows = {} if restarted else None     # nothing opened, so no line grows in again
    with closing(Live(cfg)) as live, closing(terminal.Keyboard()) as keyboard:
        live.said.extend(said)
        if keyboard.take():
            terminal.sense()              # true colour and the background, once, before a draw
        live.watch(last)                  # read once, now: the first draw has nothing else
        back = False                      # back from a seat, or the screen that opens one
        newborn = None                    # the seat `n` is typing the name of (`born`)
        framed = False                    # the last wait read no key: its frame is still up
        while True:
            live.configure()              # what `c` here saved, drawn at once
            was, cfg = cfg, live.cfg
            if isinstance(cursor, tuple):
                cursor = followed(cursor, usage_rows(was), usage_rows(cfg))
            if back:
                live.back()               # drawn as the last read left it, read behind it
                clock.forget()            # drawn anew: nothing it drew before fades or replays
                back = False
            elif look:
                live.ask(look=True)       # read and looked at again, off the draw
            # a seat being named keeps its row: notices and new code wait for it to go
            messages = orch.job_notices() + live.heard() if newborn is None else []
            if updates and newborn is None:
                news = updates.pop(0)
                if "progress" in news:
                    updating = news["progress"]
                else:
                    updating, updated = None, news.get("moved", False)
                    messages += news.get("lines", [])
            if messages:
                keyboard.take()           # a notice is a sub-screen of the menu's (`pause`)
                show_notices(messages)
                clock.forget()            # and the menu it comes back to replays nothing
                pointing = False
            # new code under an open menu, the tick's above all, draws it from here on, once
            # the menu's own update, whose install follows its swap, has said how it went; over a
            # frame the terminal holds till the next one, so back from a seat or a notice the
            # list comes up first, and no key is cut short; and so does reads stopping, once the
            # tick's log says why (`Live.stuck`)
            stuck = live.stuck()
            if (framed and not messages and newborn is None
                    and (stuck or updated or (updated is False and update.outdated()))):
                if stuck:
                    tidy_log(live.say)(stuck)
                handing = {**(warm.hand_on(last, CODE) if last[1] else {}), **terminal.hand_on(),
                           **live.hand_on()}
                live.close()
                keyboard.give(held=True)
                sys.stdout.flush()
                here = (subscription(usage_rows(cfg)[cursor[1] - 1]) if isinstance(cursor, tuple)
                        else cursor)      # as `restored` reads it
                os.execve(sys.executable, [sys.executable, *sys.argv], {
                    **os.environ, **handing, "AK_MENU_CURSOR": json.dumps(here or "", default=str)})
            found, groups = last          # after any notice: what changed under it is drawn as is
            past = past_offered(found)
            # `x` is only the popup's, for its own seat while that has a row: no screen stops
            # another seat (the owner, 27 Oct 2026)
            word = next((info["word"] for info in (groups or [(), ()])[1]
                         if info["name"] == own), None)       # no groups: draw reads them
            keys = KEYS if word is None else KEYS.replace(
                "n new", f"n new   x {'close' if word == 'done' else 'stop'}", 1)
            actions = ("n", "c") + ("p",) * past + ("x",) * (word is not None)
            drawn = {} if keyboard.take() else None
            if drawn is not None and terminal.follow(ask=framed):
                clock.forget()
            listed = (keys if drawn is None else BORN_KEYS if newborn
                      else terminal.keys(keys, enter="open"))
            page, pages = draw(cfg, found, listed, page, BORN if newborn else cursor, drawn,
                               look=False, groups=born_groups(groups, newborn) if newborn
                               else groups, clock=clock, updating=updating, pointing=pointing)
            if drawn and not newborn:     # the seat he sees highlighted, and if he points at it
                cursor, pointing = drawn["cursor"], drawn["pointing"]
            if start_update:
                update_first(live, updates=updates)    # detached, after the first frame
                start_update, updated = False, None    # None until it says how it went
            live.probe()                  # after the draw, never before it: the cache is enough
            if tidy is not None:
                live.tidy(tidy)           # maintenance too: the first draw is as recorded
                tidy = None
            if ahead is not None:
                (key, shown), ahead = ahead, None
            else:
                key, shown = moving(clock, live.reader, timeout=0 if updates and newborn is None
                                    else TICK), drawn
            framed = key is None
            if key is None:
                # the wait ended on the clock, which looks again, or on news already written down
                look = not live.drain()
                continue
            look = True
            if newborn is not None and isinstance(key, terminal.Key):
                if key.name != "point":   # a key ends its row's coming up on its last frame
                    clock.settle()
                act, look = born_key(newborn, key, shown), False
                if act == "models":
                    back = True           # the models screen, drawn where the menu was
                    live.away()
                    act = "start" if born_models(newborn, keyboard) else act
                if act == "back":
                    newborn = None
                elif act == "start" and not born_refusal(newborn):
                    # while the seat is made, no key read
                    if dry_run:
                        keyboard.give()   # it only says what it would start
                    elif terminal.follow() or back:   # new shades or back from models: drawn anew
                        draw(cfg, found, listed, page, BORN, {}, look=False,
                             groups=born_groups(groups, newborn), updating=updating,
                             pointing=pointing, doing="starting")
                    else:
                        terminal.doing("starting", shown["titled"])
                    made, newborn, back = newborn, None, True
                    live.away()
                    try:
                        name = start_born(made, dry_run, keyboard.give)
                    except config.Error as exc:
                        name = None
                        if not dry_run:
                            keyboard.take()   # given to a harness that could not take it
                        pause(f"new session: {exc}")
                    if name and overlay:
                        return 0          # the popup's client is on the new seat
                    cursor = name or cursor
                if act != "gone":
                    continue
                newborn = None            # a keyboard that is gone leaves, as Esc on the menu
            if isinstance(key, terminal.Key):
                order = drawn["order"]
                if key.name == "point":
                    spot = terminal.under(key, shown["spots"])
                    cursor, pointing = spot.what or cursor, spot.what is not None
                    look = False          # the highlight moves over what is in hand
                    continue
                if terminal.step(key):
                    if key.name.startswith("wheel"):  # a swipe stops at the seats' end, or the
                        order = [name for name in order        # meters': a key goes on past
                                 if isinstance(name, tuple) == isinstance(cursor, tuple)]
                    if order:     # with no seat highlighted, from under the meters
                        at = (order.index(cursor) if cursor in order
                              else len(order)) + terminal.step(key)
                        cursor = order[min(max(at, 0), len(order) - 1)]
                    look, pointing = False, True   # the highlight moves over what is in hand
                    continue
                # ← and →, or a click on either arrow in front of the keys, turn the page
                turn = ({"←": -1, "<": -1, "→": 1, ">": 1}.get(pressed(key, shown, found), 0)
                        if key.name == "click" else {"left": -1, "right": 1}.get(key.name, 0))
                if turn:
                    cursor = turned(shown.get("turns") or [], page, cursor, turn)
                    look, pointing = False, False
                    continue
                typed, key = key, pressed(key, shown, found)
                if (typed.name == "char" and len(key) == 1 and "1" <= key <= "9"
                        and int(key) * 10 <= len(found)):
                    # 1 then 2 within half a second is seat 12, whatever asks for a draw between
                    more, until = None, time.monotonic() + 0.5
                    while more is None and time.monotonic() < until:
                        more = moving(clock, timeout=until - time.monotonic())
                        pointed = more is not None and more.name == "point"
                        if pointed:                                      # cuts no wait short
                            spot, more = terminal.under(more, drawn["spots"]), None
                            cursor, pointing = spot.what or cursor, spot.what is not None
                        if more is None and time.monotonic() < until:
                            # a resize or the pointer: drawn anew, so the dots breathe on where
                            # they now are
                            if terminal.follow(ask=not pointed):
                                clock.forget()
                            page, pages = draw(cfg, found, listed, page, cursor, drawn,
                                               look=False, groups=groups, clock=clock,
                                               updating=updating, pointing=pointing)
                            pointing = drawn["pointing"]
                    if isinstance(more, terminal.Key) and "0" <= more.char[:1] <= "9":
                        key += more.char
                    elif more is not None:
                        ahead = (more, drawn)     # read early: kept, with the screen it was read on
                # whatever the key opens, the menu back replays nothing; the digit wait before
                # it is still the menu, where the highlight fades as anywhere on it, and so is
                # the card `x` asks on, the key ending what moves as one does on a page
                if key in ("x", "X"):
                    clock.settle()
                else:
                    clock.forget()
                if isinstance(key, Path):
                    cursor = key              # the heading, highlighted when he is back
                    show_features(key, dry_run)    # read with the keys, on the screen the menu has
                    continue
                if isinstance(key, tuple):
                    cursor = key              # the meter, highlighted again back from it
                    # a save it refused, in a notice: this screen has no line under it for one
                    note = config_subscriptions(cfg, keyboard, key[1])
                    if note:
                        pause(note)
                    continue
                key = key.lower()
                if key.isdecimal() and key.isascii() and 1 <= int(key) <= len(found):
                    cursor = found[int(key) - 1]["name"]   # and highlighted when he is back
                elif not terminal.is_esc(key) and key not in actions:
                    continue
            if not key or terminal.is_esc(key):
                return 0          # Esc leaves the menu; from a pipe an empty line or its end
            if terminal.is_sequence(key):
                continue          # an arrow key is neither Esc nor a key: draw again, silently
            key = key.lower()
            pointing = False      # the key opens something: the menu back opens no line
            if key == "x" and drawn is not None and word is not None:
                # the popup's own seat, whichever row is highlighted: a done one closes at once,
                # any other is asked under its row, highlighted
                cursor = own
                if word != "done":
                    # its runs are counted off the draw, so the card is up at once whatever
                    # the disk; one counted within a frame is simply had, a later one drawn in
                    runs, counted = Fetch(lambda: len(transitions.seat_runs(own))), [False]
                    runs.join(motion.FRAME)

                    def means():
                        counted[0] = not runs.is_alive()
                        return stop_means(runs.got.get("answer"))

                    def around(card, keys):   # the menu around the card, drawn again on a resize
                        draw(cfg, found, keys, page, cursor, drawn, ask=(own, card),
                             look=False, groups=groups, clock=clock)
                        return drawn["ask"]
                    ask = asking(clock, around, lambda: None if counted[0] else runs.is_alive)
                    if not ask(STOP_ASK.format(own), means, "Stop"):
                        continue
                stop_behind(own, dry_run)
                return 0                      # the popup over it goes first
            if key == "n" and drawn is not None and cfg:
                try:
                    newborn = born(found)     # typed where it will be
                    clock.touch(("born",))    # news: its row comes up
                except Back:
                    pass
                except config.Error as exc:
                    pause(f"new session: {exc}")
                continue
            if not key.isdigit() and key not in ("c", "n", "p", "r"):
                keyboard.give()           # whatever the key opens has the terminal as it was,
                                          # a seat as `open_session` gives it
            if key.isdigit() or key in ("n", "p"):
                back = True               # each can hand the owner a seat, where nothing is read
                live.away()
            if key.isdigit():
                if 1 <= int(key) <= len(found):
                    open_session(cfg, found[int(key) - 1], dry_run, keyboard=keyboard,
                                 starting=lambda: terminal.doing("starting", drawn["titled"]))
                    if overlay:
                        return 0
                else:
                    pause(f"no session {key}")
            elif key == "n":
                try:
                    if new_session(cfg, dry_run, keyboard, found) and overlay:
                        return 0
                except config.Error as exc:
                    pause(f"new session: {exc}")
            elif key == "x" and word is not None:
                if stop_session(own, dry_run):
                    stop_behind(own, dry_run)
                    return 0
            elif key == "c":
                # the popup's own seat, whichever row is highlighted, and in a window of its own
                # new seats (the owner, 24 Oct 2026); read with the keys
                show_config(dry_run, keyboard, own)
            elif key == "p" and past:
                if show_past(cfg, found, dry_run, keyboard) and overlay:   # read with the keys
                    return 0              # a seat reopened: the popup's client is on it
            elif key in ("j", "k") and pages > 1:
                page = (page + (1 if key == "j" else -1)) % pages
            elif key:
                pause(f"not a key: {key!r}", keys)


# --- on a client ------------------------------------------------------------


def client(alias, dry_run, hops, options=()):
    """The menu of the home at `alias`, over ssh given `options` first, told by one `--client` a
    hop how many hops it is reached over: a client's client goes no further (`main`)."""
    cmd = ["ssh", *options, "-t", alias, "ak", *["--client"] * hops]
    if dry_run:
        print(f"would run {shlex.join(cmd)}")
        return 0
    try:
        return subprocess.run(cmd).returncode
    except OSError as exc:
        raise config.Error(f"cannot run ssh: {exc}")


ANSWERS = 10    # seconds a client's home has to name its takers, and each menu's ssh to connect


def client_menu(home):
    """A client's own menu: its home's, and where ssh reached no machine there (its exit 255,
    which a connection broken midway exits too), that of the first ssh reaches of the machines
    the home last named as taking over from it (`takers`), in their order, else 255.  Where it
    named any, each ssh, the home's too, has ANSWERS seconds to connect: a home without power
    refuses nothing, and ssh waits on it as long as the system lets it, over a minute on a Mac.
    A home that answered is asked again whom it names, within ANSWERS, connecting included: a
    slower one leaves the older list.  The menu exits as the hop did, whatever the asking meets."""
    names = takers.read()       # before the hop, which writes none where it exits 255
    options = ["-o", f"ConnectTimeout={ANSWERS}"] if names else []
    code = client(home, False, 1, options)
    if code != 255:
        try:
            asked = subprocess.run(standby._home(home, "--takers"), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   timeout=ANSWERS)
            if asked.returncode == 0:
                takers.write(asked.stdout)
        except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
            pass        # the list as it was, a Ctrl-C on a slow home's answer among them
        return code
    for name in names:
        if (code := client(name, False, 1, options)) != 255:
            break
    return code


def update_first(live=None, updates=None):
    """Check and update in a detached process; a client's ssh starts without waiting for it.

    The child has no terminal and keeps going after Esc. Only the main loop reads its messages,
    so an open sub-screen keeps its keys and drafts until the owner comes back. A worktree's
    menu never updates the live checkout under it, as with the tick (update.go_live).  With
    `live`, a result always comes, from an update that never started too: the menu hears it out
    before new code restarts it (`loop`).
    """
    updates = [] if updates is None else updates
    def result(*lines):             # the main screen clears progress through this completion path
        if live:
            updates.append({"moved": False, "lines": list(lines)})
            live._wake()
    if update.agentkit_dir().resolve() != config.REPO:
        return result()
    try:
        proc = subprocess.Popen([sys.executable, "-m", "agentkit.update", "--agentkit"],
                                cwd=config.REPO, env=owner.unmarked(config.child_env()),
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE if live else subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                start_new_session=True)
    except OSError as exc:
        return result(f"update: {exc}")
    if live:
        def hear():
            ended = False
            with proc.stdout:
                for line in proc.stdout:
                    news = json.loads(line)
                    ended = "moved" in news
                    updates.append(news)
                    live._wake()
            code = proc.wait()
            if not ended:
                result(f"update: agentkit update exited {code} without a result")
        threading.Thread(target=hear, daemon=True).start()
    return proc


def main(argv):
    """The menu.  `--overlay` is the popup inside a seat, and never leaves this machine: on a
    client, which has no seat, the command prints whose client this is and exits 1.

    A popup is opened over tmux sessions that are here, so it neither hops to the server the
    way a client's menu does nor runs the maintenance that a menu opening a seat runs: reaping
    runs and retiring seats over a session the user is sitting in is not what `Ctrl-b m` was
    pressed for. A client's update starts detached before ssh; the server's starts behind the
    first frame (update_first). Neither an overlay nor a dry run starts one.

    A client's `--client` is another client's menu passing through, the old home's after a
    standby took over: it goes on to this machine's home, once, saying so with `--client` twice,
    before any of this machine's own: its bridge, its config's lock, its slice, its update (a
    standby follows its home by its passes).  Twice, a client goes no further, so two records
    naming each other never chain ssh sessions.
    """
    if command_help.show("attach", argv):
        return 0
    flags = dict.fromkeys(("--client", "--overlay", "--dry-run"), 0)
    for arg in argv:
        if arg not in flags:
            config.migrate_policy()     # as bin/ak renames before any other command's refusal
            raise config.Error(f"{USAGE}  (got {arg!r})")
        flags[arg] += 1
    home = config.server_alias()
    if home and flags["--overlay"]:
        # The popup is the menu over a seat here, and a client's seats are on its home: a
        # standby's records of them are a copy of that home's, and a row picked in this menu
        # would open one a second time, as its boot resume did on 22 Nov 2026.
        print(f"this machine is a client of {home} and opens no seat: its seats are on {home}")
        return 1
    if home and flags["--client"] > 1:
        print(f"this machine is a client of {home} and opens no menu for another client")
        return 1
    if home and flags["--client"]:
        return client(home, flags["--dry-run"], 2)
    # painted, and in a popup inside the border what it asks to be left
    terminal.screens(popup=flags["--overlay"])
    if not flags["--dry-run"]:
        from . import macbridge
        macbridge.start_background()
    from .pause import stands_still     # by name: this module's own `pause` is a notice
    # The menu that would open here says ak stands still before the config's and the state's
    # locks and the seats' tmux server, which a frozen slice may hold for good; past that, old
    # config names are renamed, as bin/ak does before every other command.
    if not (home or flags["--overlay"]) and (still := stands_still()):
        print(still)
        return 1
    config.migrate_policy()
    if home and flags["--dry-run"]:
        return client(home, True, 1)
    if home:
        update_first()
        return client_menu(home)
    from . import watch
    messages = []     # a dry run's are what it would do, for the owner to read
    watch.resume_after_boot(config.load(), dry_run=flags["--dry-run"], log=messages.append
                            if flags["--dry-run"] else tidy_log(messages.append))
    # what `ak orch` does on the way into a seat, gc and the runs nobody was told about, run
    # behind the menu's first frame
    tidy = None if flags["--dry-run"] or flags["--overlay"] else orch.maintenance
    code = loop(config.load(), flags["--client"], flags["--dry-run"], flags["--overlay"], tidy,
                messages)
    if flags["--overlay"]:
        # The popup comes down when this process ends, and Python's own teardown of all the menu
        # read took most of a second.  Nothing is cut short: a record is only ever replaced
        # whole, and the menu's threads are daemons, which no exit waits for.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
    return code
