"""`ak`: the menu.  Numbers and single letters, and nothing else: on a terminal each one acts
the moment it is pressed, and from a pipe it is a line.

    agentkit                                                              14:02
    ────────────────────────────────────────────────────────────────────────
      Claude I    ▰▰▱▱▱▱▱▱▱▱  21% left   ChatGPT     ▰▰▰▰▰▰▰▱▱▱  69% left


    atoll
    › 1  atoll-speed-check   fable   ! needs you   ━━━━━━━━━━━━━──────── 3 of 5
           Merge the MOV helper before or after?
      2  fix-api             fable   ● working     ━━━━╸───────────────── 2 of 9
      3  web-portal          fable   ✓ done

      ↑↓ move   ⏎ open   n new   x stop   c config   esc leave

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
waiting to land too, else empty -- and `✎ unsent` after it where the owner left text unsent.
What a seat left unsent, then what it asks or did, else who builds and reviews and each task's
squares (`crew`, `squares`), open under the row (`detail`).  Never two state words on one row,
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
subscription holds usage-limit resets for the owner to spend on `c`, then `? <reason>` when
the last probe errored though the meter it read still stands, and `as of HH:MM` beside it when
that reading is older than half an hour, with the weekday when it is not from today.
A probe the endpoint would not answer says nothing at all: its reading stands as it was,
and past half an hour its age says the rest.
The bar's filled cells are the company's own colour (`COLOURS`, or the provider's `colour`
key) until little is left: amber from 20% left, red from 5% (`fill`); the rows run red
through violet by the hue of that colour, the near-greys last.  `—` is drawn
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
glides -- then is still.  The sub-screens are not live: they are read once, like any other
question -- but a project's feature switches, which draw again within a second of their `list`
landing.

Six keys: the numbers, `n`, `x`, `p` (the sessions you stopped, offered while there is one),
`c` (the highlighted seat's models, every model's effort,
providers, discord, version), and Esc, which leaves, as it goes back from every
screen and question under it; `q` is no key.  Nothing needs a manual: the pointer lights what
it rests on and says nothing more of it on the key line.  A question typed inside the menu is
typed on its
keys (`terminal.field`), so Esc cancels it at once.  From a pipe an empty line or the end of
input leaves, or goes back.
On a terminal one seat row is highlighted as well: ↑/↓, k/j and the wheel move it, Enter or a
click opens a seat, and a click on the key line does what its key does (`loop`,
`terminal.Keyboard`).  `x` is
the highlighted seat's: a done one is closed at once, and any other is asked about under its row,
`Keep` or `Stop` -- so the key line says `x close` while a done seat is highlighted.  A stopped
seat leaves its project for the past screen, `p` (`show_past`): its row there under its project,
numbered after the live ones, says how long ago it stopped; Enter reopens it where it stopped and
`x` takes it off at once.  `c` holds
its orchestrator, executors and reviewers: the orchestrator moves the seat at once, the
roles flip with the same keys and save at once.
`ak run status` and `ak browser` stay as commands for
orchestrators; the menu no longer offers them. A gone session reads `session closed: press N
to reopen`; one you stopped has no row under its project, only its row on the past screen; an
ended run is its orchestrator's business, so no row ever says `press r`.

The screen is budgeted by height as well as width: the usage stays on top and the keys at the
bottom, and a list of seats longer than the room between them is drawn a page at a time -- on a terminal the page the highlight is on, which ← and →
turn, from a pipe the one `j` and `k` turn to -- and a row keeps the number it has in the whole list on whichever page
it is drawn, so what a number opens never depends on the page that is up.

`ak attach --overlay` is the same menu inside a seat, where `ak orch` binds it to `Ctrl-b m` as
a tmux popup: the same rows, keys and acts, its highlight starting on that seat.  What hands
this client a seat -- a number, Enter, `n`, a past session reopened -- and `x` on the popup's
own seat close the popup, so the seat is seen.

On the server the menu is this process.  On a client -- a machine where install.sh recorded the
server's ssh alias in ~/.agentkit/state/server -- `ak` runs the same menu over `ssh -t <alias>
ak --client`.  `ak attach` is the same menu under the name the phone
key uses.
"""

import colorsys
import copy
import errno
import json
import os
import re
import select
import shlex
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

from . import command_help, config, gitcall, history, matrix, motion, notify, orch, plan, staffing, terminal, transitions, update, usage, worker
from . import record
from . import warm

KEYS = "n new   x stop   c config   esc leave"
STOP_ASK = "Stop {} and everything it runs?"   # what `x` asks under a seat that is not done
PAGE_KEYS = "j more   k previous"   # added to the key line when the list runs to more pages
BORN = " new"            # the name of the row `n` makes: none of a seat's, which holds no space
BORN_KEYS = "⏎ start   tab models   esc back"
UNFILED = "not assigned yet"   # the heading of the seats no project has yet, the new row's too
PAST_KEYS = ("↑↓ move   ⏎ reopen   x remove   esc back", "j/k move   enter reopen   x remove   esc back")
LEAST = 3                # rows a page keeps; the usage block folds before it holds fewer
# The whole vocabulary, worst first: a rollup of seats says the one that wants him, and an idle
# seat sorts last in its project.  `watch.session_state` is what decides which of the five a
# seat is.
STATE_ORDER = ("needs you", "out of usage", "working", "done", "idle")
# Each company's own colour, for its name on the `c` screen and its usage bar and row's place: a
# provider's `colour` key in config.toml wins, and a provider named in neither is the accent.
COLOURS = {"anthropic": "#D97757", "openai": "#FFFFFF", "meta": "#3E9EFB", "xai": "#736CD3",
           "google": "#203B9B", "mimo": "#FB8046"}
# Each company's own name, on its usage row and over its models on `c` and `n`; any other
# provider is its own `name` key (provider_name), else its key capitalised.
NAMES = {"anthropic": "Claude", "openai": "ChatGPT", "meta": "Muse", "xai": "Grok",
         "google": "Gemini", "mimo": "MiMo"}
TICK = 10.0              # the longest the main screen waits for a key before drawing itself again
STIR = 1.0               # ... and how often it looks for a seat's word or the meters having moved
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


def rows(cfg):
    """The seats, their runs and their groups, as the main screen reads them (`Live.read`)."""
    found = orch.listing()
    records = run_records()           # one pass over run.json a read: filing, looking, drawing
    orch.file_projectless(found, [state for _, state in records])
    return found, records, v5o_groups(cfg, found, records, look=False)


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
    a line maintenance says does (`tidy`).
    """

    def __init__(self, cfg, every=None):
        self.cfg = cfg
        self.every = usage.PROBE_EVERY if every is None else every
        self.started = None          # when the probe now running was started, or None
        self.began = None            # ... and when, on the clock motion reads (`asking`)
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
        self.said = []                   # what maintenance said that no notice has shown yet
        self.tidied = threading.Event()  # a notice can land before maintenance's effects do
        self.reads = 0                   # how many reads have begun, the last one's number
        self.closing = {}                # seats `stop` took off: the last read begun as it ended

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
        self.started, self.began = now, time.monotonic()
        self.thread = threading.Thread(target=self._work, daemon=True)
        self.thread.start()
        return True

    def asking(self):
        """When the probe now going began, on motion's clock, or None while none is."""
        return self.began if self.thread is not None and self.thread.is_alive() else None

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
        frame: each line it says is kept for the loop's next notice and asks for a draw, and
        once it is done everything is read again, for what it reaped and retired to leave the
        rows."""
        def run():
            work(self.say)
            self.ask()
            self.tidied.set()
        threading.Thread(target=run, daemon=True).start()

    def say(self, message):
        self.said.append(message)
        self._wake()

    def heard(self):
        """What maintenance said since last asked, once."""
        return [self.said.pop(0) for _ in range(len(self.said))]

    def read(self, look=False):
        """The seats, their runs and their rows, read now into `last`, the words as recorded.

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
            self.reads += 1
            began = self.reads
        found, records, groups = rows(self.cfg)
        with self.reading:
            if self.leaves != leaves:
                return
            self.read_from = found, records
            self.meet(look)
            for name, ended in list(self.closing.items()):
                if ended is not None and began > ended:
                    del self.closing[name]    # read since its stop ended: as it now stands
            self.last[:] = without(found, groups, self.closing)

    def stop(self, name, dry_run=False):
        """Take that seat's row off the screen now, and stop it behind it (`teardown`).

        No read puts the row back while the stop goes, nor after it until one begun since it
        ended lands: that one has the seat stopped, or as it was where the stop was refused.
        The stop is a process of its own, so the menu leaving -- the popup over the seat going
        with it -- ends nothing halfway, and a refusal is a job's notice, which this menu or
        the next shows.
        """
        with self.reading:
            self.closing[name] = None
            self.last[:] = without(*self.last, self.closing)
        try:
            proc = subprocess.Popen(teardown(name, dry_run), cwd=config.REPO,
                                    env=config.owner_env(), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
        except OSError as exc:
            self.say(f"stop: {exc}")
            return self._stopped(name)
        threading.Thread(target=lambda: (proc.wait(), self._stopped(name)), daemon=True).start()

    def _stopped(self, name):
        with self.reading:
            self.closing[name] = self.reads
        self.ask()

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
        self.asked.set()

    def watch(self, last):
        """Read into `last` once, now, for the first draw -- in a menu the warm server forked, its
        last read is the first draw's (`warm`), read again within STIR -- then again in a thread
        within STIR of any record changing, or when asked (`ask`): the seats and their groups,
        for each draw to draw.

        Whatever decides a seat -- its own hook, the tick, `ak orch`, another menu -- writes the
        word to that seat's record and to its bar in one go, and a run's step, round and ending
        touch `config.runs_moved_path` before they move its bar (`handback.redress_seat`), so a screen
        that reads again when a record changes, as recorded, never shows a row its bar
        contradicts for longer than this.
        The records are noted before every read, so one written while it reads is still news.
        Looking is a `stat` per file -- its inode as well as its mtime, since every write
        replaces the file -- and nothing here captures a pane.  A read on news starts a look
        only when a seat is listed that it has not met (`read`), once, and writes nothing else,
        so no menu's read keeps waking another, or itself; each one landing asks for one draw.
        """
        self.last, primed = last, warm.primed()
        if primed:
            # the warm server's last read, read again at the watcher's first look: a read
            # beside the first frame would hold it back, the two on one interpreter
            last[:], self.seen, self.looking = primed, None, True
        else:
            self.seen = self.recorded()
            self.read(look=True)
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
        self.ask(look=True)

    def recorded(self):
        """usage.json, the runs' moved mark and every seat record: each one's name, inode and
        mtime; and each project's feature switches as its `list` last answered, so their landing
        is news too."""
        found = []
        for path in [config.STATE / "usage.json", config.runs_moved_path(),
                     *(path for _, path in config.seat_files("seat"))]:
            try:
                stat = path.stat()
            except OSError:
                continue
            found.append((path.name, stat.st_ino, stat.st_mtime_ns))
        with _SWITCHES_LOCK:
            found += [(key, entry["rows"], entry["error"]) for key, entry in _SWITCHES.items()]
        return found

    def _watch(self):
        while True:
            self.asked.wait(STIR)
            self.watching.wait()
            if self.done.is_set():
                return
            if not self.watching.is_set():
                continue                 # away since the wait: what it would read, nobody draws
            now = self.recorded()
            if now == self.seen and not self.asked.is_set():
                continue
            self.asked.clear()
            look = self.looking
            if look:
                self.looking = False     # a look asked for since is this one: it starts after
            self.seen = now
            try:
                self.read(look)
            except (config.Error, OSError, ValueError, TypeError, KeyError):
                pass    # what cannot be read now stays drawn as it was last read
            self._wake()

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


def moving(clock, wake=None, timeout=TICK, going=None):
    """`wait_key` on the main screen, its digit wait and its stop question, and on a screen whose
    content is fetched: `timeout` seconds at most, and each of `clock`'s frames drawn while
    something moves and no key is waiting.

    Only a wait that ran to its frame draws one.  One that ended before it, on news, returns
    None, its cells forgotten, for the caller to draw the screen again; so does one a resize
    ended, at any time, and the clock forgets what it had seen as well: a resize moves every
    cell, and the draw after it shows the values as they are (`motion.Clock.forget`).  So does
    one on content being fetched once `going()` says it has landed, looked at every frame
    whether or not anything moves, for the screen to draw what came.
    """
    left, until = timeout, time.monotonic() + timeout
    terminal.asked_again()          # a draw asked for before the one just made is answered
    while True:
        due = clock.wait()
        if due is None and going is not None:
            due = motion.FRAME      # nothing moves, and what is waited on is looked at as often
        key = wait_key("> ", left if due is None else max(0, min(due, left)), wake)
        if key is None and terminal.asked_again():
            clock.clear()
            clock.forget()
            return None
        if key is not None or due is None or time.monotonic() >= until:
            return key
        if going is not None and not going():
            return None
        if (clock.wait() or 0) > 0:
            clock.clear()
            return None
        sys.stdout.write(clock.frame())
        sys.stdout.flush()
        left = until - time.monotonic()


class Back(Exception):
    """Esc, the end of input or a click on `esc back`, read while a screen waited on what it
    fetches (`waited`)."""


class Fetch(threading.Thread):
    """`work()`, asked off the drawing thread from `began`; `answer` once it has landed."""

    def __init__(self, work):
        super().__init__(daemon=True)
        self.work, self.began, self.got = work, time.monotonic(), {}
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
                time.monotonic()) + " " + terminal.styled(terminal.cut(
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
    in a frame while the menu holds the screen, else printed where the terminal was given
    back, with only the keys taken so Esc goes back at once here too."""
    if terminal.taken():
        while True:
            body = ["  " + part for line in lines for part in
                    (terminal.wrap(line, terminal.layout_width() - 2) or [""])]
            spots = terminal.frame("note", body)
            key = terminal.read_key()
            if key is not None and (key.name in ("esc", "enter", "eof")
                                    or key.name == "click"
                                    and terminal.under(key, spots).cell == "esc"):
                return
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
    """Each task in flight that seat launched, as (stage, state), furthest behind first: its
    stage 0, 1 or 2 (`STAGES`), and `moving` while a model or ak works on it, `spent` while every
    model it may go on with is out of usage, `waiting` while it waits -- for a slot, behind an
    older change, for a login, for its turn in the line, for the live check.  A run that ended is no task in flight, whatever it delivered:
    the owner's word of 19 Oct 2026, as red squares of ended runs read as work still going."""
    from . import gate, watch   # here, not at the top: watch imports this module
    now = time.time() if now is None else now
    records = run_records() if records is None else records
    found = []
    for run_dir, state in transitions.runs_by_seat(records).get(name, []):
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
    rgb = terminal.STATE_STYLES[terminal.KINDS.get(kind, kind)][2]
    return f"#[fg=#{rgb}]{orch.tmux_text(text)}#[default]" if text else ""


def line_at(line):
    """Slice of `terminal.cell_texts` holding the rendered progress line, before highlighting.

    Its coloured spans distinguish it from completion prose holding the same glyphs.
    """
    match = re.search(r"(?:\033\[[\d;]+m[━╸=─-]+\033\[0m)+(?= \d+ of \d+)", line)
    if match:
        start = len(terminal.cell_texts(line[:match.start()]))
        return slice(start, start + len(terminal.cell_texts(match.group())))


def tips(line):
    """Plain-text offsets of the rendered progress tip and moving task-stage squares.

    Read their working-colour spans before highlighting or provider colouring: draft glyphs
    are plain, and waiting squares are dim. At 256 colours several bar
    cells can share the tip's colour, so only the last one breathes.
    """
    if terminal.colour_depth() <= 8:
        return []
    tip = max(line.rfind(terminal.styled(char, "working")) for char in ("━", "╸"))
    found = [(tip, 0)] if tip >= 0 else []
    for filled in ("■", "■■", "■■■"):
        found += [(group.start(), len(filled) - 1)
                  for group in re.finditer(re.escape(terminal.styled(filled, "working")), line)]
    return [len(terminal.ANSI.sub("", line[:start])) + offset for start, offset in found]



def task_cells(line, tasks):
    """Each task `squares` drew on `line`, a line a row opens as drawn, with the cell its
    squares start at: found by their own drawing, so glyphs in a draft are never a task."""
    fit = next((fit for fit in range(len(tasks), 0, -1) if squares(tasks[:fit]) in line), 0)
    at, found = line.find(squares(tasks[:fit])) if fit else 0, []
    for task in tasks[:fit]:
        found.append((terminal.cells(terminal.ANSI.sub("", line[:at])) + 1, task))
        at += len(squares([task])) + 2
    return found


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
    reviewers, else its workers, each by its full name (`config.model_name`).  A seat whose
    orchestrator builds alone names no builder, and nothing beside its orchestrator says so:
    no ⚒ is the seat itself building (the owner's word of 21 Oct 2026).  No selection: nobody.
    The menu row and the seat's own bar both read this, as they read `seat_tasks`."""
    if not selection:
        return [], []
    workers = list(selection.get("workers") or [])
    return ([config.model_name(cfg, model) for model in workers],
            [config.model_name(cfg, model) for model in selection.get("reviewers", workers)])


def crew(info, tmux=False, room=None):
    """`astra ⚒   opus ⚒◎   spark ◎`: each model that builds or reviews a seat's work named once,
    in the order it first comes, ⚒ after it where it builds and ◎ where it reviews, all dim, as
    the row's orchestrator is (the owner's pick of 18 Oct 2026); without UTF-8 `B` and `R`.  Cut to `room` cells where given; `tmux` draws
    it as tmux text."""
    builds, reviews = info.get("crew") or ((), ())
    build, review = ("⚒", "◎") if terminal.utf8() else ("B", "R")
    roles = {model: (build if model in builds else "") + (review if model in reviews else "")
             for model in (*builds, *reviews)}
    text = "   ".join(f"{terminal.plain(model)} {icons}" for model, icons in roles.items())
    return _paint(text if room is None else terminal.cut(text, room, spaced=True), "dim", tmux)


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
        newest = _watch.run_last_write(Path(run_dir))
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
    unfinished jobs -- while it is not at rest, and for `working` its place in the landing
    line (`_last_text`), else empty, then `✎ unsent` where the owner left text unsent -- never
    two state words on one row; the reason opens under it (`detail`). Every seat
    `orch.listing` offers gets a row: the ones tmux holds, and the ones only their record does
    -- a seat whose tmux instance is gone keeps its row and its number opens the conversation
    where it stopped.
    Seats with nothing to resume into never reach `found`. `jobs_cache` and `run_numbers`
    are kept for callers that still hand them down; `seat_progress` reads the jobs itself and
    gone seats name their own number now.  `mine` is the runs each seat launched, by its name
    now, so a pass over every seat reads every run once (`transitions.runs_by_seat`).
    """
    name = session["name"]
    found = seat_row_state(cfg, session, look=look, records=records, now=now, number=number,
                           run_numbers=run_numbers, index=index, silent=silent_map)
    selection = selection_of(cfg, name)
    orchestrator = selection["orchestrator"] if selection else "-"
    shown = config.model_name(cfg, orchestrator)
    done, total = seat_progress(name)
    bar = (done, total) if total > 0 else None
    word = found["word"]
    reason = found["reason"] or ""
    sentence = reason
    back = found.get("resumes_at") if word == "out of usage" else None
    go_on = back and orch.going_on(cfg, orchestrator, staffing._cached_providers())
    return {"number": str(number), "name": name, "session": session, "back": back,
            "go_on": go_on, "go_on_name": go_on and config.model_name(cfg, go_on),
            "crew": seat_crew(cfg, selection),
            "tasks": seat_tasks(name, records if mine is None else mine.get(name, []), now),
            "count": word, "orchestrator": shown, "worker": shown,
            "runs_on": ((cfg["models"].get(orchestrator) or {}).get("provider"),
                        selection.get("account") or config.DEFAULT_ACCOUNT) if selection else None,
            "sentence": sentence, "unsent": found.get("unsent"), "bar": bar,
            "needs": reason if word == "needs you" else "",
            "word": word, "since": found["since"], "repo": session.get("repo")}


def v5o_groups(cfg, found, records=None, now=None, look=True):
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
    """
    at = time.time() if now is None else now
    records = run_records() if records is None else list(records)
    all_states = [state for _, state in records]
    index = transitions.supersession_index(all_states)
    silent_map = {}
    for run_dir, state in records:
        age = silent_for_run(run_dir, state, now=at)
        if age:
            silent_map[run_dir.name] = age
    jobs_cache = {}
    infos = []
    mine = transitions.runs_by_seat(records)
    for number, session in enumerate(found, 1):
        if session.get("closed"):
            continue          # stopped: numbered after every seat with a row, on the past screen
        infos.append(v5o_seat_info(cfg, number, session, records, silent_map, jobs_cache,
                                   at, index, None, look, mine))
    stands = orch.listed()       # ~/code looked at once a read
    groups = by_project(infos, stands)
    for checkout in orch.checkouts(stands=stands):     # a project with no seat shown has no heading
        if str(checkout) in groups and switches_command(checkout):
            groups[str(checkout)]["switches"] = switches(checkout) or []
    return tallied(list(groups.values()), infos, silent_map)    # each where its first seat is


def tallied(ordered, infos, silent_map):
    """`v5o_groups`' answer for those projects and rows: each project's seats that need the owner
    and its word, and the top line's count of them all."""
    for project in ordered:
        project["needing"] = sum(1 for info in project["seats"] if info["word"] == "needs you")
        project["has_needs"] = bool(project["needing"])
        project["word"] = rollup([info["word"] for info in project["seats"]])
    # The top line counts the seats whose word is `needs you`, each once, and says so once.
    return ordered, infos, sum(project["needing"] for project in ordered), silent_map


def without(found, groups, gone):
    """`found` and `groups` with the seats named in `gone` stopped, as the read after their stop
    has them: each closed, its row gone, and its project's heading once it has no row left."""
    if not gone or groups is None:
        return found, groups
    ordered, infos, _, silent_map = groups
    found = [{**seat, "closed": seat.get("closed") or time.time()} if seat["name"] in gone
             else seat for seat in found]
    ordered = [{**project, "seats": seats} for project in ordered
               if (seats := [info for info in project["seats"] if info["name"] not in gone])]
    return found, tallied(ordered, [info for info in infos if info["name"] not in gone],
                          silent_map)


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


def project_pages(projects, room):
    """`projects`, (heading, blocks) each in order, a block one seat's lines, in pages of `room`
    lines, the main screen's and the past screen's alike: a blank line between two projects on
    a page, as on the screen that holds them all."""
    # Seat blocks packed whole under their project header, so a seat's lines never split
    # across pages: one taller than a page under its header is cut to it, as the highlight
    # shows only a seat's first page. A screen without room for a row and a line under it
    # falls back to bare line splits so tiny screens still fit.
    pages, cur, cur_header = [], [], None
    for header, own in projects:
        for block in own or [[]]:     # a heading with no seat under it still has its place
            need = (block if cur and cur_header == header else
                    [("", None)] * bool(cur) + [header] + block)
            if cur and len(cur) + len(need) > room:
                pages.append(cur)
                cur, cur_header = [], None
                need = [header] + block
            if len(need) > room:
                pages.append([header])
                for i in range(0, len(block), room):
                    pages.append(block[i:i + room])
                cur_header = header
                continue
            cur.extend(need)
            cur_header = header
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
    """`✎ <text>`, `* <text>` without UTF-8: what the owner left unsent, which never changes the
    word (owner, 20 Oct 2026) -- the mark ends its row and its whole text opens under it."""
    return f"{'✎' if terminal.utf8() else '*'} {text}"


def last_column(word, done, total, room=8, narrow=False, tmux=False, unsent="", back=None):
    """The one last column of a seat's row, and of its status bar's line one: its progress
    (`terminal.plan_bar`, a smooth line and `done of total`) in `room` cells, in its word's
    colour, while `seat_progress` finds a plan or an unfinished job and it is not at rest, its
    work waiting in the line to land too, which its squares say (`detail`); else
    empty -- never `N running`, and no other sentence: what a seat asks or did opens under its
    row (`detail`).  Where the owner left text `unsent`, `✎ unsent` follows two cells after,
    in the needs-you colour.  The line keeps 8 cells at least, which a row too short for them
    draws under itself; where `room` is all there is -- a `narrow` screen's line, each width of
    a seat's bar -- it takes that room and never more, the mark alone where both do not fit.
    `tmux` draws it for a seat's bar.  The row and the bar read this one function, so the two
    can never disagree.  A seat out of usage says when it comes back, `back 19:20` (`back`), in
    its word's colour, in its progress's place."""
    mark = unsent_mark() if unsent else ""
    left = room - (terminal.cells(mark) + 2 if mark else 0)
    if word == "out of usage":
        text = f"back {back_at(back)}" if back_at(back) else ""
        bar = _paint(text, word, tmux) if text else ""
    elif not total or word in (None, "idle"):
        text = bar = ""
    else:
        text = terminal.plan_bar(done, total, left, 0)
        bar = terminal.plan_bar(done, total, left, 0 if narrow else 8, word, tmux)
    if narrow and mark and terminal.cells(text) > left:
        bar = ""
    if not mark:
        return bar
    mark = _paint(mark, "needs you", tmux)
    return f"{bar}  {mark}" if bar else mark


def _last_text(info, room, narrow=False):
    """The row's one last column in `room` cells (`last_column`)."""
    bar = info.get("bar")
    done, total = bar if bar and len(bar) == 2 else (0, 0)
    return last_column(info.get("word"), done, total, room, narrow, unsent=info.get("unsent"),
                       back=info.get("back"))


def detail(cfg, info, room, now=None):
    """The lines under a seat's row, in `room` cells: first `✎` and the whole text the owner left
    unsent, in the needs-you colour; then what a seat not working says -- the question for
    `needs you`, what got done for `done`, an idle one's way back in, until when one out of
    usage has none -- wrapped whole at words; for any other, who builds and who reviews
    (`crew`) and each task in flight as its squares (`squares`), never a task's name.  On a
    terminal the highlighted row alone opens them; from a pipe every row saying something
    does, as there is no highlight to open them."""
    if not info:
        return []
    if "born" in info:
        return born_lines(info, room)
    unsent = [terminal.styled(line, "needs you") for line in
              terminal.wrap(unsent_mark(info["unsent"]), room)] if info.get("unsent") else []
    word = info.get("word")
    said = "" if word == "working" else terminal.plain(info.get("sentence") or "")
    if word == "out of usage":
        provider = provider_name(cfg, info["runs_on"][0]) if info.get("runs_on") else "Its model"
        when = back_at(info.get("back"))
        said = (f"{provider} has no usage left until {when}." if when else said) + (
            "" if info.get("go_on") else " No other model has any now.")
    if said or word in ("needs you", "done", "out of usage"):
        return unsent + terminal.wrap(said, room)
    tasks = info.get("tasks") or []
    # the crew gives way to the least the squares say: one task's squares, or their count
    least = 3 + terminal.cells(squares(tasks, 3)) if tasks else 0
    who = crew(info, room=room - least)
    left = room - terminal.cells(who) - 3
    line = who + ("   " + squares(tasks, left) if tasks and left >= least - 3 else "")
    return unsent + ([line] if terminal.plain(line) else [])


WAIT, GO_ON = "wait", "go on"     # the choices under a seat out of usage, as the click reads them
GAP = "   "                       # between them, on a line both fit


def choice_lines(info, room):
    """The choices under a seat out of usage's row (`detail`), with the keyboard or the pointer
    on it: `✓ Wait for 19:20`, what happens unasked, and where a model has usage now,
    `⇄ Go on now with gpt-6.1-sol`, which moves the seat and its conversation there.  Each drawn
    line in `room` cells, as its (text, choice) parts: both on one line where they fit, else
    each on lines of its own wrapped at words, so none runs past the edge of the screen and
    away from where a click finds it (`choice_cells`).  [] for any other row."""
    if info.get("word") != "out of usage" or not back_at(info.get("back")):
        return []
    said = [(choice_text(choice, info), choice) for choice in (WAIT, GO_ON)
            if choice == WAIT or info.get("go_on")]
    if terminal.cells(GAP.join(text for text, _ in said)) <= room:
        return [said]
    return [[(piece, choice)] for text, choice in said for piece in terminal.wrap(text, room)]


def choices(info, room):
    """The lines `choice_lines` draws, each choice in its colour."""
    return [GAP.join(terminal.styled(text, {WAIT: "ok", GO_ON: "amber"}[choice])
                     for text, choice in line) for line in choice_lines(info, room)]


def choice_text(choice, info):
    """One choice under a seat out of usage, whole (`choice_lines`)."""
    mark = {WAIT: "✓", GO_ON: "⇄"}[choice] if terminal.utf8() else {WAIT: "v", GO_ON: ">"}[choice]
    if choice == WAIT:
        return f"{mark} Wait for {back_at(info.get('back'))}"
    return f"{mark} Go on now with {info.get('go_on_name')}"


def choice_cells(text, info, room):
    """Where each choice of `choice_lines` in `room` is on its drawn line `text`, as a screen's
    spots hold a cell: (first, last, choice); [] on any other line."""
    for line in choice_lines(info, room):
        drawn = GAP.join(part for part, _ in line)
        if text.strip() == drawn:
            first = terminal.cells(text[:text.index(drawn)]) + 1
            found = []
            for part, choice in line:
                found.append((first, first + terminal.cells(part) - 1, choice))
                first += terminal.cells(part + GAP)
            return found
    return []


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
    while 2 + num_w + 2 + name_w + 2 + orch_w + state_w > room and max(name_w, orch_w) > 1:
        if name_w >= orch_w:
            name_w -= 1
        else:
            orch_w -= 1
    fixed = 2 + num_w + 2 + name_w + 2 + orch_w + state_w + 2
    return {"room": room, "narrow": term_width < 60, "num": num_w, "name": name_w,
            "orch": orch_w, "count": count_w, "worker": orch_w, "bar": 0,
            "sent": max(10, room - fixed), "free": room - fixed}


def _head(info, widths, tone="dim"):
    """A seat row's fixed columns -- number, name, orchestrator in `tone`, state -- in `widths`.
    Where even their narrowest do not fit, the number keeps its place behind the indent the
    highlight's `›` takes. A zero state width puts that column below the row instead."""
    number = "  " + _styled_cell(info["number"], widths["num"], "dim", right=True)
    orchestrator = info.get("orchestrator") or info.get("worker") or ""
    rest = [born_name(info["born"], widths["name"]) if "born" in info else
            terminal.pad(terminal.cut(info["name"], widths["name"]), widths["name"]),
            _styled_cell(orchestrator, widths["orch"], tone)]
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
    line (`_last_text`) where it has a plan. Content is capped at 100 columns. A line too long
    for the column, or one on a narrow phone, goes whole on the indented line under its row.
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
        last = "" if narrow else _last_text(info, widths["free"])
        if last and widths["free"] >= 10 and terminal.cells(last) <= widths["free"]:
            block = [head + "  " + last]
        else:
            # a line too long for the column is never wrapped, which drops its colours, and a
            # row without ten cells left starts nothing: it goes under its row, in that room
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
         records=None, groups=None, clock=None, updating=None, pointing=True):
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
    filled with what a key, a click or the pointer is read against: `order`, the seats' names
    top to bottom, with the checkout of a project naming its feature switches where its heading
    is; `cursor`, the one highlighted; `spots`, the seat or heading on each screen row and the
    key line's items (`terminal.under`), the one under the pointer lit; `words`, each seat's
    word.  A seat's state word, any other project's heading and a subscription of the usage
    grid are cells that only explain (`terminal.Spot`), and nothing says what any of them is on
    the key line; a subscription under the pointer is drawn in its colour and the blank line
    under the grid says the rest of it (`usage_detail`).  The highlighted seat's line opens
    under it only while the owner points at it (`pointing`: the pointer on it, or ↑/↓ moved
    there since the pointer last was), and closes once the pointer is on no row
    (`terminal.away`) or the row moves from under it (`terminal.pointer`), and stays closed
    until the pointer or ↑/↓ moves onto a row (`drawn["pointing"]`).

    `x` acts on the highlighted seat, and the key line says `x close` while that seat is done; `p past` is on it while a seat the owner stopped is
    offered (`closed` on its row, `orch.ghost`), the past screen's.  `ask` is the seat `x` is
    asking about and the card it
    asks on (`terminal.confirm`): the card is drawn under its row, the rows below moving down,
    and `drawn["ask"]` is the screen row of its first line.

    `look` is whether the seats are looked at for this draw or drawn as recorded, and
    `records` the run records it is drawn from, read here when they are not handed in;
    `groups`, `v5o_groups`' answer already in hand, is drawn as it is, and nothing is read.

    `clock`, the menu's `motion.Clock`, is handed each working seat's `●` to breathe while the
    menu has the keyboard, and the news since the draw before: a `!` that turned `needs you`
    pulses, a `✓` that turned `done` settles and a usage bar that moved glides.  Their
    first frame goes out in the draw's own write, at the clock's phase, so nothing jumps when
    the screen is drawn over.  While a popup's content fades in, the whole screen is handed to
    it, to come up out of the background (`motion.Clock.rise`).
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
    if cursor not in order:
        cursor = next((name for name in order if isinstance(name, str)),
                      order[0] if order else None)      # a seat before any heading
    if past_offered(found):
        keys = keys.replace("c config", "p past   c config", 1)
    if owned and words.get(cursor) == "done":
        keys = keys.replace("x stop", "x close", 1)
    asking, card = ask or (None, ())
    asked = list(card) if asking in words else []
    # Seat columns are sized once per draw from every row on screen, so the
    # sentence column starts at the same column under every project.
    widths = v5o_column_widths([seat for project in ordered
                                for seat in project["seats"]], width)
    # one reading of the cached meters and logins for the whole draw, so the grid the screen is
    # laid out around is the one the pointer lights, and a click signs in what was drawn amber
    rows = usage_rows(cfg)
    ending = login_notes(rows)
    meters_full = usage_lines(cfg, layout, rows=rows, ending=ending)
    # Height is budgeted the way width is: the frame, the usage and the keys always, and the
    # rows in what is left, a page at a time. Sized from the rows on screen, leaving one
    # line for the prompt and one to spare, exactly as the tests check.
    key_text = keys
    # With the keyboard ← and → turn the pages; in a pipe `j` and `k` do.  Either way the key
    # line starts with where the owner is (`page_mark`), budgeted at its widest.
    paged_keys = key_text + ("" if owned else "   " + PAGE_KEYS)
    # A question under a row is budgeted with the key line, so it never pushes a row off.
    k_single = len(terminal.key_line(key_text, width)) + len(asked)
    k_paged = len(page_mark(paged_keys, 98, 99, width, owned)) + len(asked)

    def _flat(blocks):
        flat = []
        for block in blocks:
            flat.extend(block)
            flat.append(("", None))  # one blank line between projects
        if flat:
            flat.pop()
        return flat

    # What opens under a row (`detail`): from a pipe under every row saying something, as
    # nothing is highlighted there; with the keyboard under the highlighted row alone, below.
    said_room = max(1, widths["room"] - (2 + widths["num"] + 2))
    said = {info["name"]: detail(cfg, info, said_room) + (choices(info, said_room) if owned else [])
            for info in infos}
    opened = {} if owned else {info["name"]: said[info["name"]] for info in infos
                               if info["word"] != "working" and info.get("sentence")
                               or info.get("unsent")}

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
    seat_blocks = _seat_blocks()
    blocks = [[heading(project)] + [pair for block in own for pair in block]
              for project, own in zip(ordered, seat_blocks)]
    flat = _flat(blocks) or [("  no sessions; n starts one", None)]     # a row, budgeted as one

    # The highlighted seat's lines go under its row: as many kept on every page as the most any
    # seat opens, up to half the screen, so no page overflows or turns as the highlight moves;
    # a question longer than that is cut to them, ending in `…`.
    opens = (min(max(map(len, said.values()), default=0), max(1, height // 2))
             if owned and not asked else 0)
    # a worker login that ends soon, or has, stands under the usage on every screen, grid or
    # folded, keyboard or not, while no pointer is there; a compact screen gives it a row
    from . import watch    # here, not at the top: the menu draws without the tick
    token = watch.token_standing()
    standing = ("  " + terminal.styled(terminal.cut(token, layout - 2),
                                       "amber" if "expired" in token else "dim")
                if token else "")

    def _room(meters, paged, compact=False):
        keys = (k_paged if paged else k_single) + opens
        if compact:
            return height - 2 - (keys + len(meters) + bool(standing))
        chrome = 2 + len(meters) + 2 + 1 + keys
        return height - 2 - chrome

    # The usage stays on top and the keys at the bottom, whatever the number of seats: those
    # that do not fit between them turn pages.  The block folds to its readings, each whole
    # (`usage_summary`), where that keeps every seat on one page or where the whole block
    # leaves too few rows a page; a screen too short for that drops the frame and the blank
    # lines too (compact), and only one with no room for a seat under its heading even then
    # cuts the readings.
    least = LEAST * (2 if width < 60 else 1)
    summary = usage_summary(cfg, layout, rows=rows)
    block = meters_full or summary     # a width with no grid says the readings
    # one page before pages, the whole block before its readings, and compact last
    for meters, compact, paged in ((block, False, False), (summary, False, False),
                                   (block, False, True), (summary, False, True),
                                   (summary, True, False), (summary, True, True)):
        paged = paged and len(flat) > 1
        room = _room(meters, paged, compact)
        if (len(flat) <= room) if not paged else (room >= least or compact):
            break
    # a seat under its heading: its row and, where it has one, a line under it
    need = 1 + min(2, max((len(block) for own in seat_blocks for block in own), default=0))
    # the opened lines take only what that leaves, before the usage gives any of its own
    opens = max(0, opens - max(0, need - room))
    room = _room(meters, paged, compact)
    if compact and room < need and len(meters) > 1:
        meters = usage_summary(cfg, layout, max(1, len(meters) + room - need), rows)
        room = _room(meters, paged, compact)
    if room < 1:
        meters = meters[:max(0, len(meters) + room - 1)]      # what leaves one row
    room = max(1, _room(meters, paged, compact))
    pages = (project_pages([(heading(project), own) for project, own
                            in zip(ordered, _seat_blocks(room - 1))], room)
             if paged else [flat])
    if owned and cursor is not None:
        page = next((number for number, lines in enumerate(pages)
                     if any(name == cursor for _, name in lines)), page)
    page = min(max(page, 0), len(pages) - 1)
    key_lines = terminal.key_line(key_text, width)
    if len(pages) > 1:
        needing = [any(words.get(name) == "needs you" for _, name in lines) for lines in pages]
        key_lines = page_mark(paged_keys, page, len(pages), width, owned,
                              (any(needing[:page]), any(needing[page + 1:])))
    # The layout is min(terminal width, 120); beyond that the margin grows, never the text.
    out = []
    # what may move: (key, the word it shows, its first cell, highlighted)
    moves = []
    explains = {}   # each seat row's state word, a cell that explains it
    if not compact:
        out += [terminal.header_line("updating" if updating is not None else "",
                                     time.strftime("%H:%M"), width),
                terminal.rule_line(width, updating or 0)]
    grid = len(out) + 1 if meters and meters is meters_full else None     # its first row
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
    # the subscription the pointer is on, of those on the grid; a question under a row has the
    # keys and the rows, and nothing is explained while it asks
    usage_spots = meter_spots(layout, len(rows), grid) if grid else {}
    spot = terminal.Spot() if asked else terminal.pointer_spot(usage_spots)
    pointed = spot.cell and spot.cell[1]
    seats = {info["name"]: info for info in infos}
    model_at = 3 + widths["num"] + 2 + widths["name"] + 2     # the orchestrator column, from 1
    models = []     # each seat row's (screen row, model, highlighted, the subscriptions it runs on)
    breaths = []    # what breathes while a model works: (cell, character, highlighted)
    bars = {}       # each progress line's screen row and slice of terminal.cell_texts
    for line, name in body:
        # while a question is up its first answer carries the mark, and the seat only its light;
        # a heading is flush left, so its mark goes in front of it
        lit = owned and name is not None and name == cursor and not terminal.away()
        text, word = terminal.ANSI.sub("", line), words.get(name)
        if word == "working":
            for tip in tips(line):
                breaths.append(((len(out) + 1, terminal.cells(text[:tip]) + 1), text[tip], lit))
        seat = seats.get(name) if name != above else None
        # as its block keeps it, with no trailing space (`v5o_seat_blocks`)
        head = seat and seat.get("runs_on") and _head(seat, widths).rstrip()
        if head and line.startswith(head):
            provider, account = seat["runs_on"]
            coloured = _head(seat, widths, colour(cfg, provider)).rstrip()
            on = [number for number, (each, _, _, own) in enumerate(rows, 1)
                  if each == provider and own in (None, account)]
            line = coloured + line[len(head):] if pointed in on else line
            if coloured != head:     # its model is drawn in its column, where a colour shows
                models.append((len(out) + 1, terminal.cut(seat["orchestrator"], widths["orch"]),
                               lit, on))
        out.append(terminal.highlight(("  " if isinstance(name, Path) else "") + line,
                                      mark=name != above and not at) if lit else line)
        above = name
        info = seats.get(name)
        if info and name not in bars and (span := line_at(line)):
            bars[name] = len(out), span
            if info.get("bar"):       # a line that glides to its new length as its plan moves
                moves.append((("bar", name), info["bar"], (len(out), span), lit))
        if seat is None and info:      # the line a row opens: its tasks
            for column, task in task_cells(line, info.get("tasks") or []):
                moves.append((("task", getattr(task, "run", None)), tuple(task),
                              (len(out), column), lit))
        if seat is None and info and (cells := choice_cells(text, info, said_room)):
            explains[len(out)] = cells     # the choices under a seat out of usage: a click answers
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
    spots = {top + number: ((None, [(1, layout, name)]) if isinstance(name, tuple)
                            else (name, explains.get(top + number, [])))
             for number, (_, name) in enumerate(body, 1) if name}
    spots.update(usage_spots)
    spots.update(terminal.key_spots(key_lines, keys_top + 1))
    washes, spans = {}, {}     # each subscription's colour and the cells that take it
    if grid:
        # the one the pointer is on in its colour, as every seat's model that runs on it is, and
        # what its cell has no room for on the blank line under the grid
        out[grid - 1:grid - 1 + len(meters)] = usage_lines(cfg, layout, lit=pointed, rows=rows,
                                                           spans=spans, ending=ending)
        for number, (provider, *_) in enumerate(rows, 1):
            washes[number] = colour(cfg, provider), [
                *((grid + line, column, text, rest, False)
                  for line, column, text, rest in spans.get(number, ())),
                *((row, model_at, model, "dim", bright) for row, model, bright, on in models
                  if number in on)]
            moves.append((("sub", number), number == pointed, None, False))
        if pointed:
            out[grid + len(meters) - 1] = "  " + usage_detail(cfg, pointed, layout, rows=rows,
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
        # a question shown the first time writes itself out under its row, but as the screen
        # opens, when every value is drawn as it is; one hidden mid-way is written out by then
        question = ((cursor, seats[cursor].get("sentence")) if lines
                    and words.get(cursor) == "needs you" else None)
        asked = (clock.asked.get(question, time.monotonic())
                 if question and clock.seen is not None else None)
        clock.asked = dict.fromkeys(clock.asked)
        if question:
            clock.asked[question] = asked
        typed = asked is not None and time.monotonic() < asked + motion.WRITE
        news = clock.look({key: shown for key, shown, _, _ in moves})

        def line(name, moving, counted=None):
            """Move a seat's line by `moving`, a function of its cells to their animations and
            when they are still, and its count with it: counting up from `counted`, the done
            before, since when and for how long (motion.counting), else as drawn.  Whatever moves
            a line last moves its count, so the two never part."""
            row, span = bars[name]
            written = terminal.cell_texts(out[row - 1])
            animations, until = moving(written[span])
            clock.span(row, terminal.cells("".join(written[:span.start])) + 1, animations, until)
            after = terminal.ANSI.sub("", "".join(written[span.stop:]))
            if count := re.match(r" \d+ of \d+", after):
                cells = written[span.stop + 1:span.stop + count.end()]
                clock.span(row, terminal.cells("".join(written[:span.stop])) + 2, *(
                    motion.counting(cells, *counted) if counted else
                    ([lambda now, text=text: text for text in cells], until)))
        # As it opens each seat's line grows to its length, row after row, and on through the
        # draws until it has -- the read that lands as it opens draws the screen again at once --
        # each from its own start, until news moves the line instead.
        if clock.grows is None:
            clock.grows = {name: time.monotonic() + n * motion.STAGGER
                           for n, name in enumerate(bars)}
        for name, began in clock.grows.items():
            if name in bars:
                line(name, lambda cells: motion.growing(cells, began), (0, began, motion.GROW))
        # Older effects must not overwrite newer news at a shared cell.
        for key, shown, cell, lit in sorted(moves, key=lambda move: news.get(move[0], (0,))[0]):
            since, before = news.get(key, (None, None))
            if shown == "working":
                clock.start([cell], motion.breathing(terminal.state_glyph(shown), shown, lit))
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
            elif key[0] == "task" and before:    # a task moved on a stage
                row, column = cell
                written = terminal.cell_texts(out[row - 1])
                if shown[0] > before[0]:
                    clock.start([(row, column + shown[0])], *motion.halving(
                        written[column - 1 + shown[0]], since, motion.STEP, lit))
            elif key[0] == "opened" and typed:
                continue        # it writes itself out instead, below
            elif key[0] in ("opened", "page"):    # what comes up out of the background
                for row in (opened if key[0] == "opened" else range(top + 1, top + len(body) + 1)):
                    motion.fading(out[row - 1], motion.OPEN if key[0] == "opened" else motion.TURN)(
                        clock, row, since, None)
            elif key[0] == "sub":     # the pointer came onto it, or left it
                ink, cells = washes[key[1]]
                for row, column, text, rest, bright in cells:
                    clock.start([(row, column)], *motion.colouring(text, since, ink, shown, rest,
                                                                   bright))
            elif shown in ("needs you", "done"):
                # its row glows in its word's colour and fades, and a line just done is crossed
                # by one light
                row = cell[0]
                motion.glowing(out[row - 1], shown, motion.NEWS)(clock, row, since, None)
                clock.start([cell], *(motion.pulsing if shown == "needs you" else motion.settling)(
                    terminal.state_glyph(shown), shown, since, lit))
                if shown == "done" and key[1] in bars:
                    clock.grows.pop(key[1], None)
                    line(key[1], lambda cells: motion.sweeping(cells, since, shown, lit))
        if typed:       # line after line, a cell at a time, each at its terminal column
            written = [terminal.cell_texts(out[row - 1])[len(indent):] for row in opened]
            total, before = sum(map(len, written)), 0
            for row, cells in zip(opened, written):
                animations, until = motion.writing(cells, asked, before, total)
                column = len(indent) + 1
                for text, animation in zip(cells, animations):
                    clock.start([(row, column)], animation, until)
                    column += terminal.cells(text)
                before += len(cells)
        for cell, char, bright in breaths:
            breathe, growing = motion.breathing(char, "working", bright), clock.cells.get(cell)
            if growing:       # a tip still growing in breathes once it is there
                breathe = (lambda now, grow=growing[0], until=growing[1], breathe=breathe:
                           grow(now) if now < until else breathe(now))
            clock.start([cell], breathe)
        moved = clock.frame()
    # Home and write over, each line cleared past its end and the screen below the last: one
    # write, so no draw ever shows a blank screen or a half-drawn one.  Lines that rise are
    # the frame's to write, from the background up, and never first as they are.
    sys.stdout.write("\033[H" + ("" if rising else "".join(f"\033[K{line}\n" for line in out))
                     + "\033[J" + moved)
    sys.stdout.flush()
    # each page's first seat or heading drawn on no page before it, so the highlight resting
    # there has that page up: a heading over its project's next page, or a tall seat's rest, is not
    turns, before = [], set()
    for lines in pages:
        turns.append(next((name for _, name in lines
                           if isinstance(name, (str, Path)) and name not in before), None))
        before.update(name for _, name in lines)
    logins = {number: (name, account) for number, ((name, _, _, account), note)
              in enumerate(zip(rows, ending), 1) if note}
    drawn.update(order=order, cursor=cursor, pointing=pointing, words=words, rule=not compact,
                 ask=top + at + 1 if at else None, spots=spots, turns=turns, logins=logins,
                 go_on={info["name"]: info["go_on"] for info in infos if info.get("go_on")})
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


def go_on_now(cfg, name, model, dry_run=False):
    """`⇄ Go on now` under a seat out of usage: it moves to `model`, its conversation and the
    turn its usage cut off with it, as its orchestrator mark moved on its models screen does
    (`orch.switch_orchestrator`), never onto credits; a refusal is said."""
    if dry_run:
        print(f"would move {name} to {model}")
        return
    note = orch.switch_orchestrator(cfg, name, model, staffing._cached_providers(), credits=False)
    if note:
        pause(note)


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


def teardown(name, dry_run):
    """The process `x` stops that seat in (`Live.stop`, and the past screen's `x` removes a
    stopped one in): `close_seat`, leaving a refusal as a job's notice (`orch.job_notices`),
    since the popup it came from may be gone by then."""
    return [sys.executable, "-c", "import sys; from agentkit import menu, orch; "
            "menu.close_seat(sys.argv[1], sys.argv[2] == '1', refused=orch.leave_notice)",
            name, "1" if dry_run else "0"]


def stop_session(found, dry_run):
    """`x` read a line at a time -- a pipe, a file: which seat, then one question, and nothing else;
    the seat to stop, which the menu stops as the keyboard's `x` does (`Live.stop`), or None.

    With the keyboard `x` is the highlighted seat's instead (`loop`, `close_seat`).  The seat is
    picked by the number the main screen gives it or by name, among the ones not stopped already
    -- a stopped one keeps its number for the past screen (`show_past`), where it is removed,
    and is never asked about here; Esc and an empty Enter go back
    to the menu, as does anything but `y` to the one question, which says, as the
    keyboard's card does, that the past screen reopens the seat.
    """
    offered = {number: session for number, session in enumerate(found, 1)
               if not session.get("closed")}
    if not offered:
        pause("no session to stop")
        return
    terminal.frame("stop")
    names = [session["name"] for session in offered.values()]
    choice = terminal.ask("Stop", names[0], names, read=read, numbers=list(offered))
    if not choice:
        return
    session = next(session for session in offered.values() if session["name"] == choice)
    if dry_run:
        would_stop(session["name"])
        print(f"would stop {session['name']}")
        return
    terminal.frame("stop", terminal.wrap(stop_means(None), terminal.width()))
    if read(stop_question(session["name"]), "") == "y":
        return session["name"]


def open_session(cfg, session, dry_run):
    """A number: into that seat, or back into the conversation it left behind.

    A seat whose orchestrator has exited, and one tmux no longer holds at all, are both opened
    by resuming their owned conversation or clearly starting fresh -- the same key either way.
    """
    name = session["name"]
    if not any(session.get(key) for key in orch.CLOSED):
        if dry_run:
            print(f"would attach {name}")
            return
        orch.attach(name, wait=True, session=session)
        return
    if dry_run:
        print(f"would resume {name}")
        return
    try:
        orch.resume(cfg, name, wait=True)
    except config.Error as exc:
        pause(f"resume: {exc}")


def new_session(cfg, dry_run, keyboard=None, found=None):
    """`n`: the name, then the orchestrator and both roles on one screen (`orch.pick`), both on
    the menu's `keyboard`, or from a pipe one question at a time; Esc goes back, nothing
    created. Enter at the name leaves it for the orchestrator to choose, and a dry run only
    says what it would start: it creates no session, so neither its record nor its harness's
    rulebook. The terminal is given back once all is chosen, for the seat to open on.  `found`
    is the menu's last listing, so the name is asked without another."""
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
        taken = orch.taken_names()        # its name is chosen now: the picker may have waited
        name = orch.character_name(taken)
    if dry_run:
        reviewers = selected[3] if len(selected) == 4 else cfg["defaults"].get("reviewers")
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
    _notes, selected = orch.default_crew(cfg, providers, default)
    # every model spent: launched anyway, as `orch.choose` launches its default
    selected["orchestrator"] = selected["orchestrator"] or default
    selected["reviewers"] = selected["reviewers"] or [selected["orchestrator"]]
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
    shown = config.model_name(cfg, selected["orchestrator"])
    row = {"number": "", "name": BORN, "born": born, "orchestrator": shown, "worker": shown,
           "count": "new", "word": "new", "crew": seat_crew(cfg, selected), "tasks": [],
           "sentence": "", "repo": None}
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
    crew has no pair that can run (`orch.role_refusal`, as the picker's Enter refuses); else ""."""
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
    line = crew(info)
    return [line if terminal.cells(line) <= room else terminal.cut(line, room)]


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


def born_models(born):
    """Tab on the born row: its models chosen on `orch.pick`'s screen, which starts from the
    last creation's -- "start" with Enter there, None with Esc, back to the row."""
    picked = orch.pick(born["cfg"], born["providers"], born["default"])
    if picked is None or picked is orch.BACK:
        return None
    born["selected"] = dict(zip(("orchestrator", "workers", "reviewers"), picked))
    return "start"


def start_born(born, dry_run):
    """Make the born seat and open it, filed under its project: by the name typed, else the
    one the row showed, which its orchestrator replaces (`unnamed`); a dry run only says what it
    would start.  The name, or None where `orch.create` made nothing.  The names taken are read
    again: another menu may have made a seat since the row opened, and `create` would write
    over its record, so a name taken since is another free character's."""
    taken = orch.taken_names()
    unnamed = not born["typed"]
    name = (orch.session_name(born["typed"]) if not unnamed else born["name"]
            if born["name"] not in taken else orch.character_name(taken))
    selected = born["selected"]
    if dry_run:
        print(f"would start {name}: {selected['orchestrator']}, workers "
              f"{' '.join(selected['workers'])}, reviewers {' '.join(selected['reviewers'])}")
    elif orch.create(born["cfg"], name, orch.seat_cwd(), prompting=True,
                     selection=(born["providers"], (selected["orchestrator"], born["reason"]
                                if selected["orchestrator"] == born["default"] else "selected",
                                selected["workers"], selected["reviewers"])),
                     unnamed=unnamed, taken=taken) is None:
        return None
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
    def __init__(self, root):
        self.root, self.known, self.db = root, {}, None
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
                    key, state = json.loads(value)
                    if isinstance(key, list) and isinstance(state, dict):
                        self.known[name] = key, state
                except (ValueError, TypeError, RecursionError):
                    continue
        except sqlite3.Error:
            self.close()       # the run files remain authoritative, even with no writable cache

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None

    def read(self):
        found, fresh, changed, resolved = [], {}, [], {}
        for run_dir in record.run_dirs():
            try:
                info = (run_dir / "run.json").stat()
            except OSError:
                continue
            key = [info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size]
            if run_dir.name in self.known and self.known[run_dir.name][0] == key:
                state = self.known[run_dir.name][1]
            else:
                state = record.read_state(run_dir)
                if state is None:
                    continue
                changed.append((run_dir.name, json.dumps([key, state])))
            fresh[run_dir.name] = key, state
            if not state.get("unattended") and not smoke_run(state, resolved):
                found.append((run_dir, state))
        removed = self.known.keys() - fresh.keys()
        self.known = fresh
        if self.db is not None and (changed or removed):
            try:
                with self.db:
                    self.db.executemany("INSERT INTO records VALUES (?, ?) ON CONFLICT(name) "
                                        "DO UPDATE SET value = excluded.value", changed)
                    self.db.executemany("DELETE FROM records WHERE name = ?",
                                        ((name,) for name in removed))
            except sqlite3.Error:
                pass           # another process can fill the cache; this one keeps its reads
        return found


def run_records():
    """Every run's record, loading the shared cache only once per process.

    Only a changed run.json is opened again, with its stat taken before the read so a racing
    write can cause another read, never hide one. SQLite commits only changed rows and keeps
    other processes' reads whole. Cache failures leave the run files authoritative. Returned
    records are shared read-only snapshots, replaced only when their run.json changes.

    Unattended runs and tasks or repos resolving under ~/.agentkit/tmp/smoke-* are left out.
    Paths are resolved on every pass: a symlink can move without a run.json changing. Bad run
    files are skipped, never repaired.
    """
    global _RUN_RECORDS
    with _RUN_RECORDS_LOCK:
        root = config.RUNS, config.STATE, os.getpid()
        if _RUN_RECORDS is None or _RUN_RECORDS.root != root:
            if _RUN_RECORDS is not None:
                _RUN_RECORDS.close()
            _RUN_RECORDS = _RunRecords(root)
        return _RUN_RECORDS.read()


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
    """`Fable 41%` for each meter one model has to itself whose figure is not the shared one.

    A cap that reads the same as the shared week says nothing the row has not said already,
    so it is left off; the note is there for the gap, which is the whole reason the cap exists.
    """
    notes = []
    for meter in weekly:
        if meter is shared or percent_left(meter) == percent_left(shared):
            continue
        owner = next((name for name, entry in cfg["models"].items()
                      if entry.get("provider") == provider
                      and entry.get("meter") == meter.get("name")), None)
        if owner:
            notes.append(f"{owner.capitalize()} {percent_left(meter)}%")
    return notes


def percent_left(meter):
    """What this meter has left, as the row shows it: a whole number of percent."""
    return round(max(0, min(100, 100 - meter["used"])))


def in_hand(prov):
    """`1 reset in hand`, `2 resets in hand`: the usage-limit resets this subscription holds,
    for the owner to spend on `c` (config_spend_reset); "" with none, or none known."""
    held = int(usage._number(prov.get("resets")) or 0)
    return f"{held} reset{'' if held == 1 else 's'} in hand" if held > 0 else ""


def resets_note(meter, now):
    """`resets Fri 14:00`, `resets 23 Oct` or `resets in 3d`: `ak usage`'s `resets`, as words."""
    when = usage.reset_when(meter, now)
    return f"resets {when}" if when else ""


def session_window(prov, now):
    """The 5h window this account reports that a note can be read from, or None.

    The furthest along of its session meters with a numeric used% in a window that has not
    rolled over; the week aside, this is what stops a turn first.
    """
    meters = [m for m in prov.get("meters") or []
              if m.get("window_secs") == usage.SESSION_SECS
              and usage._number(m.get("used")) is not None and not usage._past(m, now)]
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
    reading may be wrong, then the 5h window, then the scoped cap -- and they are offered in
    that order and drawn in the row's.
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


def provider_name(cfg, name):
    """This provider's name on every screen: its own `name` key -- the one its harness gives
    it, written by `+ add` (`Z.AI Coding Plan`) -- else the company's, else its key
    capitalised."""
    entry = cfg["providers"].get(name)
    own = entry.get("name") if isinstance(entry, dict) else None
    return own.strip() if isinstance(own, str) and own.strip() else NAMES.get(name, name.title())


def colour(cfg, name):
    """This provider's colour: its own `colour` key, else the shipped one, else the accent."""
    entry = cfg["providers"].get(name)
    own = entry.get("colour") if isinstance(entry, dict) else None
    if isinstance(own, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", own):
        return own
    return COLOURS.get(name, "accent")


def hue(kind):
    """Where a colour sorts: red through violet by its hue, then the near-greys, lightest first.

    A grey's hue is noise, so the greys go by how light they are instead.
    """
    rgb = kind[1:] if kind.startswith("#") else terminal.STATE_STYLES["working"][2]
    shade, saturation, value = colorsys.rgb_to_hsv(*(int(rgb[i:i + 2], 16) / 255
                                                     for i in (0, 2, 4)))
    return (True, -value) if saturation < terminal.GREY else (False, shade)


def usage_rows(cfg):
    """Each usage row `usage_lines` draws, in its order: the provider, the row's label, the
    reading it is drawn from, out of the cached meters, and its account, None for the
    provider's single row.  A provider whose table says `mode = "free"` is no subscription
    and has no row."""
    try:
        providers = json.loads((config.STATE / "usage.json").read_text())["providers"]
        if not isinstance(providers, dict):
            providers = {}
    except (OSError, ValueError, KeyError, TypeError):
        providers = {}
    rows = []
    for name in sorted(cfg["providers"], key=lambda name: hue(colour(cfg, name))):
        if cfg["providers"][name].get("mode") == "free":
            continue
        top = providers.get(name)
        top = top if isinstance(top, dict) else {}
        found = top.get("accounts") if isinstance(top.get("accounts"), dict) else {}
        shown = provider_name(cfg, name)
        for account in config.accounts(cfg, name) or [None]:
            rec = top if account is None else found.get(account)
            rows.append((name, shown if account is None else
                         config.account_label(cfg, name, account, shown),
                         rec if isinstance(rec, dict) else {}, account))
    return rows


def usage_summary(cfg, width, most=None, rows=None):
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
    found = usage_cells(cfg, rows=rows)
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


METER = 10        # cells of a subscription's meter on the ak screen
COLUMN = 33       # ... and of its whole cell, its label, meter and share or `empty until` date


def usage_columns(width):
    """How many subscriptions a line of the grid holds at `width`: one to three, two apart."""
    return max(1, min(3, width // (COLUMN + 2)))


def usage_lines(cfg, width, lit=None, rows=None, spans=None, ending=None):
    """The cached weekly allowances as a grid, without probing adapters or spending a reset:
    each subscription (`usage_cells`), as many to a line as `usage_columns` fits, by its label,
    a meter -- `▰` left, `▱` spent -- and what its cell says.  At rest no company's colour is
    drawn; `lit`, from 1, the one the pointer is on, has its label and its meter's filled cells
    in its provider's (`colour`), and one whose login ends soon (`login_notes`) has its meter
    amber the rest of the time.  The rest is said under the grid (`usage_detail`).  What
    each cell says is whole: the labels give way to the longest, and a width with no room for
    a label beside it has no grid (`[]`), the screen saying the readings (`usage_summary`).
    `spans`, where handed in, gets each one's cells that take its colour: {number: [(line,
    column, text, what it is drawn in at rest)]}, the line from 0 and the column from 1;
    `ending`, `login_notes` of `rows` where the caller has read them already."""
    rows = usage_rows(cfg) if rows is None else rows
    found = [(*cell[:3], terminal.plain(cell[3])) for cell in usage_cells(cfg, rows=rows)]
    if not found:
        return []
    columns, room = usage_columns(width), min(COLUMN, width - 2)
    # what a cell says beside its label: its meter at the least, four cells, then its share
    said_room = max(terminal.cells(said) + (6 if left else 0) for _, _, left, said in found)
    label_room = min(12, room - 2 - said_room,
                     max(terminal.cells(terminal.plain(label)) for _, label, _, _ in found))
    if label_room < 1:
        return []
    # a phone's one column is its width: the meter gives way first, down to four cells
    meter = max(4, min(METER, room - label_room - 13))
    full, empty = ("▰", "▱") if terminal.utf8() else ("#", "-")
    ending = login_notes(rows) if ending is None else ending
    lines = []
    for start in range(0, len(found), columns):
        cells = []
        for number, (name, label, left, said) in enumerate(found[start:start + columns],
                                                           start + 1):
            ink = colour(cfg, name) if number == lit else None
            warn = ending[number - 1] and not ink    # under the pointer its line says when
            shown = terminal.cut(terminal.plain(label), label_room)
            at = (start // columns, 3 + (number - 1) % columns * (COLUMN + 2))
            took = [(*at, shown, None)]
            text = ((terminal.styled(shown, ink) if ink else shown)
                    + " " * (label_room - terminal.cells(shown) + 2))
            if not left:     # no meter: `empty until`, or why there is none, or the credits
                text += (terminal.styled(said, "amber") if warn
                         else terminal.styled(said, "dim") if left is None else said)
            else:
                filled = max(1, round(meter * left / 100))
                fill = ink or warn and "amber"
                took.append((at[0], at[1] + label_room + 2, full * filled,
                             ending[number - 1] and "amber"))
                text += ((terminal.styled(full * filled, fill) if fill else full * filled)
                         + terminal.styled(empty * (meter - filled), "dim") + "  " + said)
            cells.append(text + " " * max(0, room - terminal.cells(text)))
            if spans is not None:
                spans[number] = took
        lines.append(("  " + "  ".join(cells)).rstrip())
    return lines


def login_notes(rows, now=None):
    """What the line under the grid says of each of `rows`' (`usage_rows`') login while it ends
    within logins.WARN_WITHIN or has ended, `login owner@acme.test ends Mon 26 Oct 04:47 (in 2
    days)`, its meter amber meanwhile; None for the rest."""
    from . import logins    # here, not at the top: logins names subscriptions through the menu
    now = time.time() if now is None else now
    found = logins.read()
    notes = []
    for name, _, _, account in rows:
        login = found.get(name)
        login = login.get(account or config.DEFAULT_ACCOUNT) if isinstance(login, dict) else None
        when = logins.ending(login, now)
        notes.append(when and " ".join(filter(None, ("login", login.get("email"), when))))
    return notes


def meter_spots(width, count, first, rows=False):
    """Where each of `count` subscriptions' meters sits on the grid `usage_lines` draws `width`
    wide from line `first`: {line: (None, [(first, last, ("usage", number))])}, `number` from
    1, the columns counted from 1 as the terminal counts; with `rows`, as on `c`, each meter a
    row of its own (terminal.under), its cell after it again."""
    columns = usage_columns(width)
    return {first + line: (None, [(3 + n * (COLUMN + 2), 2 + n * (COLUMN + 2) + COLUMN,
                                   *(("usage", line * columns + n + 1),) * (1 + rows))
                                  for n in range(min(columns, count - line * columns))])
            for line in range(-(-count // columns))}


def usage_detail(cfg, number, width=None, now=None, rows=None, ending=None):
    """What the line under the usage grid says of subscription `number`, from 1, while the
    pointer is on it: its label in its provider's colour, then -- each where it applies, joined
    with ` · ` -- a login that ends soon, in amber (`login_notes`), when its week resets, the
    credits it holds, the resets in hand (`in_hand`), each model's own cap that differs
    (`scoped_notes`), its 5-hour window (`session_note`), why its last probe failed (`fault`)
    and how old the reading is (`usage.as_of`); for one with no week to draw, why (`unread`).
    In `width` cells the notes give way one by one, the least worth keeping first (`fitting`),
    and the label too, past the notes but before the login; `rows` as `usage_cells`', and
    `ending` as `usage_lines`'."""
    now = time.time() if now is None else now
    rows = usage_rows(cfg) if rows is None else rows
    if not 0 < number <= len(rows):
        return ""
    name, label, prov, _ = rows[number - 1]
    week, why, readable = reading(cfg, name, prov, now)
    notes = [(0, why)] if week is None else [
        (-1, usage.credits_note(prov)), (0, resets_note(week, now)), (1, in_hand(prov)),
        *((3, note) for note in scoped_notes(cfg, name, readable, week)),
        session_note(prov, now) or (0, ""), (1, fault(prov)), (1, usage.as_of(prov, now))]
    login = (login_notes(rows[number - 1:number], now) if ending is None
             else ending[number - 1:number])[0]
    notes = [note for note in [(-2, login), (-2, login and "click to log in again"), *notes]
             if note[1]]
    room = 10 ** 6 if width is None else width - 4
    # a login ending is kept before the label, which the lit cell above already shows; a label
    # too long for the line gives way, as in its cell
    held = terminal.cells(login or "")
    label = terminal.cut(label, room - (held if held <= room else 0))
    room -= terminal.cells(label)
    return (terminal.styled(label, colour(cfg, name)) + "  " + terminal.styled(" · ", "dim")
            .join(terminal.styled(part, "amber") if part == login else _note_styled(part)
                  for part in fitting(notes, room)))


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


def show_notices(messages):
    """Read boot resume, maintenance and job messages once, before the main screen clears them."""
    if messages:
        pause(*(" " + part for message in messages for part in terminal.wrap(
            message.replace(os.path.expanduser("~") + "/", "~/"), terminal.width() - 1)))


# The rows under the models, each running its own step.
CONFIG_ROWS = ("+ add a model", "+ add a provider", "Subscriptions", "Discord", "Weekly audit")
AUDIT = ("row", "Weekly audit")  # on or off, and the models its seat takes (config.audit)
# What a subscription offers, its meter over `c`'s page and its row on `Subscriptions` alike, each
# where it applies (subscription_acts), and without UTF-8.
SUBSCRIPTION_ACTS = (("↻ spend a reset", "spend a reset"), ("− remove", "- remove"))
# What `+ add a provider` offers each provider the shipped default has as: its company, and the
# harness it runs on; any other is its name.  One shipped on a harness that runs any
# provider (config.provider_hosts) is offered among that harness's own.
COMPANIES = {"anthropic": "Anthropic / Claude Code", "openai": "OpenAI / Codex",
             "meta": "Meta / Muse", "xai": "xAI / Grok Build", "google": "Google / Antigravity"}
# What `− remove` asks, and what it means; then the same about one subscription of a provider.
REMOVE_PROVIDER_ASK = ("Remove {} and its models?",
                       "Its models leave the config with it; its login stays on this machine.")
REMOVE_SUBSCRIPTION_ASK = ("Remove {}?",
                           "Nothing new starts on it; its login stays on this machine.")
# Short headings leave room for both roles and the effort on a phone.
CONFIG_HEADS = (*orch.ROLE_HEADS, "effort")
# The key line for the cell the highlight is on, and the same without UTF-8.
# The key on the config screen that opens what `ak models` recommends per role.
ADVICE_KEY = "r recommended"
CONFIG_KEYS = {"mark": ("↑↓←→ move   ⏎ mark", "arrows move   enter mark"),
               "effort": ("↑↓←→ move   ⏎ effort", "arrows move   enter effort"),
               "row": ("↑↓ move   ⏎ open", "arrows move   enter open"),
               "label": ("↑↓←→ move   ⏎ open", "arrows move   enter open")}
# A model's own screen: the values ←/→ step, then the one that asks first; the role whose
# effort each effort among them sets (its key: config.ROLE_EFFORTS), a worker's reading `same`
# while its key is unset.
MODEL_ROWS = ("model id", "effort", "executes at", "reviews at", "Remove")
EFFORT_ROWS = {"effort": "orchestrator", "executes at": "executor", "reviews at": "reviewer"}
SAME = "same"
MODEL_KEYS = {"step": ("↑↓ move   ←→ choose", "arrows move   left/right choose"),
              "remove": ("↑↓ move   ⏎ remove", "arrows move   enter remove")}
REMOVE_ASK = ("Remove {} from the config?",   # what `Remove` asks, and what it means
              "Nothing new starts on it; + add a model brings it back.")
# Every effort word, weakest first -- the widest list a manifest names (adapters/muse.toml) --
# so a new model id that does not take its model's effort takes the nearest one it does.
EFFORT_RANK = ("none", "minimal", *config.EFFORTS)
ADD_STEPS = ("harness", "model", "effort")   # `add a model`'s lists, each opening under the last
ADD_KEYS = {"choose": ("↑↓ move   ⏎ choose", "arrows move   enter choose"),
            "add": ("↑↓ move   ⏎ add", "arrows move   enter add")}


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
    providers."""
    return config.offered(cfg)


def model_label(cfg, name, width):
    """The model's full name on `c` and `n` (`config.model_name`), cut only to the space its
    row has."""
    return terminal.cut(config.model_name(cfg, name), width)


def model_heading(cfg, provider):
    """The same provider heading over the models on `c` and `n`."""
    return terminal.styled(provider_name(cfg, provider), "accent")


# the roles `r` takes, each with its group in a seat's record (its config role: matrix.CONFIG_ROLES)
TAKEN = {"execute": "workers", "review": "reviewers"}


def takes(cfg, row, role):
    """The configured model `r` takes a recommended `row` as in `role`, read off `cfg` as it
    stands, not the row as stored, so the same matrix is read against the config each draw:
    the one running the row in that role (matrix.runs), else the first running that model on
    that harness, which `r` sets the row's effort on; None, `(not configured)`, where none
    does, a model removed on the `c` screen at once."""
    return matrix.runs(cfg, row, role) or next(
        (name for name in config.offered(cfg)
         if (cfg["models"][name]["harness"], cfg["models"][name]["model"])
         == (row["harness"], row["model"])), None)


def advice(cfg, held):
    """What `ak models` recommends per role off `held`, the matrix as last computed
    (matrix.stored): {role: (its row's label, the configured model `r` takes it as or None
    (takes), the row's effort)}; {} while nothing is computed."""
    found = {}
    marked = matrix.assessment(cfg, held.get("rows") or [])
    for role, rows in matrix.recommended(marked, matrix.within(cfg)).items():
        name = takes(cfg, rows[0], role)
        found[role] = (matrix.row_label({**rows[0], "name": name}), name, rows[0].get("effort"))
    return found


def take_advice(cfg, name, selected, providers, found):
    """`r`: the seat's executors and reviewers become the recommended rows' models, each at
    the row's effort as its entry's own for that role (`exec_effort`, `review_effort`; a row
    at the entry's effort or at none leaves it following the effort, _follows), saved to the
    config (_saved) and then to the seat's record at once as a flipped mark is (marks_saved);
    a config that cannot be saved changes no mark and says why.  The orchestrator is only
    said, since moving the seat is its orchestrator mark's.  What to say under the rows, or
    ""."""
    taken = {role: found.get(role, (None, None, None))[1:] for role in TAKEN}
    if not any(model for model, _ in taken.values()):
        return "nothing to take: the recommended rows are not configured models"
    changed, note = orch.role_groups(cfg, selected, providers, **{
        TAKEN[role]: [model] for role, (model, _) in taken.items() if model})
    if note:
        return note
    before = copy.deepcopy(cfg)
    for role, (model, effort) in taken.items():
        if model:
            entry, key = cfg["models"][model], config.ROLE_EFFORTS[matrix.CONFIG_ROLES[role]]
            entry[key] = effort or entry["effort"]
            _follows(entry, [key])
    note = _saved(cfg, cfg, before) if cfg != before else ""
    return note or marks_saved(name, selected, changed)


def marks_saved(name, selected, changed):
    """A seat's role groups as `changed` has them, saved to its record at once and then into
    `selected`; a save that fails leaves both alone.  What to say under the rows, or ""."""
    try:
        # a screen open across a rename has the old name
        saved = config.update_session(config.resolve_session(name), workers=changed["workers"],
                                      reviewers=changed["reviewers"])
    except OSError as exc:
        return f"session: {exc}"
    if saved is None:
        return f"session: {name} has no saved models"
    selected.update(changed)
    return ""


# The models screen, `r recommended` on `c`: every model the matrix has a row for against the
# public boards, at the effort its arrows stand on, the recommendation and the rows as good,
# and the one knob, how far under the best still counts as as good (`within` in config.toml).
MODELS_KEYS = {"knob": ("↑↓ move   ←→ as good", "arrows move   left/right as good"),
               "effort": ("↑↓ move   ←→ effort", "arrows move   left/right effort"),
               "still": ("↑↓ move", "arrows move")}
MODELS_TAKE = "r take recommended"
KNOB = ("knob", "within")
KNOB_TEXT = "as good as the best: within "
MODELS_HEADS = ("model", "harness", "effort", *orch.ROLE_HEADS, "cost $")
MODELS_NOTE = ("quality is 100 less how many points a model is behind the best on the public "
               "boards; cost is what a task of Artificial Analysis's index run cost it, in dollars")
CHEAPEST = "the cheapest as good: "   # why the recommended row is the one: said before it
SAID = ("best", "as good", "recommended")   # the lines that say why, rows the highlight rests on


def models_table(held):
    """The matrix's rows by model, {(harness, model): {effort: row}}: the scored models first,
    by their best quality in any role at any effort, then the rest, each by harness and
    model."""
    table = {}
    for row in held.get("rows") or []:
        table.setdefault((row["harness"], row["model"]), {})[row["effort"]] = row

    def quality(rows):
        return max(map(matrix.best, rows.values()), default=-1)
    return dict(sorted(table.items(), key=lambda item: (-quality(item[1]), *item[0])))


def models_levels(cfg, key, rows):
    """The efforts a model's arrows step through: its catalog's, as the `c` screen's bars
    count them (effort_levels), and any the matrix has a row at or the config runs it at
    besides, weakest first."""
    listed = effort_levels({"harness": key[0], "model": key[1]}) or []
    besides = {effort for effort in rows if effort}
    besides.update(cfg["models"][name].get("effort") for name in _runs(cfg, *key))
    return listed + sorted((effort for effort in besides if effort and effort not in listed),
                           key=matrix.effort_rank)


def models_shown(cfg, key, rows, levels):
    """The effort a model's row opens on: the one the config runs it at, else the effort of
    its best row, else the first its arrows step through, else none (a model whose one row is
    at none, the boards naming no effort, opens on its first level and shows that row)."""
    names = _runs(cfg, *key)
    if names:
        return cfg["models"][names[0]].get("effort")
    scored = {effort: matrix.best(row) for effort, row in rows.items() if effort}
    best = max((effort for effort, score in scored.items() if score >= 0),
               key=lambda effort: (scored[effort], matrix.effort_rank(effort)), default=None)
    return best if best is not None else levels[0] if levels else None


def models_at(rows, effort):
    """A model's row ({effort: row}, models_table) at `effort`, else the one every board it
    matched names no effort for, at none or the config's effort, which stands at every effort
    of the model (matrix.placed stands it at any); {} with neither."""
    return rows.get(effort) or next(
        (row for row in rows.values()
         if all(hit["effort"] is None for hit in (row.get("matched") or {}).values())), {})


def _entry(cfg, row, role):
    """A row as the lines above the table say it: its label under the configured model `r`
    takes it as in `role` (takes), its quality for the role and what a task of its index run
    cost (`Opus 5.5 @ xhigh 97 $5.98`, by its full name; the cost left out where Artificial
    Analysis has not run it)."""
    cost, name = row["values"].get(matrix.COST), takes(cfg, row, role)
    return (f"{matrix.row_label({**row, 'name': name and config.model_name(cfg, name)})} "
            f"{row['scores'][role]['score']:.0f}" + ("" if cost is None else f" ${cost:.2f}"))


def models_body(cfg, table, levels, shown, at, picks):
    """The models screen's lines, and where its rows sit on them: {line: (row, cells)}.

    First the knob, `within` between the arrows that step it (KNOB), then the three lines that
    say why (SAID): dim, the best row per role (matrix.tops) and the rows as good as it
    (`picks`, matrix.recommended), then the recommended row per role, said as the cheapest as
    good (CHEAPEST), each row with its quality and cost (_entry) under the configured model `r`
    takes it as; each line a row the highlight rests on and nothing more, so a short screen,
    where they wrap to more lines than its page holds, shows each in turn, a page at a time
    where one is taller than the page (matrix_key).  Then, dim, what
    quality and cost are, a row read the same way, and under it every model of `table`
    (models_table) once: its label, its full name where the config runs it, else its id, dim
    where no board scores it, its harness (dim), its effort between the arrows that step it
    (`shown`; a word alone with one effort, `-` with none), its quality per role at that effort
    (its row there, models_at; `-` without a score, the recommended row's in `done`'s colour,
    one as good in the accent) and what a task of Artificial Analysis's index run cost; on a narrow
    screen the harness gives way, then the cost, and where the label would still be cut each
    model takes two lines, its label and harness over its effort and numbers, the harness
    giving way again where the label would still be cut beside it.  `at`
    is the highlighted row; `cells` are the knob's and each effort's text, arrows and all, for
    a click, counted from 1 as the terminal counts.
    """
    room, utf = terminal.layout_width(), terminal.utf8()
    arrows = "‹ {} ›" if utf else "< {} >"
    lines, places = [], {}
    knob = arrows.format(f"{matrix.within(cfg):g}")
    first = 2 + terminal.cells(KNOB_TEXT)
    line = "  " + KNOB_TEXT + (terminal.styled(knob, "reverse") if at == KNOB else knob)
    places[len(lines)] = (KNOB, [(first + 1, first + terminal.cells(knob), 0)])
    lines.append(terminal.highlight(line) if at == KNOB else line)
    ids = {role: [(row["harness"], row["model"], row["effort"]) for row in rows]
           for role, rows in picks.items()}
    tops = matrix.tops(matrix.assessment(cfg, [row for rows in table.values()
                                                for row in rows.values()]))
    said = {word: [] for word in SAID}
    for number, role in enumerate(matrix.ROLES):
        rows, head = picks.get(role) or [], orch.ROLE_HEADS[number]
        if role in tops:
            said["best"].append(f"{head} {_entry(cfg, tops[role], role)}")
        if rows[1:]:
            said["as good"].append(f"{head} " + ", ".join(_entry(cfg, row, role)
                                                           for row in rows[1:]))
        if rows:
            said["recommended"].append(f"{head} {_entry(cfg, rows[0], role)}")
    wide = max(terminal.cells(word) for word in said)
    for word, parts in said.items():
        text = (CHEAPEST if word == "recommended" and parts else "") + (" · ".join(parts) or "none")
        for number, part in enumerate(terminal.wrap(text, room - 2 - wide - 2)):
            places[len(lines)] = (("said", word), [])
            line = terminal.table_row([word if number == 0 else "", part],
                                      [wide, room - 2 - wide - 2], indent="  ",
                                      kinds=("dim", None if word == "recommended" else "dim"))
            lines.append(terminal.highlight(line, number == 0) if at == ("said", word) else line)
    here = ("said", "quality and cost")
    for number, part in enumerate(terminal.wrap(MODELS_NOTE, room - 2)):
        places[len(lines)] = (here, [])
        line = "  " + terminal.styled(part, "dim")
        lines.append(terminal.highlight(line, number == 0) if at == here else line)
    lines.append("")
    labels = {key: next((config.model_name(cfg, name) for name in _runs(cfg, *key)), key[1])
              for key in table}
    showing = {key: models_at(rows, shown[key]) for key, rows in table.items()}
    texts, kinds = {}, {}
    for key, row in showing.items():
        scored = any(found for other in table[key].values()
                     for found in (other.get("scores") or {}).values())
        stepper = (arrows if len(levels[key]) > 1 else "{}").format(shown[key] or "-")
        texts[key] = [labels[key], key[0], stepper]
        kinds[key] = [None if scored else "dim", "dim",
                      "reverse" if at == ("model", *key) else None]
        for role in matrix.ROLES:
            found = (row.get("scores") or {}).get(role)
            place = (*key, row.get("effort"))
            texts[key].append("-" if not found else f"{found['score']:.0f}")
            kinds[key].append("dim" if not found else "done" if place == ids.get(role, [None])[0]
                              else "accent" if place in ids.get(role, []) else None)
        cost = (row.get("values") or {}).get(matrix.COST)
        texts[key].append("-" if cost is None else f"{cost:.2f}")
        kinds[key].append("dim" if cost is None else None)
    widths = [max(terminal.cells(text) for text in (head, *(texts[key][n] for key in table)))
              for n, head in enumerate(MODELS_HEADS)]
    # the columns that fit the screen: the harness gives way first, then the cost; where the
    # label would still be cut, each model takes two lines, its label and harness on the
    # first, its effort and numbers under them (a 40-cell phone), and the harness gives way
    # again where the label would still be cut beside it (a catalog id 35 cells wide)
    kept, under = list(range(len(MODELS_HEADS))), []
    for column in (1, 6):
        if sum(widths[n] + 2 for n in kept) > room:
            kept.remove(column)
    if sum(widths[n] + 2 for n in kept) > room:
        kept, under = [0, 1], kept[1:]
        if sum(widths[n] + 2 for n in kept) > room:
            kept.remove(1)
    widths[0] = max(1, min(widths[0], room - sum(widths[n] + 2 for n in kept[1:]) - 2))
    groups = [(columns, indent, {n for n, column in enumerate(columns) if column >= 3})
              for columns, indent in [(kept, "  "), (under, "    ")] if columns]
    for columns, indent, right in groups:
        lines.append(terminal.styled(terminal.table_row([MODELS_HEADS[n] for n in columns],
                                                        [widths[n] for n in columns],
                                                        indent=indent, right=right), "dim"))
    for key in table:
        here = ("model", *key)
        for number, (columns, indent, right) in enumerate(groups):
            cells = []
            if 2 in columns:          # the effort's text, arrows and all, for a click
                first = len(indent) + sum(widths[n] + 2 for n in columns[:columns.index(2)])
                cells = [(first + 1, first + terminal.cells(texts[key][2]), 0)]
            places[len(lines)] = (here, cells)
            line = terminal.table_row([texts[key][n] for n in columns],
                                      [widths[n] for n in columns], indent=indent,
                                      kinds=[kinds[key][n] for n in columns], right=right)
            lines.append(terminal.highlight(line, number == 0) if at == here else line)
    return lines, places


def config_within(cfg, step):
    """`within`, how far under the best still counts as as good, one point along, never under
    0, and saved (_saved); what to say under the rows, or ""."""
    value = max(0, matrix.within(cfg) + step)
    if value == matrix.within(cfg):
        return ""
    before = copy.deepcopy(cfg)
    cfg["within"] = value
    return _saved(cfg, cfg, before)


@terminal.clicks_its_own
def models_screen(cfg, session, selected, providers, held):
    """`models · <seat>`, `r recommended` on `c`: every model the matrix (`held`,
    matrix.stored) has a row for, against the public boards, read with the matrix's keys
    until Esc (models_body).

    ↑/↓, k/j and the wheel move between the knob, the three lines that say why (SAID), the
    quality and cost note (rows read with no action) and the models.  ←/→ on the knob step
    `within`, saved to config.toml at once, and the recommendation follows; on a model they
    step the effort its row shows, through its own efforts (models_levels), the numbers and
    the cost following, nothing saved: the effort a model runs at is set on `c`.  `r` takes
    the recommendation as `c` says it (take_advice): the seat's executors and reviewers
    become the recommended rows' models at their efforts, the orchestrator only said.
    """
    table = models_table(held)
    levels = {key: models_levels(cfg, key, rows) for key, rows in table.items()}
    shown = {key: models_shown(cfg, key, rows, levels[key]) for key, rows in table.items()}
    models = [("model", *key) for key in table]
    here, top, note, title = models[0] if models else KNOB, 0, "", f"models · {session}"
    clock = motion.Clock(page=True)
    while True:
        picks = matrix.recommended(matrix.assessment(cfg, held.get("rows") or []),
                                   matrix.within(cfg))
        where = ("knob" if here == KNOB else "effort"
                 if here[0] == "model" and len(levels[here[1:]]) > 1 else "still")
        keys = (MODELS_KEYS[where][0 if terminal.utf8() else 1]
                + f"   {MODELS_TAKE}   esc back")
        body, places = models_body(cfg, table, levels, shown,
                                   None if terminal.away() else here, picks)
        rows = list(dict.fromkeys(row for row, _ in places.values()))
        act, here, _, top = matrix_key(title, body, places, rows, here, top, note, keys, marks=0,
                                       clock=clock)
        if act is None:
            continue                  # a resize or the pointer: drawn again
        note = ""
        if act == "back":
            return
        if act == "r":
            note = take_advice(cfg, session, selected, providers, advice(cfg, held))
        elif act in ("left", "right", "less", "more") and not terminal.unseen():
            step = 1 if act in ("right", "more") else -1
            if here == KNOB:
                note = config_within(cfg, step)
            elif here[0] == "model":
                taken, key = levels[here[1:]], here[1:]
                at = taken.index(shown[key]) if shown[key] in taken else -1
                if taken:
                    shown[key] = taken[min(max(at + step, 0), len(taken) - 1)]


def config_body(cfg, at=None, column=0, selected=None, providers=None, moves=None, subs=(),
                lit=None):
    """The `c` screen's lines, and where its rows sit on them: {line: (row, cells)}.

    Every offered model once, under its provider's name, a line each: label, the three role
    marks of `selected` -- a session's record, whose missing reviewers are its workers -- and
    its effort: a cell for each level it offers, full up to its effort (terminal.effort_cells,
    effort_levels), then its word; a model with one effort is its word alone.  With no
    session, only the effort, still column 3.  `moves`, a list, is handed each mark's line, key,
    glyph and how it moves once flipped or refused (motion.toggled), and each effort's line,
    key, word and how its cells move once a step changed it (_effort_moves), for the clock.
    A model `providers` read as spent is dim.  A model whose provider runs the subscription
    `lit`, from 1, of `subs` (`usage_rows`) has its label in that company's colour, which the
    clock washes in and out as `lit` comes and goes (motion.washing).  Then `+ add a model`,
    `+ add a provider`, `Subscriptions`, `Discord` and `Weekly audit` with
    their values. A row is `("model", name)` or `("row", one of CONFIG_ROWS)`, so a model that
    happens to be called `Discord` is still a model; `at` is the highlighted one and `column`
    the cell on it the keys act on, -1 its label.  `cells` are a model row's (first, last,
    column), for a click, counted from 1 as the terminal counts. On a phone the cells give
    way, then the label.
    """
    room, utf = terminal.layout_width(), terminal.utf8()
    marks = "●○■□" if utf else "*.x."
    names, models = config_models(cfg), cfg["models"]
    levels = {name: effort_levels(models[name]) for name in names}
    efforts, levelled = {}, {}
    for name in names:
        effort, taken = models[name].get("effort", "?"), levels[name]
        efforts[name] = effort
        # one effort is nothing to step to and no level to show
        levelled[name] = terminal.effort_cells(len(taken), taken.index(effort) + 1 if effort
                                               in taken else 0) if len(taken) > 1 else []
    label = max(terminal.cells(config.model_name(cfg, name)) for name in names)
    heads = CONFIG_HEADS if selected else CONFIG_HEADS[3:]
    widths = [terminal.cells(head) for head in heads[:-1]]
    word = max(terminal.cells(text) for text in efforts.values())
    rest = sum(2 + width for width in widths) + 2
    tall = max(len(cells) for cells in levelled.values())    # the cells, before every word
    tall = tall if 2 + label + rest + tall + 2 + word <= room else 0
    # the words in one column after the most cells any model has, a cell-less one's too
    leads = {name: "".join(levelled[name]) + " " * (tall + 2 - len(levelled[name]))
             if tall else "" for name in names}
    widths.append(max(terminal.cells(heads[-1]),
                      *(terminal.cells(leads[name] + efforts[name]) for name in names)))
    rest += widths[-1]
    label = min(label, max(1, room - 2 - rest))
    left = 2 + label                                        # the columns before the marks
    lines = [terminal.styled((" " * left + "".join(
        "  " + terminal.pad(head, width) for head, width in zip(heads, widths))).rstrip(), "dim")]
    places = {}
    for provider in dict.fromkeys(models[name]["provider"] for name in names):
        lines.append(model_heading(cfg, provider))
        for name in (name for name in names if models[name]["provider"] == provider):
            texts, builds = orch.role_texts(selected, name, marks) if selected else ((), False)
            texts += (efforts[name],)
            note = orch.spent_note(cfg, name, providers) if providers else ""
            shown = model_label(cfg, name, label)
            on = [number for number, (each, *_) in enumerate(subs, 1) if each == provider]
            ink = colour(cfg, provider)
            kind = ("reverse" if at == ("model", name) and column < 0 else ink if lit in on
                    else "dim" if note else None)
            # one wash a label, so a step between its provider's subscriptions keeps it lit
            if moves is not None and on:
                moves.append((len(lines), ("subs", provider), lit in on, motion.washing(
                    [(3, shown, "dim" if note else None)], ink, at == ("model", name))))
            line = "  " + (terminal.styled(shown, kind) if kind else shown) + " " * (
                label - terminal.cells(shown))
            cells, first = [(3, 2 + terminal.cells(shown), -1)], left + 1
            for number, text, width in zip(range(4 - len(texts), 4), texts, widths):
                kind = ("reverse" if at == ("model", name) and number == column else
                        "dim" if note or text in (marks[1], marks[3]) or builds and number == 1
                        else None)
                if number == 3:   # the keys' effort is its word reversed, its cells before it
                    lead = leads[name]
                    lead = terminal.styled(terminal.plain(lead, True), kind) if (
                        kind == "dim" and lead) else lead
                    text = lead + (terminal.styled(text, kind) if kind else text)
                line += "  " + (terminal.toggle(text, width, kind) if number < 3 else
                                text + " " * (width - terminal.cells(text)))
                if number < 3 and moves is not None:
                    moves.append((len(lines), ("mark", name, number), text, motion.toggled(
                        text, width, kind, at == ("model", name), first + 2)))
                # a mark is its whole column; an effort is its own text, cells and all
                cells.append((first + 2, first + 1 + (width if number < 3
                                                      else terminal.cells(text)), number))
                if number == 3 and moves is not None and len(levels[name]) > 1:
                    moves.append((len(lines), ("effort", name), models[name].get("effort"),
                                  _effort_moves(levels[name], models[name].get("effort"), kind,
                                                at == ("model", name),
                                                first + 2 + terminal.cells(leads[name]),
                                                first + 2 if leads[name] and not note else None)))
                first += 2 + width
            places[len(lines)] = (("model", name), cells)
            lines.append(terminal.highlight(line.rstrip()) if at == ("model", name)
                         else line.rstrip())
    lines.append("")
    values = ("", "", "", discord_value(), audit_value(cfg))
    # the values line up past the widest row that has one
    wide = max(terminal.cells(row) for row, value in zip(CONFIG_ROWS, values) if value)
    for row, value in zip(CONFIG_ROWS, values):
        # the value wraps at a word under itself, never cut
        for number, part in enumerate(terminal.wrap(value, room - 2 - wide - 2) or [""]):
            line = terminal.table_row([row if number == 0 else "", part],
                                      [wide, room - 2 - wide - 2], indent="  ") if value else (
                "  " + terminal.cut(row, room - 2))
            places[len(lines)] = (("row", row), [])
            lines.append(terminal.highlight(line, number == 0) if at == ("row", row) else line)
    return lines, places


def effort_levels(entry):
    """The efforts a model's bars count: config.efforts off the catalog its harness last listed
    (config.catalog_held), the one list a step on it walks (config_effort).  None where they
    cannot be read."""
    try:
        return config.efforts(entry.get("harness"), entry.get("model"), config.catalog_held)
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


def _saved(cfg, table, before):
    """config.save; "" when it held.  One that fails puts `table` back as `before`, so the
    screen, and the menu after it, go on with what the file holds, and says why."""
    try:
        config.save(cfg)
    except (config.Error, OSError) as exc:
        table.clear()
        table.update(before)
        return f"config: {exc}"
    return ""


def config_effort(cfg, name, step, wrap=False, role="orchestrator", to=None):
    """`name`'s effort in `role` (config.role_effort: a worker's is the effort while its own
    key is unset) one step along that model's own efforts (config.efforts), never past either
    end unless `wrap` takes it round to the other, or onto the `to`-th of them, and saved; one
    set to an effort it does not take lands on its first, and a worker's stepped onto the
    effort itself is unset again (_follows), while the effort's own step moves no other key.
    The efforts are read `now`, off the catalog already in hand (config.catalog_now): a listing
    never stands between the key and its frame.  What to say under the matrix, or ""."""
    entry, key = cfg["models"][name], config.ROLE_EFFORTS[role]
    try:
        levels = config.efforts(entry.get("harness"), entry.get("model"), config.catalog_now)
    except config.Error as exc:
        return f"config: {exc}"
    current = entry.get(key, entry.get("effort"))
    at = to if to is not None else levels.index(current) + step if current in levels else 0
    at = at % len(levels) if wrap else at
    if not 0 <= at < len(levels) or levels[at] == current:
        return ""
    before = dict(entry)
    entry[key] = levels[at]
    _follows(entry, [key])
    return _saved(cfg, entry, before)


def _follows(entry, keys):
    """Each of `keys`, a role's effort key (config.ROLE_EFFORTS), that sits on the effort
    itself is unset: `same`, it follows the effort again; the effort is the one followed."""
    for key in keys:
        if key != "effort" and entry.get(key) == entry.get("effort"):
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


def _offered(harness, *screen, provider=None):
    """Every model that harness's catalog lists for `provider`, asked while `screen` waits on
    it (`waited`), each with the efforts it is offered at (config.efforts), read off that
    listing without asking the catalog a second time.  A `<provider>/<model>` id is that
    provider's, the way OpenCode names every provider's models, and any other id is every
    provider's the harness runs."""
    listed = waited(lambda: config.catalog(harness), *screen,
                    doing=f"reading the models {harness} offers")
    return [dict(model, efforts=config.efforts(harness, model["id"], lambda _harness: listed))
            for model in listed
            if provider is None or model["id"].partition("/")[0] in (provider, model["id"])]


def config_model_id(cfg, name, step, screen):
    """`name`'s model id one step along the models its harness's catalog lists (_offered),
    never past either end, and saved with the efforts that follow it (_nearest); an id not
    among them lands on the first.  `screen` is what waits on the catalog (`waited`).  What to
    say under the screen, or ""."""
    entry = cfg["models"][name]
    try:
        models = _offered(entry.get("harness"), *screen, provider=entry.get("provider"))
    except config.Error as exc:
        return f"config: {exc}"
    if not models:
        return f"the {entry.get('harness')} catalog names no model"
    ids, current = [model["id"] for model in models], entry.get("model")
    at = ids.index(current) + step if current in ids else 0
    if not 0 <= at < len(ids) or ids[at] == current:
        return ""
    before, levels = dict(entry), models[at]["efforts"]
    entry["model"] = ids[at]
    for key in config.ROLE_EFFORTS.values():     # a role's own key follows only where it is set
        if key == "effort" or key in entry:
            entry[key] = _nearest(entry.get(key), levels)
    _follows(entry, config.ROLE_EFFORTS.values())
    return _saved(cfg, entry, before)


def model_body(cfg, name, at=None):
    """A model's own screen's lines, and where its rows sit on them: {line: (row, cells)}, the
    cells `left` and `right` the arrows of the value on that line, counted from 1 (`under`).

    Its model id, its effort and the efforts it executes and reviews at, each between the
    arrows that step it, then `Remove` and its reviewing so far; `at` is the highlighted row.
    On a phone, where a label and its value do not fit on one line, the value goes under its
    label.
    """
    entry, room = cfg["models"][name], terminal.layout_width()
    arrows = "‹ {} ›" if terminal.utf8() else "< {} >"
    values = [arrows.format(value) for value in (
        entry.get("model", "?"), entry.get("effort", "?"),
        *(entry.get(config.ROLE_EFFORTS[EFFORT_ROWS[row]], SAME)
          for row in MODEL_ROWS[2:4]))] + [""]
    wide = max(terminal.cells(row) for row in MODEL_ROWS)
    under = 2 + wide + 2 + max(terminal.cells(value) for value in values) > room
    lines, places = [], {}
    for row, value in zip(MODEL_ROWS, values):
        value = terminal.cut(value, room - 4 - (0 if under else wide))
        first = 5 + (0 if under else wide)
        parts = ([f"  {row}", f"    {value}"] if under and value
                 else [f"  {terminal.pad(row, wide)}  {value}".rstrip()])
        last = first + terminal.cells(value) - 1
        if row in MODEL_ROWS[2:4] and config.ROLE_EFFORTS[EFFORT_ROWS[row]] not in entry:
            parts[-1] = parts[-1].replace(SAME, terminal.styled(SAME, "dim"))
        for number, line in enumerate(parts):
            places[len(lines)] = (row, [(first, first + 1, "left"), (last - 1, last, "right")]
                                  if number == len(parts) - 1 and value else [])
            lines.append(terminal.highlight(line, number == 0) if row == at else line)
    reviewed, caught, already, unproven = history.review_counts(entry.get("harness"), entry.get("model"))
    summary = (f"Reviewed {reviewed} time{'s' if reviewed != 1 else ''} · caught {caught} · "
               f"{already} already on main · {unproven} unproven" if reviewed
               else "Not used as a reviewer yet")
    lines.extend(["", *("  " + part for part in terminal.wrap(summary, room - 2))])
    return lines, places


@terminal.clicks_its_own
def config_model(cfg, name):
    """`config · <name>`: one model's id, its effort, the efforts it executes and reviews at,
    and `Remove`, read with the matrix's keys until Esc, each change saved and drawn at once.

    ↑/↓, k/j and the wheel move between rows and ←/→ step the value on one: the id through
    its harness's catalog (config.catalog) and nothing else, each effort through that model's
    own (config.efforts).  Nothing is typed, so no id or effort ak does not offer is ever
    written.  Enter on `Remove` asks `Keep` or `Remove` under it, `Keep` picked and Esc
    keeping it; the last model is refused without asking, and one removed goes back to the
    matrix at once.
    """
    here, note = MODEL_ROWS[0], ""
    while name in cfg["models"]:
        title = f"config · {config.model_name(cfg, name)}"     # a stepped id renames it
        keys = (MODEL_KEYS["remove" if here == "Remove" else "step"][0 if terminal.utf8() else 1]
                + "   esc back")
        body, places = model_body(cfg, name, None if terminal.away() else here)
        shown = body + (["", *(terminal.styled("  " + part, "dim") for part in terminal.wrap(
            note, terminal.layout_width() - 2))] if note else [])
        spots = terminal.frame(title, shown, keys, places=places)
        key = terminal.read_key()
        if key is None:
            continue                  # a resize: drawn again at the new size
        spot = terminal.under(key, spots)
        if key.name == "point":
            here = spot.what or here  # the highlight on the pointer's row, an arrow lit
            continue
        act, note = key.name, ""
        if act == "click":
            if spot.what is None:
                if spot.cell == "esc":
                    return
                continue
            here = spot.what          # on the value an arrow steps it
            act = "enter" if here == "Remove" else spot.cell or ""
        if act in ("esc", "eof"):
            return
        if terminal.step(key):
            here = MODEL_ROWS[min(max(MODEL_ROWS.index(here) + terminal.step(key), 0),
                                  len(MODEL_ROWS) - 1)]
        elif here == "Remove" and act in ("enter", "space"):
            if config.offered(cfg) == [name]:
                note = "the config needs one model"
                continue

            def around(card):     # the screen around the card, drawn again on a resize
                lines = model_body(cfg, name)[0]
                terminal.frame(title, [*lines, *card], "esc back")
                return 3 + len(lines)
            if terminal.confirm(REMOVE_ASK[0].format(config.model_name(cfg, name)), REMOVE_ASK[1], "Remove", around):
                before = copy.deepcopy(cfg)
                config.remove_model(cfg, name)
                note = _saved(cfg, cfg, before)
        elif here != "Remove" and act in ("left", "right") and not terminal.unseen():
            step = 1 if act == "right" else -1
            try:
                note = (config_model_id(cfg, name, step, (
                    title, lambda: model_body(cfg, name, here)[0], keys))
                        if here == "model id"
                        else config_effort(cfg, name, step, role=EFFORT_ROWS[here]))
            except Back:
                return                # Esc while the catalog was asked


def config_meters(cfg, at=None, rows=None, spans=None):
    """The lines over the `c` screen's page, on every page, and where its meters are on them
    (meter_spots): each subscription's meter as the main screen draws it (`usage_lines`, of
    `rows` where read already, `spans` handed on), and under them a line that, while `at`, from
    1, has the highlight, says what its cell has no room for (`usage_detail`), its meter lit as
    the pointer lights it there; none without a grid."""
    rows, width = usage_rows(cfg) if rows is None else rows, terminal.layout_width()
    ending = login_notes(rows)
    meters = usage_lines(cfg, width, lit=at, rows=rows, spans=spans, ending=ending)
    if not meters:
        return [], {}
    detail = "  " + usage_detail(cfg, at, width, rows=rows, ending=ending) if at else ""
    return [*meters, detail], meter_spots(width, len(rows), 0, rows=True)


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


def matrix_page(body, places, here, top, under, keys, over=()):
    """The page of a matrix screen's rows that fits between `over` and `under`, lines of its
    own above and below the rows, and its key line: (top, room), the first line of `body` shown
    and how many are.  `top` stays where it was while the page holds every line of `here`, or
    any of them for a row taller than the page, else moves the least that makes it so, and
    never past the last page; a cell that is a row of its own (terminal.under) is on its line."""
    room = max(1, terminal.height() - 5 - len(terminal.key_line(keys)) - len(under) - len(over))
    drawn = [number for number, (row, cells) in places.items()
             if row == here or any(here in cell[3:] for cell in cells)] or [0]
    lo, hi = drawn[-1] - room + 1, drawn[0]       # the tops holding every line of the row
    if lo > hi:                                   # taller than the page: the tops holding any
        lo, hi = drawn[0] - room + 1, drawn[-1]
    return max(0, min(max(top, lo), hi, len(body) - room)), room


def note_lines(note):
    """A matrix screen's `note`, dim lines of its own under a blank one; none for no note."""
    return ["", *(terminal.styled("  " + part, "dim") for line in note.splitlines()
                  for part in terminal.wrap(line, terminal.layout_width() - 2))] if note else []


def matrix_key(title, body, places, rows, here, top, note, keys, timeout=None, marks=2,
               fetched=None, clock=None, moves=(), under=(), over=(), over_places=None):
    """One draw of a matrix screen and the key read on it: (act, here, column, top).

    The `c` screen and a project's feature switches are read this way: rows the highlight moves
    through, and on a row cells, one a column.  `places` is {line: (row, cells)}, each cell
    (first, last, column) counted from 1 as the terminal counts.  On a screen too short for
    every row the part the highlight is on is shown, `over` has lines of its own above it and
    `under`, then `note`, under it, whatever the height; `moves` counts `under`'s on after
    `body`'s, and `over_places` are `over`'s, each cell on a line a row of its own (a meter on
    `c`).  ↑/↓, k/j and the wheel move `here` through `rows`, turning the pages of a row
    taller than the page before they leave it.  A click on a row
    makes it `here`, and one on a cell makes that the column, acting `enter` on the first
    `marks` columns and, on another's, the cell of it clicked, from 0; `column` is None where
    no cell was clicked; a cell that only explains is none.  The pointer does the same and acts
    on nothing, the cell it is on lit.  `act` is `back` for Esc or a click on `esc back`, None when the screen wants drawing again -- a
    resize, the pointer, or `timeout` seconds with no key -- a character key's character, its
    key-line item's too (`r recommended`), and any other key's name, `enter` a click on `⏎`'s.
    `fetched()` says since when the screen's content is being fetched, or None: while it is, the
    rule under the header glides (`motion.fetching`) and the read ends, None, once it lands.
    `clock` moves what `moves` -- (line, key, value, start) -- says is news (`motion.Clock.look`)
    on the lines shown, `over`'s counted back from the page's first, -1 its last, each by `start(clock, row, since, before)`, its frames drawn while the
    key is waited for; a key, not the pointer, ends them on their last frames.
    """
    said = note_lines(note)
    top, room = matrix_page(body, places, here, top, [*under, *said], keys, over)
    shown, first = body[top:top + room], 3 + len(over)     # the screen row of the page's first
    spots = terminal.frame(title, [*over, *shown, *under, *said], keys, places={
        **(over_places or {}), **{len(over) + line - top: place for line, place in places.items()
                                  if top <= line < top + room}},
        drawn=clock and (lambda: clock.drawn(moves, lambda line: first + line if line < 0
                                             else first + line - top
                                             if top <= line < top + room else
                                             first + len(shown) + line - len(body)
                                             if line >= len(body) else None)))
    began = fetched and fetched()
    if began is not None:     # on the screen's own clock, so what else moves goes on with it
        clock = motion.fetching(clock or motion.Clock(), began)
    if clock is None or clock.wait() is None:
        key = terminal.read_key(timeout)
    else:
        key = moving(clock, timeout=timeout or TICK,
                     going=None if began is None else lambda: fetched() == began)
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
            item = {"esc": "back", "⏎": "enter"}.get(spot.cell, spot.cell or "")
            return (item if item in ("back", "enter") or len(item) == 1 and item.isalpha()
                    else ""), here, None, top
        act = "enter" if here[0] in ("row", "usage") else ""      # a row runs its step
        if column is not None:
            act = "enter" if column < marks else key.col - spot.first
    if act in ("esc", "eof"):
        return "back", here, column, top
    step = terminal.step(key)
    if step and rows:
        mine = [line for line, (row, _) in places.items() if row == here]
        if mine and (mine[-1] >= top + room if step > 0 else mine[0] < top):
            top += step * room    # a row taller than the page: its next page before the next row
        else:
            here = rows[min(max(rows.index(here) + step, 0), len(rows) - 1)]
    return act, here, column, top


@terminal.clicks_its_own
def config_matrix(cfg, keyboard, version, session=None, selected=None, providers=None, note=""):
    """The `c` screen read with the keys until Esc; the config as it left it, each
    subscription's meter over its page (config_meters).

    `selected` is `session`'s record, and its role marks are that seat's models: Enter, space or
    a click flips one (session_mark), the orchestrator moving the seat at once, the roles saved
    to the record for the runs it launches next, the mark filling or emptying over two frames
    and one refused shaking (motion.toggled).  With no session they are new seats': a flip is
    [defaults], what the next `n` starts from (defaults_mark), and no open seat changes.
    ↑/↓, k/j and the wheel move between rows and ←/→ between columns, the effort's too.  Enter
    or space on an effort steps it up, from its highest round to its lowest, as a click on its
    word does, and a click on one of its cells takes that level: each change is saved and drawn
    at once, each cell it fills lighting and each it empties dimming in turn, and a step onto
    the model's highest sends a light through its word (config_body, on the clock); nothing
    replays after another screen.
    Enter or a click on a model's label, left of its marks, opens that model's own screen
    (config_model), and Esc there comes back to its row.  `r`, or a click on `r recommended`,
    opens the models screen (models_screen), every model against the boards, where `r` takes
    the recommendation.  Enter or a click
    on `+ add a model` opens its screen (config_add), and a model added there is the row
    highlighted after it, `+ add a provider` its own (config_add_provider) and
    `Subscriptions` its page (config_subscriptions).  ↑ past the
    first model, and the pointer, reach
    the meters over the page: one is lit as the main screen lights it, its colour washing in
    over it and the labels of the models on it and out as it goes, and Enter or a click
    opens what it offers (config_usage).  The row a model, a provider or a subscription was just
    added on glows (motion.glowing); on `Discord` its two
    secrets are typed on the same keys (config_discord).  agentkit's build, `version`, is read
    under the rows, dim, on every page.
    On a screen too short for every row the part the highlight is on is shown, and what the
    last key could not do -- the last reviewer, a switch, a save or a catalog that failed -- has
    lines of its own under it, whatever the height, until the next key; `note` is said so
    before the first.  The worker token's date stands under the rows from TOKEN_WARN_DAYS out.
    """
    from . import watch   # here, not at the top: the menu draws without the tick
    standing = watch.token_standing() or ""     # a file's date, read once a visit
    columns = (-1, 0, 1, 2, 3) if selected else (-1, 3)    # the label, the marks, the effort
    title = config_title(session, selected)
    here, column, top, clock = None, columns[1], 0, motion.Clock(page=True)
    held = matrix.stored()                          # read once a visit: the tick keeps the file
    while True:
        # what `r` recommends is a seat's to take, against the config as it stands
        found = advice(cfg, held) if selected and session else None
        # the meter the highlight or the pointer is on, lit as the main screen lights one
        lit = here[1] if here and here[0] == "usage" and not terminal.away() else None
        subs, spans = usage_rows(cfg), {}
        over, meters = config_meters(cfg, lit, subs, spans)
        models = [*(("model", name) for name in config_models(cfg)),
                  *(("row", row) for row in CONFIG_ROWS)]
        rows = [cell for _, cells in meters.values() for *_, cell in cells] + models
        here = here if here in rows else models[0]    # the highlight is the row itself
        if here[0] == "model" and column not in columns:
            column = columns[-1]      # onto a row without marks
        where = ("row" if here[0] in ("row", "usage") else "effort" if column == 3
                 else "label" if column < 0 else "mark")
        keys = (CONFIG_KEYS[where][0 if terminal.utf8() else 1]
                + (f"   {ADVICE_KEY}" if found else "") + "   esc back")
        # each meter's cells, on the lines over the page counted back from it, washing in and out
        moves = [(line - len(over), ("sub", number), number == lit,
                  motion.washing([(column, text, rest)], colour(cfg, subs[number - 1][0])))
                 for number, took in spans.items() for line, column, text, rest in took]
        body, places = config_body(cfg, None if terminal.away() else here, column,
                                   selected, providers, moves, subs, lit)
        moves += [(line, here, None, motion.glowing(body[line]))     # a row just added glows
                  for line, (row, _) in places.items() if row == here]
        # agentkit's build, read under the page so every page shows it, and what was said under it
        told = "\n".join(filter(None, (f"Version {version or '?'}", note or standing)))
        over, meters, body, places, moves = meters_led((over, meters), body, places,
                                                       note_lines(told), keys, moves)
        act, here, clicked, top = matrix_key(title, body, places, rows, here, top,
                                            told, keys, marks=3,
                                            clock=clock, moves=moves,
                                            over=over, over_places=meters)
        column = column if clicked is None else clicked
        if act is None:
            continue                  # a resize or the pointer: drawn again
        note = ""
        if act == "back":
            return cfg
        if act == "r" and found:
            clock.forget()            # another screen: the matrix back from it replays nothing
            models_screen(cfg, session, selected, providers, held)
            continue
        if act in ("enter", "space") and (here[0] in ("row", "usage") or column < 0):
            clock.forget()            # another screen: the matrix back from it replays nothing
        if here == ("row", CONFIG_ROWS[0]):
            if act in ("enter", "space"):
                added = config_add(cfg)
                here = ("model", added) if added else here    # the highlight on its new row
                if added:
                    clock.touch(here)
        elif here[0] == "usage":
            if act in ("enter", "space"):
                note = config_usage(cfg, here[1])
        elif here == ("row", CONFIG_ROWS[1]):
            if act in ("enter", "space"):
                before = copy.deepcopy(cfg["providers"])
                note = config_add_provider(cfg, keyboard)
                if cfg["providers"] != before:  # a provider or a subscription just added
                    clock.touch(here)
        elif here == ("row", CONFIG_ROWS[2]):
            if act in ("enter", "space"):
                config_subscriptions(cfg, keyboard)
        elif here[0] == "row":
            if act in ("enter", "space"):
                if here == AUDIT:
                    config_audit(cfg)
                else:
                    config_discord()
                try:
                    cfg = config.load()
                except config.Error as exc:
                    pause(f"config: {exc}")
                    return cfg
        elif act in ("left", "right"):
            at = columns.index(column) + (1 if act == "right" else -1)
            column = columns[min(max(at, 0), len(columns) - 1)]
        elif act in ("enter", "space") and column < 0:
            config_model(cfg, here[1])
            if here[1] not in cfg["models"]:
                here = rows[rows.index(here) + 1]     # removed: the row under it is highlighted
        elif act in ("enter", "space") and column < 3:
            note = (session_mark(cfg, session, selected, here[1], column, providers) if session
                    else defaults_mark(cfg, selected, here[1], column))
            if note:
                clock.touch(("mark", here[1], column))    # refused: the mark shakes
        elif act in ("enter", "space") or isinstance(act, int):     # the effort column
            # a click on one of its cells takes that level, and one on its word steps it on
            lead = next((last - first + 1 for row, cells in places.values() if row == here
                         for first, last, at in cells if at == 3), 0) - terminal.cells(
                cfg["models"][here[1]].get("effort", "?"))
            note = (config_effort(cfg, here[1], 0, to=act) if isinstance(act, int) and act < lead
                    else config_effort(cfg, here[1], 1, wrap=True))


def _runs(cfg, harness, model, effort=None):
    """The names the config runs that harness's `model` under, at `effort` if one is given."""
    return [name for name, entry in cfg["models"].items() if isinstance(entry, dict)
            and (entry.get("harness"), entry.get("model")) == (harness, model)
            and effort in (None, entry.get("effort"))]


def _add_choices(cfg, picked, screen):
    """The choices of `add a model`'s step after the values `picked`, each (value, the columns
    it shows).

    The harnesses of the providers the config has (config.provider_harnesses), with their
    providers' names; then every model that harness's catalog lists for that provider, as
    config_model_id offers them (_offered), each id beside its label where the two differ;
    then that model's efforts.
    A model the config runs already, or an effort it runs it at, is marked with the names it
    runs under (_marked).  `screen` is what waits on a catalog (`waited`).
    """
    if not picked:
        return [((harness, provider), [harness, provider_name(cfg, provider)])
                for provider in cfg["providers"]
                for harness in config.provider_harnesses(cfg, provider)]
    harness, provider = picked[0]
    if len(picked) == 1:
        return [(model, [model["label"], "" if model["id"] == model["label"] else model["id"],
                         _marked(_runs(cfg, harness, model["id"]))])
                for model in _offered(harness, *screen, provider=provider)]
    model = picked[1]["id"]
    return [(effort, [effort, _marked(_runs(cfg, harness, model, effort))])
            for effort in picked[1]["efforts"]]


def _marked(names):    # the names a model or effort runs under already, after a tick
    return f"{terminal.glyph('done')} {', '.join(names)}" if names else ""


def _through_choices(cfg, harness, listed, screen):
    """`add a provider`'s first list for `harness`, as OpenCode's own `/models` lists them:
    every model its catalog lists (_offered) of a provider in `listed` with a mode, which it
    runs now, beside that provider's name; then each provider it lists with none, to log in
    to.  Each is ((harness, provider), the model, or None for a login) and the columns it
    shows, so typing a model's name after `/` finds it before a provider that shares it."""
    ready = {provider: name for provider, name, mode in listed if mode}
    choices = []
    for model in _offered(harness, *screen):
        provider = model["id"].partition("/")[0]
        if provider in ready:
            choices.append((((harness, provider), model),
                            [model["label"], ready[provider],
                             _marked(_runs(cfg, harness, model["id"]))]))
    return choices + [(((harness, provider), None),
                       [name, "" if name == provider else provider, "log in"])
                      for provider, name, mode in listed if not mode]


def _short_name(cfg, label):
    """`sonnet` for `Sonnet 5`, `gemini-pro` for `Gemini 3 Pro`: a label's words without their
    versions, then `-2`, `-3` and on until it names no model the config has."""
    words = [word for word in re.findall(r"[a-z0-9]+", label.lower().replace("'", ""))
             if not any(char.isdigit() for char in word)]
    base = "-".join(dict.fromkeys(words)) or "model"
    name, number = base, 1
    while name in cfg["models"]:
        number += 1
        name = f"{base}-{number}"
    return name


def add_body(picked, choices, at, steps=ADD_STEPS, finding=None):
    """`add a model`'s lines, and the choice each list row is: {line: index}.

    Each step chosen so far on a line of its own -- `harness  claude · Claude` -- and under
    them the step being chosen, its name -- and `/` with what is being found in it, while
    `finding` -- then its choices in columns with `at` highlighted: the steps stack up as they
    are chosen.  On a phone a model's id gives way first, then its
    label, and its mark keeps up to half the row.
    """
    room = terminal.layout_width()
    wide = max(terminal.cells(step) for step in steps)
    lines = [f"  {terminal.pad(step, wide)}  "
             + terminal.cut(" · ".join(filter(None, texts[:2])), room - 4 - wide)
             for step, (_, texts) in zip(steps, picked)]
    lines.append(f"  {steps[len(picked)]}" + ("" if finding is None else f"  /{finding}"))
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
def config_add(cfg, keyboard=None, through=None):
    """`config · add a model`: a harness, then a model its catalog offers, then an effort that
    model takes, each picked from a list with the matrix's keys; the name it was added under,
    or None.

    With `through`, a harness that runs any provider it can log in to (config.provider_hosts),
    `config · add a provider` instead, whose first list is every model it runs now, then every
    provider it lists with no login (_through_choices).  One of those picked is logged in on
    `keyboard`'s terminal, given back for it, then asked for again, its first model
    highlighted once it has a mode.  The
    model goes in with its provider's table where the config has none: the shipped one where
    the shipped default has it, else that mode, read off what the harness prices its models;
    the model takes that mode as its own where its provider's table says another.

    Only a provider the config has offers its harnesses, so the new model's provider is the
    one its harness was picked with.  ↑/↓, k/j and the wheel move, and Enter or a click picks
    a choice and opens the next step under it; Enter on an effort adds the model, named from
    its label (_short_name), and saves.  A model the config runs already is marked, and can be
    added at another effort, never at one it runs it at.  Esc steps back one level, and
    out from the harnesses.  Nothing is typed, so no harness, model or effort the catalog does
    not offer is ever written.  The new model is offered as orchestrator and as worker at
    once, and holds no seat's role until it is marked there.
    """
    picked, ats, top, note = [], [0], 0, ""   # (value, texts) of each step chosen; its highlight
    finding = None                    # typed after `/`: the open list shows only what holds it
    steps = ADD_STEPS[1:] if through else ADD_STEPS
    title = (f"config · add a provider · {config.provider_hosts().get(through, through)}"
             if through else "config · add a model")
    screen = (title, lambda: add_body(picked, [], 0, steps)[0])
    listed = pending = None           # `through`'s providers, as (id, name, mode); one logged in
    while True:
        # what is picked as _add_choices takes it: `through`'s one pick is (harness, provider)
        # and a model at once
        values = [*picked[0][0]] if through and picked else [value for value, _ in picked]
        try:
            if through and listed is None:
                listed = waited(lambda: config.listed_providers(through), *screen,
                                doing=f"asking {config.provider_hosts().get(through, through)} "
                                      "which providers it has")
            choices = (_through_choices(cfg, through, listed, screen) if through and not picked
                       else _add_choices(cfg, values, screen))
        except config.Error as exc:
            choices, note, listed = [], f"config: {exc}", listed or []
        except Back:                  # Esc while a list was asked: back one list
            if not picked:
                return None
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
                    else f"the {values[0][0]} catalog names no model" if picked
                    else f"{through} lists no model or provider" if through
                    else "no provider the config has names a harness")
        adding = len(picked) == len(steps) - 1
        keys = ADD_KEYS["add" if adding else "choose"][0 if terminal.utf8() else 1] + "   esc back"
        at = min(ats[-1], max(0, len(choices) - 1))
        body, places = add_body(picked, choices, None if terminal.away() else at, steps,
                                finding)
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
            if top <= line < top + room})
        key = terminal.read_key()
        if key is None:
            continue                  # a resize: drawn again at the new size
        spot = terminal.under(key, spots)
        if key.name == "point":
            ats[-1] = at if spot.what is None else spot.what     # the highlight on its choice
            continue
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
                return None
            picked.pop()
            ats.pop()
            finding = None
        elif terminal.step(key):
            ats[-1] = min(max(at + terminal.step(key), 0), max(0, len(choices) - 1))
        elif act in ("enter", "space") and choices:
            ats[-1] = at
            if through and not picked and choices[at][0][1] is None:     # a provider to log in to
                row = next(row for row in listed if row[0] == choices[at][0][0][1])
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
            name, before = _short_name(cfg, model["label"]), copy.deepcopy(cfg)
            cfg["models"][name] = {"harness": harness, "model": model["id"], "effort": effort,
                                   "provider": provider}
            if through:
                row = next(row for row in listed if row[0] == provider)
                if provider not in cfg["providers"]:
                    tables = config.shipped().get("providers") or {}
                    cfg["providers"][provider] = (copy.deepcopy(tables[provider])
                                                  if provider in tables
                                                  else {"mode": row[2], "name": row[1]})
                # a table that came with another harness's login: Codex's plan pays for no
                # call OpenCode makes on an OpenAI key
                if row[2] != cfg["providers"][provider].get("mode", "subscription"):
                    cfg["models"][name]["mode"] = row[2]
            note = _saved(cfg, cfg, before)
            if not note:
                return name


def _by_label(names, label):
    """{label: name} for a list of providers: a label two of them share is followed by the
    name itself, so the one picked is always the one it says -- a provider of the owner's own
    called `claude` reads `Claude` as Anthropic's does."""
    labels = [label(name) for name in names]
    return {text if labels.count(text) == 1 else f"{text} ({name})": name
            for text, name in zip(labels, names)}


def _adapter_verbs(keyboard, harness, verbs, picked, account=None, provider=None):
    """Each of `verbs` of `harness`'s adapter (one with its words, `login again`), run as
    install.sh runs them, for `account`'s
    login when one is named and of `provider` when one is (config.provider_env), with the
    terminal given back for them and taken again after.  The
    first that fails ends them, and waits until what it said has been read: what to say about
    it under the matrix, or "".  No verbs is nothing to run, and the terminal stays."""
    if not verbs:
        return ""
    keyboard.give()
    failed = ""
    for verb in verbs:
        try:
            code = subprocess.run([str(config.adapter(harness)), *verb.split()],
                                  env={**config.child_env(), **config.account_env(account),
                                       **config.provider_env([provider] if provider else [])}
                                  ).returncode
        except (config.Error, OSError) as exc:
            print(f"{harness}: {exc}")
            code = 1
        if code:
            failed = f"{harness} {verb} did not finish; {picked} is not added"
            pause()
            break
    keyboard.take()
    return failed


def sign_in(cfg, keyboard, provider, account):
    """`provider`'s login for `account` (None: its only one) made afresh on the terminal, for
    one whose meter is amber: its harness's `login again` (`logins.harness`), and the menu back
    as soon as that ends, one that failed once what it said has been read.  One that finished
    is asked its end at once (`logins.renewed`), so the menu comes back with its meter grey."""
    from . import logins    # here, not at the top: logins names subscriptions through the menu
    harness = logins.harness(cfg, provider)
    if harness and not _adapter_verbs(keyboard, harness, ("login again",), provider, account,
                                      provider):
        logins.renewed(cfg, provider, account or config.DEFAULT_ACCOUNT)


def _add_subscription(cfg, keyboard, provider, listed, picked, verbs=("login",)):
    """Another subscription of `provider`, `picked` being the name it will get: its harness's
    login, run on the terminal under the account name last in `listed`, then `listed` as the
    provider's `accounts` -- the ones it had, `default` when it had none, and that name.  A
    kept login is given no `verbs`, since it is logged in already.  Its harness is its models'
    or, with none left, the shipped default's (config.provider_harnesses).  A login that fails
    adds nothing.  What to say under the matrix, or ""."""
    harnesses = config.provider_harnesses(cfg, provider)
    if not harnesses:
        return f"config: no model names a harness for [providers.{provider}]"
    failed = _adapter_verbs(keyboard, harnesses[0], verbs, picked, listed[-1], provider)
    if failed:
        return failed
    before = copy.deepcopy(cfg)
    cfg["providers"][provider]["accounts"] = listed
    return _saved(cfg, cfg, before)


@terminal.clicks_its_own
def config_add_provider(cfg, keyboard):
    """`+ add a provider` on `c`: a provider the shipped default has and the config has not,
    picked from a list, then put in the way it ships, so nothing is typed; or, listed after
    them as the name it will get (`ChatGPT II`, config.account_label), another subscription
    of a provider the config has, which is only logged in and listed (_add_subscription), where
    its harness keeps more than one login (config.one_login); or,
    last, `Use <who>`, a login `− remove` left on disk (config.kept_logins) whose adapter's
    `auth` still passes, put back with no login: into its provider's `accounts` under its old
    name, or, its provider gone too, with that provider as it ships, a subscription as its one
    login.  <who> is who that `auth` says it is `; logged in as`, else the name the login's
    usage row had; one several share is followed by that row, then by a number (` (2)`), so
    every such login is listed, each as itself.  A harness that runs any provider it can log in
    to (config.provider_hosts) is listed by its name after the shipped providers, standing in
    for those shipped on it: picked, it is installed where its program is missing, then
    `config_add` through it picks the provider, logs it in, and adds the model.

    A new provider's harness, the shipped default's for it, is installed when its program is
    nowhere to be found, then logged in: each its adapter's own verb, run as install.sh runs
    them, with the terminal given back for it and taken again after.  Then its shipped
    [providers.*] table goes in, with the first model its harness's catalog lists (_offered),
    under the name and at the effort the shipped default gives that provider's first model --
    `spark`, and the effort or the nearest one it takes -- so a `usage_model` in that table
    names it.  It holds no seat's role until it is marked there.  Where a model of that name
    is here already nothing is installed or added, since the table would name that model
    instead.  A verb that fails adds nothing, and waits until what it said has been read.  Esc
    goes back with nothing done.  What to say under the matrix, or "".
    """
    shipped, hosts = config.shipped(), config.provider_hosts()
    gone = [name for name in shipped.get("providers") or {} if name not in cfg["providers"]]
    labels = _by_label([name for name in gone
                        if hosts.keys().isdisjoint(config.provider_harnesses(shipped, name))],
                       lambda name: COMPANIES.get(name, NAMES.get(name, name.title())))
    through = {label: harness for harness, label in hosts.items() if label not in labels}
    more = {}
    for text, name in _by_label(list(cfg["providers"]),
                                lambda name: provider_name(cfg, name)).items():
        harnesses = config.provider_harnesses(cfg, name)
        if harnesses and config.one_login(harnesses[0]):
            continue                  # _add_subscription's login would be refused
        # A random name, never the next free one: a removed subscription's login stays on
        # disk, and a `login` under its old name would find it and call the new one logged in.
        after = [*(config.accounts(cfg, name) or [config.DEFAULT_ACCOUNT]), os.urandom(3).hex()]
        more[config.account_label({"providers": {name: {"accounts": after}}}, name, after[-1],
                                  text)] = (name, after)
    offers = []
    for name, account, label in config.kept_logins():
        listed = config.accounts(cfg, name) or [config.DEFAULT_ACCOUNT]
        if name in gone:      # listed or not: one on a host harness is listed through it
            after = None if account == config.DEFAULT_ACCOUNT else [account]
        elif name in cfg["providers"] and account not in listed:
            after = [*listed, account]
        else:
            continue       # it is in ak again, or has no provider to go back to
        # its provider's harness even with none of its models left, as _add_subscription finds it
        harnesses = config.provider_harnesses(cfg, name)
        passed, said = (worker.auth_ok(harnesses[0], account=account, provider=name)
                        if harnesses else (0, ""))
        if passed:
            who = re.search(r"; logged in as (.+)$", said)
            offers.append((who[1] if who else "", label, (name, after)))
    kept = {}
    for who, label, offer in offers:
        text = (f"Use {who} ({label})" if who and [other for other, _, _ in offers].count(who) > 1
                else f"Use {who or label}")
        shown, number = text, 1
        while shown in kept:
            number += 1
            shown = f"{text} ({number})"
        kept[shown] = offer
    keys = ADD_KEYS["add"][0 if terminal.utf8() else 1] + "   esc back"

    def around():     # the screen the list is drawn on, drawn again on a resize
        terminal.frame("config · add a provider",
                       [""] * (len(labels) + len(through) + len(more) + len(kept)), keys)
        return 3
    picked = terminal.choose([*labels, *through, *more, *kept], around=around)
    if picked is None:
        return ""
    if picked in through:
        harness = through[picked]
        failed = _adapter_verbs(keyboard, harness, () if config.harness_present(harness)
                                else ("install",), picked)
        if not failed:
            config_add(cfg, keyboard, through=harness)
        return failed
    name, after = {**more, **kept}.get(picked) or (labels[picked], None)
    if name in cfg["providers"]:
        return _add_subscription(cfg, keyboard, name, after, picked,
                                 () if picked in kept else ("login",))
    try:
        harness, first = config.provider_harness(shipped, name)
    except config.Error as exc:
        return f"config: {exc}"
    if first in cfg["models"]:
        return f"{picked} adds its model as {first}, and a model has that name; nothing added"
    verbs = () if config.harness_present(harness) else ("install",)
    failed = _adapter_verbs(keyboard, harness, verbs if picked in kept else (*verbs, "login"),
                            picked, provider=name)
    if failed:
        return failed
    try:
        models = _offered(harness, "config · add a provider", provider=name)
    except Back:
        return ""                     # Esc while its catalog was asked: nothing added
    if not models:
        return f"the {harness} catalog names no model; {picked} is not added"
    model, before = models[0], copy.deepcopy(cfg)
    cfg["providers"][name] = shipped["providers"][name]
    if after:                   # a subscription it had, back as its one login
        cfg["providers"][name]["accounts"] = after
    cfg["models"][first] = {
        "harness": harness, "model": model["id"],
        "effort": _nearest(shipped["models"][first].get("effort"), model["efforts"]),
        "provider": name}
    return _saved(cfg, cfg, before)


@terminal.clicks_its_own
def config_remove_provider(cfg, picked):
    """`− remove` on a meter or a row of `Subscriptions` (subscription_acts): `picked`, its
    subscription as (provider, account, label), `Remove <provider> and its models?` for its usual
    login or its only one, `Remove <subscription>?` for another, asked under its name, `Keep`
    picked and Esc keeping it.  config.remove_provider takes a provider's table, its models and their places
    in [defaults], and with its table goes its meter; a subscription leaves only the
    provider's `accounts`.  The last provider is refused without asking.  Either way no login
    file goes: the login taken out is recorded (config.keep_login) for `+ add a provider` to
    offer back.  What to say under the screen, or "".
    """
    (name, account, label), title = picked, f"config · {picked[2]}"
    # a provider listing no subscription has its usual login, so its last one takes it along
    usual = account in (None, config.DEFAULT_ACCOUNT) or config.accounts(cfg, name) == [account]
    if usual and len(cfg["providers"]) < 2:
        return "the config needs one provider"
    shown = provider_name(cfg, name) if usual else label
    question, means = REMOVE_PROVIDER_ASK if usual else REMOVE_SUBSCRIPTION_ASK

    def asked(card):
        terminal.frame(title, card, "esc back")
        return 3
    if not terminal.confirm(question.format(shown), means, "Remove", asked):
        return ""
    before = copy.deepcopy(cfg)
    try:
        # first, so nothing leaves ak unrecorded; a removal that fails below leaves its login
        # in ak, and a login in ak is never offered
        config.keep_login(name, account or config.DEFAULT_ACCOUNT, label)
        if usual:
            config.remove_provider(cfg, name)
        else:
            cfg["providers"][name]["accounts"].remove(account)
    except (config.Error, OSError) as exc:
        return str(exc)
    return _saved(cfg, cfg, before)


@terminal.clicks_its_own
def config_spend_reset(cfg, picked):
    """`↻ spend a reset` on a meter or a subscription's row: one usage-limit reset spent,
    by hand, on `picked`, its subscription as (provider, account, label).  usage.replenish
    spends it where it still holds one and reads the meters back into the cache, so its meter
    shows the week that came back; Esc while it is spent lets it finish.  What to say under the
    matrix: its name and what its cell on the `ak` screen says now (`usage_cells`), `ChatGPT II
    · 100% left`."""
    title = f"config · {picked[2]}"
    name, account, label = picked
    try:
        spent, _ = waited(lambda: usage.replenish(cfg, name, account=account), title,
                          doing=f"spending a reset of {label}")
    except Back:
        return ""
    if not spent:
        return f"{label}: no reset was spent"
    said = next(said for provider, shown, _, said in usage_cells(cfg)
                if (provider, shown) == (name, label))
    return f"{label} · {said}"


def subscription_acts(cfg, number):
    """What subscription `number`, from 1 in usage_rows' order, offers, as (text, act) each, an
    act what to say under the screen or "": `spend a reset` while it holds one
    (config_spend_reset), and `remove` (config_remove_provider)."""
    name, label, prov, account = usage_rows(cfg)[number - 1]
    # its label as usage_cells has it, which config_spend_reset reads its week back by
    picked = (name, account, label)
    return [(text[0 if terminal.utf8() else 1], act) for text, act, offers in (
        (SUBSCRIPTION_ACTS[0], lambda: config_spend_reset(cfg, picked), in_hand(prov)),
        (SUBSCRIPTION_ACTS[1], lambda: config_remove_provider(cfg, picked), True)) if offers]


@terminal.clicks_its_own
def config_usage(cfg, number):
    """Enter or a click on subscription `number`'s meter, from 1, over the page of `c`: what it
    offers (subscription_acts), picked from a list under its name where it offers more than one,
    the highlight on `− remove`, so only a move or a click picks the spend.  What to say under
    the matrix, or ""."""
    acts = dict(subscription_acts(cfg, number))
    texts = list(acts)
    chosen = texts[0]
    if len(texts) > 1:
        keys = ADD_KEYS["choose"][0 if terminal.utf8() else 1]

        def listed():     # the screen the list is drawn on, drawn again on a resize
            terminal.frame(f"config · {usage_rows(cfg)[number - 1][1]}", [""] * len(texts),
                           keys + "   esc back")
            return 3
        chosen = terminal.choose(texts, around=listed, default=texts[-1])
    return "" if chosen is None else acts[chosen]()


def config_subscriptions(cfg, keyboard):
    """`Subscriptions` on `c`: a row for each subscription, saying when its login ends where it
    soon does (login_notes) and the resets it holds, Enter opening what it offers under it
    (subscription_acts)."""
    def acts(number):     # `− remove`, last, highlighted: only a move or a click picks the spend
        offered = subscription_acts(cfg, number)
        return [(text, act, at == len(offered)) for at, (text, act) in enumerate(offered, 1)]

    def page():
        subs = usage_rows(cfg)
        rows = [(label, " · ".join(filter(None, (ends, in_hand(prov)))),
                 (lambda number=number: acts(number), False))
                for number, ((_, label, prov, _), ends)
                in enumerate(zip(subs, login_notes(subs)), 1)]
        return rows, ""
    config_page("subscriptions", page)


def page_body(rows, at=None):
    """The lines of a page `c` opens -- `Discord`, `Weekly audit` -- and the row each is,
    {line: (row, [])}: of `rows`, (row, label, value) each, its label and then its value,
    lined up past the widest label as `c`'s own rows are, or with no label a choice of a list
    opened under the row above it, indented as `add a model`'s are.  A value is text, or
    parts, (text, kind) each, a space apart, wrapped at a word under itself as `c`'s own
    values are, never cut; `at` is the row lit."""
    room = terminal.layout_width()
    wide = max((terminal.cells(label) for _, label, _ in rows if label is not None), default=0)
    lines, places = [], {}
    for row, label, value in rows:
        lead = "    " if label is None else f"  {terminal.pad(label, wide)}  "
        left, wrapped, used = max(1, room - terminal.cells(lead)), [[]], 0
        for text, kind in [(value, None)] if isinstance(value, str) else value:
            for piece in terminal.wrap(text, left):
                if used and used + 1 + terminal.cells(piece) > left:
                    wrapped, used = [*wrapped, []], 0
                wrapped[-1].append(terminal.styled(piece, kind) if kind else piece)
                used += bool(used) + terminal.cells(piece)
        for number, parts in enumerate(wrapped):
            line = ((lead if number == 0 else " " * terminal.cells(lead)) + " ".join(parts)).rstrip()
            places[len(lines)] = (row, [])
            lines.append(terminal.highlight(line, number == 0) if row == at else line)
    return lines, places


@terminal.clicks_its_own
def config_page(name, page):
    """`config · <name>`, a page `c` opens: `page()` gives its rows -- (label, value, act) each
    -- and the note under them, asked again for every draw, drawn as page_body draws them and
    read with `c`'s keys until Esc.

    Enter or a click on a row calls its act.  One that is a list's, (choices, several), opens
    the list under the row, the highlight on the first choice marked: `choices()` gives (value,
    pick, marked) each, asked as it opens and again after each pick, so a reading that moves
    underneath never moves the highlight onto another choice, and Enter or a click on one calls
    its `pick()`, the list closing unless `several`; Esc closes it.  Any other act is called with
    `draw`, which draws the page with lines under the row and returns the screen row of the
    first, as terminal.field takes it.  What a call returns is said under the rows, over the
    note, until the next key."""
    here, top, said, opened, title = ("row", 0), 0, "", None, f"config · {name}"
    listed = []                       # the open list's choices, as last asked
    keys = ADD_KEYS["choose"][0 if terminal.utf8() else 1] + "   esc back"
    while True:
        rows, note = page()
        if not opened:                # a pick removed the last row: the highlight on the new last
            here = ("row", max(0, min(here[1], len(rows) - 1)))
        drawn = [(("row", number), label, value) for number, (label, value, _) in enumerate(rows)]
        if opened:
            drawn[opened[0] + 1:opened[0] + 1] = [(("row", opened[0], number), None, value)
                                                  for number, (value, _, _) in enumerate(listed)]
        # with a list open its choices are what the keys move through, else the rows
        ids = [row for row, label, _ in drawn if (label is None) == bool(opened)]
        body, places = page_body(drawn, None if terminal.away() else here)
        act, moved, _, top = matrix_key(title, body, places, ids, here, top,
                                        "\n".join(filter(None, (said, note))), keys)
        here = moved if moved in ids or act == "enter" else here    # the pointer on a row off-list
        if act is None:
            continue                  # a resize or the pointer: drawn again
        said = ""
        if act == "back":
            if not opened:
                return
            here, opened = ("row", opened[0]), None
        elif act not in ("enter", "space") or not rows:
            continue
        elif len(here) == 3:
            said = listed[here[2]][1]() or ""
            if opened[2]:
                listed = opened[1]()
            else:
                here, opened = here[:2], None
        elif isinstance(rows[here[1]][2], tuple):
            opened = (here[1], *rows[here[1]][2])
            listed = opened[1]()
            here = (*here, next((number for number, (_, _, marked) in enumerate(listed)
                                 if marked), 0))
        else:
            opened, at = None, here[1]

            def draw(lines):          # the page of matrix_key's height that holds the lines
                rows, note = page()
                body, places = page_body([(("row", number), label, value)
                                          for number, (label, value, _) in enumerate(rows)])
                # under the row's last line, a value that wrapped included
                end = 1 + max(line for line, (row, _) in places.items() if row == ("row", at))
                body[end:end], said = lines, note_lines(note)
                first, room = matrix_page(body, {end: ("lines", [])}, "lines", top, said, keys)
                terminal.frame(title, [*body[first:first + room], *said], keys)
                return 3 + end - first
            said = rows[at][2](draw) or ""


# What `Discord` and `Weekly audit` say under their rows.
DISCORD_NOTE = "A card reads only Needs you · <seat> or Done · <seat>, and mentions you."
AUDIT_NOTE = "Once a week ak opens a seat named audit with the week's largest loss."


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
    Opus 5.5, GPT-6-Astra · reviews GPT-6-Astra`; a setting the config cannot read is shown as
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


def audit_table(cfg):
    """`[audit]` as a change on `Weekly audit` keeps it: each key the tick reads on its own
    (config.audit), so the first change mends a table it cannot read; one that is not a table
    keeps nothing."""
    table = cfg.get("audit")
    kept = {}
    for key, value in table.items() if isinstance(table, dict) else ():
        try:
            config.audit({**cfg, "audit": {key: value}})
        except config.Error:
            continue
        kept[key] = value
    return kept


def audit_shown(cfg):
    """`Weekly audit`'s setting as its rows say it, and why the tick reads none, or "": what the
    tick reads (config.audit), else what it will once a change leaves out each key it cannot
    read (audit_table)."""
    try:
        return config.audit(cfg), ""
    except config.Error as exc:
        return config.audit({**cfg, "audit": audit_table(cfg)}), str(exc)


def audit_write(cfg, key, value):
    """`[audit]`'s `key` set to `value` beside the keys a change keeps (audit_table) and saved,
    `cfg` with it, once the tick reads it (config.audit); else nothing is written, and why is
    what it returns, else ""."""
    table = {**audit_table(cfg), key: value}
    try:
        config.audit({**cfg, "audit": table})
        config.save({**cfg, "audit": table})
    except (config.Error, OSError) as exc:
        return f"weekly audit: {exc}"
    cfg["audit"] = table
    return ""


def config_audit(cfg):
    """`Weekly audit`: whether it runs and the models its seat takes, a row each (config_page),
    each change written to `[audit]` in config.toml at once (audit_write).  Enter on `On`
    turns it the other way; on `Orchestrator` it opens every model under it, `●` the one it
    is, and Enter on one takes it; on `Builds` and `Reviews` every model `■` in that role or
    `□` not, Enter taking one in or out until Esc."""
    on, off, full, empty = ("●", "○", "■", "□") if terminal.utf8() else ("*", ".", "#", "-")

    def models(key):          # the list a role's row opens
        one = key == "orchestrator"

        def choices():
            held = audit_shown(cfg)[0][key]
            held = [held] if one else held
            return [([(on if one else full, "accent") if name in held
                      else (off if one else empty, "dim"), (config.model_name(cfg, name), None)],
                     lambda name=name: audit_write(cfg, key, name if one else [
                         other for other in held if other != name] if name in held
                         else [*held, name]),
                     name in held)
                    for name in config.offered(cfg)]
        return choices, not one

    def page():
        setting, why = audit_shown(cfg)
        return [("On", [(on, "accent"), ("on", None)] if setting["on"]
                 else [(off, "dim"), ("off", None)],
                 lambda draw: audit_write(cfg, "on", not setting["on"])),
                ("Orchestrator", config.model_name(cfg, setting["orchestrator"]),
                 models("orchestrator")),
                ("Builds", audit_names(cfg, setting["workers"]) or "nobody", models("workers")),
                ("Reviews", audit_names(cfg, setting["reviewers"]), models("reviewers"))], \
            "\n".join(filter(None, (why, AUDIT_NOTE)))
    config_page("weekly audit", page)


def show_config(dry_run=False, keyboard=None, session=None):
    """`c`: every model in one matrix of `session`'s roles -- the seat highlighted on the main
    screen, read from its own record -- and the efforts, under each subscription's meter, then
    `+ add a model`, `+ add a provider`, `Subscriptions`, `Discord` and `Weekly audit`,
    agentkit's build under them, read with the menu's keyboard (config_matrix), so nothing is
    typed.
    On a heading, with no seats, or for a seat with no record, the marks are new seats'
    ([defaults]); a record that will not read has the efforts alone, saying so under the rows:
    the screen that changes the models still opens.

    Providers, models, efforts and the two Discord secrets live here, the way they live in
    ~/.agentkit/config.toml and ~/.agentkit/secrets, so nobody opens either file; a seat's
    models live in its record, the one place its row and its runs read them from too.  A dry
    run, and a menu with no keyboard to read -- a pipe -- draw it once and read nothing.
    Returns the config as the screen left it, for the menu to go on with; None when there was
    nothing to show.
    """
    try:
        cfg = config.load()
    except config.Error as exc:
        if keyboard is not None:
            keyboard.give()
        pause(f"config: {exc}")
        return None
    try:
        selected, note = (config.load_session(cfg, session, required=False)
                          if session else None), ""
    except config.Error as exc:
        selected, note = None, f"{session}'s roles are not shown: {exc}"
    if selected is None and not note:     # a seat with no record has no models to give
        session, selected = None, copy.deepcopy(cfg["defaults"])
    try:                      # what a seat's flip is refused on, and spent; Esc while it is read
        providers = waited(lambda: usage.collect(cfg), f"config · {session}",
                           keyboard=keyboard, doing=LEFT) if session and selected else {}
    except Back:
        return cfg
    # one git call a visit, not a draw; nothing about a harness and nothing over the network
    version = update.agentkit_version()
    if dry_run or keyboard is None or not keyboard.take():
        terminal.frame(config_title(session, selected),
                       [*config_meters(cfg)[0],
                        *config_body(cfg, selected=selected, providers=providers)[0],
                        *note_lines(f"Version {version or '?'}")],
                       "esc back")
        return cfg
    return config_matrix(cfg, keyboard, version, session, selected, providers, note)


def config_title(session, selected):
    """`c`'s title: whose marks it shows, a seat's or new seats', or none's."""
    return f"config · {session or 'new seats'}" if selected else "config"


def defaults_mark(cfg, selected, model, column):
    """Act on one of new seats' marks, `selected` being [defaults]: saved at once
    (config.remember_defaults) and into `cfg` and `selected`, no open seat changing.  What to
    say under the rows, or ""."""
    # a new seat's crew is read as it is made (orch.default_crew), so no meter refuses one now
    changed, note = orch.role_mark(cfg, selected, model, column, {})
    if note or changed == selected:
        return note
    note = config.remember_defaults(changed)
    if note:
        return f"config: {note}"
    cfg["defaults"] = copy.deepcopy(changed)
    selected.update(changed)
    return ""


def session_mark(cfg, name, selected, model, column, providers):
    """Act on one of a session's marks, saving it to the session's record at once.

    `column` is 0 for the orchestrator and 1 for executes and 2 for reviews, as
    `orch.role_mark` numbers them. The orchestrator moves the seat to that model at once,
    under the same name, asking nothing, and a harness that is not installed or not logged in, or a meter
    that is spent, is refused in one line with the seat as it was, and so is a record naming
    a model removed on this screen. Reviewers keep one model, executors may be empty, and a
    flip leaving no allowed pair is refused. A run launched afterwards reads the record as
    left here (marks_saved); one already going keeps the groups its receipt saved. A refusal
    or a save that fails leaves the record, and `selected`, alone. What to say under the
    rows, or "".
    """
    if column == 0:
        note = orch.switch_orchestrator(cfg, name, model, providers)
        if not note:
            selected["orchestrator"] = model
        return note
    changed, note = orch.role_mark(cfg, selected, model, column, providers)
    return note or marks_saved(name, selected, changed)


# A production project's feature switches are live data in the project, reached through the one
# command its AGENTS.md names under `features:`: `list`, and `set <id> you|everyone on|off`.
FEATURES_EVERY = 60     # how old a project's last `list` grows before the menu asks again
FEATURES_WAIT = 20      # the longest `list` or `set` is waited for
FEATURES_HEADS = ("you", "everyone")
FEATURES_KEYS = ("↑↓←→ move   ⏎ flip", "arrows move   enter flip")
_SWITCHES = {}          # checkout -> its last answer: rows, why there are none, when asked
_SWITCHES_LOCK = threading.Lock()


def switches_command(checkout):
    """The command a checkout's AGENTS.md names for its feature switches, or None."""
    return gitcall.declared(checkout, "features")


def features_run(checkout, *words):
    """The project's features command with `words` after it: (its JSON answer, "") or (None,
    the one line saying why).  Its stdin is nothing, so an ssh in it never reads the keys.

    It runs in a session of its own, and one past FEATURES_WAIT is killed with everything it
    started: the shell alone would leave its ssh going, and a `set` said to have failed could
    still flip the switch after it.
    """
    command = switches_command(checkout)
    if not command:
        return None, "AGENTS.md names no features command"
    try:
        with subprocess.Popen(f"{command} {shlex.join(map(str, words))}", shell=True,
                              cwd=checkout, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                              env=config.child_env(), start_new_session=True) as proc:
            try:
                out, err = proc.communicate(timeout=FEATURES_WAIT)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                return None, f"{words[0]}: no answer in {FEATURES_WAIT} s"
    except OSError as exc:
        return None, f"{words[0]}: {exc}"
    said = err.strip().splitlines()
    if proc.returncode:
        return None, said[-1] if said else f"{words[0]} exited {proc.returncode}"
    try:
        return json.loads(out), ""
    except ValueError:
        return None, f"{words[0]} answered no JSON"


def switches(checkout, every=FEATURES_EVERY):
    """The checkout's feature rows as its `list` last answered, or None before any; never waits.

    Once the last `list` was asked `every` seconds ago and none is going, it is asked again in
    a thread of its own, and the draw after its answer lands shows it (`Live.watch`).
    """
    with _SWITCHES_LOCK:
        entry = _SWITCHES.setdefault(str(checkout), {"rows": None, "error": "", "asked": None,
                                                     "going": False, "set": 0, "flips": {}})
        if not entry["going"] and (entry["asked"] is None
                                   or time.monotonic() - entry["asked"] >= every):
            entry["asked"], entry["going"] = time.monotonic(), True
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
            kind = ("reverse" if at == row["id"] and number == column else
                    "dim" if text in (off, fixed) else ("accent", "ok")[number])
            line += "  " + terminal.toggle(text, width, kind)
            if moves is not None:
                moves.append((len(lines), ("mark", row["id"], number), text, motion.toggled(
                    text, width, kind, at == row["id"], first + 2)))
            cells.append((first + 2, first + 1 + width, number))
            first += 2 + width
        places[len(lines)] = (("feature", row["id"]), cells)
        line = line.rstrip()
        lines.append(terminal.highlight(line) if at == row["id"] else line)
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
    of landing.  ↑/↓ move between features and ←/→ between `you` and `everyone`; Enter, space
    or a click flips a mark by calling the project's `set` at once, off the drawing thread, the
    rule gliding the same way, and draws the row it answers with, a mark it changed filling or
    emptying; a flip before that is let go.  What a `set` could not do is one dim line under the
    rows, the mark as it was and shaking, until the next key; a `list` that failed is one too,
    for as long as the rows drawn are older than it.  A dry run draws it once.
    """
    here, column, top, note, clock = None, 0, 0, "", motion.Clock(page=True)
    keys = FEATURES_KEYS[0 if terminal.utf8() else 1] + "   esc back"

    flip = flipped = None   # the `set` asked from here, till its answer is drawn, and its mark

    def fetched():      # when the `set` or else the list now going was asked, till it lands
        entry = _SWITCHES[str(checkout)]
        return (flip.began if flip and flip.is_alive() else entry["asked"] if entry["going"]
                else None)

    while True:
        if flip and not flip.is_alive():
            note, flip = flip.answer(), None
            if note:
                clock.touch(flipped)  # refused: the mark shakes
        features = switches(checkout, TICK)
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
                                             "\n".join(said), keys, STIR, fetched=fetched,
                                             clock=clock, moves=moves)
        column = column if clicked is None else clicked
        if act is None:
            continue                  # a resize, the pointer, or a look at whether it landed
        note = ""
        if act == "back":
            return
        if act in ("left", "right"):
            column = 1 if act == "right" else 0
        elif act in ("enter", "space") and here and flip is None:
            flipped = ("mark", here[1], column)
            flip = Fetch(lambda feature=here[1], column=column:
                         features_flip(checkout, feature, column))


def past_offered(found):
    """Whether the past screen has a row, so `p` is a key and the key line offers it: a seat
    the owner stopped is among `found` (`closed`, `orch.ghost`)."""
    return any(session.get("closed") for session in found)


def took(seconds):
    """How long a past session took, never in minutes: `under an hour`, `1 day and 3 hours`."""
    if seconds < 3600:
        return "under an hour"
    hours = round(seconds / 3600)
    return " and ".join(f"{n} {unit}{'s' * (n != 1)}"
                        for n, unit in zip(divmod(hours, 24), ("day", "hour")) if n)


def past_said(cfg, session):
    """(sentence, stats) a past session's row opens with: its plan's first done line, then its
    tasks, how long it took, from its start to its last done, else to its stop, and the models it
    used (past_models)."""
    name, start, stop = session["name"], session.get("created"), session["closed"]
    seat = notify.conversation_of(name)
    last = seat and seat[3] and (history.last_done(f"{seat[0].name}:{seat[3]}") or [None])[0]
    from . import watch   # here, not at the top: the menu draws without the tick
    done, total = watch.plan_progress(name)
    tasks = (f"{done} of {total} tasks" if done < total else
             f"{total} task{'s' * (total != 1)}") if total else ""
    end = last if last and start and start < last <= stop else stop
    return plan.first_done(name) or "", " · ".join(part for part in (
        tasks, start and "took " + took(end - start), ", ".join(past_models(cfg, session))) if part)


def past_models(cfg, session):
    """The models a past session used, each once by its full name (`config.model_name`): its
    orchestrator, then every other its runs between its start and its stop ran on --
    orchestrating, building, a builder its turn went from (`executor_history`), a reviewer that
    finished a review, by any name the config runs its model under, else its own id."""
    runs, reviews = history.seat_runs(plan.names(session["name"]), session.get("created") or 0,
                                      session["closed"]) or ((), ())
    used = {model for _run_id, *models in runs for model in models}
    used |= {entry.get(key) for run_id, *_ in runs for entry in (record.read_state(
        config.RUNS / str(run_id)) or {}).get("executor_history") or () for key in ("from", "to")}
    used |= {next(iter(_runs(cfg, harness, model)), model) for harness, model in reviews}
    orchestrator = (selection_of(cfg, session["name"]) or {}).get("orchestrator")
    first = orchestrator and config.model_name(cfg, orchestrator)
    names = {config.model_name(cfg, model) for model in used if model} - {first}
    return [first] * bool(first) + sorted(names, key=str.casefold)


def past_body(past, at=None, models=None, room=None, said=None):
    """The past screen's lines -- the main screen's rows, one a stopped seat under its project's
    heading in the order their numbers go: its number, name, orchestrator (`models`, in full),
    how long ago it was stopped in the state's column and, where its harness starts it fresh
    and the row has room, that -- and where each is, {line: (("row", name), [])}.  Every row, a
    blank line between projects, where `room` lines hold them or no `room` is given; else the
    page of `room` lines `at` is on (every page of a row taller than one), each row under its
    project's heading (`project_pages`).  `at` is the highlighted seat's name, lit while the
    pointer is on the rows (`terminal.away`); a row in `said` opens it under itself."""
    infos = [{"number": str(number), "name": session["name"],
              "orchestrator": (models or {}).get(session["name"]) or "-",
              "count": f"stopped {orch.age(session['closed'])} ago",
              "restart": session.get("restart") or "", "repo": session.get("repo")}
             for number, session in past]
    width = terminal.width()
    widths = v5o_column_widths(infos, width)
    room_under = max(1, widths["room"] - (2 + widths["num"] + 2))
    opened = {name: terminal.wrap(sentence, room_under) + [
        terminal.styled(line, "dim") for line in stats_lines(stats, room_under)]
        for name, (sentence, stats) in (said or {}).items()}

    def drawn(info):
        block = v5o_seat_blocks([info], width, widths, details=opened)[0]
        if info["restart"] and terminal.cells(info["restart"]) <= widths["free"]:
            block[0] += "  " + terminal.styled(info["restart"], "dim")
        lit = at == info["name"] and not terminal.away()
        return [terminal.highlight(line.rstrip(), mark=number == 0) if lit else line.rstrip()
                for number, line in enumerate(block)]
    projects = [((v5o_header(project, width), None),
                 [[(line, info["name"]) for line in drawn(info)] for info in project["seats"]])
                for project in by_project(infos, orch.listed(), "no project").values()]
    flat = [line for number, (heading, rows) in enumerate(projects)
            for line in [("", None)] * bool(number) + [heading] + sum(rows, [])]
    pages = [flat] if room is None or len(flat) <= room else project_pages(projects, room)
    # a row taller than a page is one body under its heading, which project_pages puts on a
    # page of its own before it; ↑/↓ turn the body's pages before leaving it (matrix_key)
    held = [number for number, page in enumerate(pages) if any(name == at for _, name in page)]
    if held and held[0] and not any(name for _, name in pages[held[0] - 1]):
        held.insert(0, held[0] - 1)
    page = [line for number in held for line in pages[number]] or pages[0]
    return ([line for line, _ in page],
            {number: (("row", name), []) for number, (_, name) in enumerate(page) if name})



def stats_lines(stats, room):
    """A past session's stats on lines of `room` cells, broken only after a `·` or a `,`: a
    model's name stays on one line, unless it is too long for one by itself."""
    lines = []
    for part in re.findall(r".+?(?:, | · |$)", stats):
        if lines and terminal.cells(lines[-1] + part.rstrip()) <= room:
            lines[-1] += part
        else:
            lines.append(part)
    return [cut for line in lines for cut in terminal.wrap(line, room)]


@terminal.clicks_its_own
def show_past(cfg, found, dry_run=False, keyboard=None):
    """`past sessions`, `p`: the seats you stopped, the main screen's rows under their projects
    (`past_body`), for the one you want back, the page the highlight is on where they fill more
    than one.  ↑/↓, k/j and the wheel move the highlight, and the row it is on opens what that
    session did under itself (`past_said`) while the pointer is on the rows; Enter or a
    click reopens one where it stopped (`open_session`, what its number does on the main screen),
    True said, and the menu is back; `x`, or a click on `x remove`, removes the highlighted one at once
    (`close_seat`, the second stop), the rest staying up, and only brings the highlight back
    while the pointer has it out (`terminal.unseen`); Esc goes back.  From a pipe a number reopens, `x` asks which to
    remove by the numbers on the screen, and an empty line goes back.  A dry run draws it once.
    """
    here, clock, said, top = None, motion.Clock(page=True), {}, 0
    while True:
        past = [(number, session) for number, session in enumerate(found, 1)
                if session.get("closed")]
        if not past:
            return
        names = [session["name"] for _, session in past]
        here = here if here in names else names[0]
        models = {name: model and config.model_name(cfg, model) for name in names
                  for model in [(selection_of(cfg, name) or {}).get("orchestrator")]}
        if not terminal.taken():
            keys = "x remove   esc back"
            terminal.frame("past sessions", past_body(past, models=models)[0], keys)
            if dry_run:
                return
            line = read("> ", "")
            if not line or terminal.is_esc(line):
                return
            if line.isdecimal() and line.isascii() and 1 <= int(line) <= len(found):
                if found[int(line) - 1].get("closed"):
                    open_session(cfg, found[int(line) - 1], dry_run)
                    return True
                pause(f"no past session {line}", keys)
            elif line.lower() == "x":
                choice = terminal.ask("Remove", names[0], names, read=read,
                                      numbers=[number for number, _ in past])
                if choice:
                    remove_seat(choice, dry_run)
                    found = [session for session in found if session["name"] != choice]
            else:
                pause(f"not a key: {line!r}", keys)
            continue
        keys = PAST_KEYS[0 if terminal.utf8() else 1]
        room = matrix_page([], {}, None, 0, [], keys)[1]      # the lines a page holds
        if here not in said:      # read once a row, as the pointer comes and goes on it
            said[here] = past_said(cfg, next(session for _, session in past
                                             if session["name"] == here))
        body, places = past_body(past, here, models, room,
                                 {} if terminal.away() else {here: said[here]})
        act, row, _column, top = matrix_key("past sessions", body, places,
                                            [("row", name) for name in names], ("row", here),
                                            top, "", keys, clock=clock)
        top = top if row[1] == here else 0      # another row is another body, from its start
        here = row[1]
        if act is None:
            continue              # a resize or the pointer: drawn again
        if act == "back":
            return
        if act == "enter":
            keyboard.give()       # the seat has the terminal while he is in it
            open_session(cfg, next(session for _, session in past if session["name"] == here),
                         dry_run)
            return True
        if act == "x" and not terminal.unseen():     # unseen, it only brings the highlight back
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


def move_keys():
    """The key line's first two items while the menu has the keyboard; ASCII without UTF-8."""
    return "↑↓ move   ⏎ open" if terminal.utf8() else "j/k move   enter open"


def page_mark(keys, page, pages, width, arrows=True, needs=(False, False)):
    """The key line with where the owner is in front of the keys, `←  2 / 3  →`, wrapped with
    them as one more item: each arrow a key a click turns the page with, amber where a seat that
    needs the owner is that way (`needs`, back and on), the place between them none.  From a
    pipe, which turns pages with `j` and `k`, the place alone, `2 / 3`."""
    arrow, ahead = ("←", "→") if terminal.utf8() else ("<", ">")
    tone = ["amber" if need else "dim" for need in needs]
    return terminal.key_line(keys, width, first=(
        f"{terminal.styled(arrow, tone[0])}  {page + 1} / {pages}  "
        f"{terminal.styled(ahead, tone[1])}" if arrows else f"{page + 1} / {pages}"))


def turned(turns, page, cursor, step):
    """Where ← (`step` -1) or → (1) takes the highlight from `page`: to the first thing it can
    rest on (`turns`, each page's) of the nearest page that way holding one, passing a page
    with none -- only a heading, or the rest of a tall seat; else it stays on `cursor`."""
    ahead = range(page + step, len(turns) if step > 0 else -1, step)
    return next((turns[n] for n in ahead if turns[n] is not None), cursor)


def pressed(key, drawn, found):
    """What one `terminal.Key` asks of the main screen, in the line menu's own words.

    Enter is the highlighted seat's number, and a click on any line of a seat is that seat's;
    on a project's heading either is that project's checkout, whose switches it opens.
    A click on the key line is the key of the item under it, `⏎ open` being Enter; Esc, a click
    on `esc leave` and a keyboard that is gone are ESC, which leaves; a character is itself;
    anything else is "", which asks for nothing.  `drawn` is the layout on the screen when the
    key was read, so a click lands where he saw, and `found` the seats now, so a seat is
    opened by the number it has now.
    """
    numbers = {session["name"]: str(number) for number, session in enumerate(found, 1)}

    def opens(name):
        return name if isinstance(name, Path) else numbers.get(name, "")
    if key.name == "click":
        spot = terminal.under(key, drawn["spots"])
        if spot.what is not None:
            return opens(spot.what)
        item = spot.cell or ""
        if item not in ("⏎", "enter", "esc"):
            # the page's place between the arrows is no seat's number
            return item if len(item) == 1 and not item.isdigit() else ""
        key = terminal.Key({"⏎": "enter"}.get(item, item))
    if key.name == "enter":
        return opens(drawn["cursor"])
    if key.name in ("esc", "eof"):
        return terminal.ESC
    return key.char if key.name == "char" else ""


def loop(cfg, client=False, dry_run=False, overlay=False, tidy=None):
    """The menu until Esc, or from a pipe until an empty line or the end of input.

    `overlay` is the menu as a tmux popup over a running seat, the same menu with its highlight
    starting on that seat.  A number, `n` and a past session reopened hand this client to a
    session, and the popup has to come down for it to be seen, so those return, as `x` on the
    popup's own seat does before the stop ends.  Read a line at a time, `j` and `k` turn the pages of a list
    longer than the screen, and a number is answered from whichever page is up.

    The main screen is live: the read waits at most TICK seconds, and a wait that ends with
    nothing typed draws again, so the clock, the seat rows, the counts on the top line and the
    usage stay true in front of whoever left it open -- and it ends within STIR of any seat's
    record or the usage cache changing, so a row never says for longer what its bar no longer
    does.  Nothing is read between a key and its frame: the seats, their runs and their rows
    are read once before the first draw, then in `Live`'s thread -- on the clock, after a key
    that did more than move the highlight, and within STIR of a record changing -- and every
    draw is what the last read left, drawn again when the next one lands.  While the owner is in
    a seat it opened, or on the screen that opens one, nothing is read but by the pass a seat
    listed was still owed (`Live.away`), and back, the menu is drawn at once as it was and read
    again behind it, what changed meanwhile coming in as news (`Live.back`).  The clock and those
    keys have every seat looked at again as well, in a thread of its own (`Live.look`), so no
    seat's capture holds up a read or a draw: the first draw is the records as they stand, and
    a look landing has them read and drawn again.  The first draw's meters are the cache's, and
    the probe that follows it runs in a thread and asks for one more draw when it lands.  So
    does `tidy`, `main`'s maintenance (`Live.tidy`): what it says is a notice as it lands.
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
    on a row moves the highlight there, and on a key-line item lights it (`draw`).  A digit
    waits half a second for a second one, a resize or not, and a key read while it waits is
    kept for after, with the screen it was read on.  The highlight is the seat's name, so it
    stays on its seat whatever comes or goes above it.  A key that does nothing here is let
    go without a word, `i` among them, and every key that does something gives the terminal back
    before it does it -- but `c`, `n` and `x`'s question, which are read with the keys on
    the screen the menu has: `x` on a done seat closes it at once and on any other asks `Keep`
    or `Stop` under its row, Enter or a click answering and Esc keeping it; `p` opens the past
    screen (`show_past`) on the same keys, and is a key only while the key line offers it
    (`past_offered`).  Esc, and a click
    on `esc leave`, leaves at once, whatever a thread is doing (`Live.close`); `q` is no key.

    A test driving this mocks `wait_key` beside `read`: the real wait selects on stdin, and a
    stdin that never delivers EOF redraws forever instead of finishing.  It leaves `Live`'s
    probe unstarted: its thread calls `usage.collect` after the test's mock is gone.
    """
    keys = KEYS
    own = config.current_session() if overlay else None     # the seat the popup is over
    cursor = os.environ.pop("AK_MENU_CURSOR", "") or own
    if cursor and cursor.startswith("/"):
        cursor = Path(cursor)
    page, ahead, look, updating, updated = 0, None, False, None, False
    pointing = False                      # the highlight is where the owner points (`draw`)
    updates = []                         # this loop's inbox, independent of the usage/read worker
    start_update = not (dry_run or overlay)
    last = [[], None]                     # what the last read left: the seats and their groups
    clock = motion.Clock(fade=overlay)    # what moves between draws: the dots, news, and
                                          # the popup's first draw coming up
    with closing(Live(cfg)) as live, closing(terminal.Keyboard()) as keyboard:
        if keyboard.take():
            terminal.sense()              # true colour and the background, once, before a draw
        live.watch(last)                  # read once, now: the first draw has nothing else
        back = False                      # back from a seat, or the screen that opens one
        newborn = None                    # the seat `n` is typing the name of (`born`)
        while True:
            if back:
                live.back()               # drawn as the last read left it, read behind it
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
                keyboard.give()           # a notice waits for its Enter, like any sub-screen
                show_notices(messages)
                clock.forget()            # and the menu it comes back to replays nothing
                pointing = False
            # new code under an open menu, the tick's above all, draws it from here on, once
            # the menu's own update, which stamps the install too, has said how it went
            if updated or (updated is False and newborn is None and update.outdated()):
                keyboard.give()
                live.close()
                sys.stdout.flush()
                os.execve(sys.executable, [sys.executable, *sys.argv],
                          {**os.environ, "AK_MENU_CURSOR": str(cursor or "")})
            found, groups = last          # after any notice: what changed under it is drawn as is
            past = past_offered(found)
            actions = ("n", "x", "c", "p") if past else ("n", "x", "c")
            drawn = {} if keyboard.take() else None
            listed = (keys if drawn is None else BORN_KEYS if newborn
                      else f"{move_keys()}   {keys}")
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
            asking = live.asking()        # once: the probe may land between two asks
            if asking is not None and updating is None and drawn and drawn["rule"]:
                motion.fetching(clock, asking)            # the rule glides while it is asked
            if ahead is not None:
                (key, shown), ahead = ahead, None
            else:
                key, shown = moving(clock, live.reader, timeout=0 if updates and newborn is None
                                    else TICK), drawn
            if key is None:
                # the wait ended on the clock, which looks again, or on news already written down
                look = not live.drain()
                continue
            look = True
            if newborn is not None and isinstance(key, terminal.Key):
                act, look = born_key(newborn, key, shown), False
                if act == "models":
                    back = True           # the picker's screen, drawn where the menu was
                    live.away()
                    act = born_models(newborn)
                if act == "back":
                    newborn = None
                elif act == "start" and not born_refusal(newborn):
                    made, newborn, back = newborn, None, True
                    keyboard.give()       # the seat has the terminal once it is made
                    live.away()
                    try:
                        name = start_born(made, dry_run)
                    except config.Error as exc:
                        name = None
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
                    if order:
                        at = order.index(cursor) + terminal.step(key)
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
                clock.forget()            # whatever the key opens, the menu back replays nothing
                spot = (terminal.under(key, shown["spots"]) if key.name == "click"
                        else terminal.Spot())
                cell = spot.cell
                if isinstance(cell, tuple) and cell[0] == "usage" and cell[1] in shown["logins"]:
                    pointing = False          # and opens no line
                    sign_in(cfg, keyboard, *shown["logins"][cell[1]])   # an amber meter
                    continue
                if spot.what is not None and cell in (WAIT, GO_ON):
                    pointing = False          # answered: its lines close
                    if cell == GO_ON and shown.get("go_on", {}).get(spot.what):
                        go_on_now(cfg, spot.what, shown["go_on"][spot.what], dry_run)
                    continue
                typed, key = key, pressed(key, shown, found)
                if isinstance(key, Path):
                    cursor = key              # the heading, highlighted when he is back
                    show_features(key, dry_run)    # read with the keys, on the screen the menu has
                    continue
                key = key.lower()
                if (typed.name == "char" and len(key) == 1 and "1" <= key <= "9"
                        and int(key) * 10 <= len(found)):
                    # 1 then 2 within half a second is seat 12, whatever asks for a draw between
                    more, until = None, time.monotonic() + 0.5
                    while more is None and time.monotonic() < until:
                        more = moving(clock, timeout=until - time.monotonic())
                        if more is not None and more.name == "point":    # cuts no wait short
                            spot, more = terminal.under(more, drawn["spots"]), None
                            cursor, pointing = spot.what or cursor, spot.what is not None
                        if more is None and time.monotonic() < until:
                            # a resize or the pointer: drawn anew, so the dots breathe on where
                            # they now are
                            page, pages = draw(cfg, found, listed, page, cursor, drawn,
                                               look=False, groups=groups, clock=clock,
                                               updating=updating, pointing=pointing)
                            pointing = drawn["pointing"]
                    if isinstance(more, terminal.Key) and "0" <= more.char[:1] <= "9":
                        key += more.char
                    elif more is not None:
                        ahead = (more, drawn)     # read early: kept, with the screen it was read on
                if key.isdecimal() and key.isascii() and 1 <= int(key) <= len(found):
                    cursor = found[int(key) - 1]["name"]   # and highlighted when he is back
                elif not terminal.is_esc(key) and key not in actions:
                    continue
            if not key or terminal.is_esc(key):
                return 0          # Esc leaves the menu; from a pipe an empty line or its end
            if terminal.is_sequence(key):
                continue          # an arrow key is neither Esc nor a key: draw again, silently
            key = key.lower()
            if key in ("x", "c") and terminal.unseen():
                continue          # it acts on the highlighted seat: brought back, to be seen first
            seat = cursor
            if key == "x" and isinstance(seat, Path):
                continue          # a heading is no seat to stop
            pointing = False      # the key opens something: the menu back opens no line
            if key == "x" and drawn is not None and seat in drawn["words"]:
                # the seat it acts on: a done one closes at once, any other is asked under its row
                if drawn["words"][seat] != "done":
                    cursor = seat

                    # its runs are counted off the draw, so the card is up at once whatever
                    # the disk; one counted within a frame is simply had, a later one drawn in
                    runs, counted = Fetch(lambda: len(transitions.seat_runs(seat))), [False]
                    runs.join(motion.FRAME)

                    def means():
                        counted[0] = not runs.is_alive()
                        return stop_means(runs.got.get("answer"))

                    def around(card):     # the menu around the card, drawn again on a resize
                        draw(cfg, found, "esc back", page, cursor, drawn, ask=(seat, card),
                             look=False, groups=groups, clock=clock)
                        return drawn["ask"]
                    if not terminal.confirm(
                            STOP_ASK.format(seat), means, "Stop", around, wait=lambda: moving(
                                clock, going=None if counted[0] else runs.is_alive)):
                        continue
                live.stop(seat, dry_run)      # its row gone at once, the stop behind it
                if seat == own:
                    return 0                  # its own seat: the popup over it goes first
                continue
            if key == "n" and drawn is not None and cfg:
                try:
                    newborn = born(found)     # typed where it will be
                except Back:
                    pass
                except config.Error as exc:
                    pause(f"new session: {exc}")
                continue
            if key not in ("c", "n", "p", "r"):
                keyboard.give()           # whatever the key opens has the terminal as it was
            if key.isdigit() or key in ("n", "p"):
                back = True               # each can hand the owner a seat, where nothing is read
                live.away()
            if key.isdigit():
                if 1 <= int(key) <= len(found):
                    open_session(cfg, found[int(key) - 1], dry_run)
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
            elif key == "x":
                seat = stop_session(found, dry_run)
                if seat:
                    live.stop(seat, dry_run)
                    if seat == own:
                        return 0
            elif key == "c":
                # read with the keys, too; the looks and probes go on with what it saved
                cfg = live.cfg = show_config(dry_run, keyboard,
                                             seat if isinstance(seat, str) else None) or cfg
            elif key == "p" and past:
                if show_past(cfg, found, dry_run, keyboard) and overlay:   # read with the keys
                    return 0              # a seat reopened: the popup's client is on it
            elif key in ("j", "k") and pages > 1:
                page = (page + (1 if key == "j" else -1)) % pages
            elif key:
                pause(f"not a key: {key!r}", keys)


# --- on a client ------------------------------------------------------------


def client(alias, dry_run):
    cmd = ["ssh", "-t", alias, "ak", "--client"]
    if dry_run:
        print(f"would run {shlex.join(cmd)}")
        return 0
    try:
        return subprocess.run(cmd).returncode
    except OSError as exc:
        raise config.Error(f"cannot run ssh: {exc}")


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
                                cwd=config.REPO, env=config.child_env(), stdin=subprocess.DEVNULL,
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
    """The menu.  `--overlay` is the popup inside a seat, and never leaves this machine.

    A popup is opened over tmux sessions that are here, so it neither hops to the server the
    way a client's menu does nor runs the maintenance that a menu opening a seat runs: reaping
    runs and retiring seats over a session the user is sitting in is not what `Ctrl-b m` was
    pressed for. A client's update starts detached before ssh; the server's starts behind the
    first frame (update_first). Neither an overlay nor a dry run starts one.
    """
    if command_help.show("attach", argv):
        return 0
    flags = {"--client": False, "--overlay": False, "--dry-run": False}
    for arg in argv:
        if arg not in flags:
            raise config.Error(f"{USAGE}  (got {arg!r})")
        flags[arg] = True
    if flags["--overlay"]:
        terminal.inset()                  # inside the border, what the popup asks to be left
    if not flags["--dry-run"]:
        from . import macbridge
        macbridge.start_background()
    alias = config.server_alias()
    if alias and not (flags["--client"] or flags["--overlay"]):
        if not flags["--dry-run"]:
            update_first()
        return client(alias, flags["--dry-run"])
    from . import watch
    messages = []
    watch.resume_after_boot(config.load(), dry_run=flags["--dry-run"], log=messages.append)
    show_notices(messages)
    # what `ak orch` does on the way into a seat, gc and the runs nobody was told about, run
    # behind the menu's first frame
    tidy = None if flags["--dry-run"] or flags["--overlay"] else orch.maintenance
    code = loop(config.load(), flags["--client"], flags["--dry-run"], flags["--overlay"], tidy)
    if flags["--overlay"]:
        # The popup comes down when this process ends, and Python's own teardown of all the menu
        # read took most of a second.  Nothing is cut short: a record is only ever replaced
        # whole, and the menu's threads are daemons, which no exit waits for.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
    return code
