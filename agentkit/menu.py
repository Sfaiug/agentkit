"""`ak`: the menu.  Numbers and single letters, and nothing else: on a terminal each one acts
the moment it is pressed, and from a pipe it is a line.

    agentkit                                                              14:02
    ────────────────────────────────────────────────────────────────────────

      usage left
      Claude   ███░░░░░░░░░   21% left · resets Fri 14:00 · Fable 47%

      your projects · 1 needs you

    atoll
    › 1  atoll-speed-check   fable   ! needs you   Merge the MOV helper before or after?
      2  fix-api             fable   ● working     tasks ██░░░ 2/5
      3  web-portal          fable   ✓ done        hero swapped and published

      ↑↓ move   ⏎ open   n new   x stop   c config   esc leave

`n` asks for a name, then shows the orchestrator and both roles with the last created session's
chosen already.
Enter leaves naming to the orchestrator once it knows the work. The name is the row, the
status bar and the title of every message it sends until `r` renames it.

A session is **working**, **needs you** or **done**, and nothing else exists: it works until
it is done or it is blocked on him.  `watch.session_state` decides which, once, from the
facts -- an expired login, its own runs, a turn in flight, a seat
nobody is in any more, what it last said with `ak notify` -- and every screen here reads that
one answer: the row, the top line, `ak orch list`, `ak orch why`, the
seat's own status bar and its window title.  `ak orch why <seat>` says what decided it.

A row is number, name, orchestrator, state, and one last column: for `needs you` the reason
from the state function, for `working` the tasks bar (`tasks ██░░░ 2/5` from
`~/.agentkit/state/plan-<session>.md`, under any name a rename led from, else from its
unfinished jobs), else empty, for `done` the first line of the done summary. Never two
state words on one row, and never `N running`.

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
window (`5h spent until 14:00` once it reads 100% used), then `? <reason>` when the last
probe errored though the meter it read still stands, and `as of HH:MM` beside it when
that reading is older than half an hour, with the weekday when it is not from today.
A probe the endpoint would not answer says nothing at all: its reading stands as it was,
and past half an hour its age says the rest.
The bar's filled cells are the company's own colour (`COLOURS`, or the provider's `colour`
key) until little is left: amber from 20% left, red from 5% (`fill`); the rows run red
through violet by the hue of that colour, the near-greys last.  `—` is drawn
only when there is no shared week to draw -- no reading at all, or nothing but one model's
private cap -- and the words after it say why.  Everything else `ak usage` knows -- week
elapsed, the resets in hand, headroom, budget, outlook -- stays in `ak usage`.

The main screen is live.  It draws at once from the cached meters, then probes every provider
in the background and draws again when the answer lands, and again every ten seconds after
that, so the clock, the seat rows, the counts and the usage stay true while it is open.  A
reading younger than `usage.PROBE_EVERY` is fresh, so the probe asks an adapter at most once a
minute -- the cadence is the host's and not this screen's -- and never blocks a keypress or a
draw; Muse's adapter keeps its own ten-minute cache, because its probe is a billed request.
Those ten seconds hold whatever stdin is, a script's half-written line included, and a key typed
during a draw is read by the next wait.  At rest one thing moves: on a terminal of 256 colours or
more each working seat's `●` breathes, all in one phase, on `motion`'s clock (`moving`); and
news seen while the menu is up moves once on it -- a `!` pulses, a `✓` settles, a bar glides --
then is still.  The sub-screens are not live: they are read once, like any other question --
but a project's feature switches, which draw again within a second of their `list` landing.

Five keys: the numbers, `n`, `x`, `c` (the highlighted seat's models, every model's effort,
providers, discord, version), and Esc, which leaves, as it goes back from every
screen and question under it; `q` is no key.  Nothing needs a manual: while the pointer rests
on a row, a state word, a heading, a usage row or a key-line item, the key line says what it
is in one sentence (terminal.TIPS), and the keys come back when it leaves; a usage row under
it sends one light across its bar and marks the share that would be left had it been spent as
fast as time passes.  A question typed inside the menu is typed on its
keys (`terminal.field`), so Esc cancels it at once.  From a pipe an empty line or the end of
input leaves, or goes back.
On a terminal one seat row is highlighted as well: ↑/↓, k/j and the wheel move it, Enter or a
click opens a seat, and a click on the key line does what its key does (`loop`,
`terminal.Keyboard`).  `x` is
the highlighted seat's: a done one is closed at once, and any other is asked about under its row,
`Keep` or `Stop` -- so the key line says `x close` while a done seat is highlighted.  `c` holds
its orchestrator, executors and reviewers: the orchestrator moves the seat at once, the
roles flip with the same keys and save at once.
`ak run status` and `ak browser` stay as commands for
orchestrators; the menu no longer offers them. A gone session reads `session closed: press N
to reopen`; an ended run is its orchestrator's business, so no row ever says `press r`.

The screen is budgeted by height as well as width: a list of seats longer than the
screen is drawn a page at a time -- on a terminal the page the highlight is on, from a pipe the
one `j` and `k` turn to -- and a row keeps the number it has in the whole list on whichever page
it is drawn, so what a number opens never depends on the page that is up.

`ak attach --overlay` is the same menu inside a seat, where `ak orch` binds it to `Ctrl-b m` as
a tmux popup: a number switches this client to that session and `n` starts one and switches to
it, both of which close the popup, `r` renames this session, `x` stops this session -- or,
done, closes it at once -- and Esc closes the popup.  The
popup offers those four keys and the
numbers; `c` lives on the menu outside.

On the server the menu is this process.  On a client -- a machine where install.sh recorded the
server's ssh alias in ~/.agentkit/state/server -- `ak` runs the same menu over `ssh -t <alias>
ak --client`.  `ak attach` is the same menu under the name the phone
key uses.
"""

import colorsys
import copy
import json
import os
import re
import select
import shlex
import signal
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

from . import command_help, config, history, motion, notify, orch, terminal, update, usage, worker
from . import record
from .harness import load as harness_plugin

KEYS = "n new   x stop   c config   esc leave"
OVERLAY_KEYS = "n start a session   r rename this session   x stop this session   esc leave"
STOP_ASK = "Stop {} and everything it runs?"   # what `x` asks under a seat that is not done
PAGE_KEYS = "j more   k previous"   # added to the key line when the list runs to more pages
LEAST = 3                # rows a page keeps; the usage block gives way before it holds fewer
# The whole vocabulary, worst first: a rollup of seats says the one that wants him.
# `watch.session_state` is what decides which of the three a seat is.
STATE_ORDER = ("needs you", "working", "done")
# Each company's own colour, for its name on the `c` screen and its usage bar and row's place: a
# provider's `colour` key in config.toml wins, and a provider named in neither is the accent.
COLOURS = {"anthropic": "#D97757", "openai": "#FFFFFF", "meta": "#3E9EFB", "xai": "#736CD3",
           "google": "#203B9B", "mimo": "#FB8046"}
# Each company's own name, on its usage row and over its models on `c` and `n`; any other
# provider is its own name, capitalised.
NAMES = {"anthropic": "Claude", "openai": "ChatGPT", "meta": "Muse", "xai": "Grok",
         "google": "Gemini", "mimo": "MiMo"}
TICK = 10.0              # the longest the main screen waits for a key before drawing itself again
STIR = 1.0               # ... and how often it looks for a seat's word or the meters having moved
ESTIMATE_EVERY = 60      # how long a repo's estimate is kept before its history is asked again
# What the `—` says, from the error the last probe left; the first match wins.  No pattern here
# guesses at a login: `token`, `401` and `login` turn up in lines a logged-in seat produces too,
# and the one party that can say is the harness's `auth` verb, which the probe asks and records.
UNREAD = ((re.compile(r"already reset"), "window reset"),
          (re.compile(r"without a name"), "bad reading"),
          (re.compile(r"returned no meters"), "no reading yet"))
USAGE = ("usage: ak [--client] [--overlay] [--dry-run]   "
         "(the menu; `ak attach` is the same)")


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
        self.seen = None                 # the records the last read was read from, as they stood
        self.looker = None               # the pass looking at every seat, while one is going
        self.asked, self.looking = threading.Event(), False   # a read asked for, and a look
        self.last = None                 # where each read leaves the seats and their groups
        self.said = []                   # what maintenance said that no notice has shown yet
        self.tidied = threading.Event()  # a notice can land before maintenance's effects do

    def close(self):
        """Give the pipe back, and wait on no thread: Esc leaves at once.

        Whatever a thread is in the middle of -- a read, a look, maintenance -- is safe to leave
        there: every state file is written whole, the `ak watch` tick runs the same reconcile and
        sweep, and the thread is a daemon.  The lock is the whole point: a descriptor closed
        while a thread is writing could already be somebody else's file, and a byte in the wrong
        file is worse than a draw nobody asked for.
        """
        self.done.set()
        self.asked.set()                 # the watcher out of its wait, to see it is done
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

    def look(self, found):
        """Look at every seat again, off the read, and wait for none of it.

        The looks are `v5o_groups`' own -- each seat captured, decided, and written to its record
        and its bar -- in a thread of their own, so a seat whose capture hangs holds up no read
        and no draw: the read is the records as they stand, and a look landing has them read
        again (`ask`) for its words to be drawn.  One pass at a time; one still going is not
        doubled, and a menu that has left starts none.
        """
        if not self.done.is_set() and (self.looker is None or not self.looker.is_alive()):
            self.looker = threading.Thread(target=self._look, args=(found,), daemon=True)
            self.looker.start()

    def _look(self, found):
        try:
            v5o_groups(self.cfg, found)
        except (config.Error, OSError, ValueError, TypeError, KeyError):
            pass    # a seat that cannot be looked at keeps what its record says
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
        nothing more, and one back from another screen shows the list at once.  With `look`
        every seat is looked at as well, behind it (`look`).
        """
        found = orch.listing()
        records = run_records()       # one pass over run.json a read, filing and drawing
        orch.file_projectless(found, [state for _, state in records])
        if look:
            self.look(found)
        self.last[:] = found, v5o_groups(self.cfg, found, records, look=False)

    def ask(self, look=False):
        """Have everything read again, and with `look` every seat looked at, off the draw."""
        self.looking = self.looking or look
        self.asked.set()

    def watch(self, last):
        """Read into `last` once, now, then again in a thread within STIR of any record
        changing, or when asked (`ask`): the seats and their groups, for each draw to draw.

        Whatever decides a seat -- its own hook, the tick, `ak orch`, another menu -- writes the
        word to that seat's record and to its bar in one go, so a screen that reads again when a
        record changes, as recorded, never shows a row its bar contradicts for longer than this.
        The records are noted before every read, so one written while it reads is still news.
        Looking is a `stat` per file -- its inode as well as its mtime, since every write
        replaces the file -- and nothing here captures a pane.  A read on news looks at no seat
        and writes nothing, so no menu's read ever wakes another, or itself; each one landing
        asks for one draw.
        """
        self.last, self.seen = last, self.recorded()
        self.read(look=True)
        self.watcher = threading.Thread(target=self._watch, daemon=True)
        self.watcher.start()

    def recorded(self):
        """usage.json and every seat record: each one's name, inode and mtime; and each
        project's feature switches as its `list` last answered, so their landing is news too."""
        found = []
        for path in [config.STATE / "usage.json", *(path for _, path in config.seat_files("seat"))]:
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
            if self.done.is_set():
                return
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


def waited(work, title, body=list, keys="esc back", keyboard=None):
    """What `work()` answers, asked off the drawing thread while the screen it is asked on waits
    on it: `title` over the lines `body()` lays out at the terminal's width and `keys`, as
    terminal.frame draws it.

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
            spots = terminal.frame(title, lines, keys)
            clock = motion.fetching(motion.Clock(), fetch.began)
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
    recorded yet is decided on what there is, until a look records it.
    """
    from . import watch
    if look:
        return watch.announce_state(session, cfg=cfg, look=True, **facts)
    recorded = watch.seat_read(session["name"])
    if recorded.get("word"):
        return {"word": recorded["word"], "reason": recorded.get("reason"),
                "since": recorded.get("word_since")}
    return seat_state(cfg, session, **facts)


def status(session, cfg=None):
    """(what the row says about the seat, the time that became true or None)."""
    found = seat_row_state(cfg, session)
    return found["word"], found["since"]


def state(session):
    """The one word the row says about that seat."""
    return status(session)[0]


def row(cfg, number, session):
    """One seat's cells: number, name, worker, word, reason, age."""
    try:
        selection = config.load_session(cfg, session["name"], required=False)
    except config.Error:
        selection = None
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

    `counts` is the seat's entry from run.seat_tallies -- (running, needing him, merged) -- or
    None.  Endings that need him come before the merges, because they are what the number
    is for; the merges are the last seven days' only.
    """
    if counts is None:
        return "no runs yet"
    running, look, merged = counts
    return f"{running} running · " + (f"{look} needs you" if look else f"{merged} merged")


def bar_tally(counts, queued=(), estimate=None):
    """What a seat's status bar carries for its runs, in `tally`'s words.

    `tally` counts going runs as `<n> running` and endings that still want him as
    `needs you`; merges and empty seats it shows another way, so the bar
    shows them no way at all: a seat with nothing going and nothing to look at
    draws no tally, and a seat that launched nothing is not in the counts at
    all.  `counts` is the seat's entry from run.seat_tallies, or None; either
    way, nothing to show reads back as None, which is what unsets the option.
    """
    if counts is None:
        return None
    running, look, _merged = counts
    running -= len(queued)
    bits = []
    if running:
        bits.append(f"{running} running")
    if look:
        bits.append(f"{look} needs you")
    if queued:
        bits.append(f"{len(queued)} waiting")
    if estimate:
        bits.append(estimate)
    return " · ".join(bits) or None


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
    from . import run
    groups = {}

    def group(repo, fallback="no project"):
        name = orch.project_name(repo, fallback)
        return groups.setdefault(name, {"name": name, "rows": [], "runs": [], "words": []})

    # one pass over run.json for the rows' tallies
    records = run_records()
    tallies = run.seat_tallies(state for _, state in records)
    for number, session in enumerate(found, 1):
        item = row(cfg, number, session)
        counts = tallies.get(session["name"])
        item.append(tally(counts))
        if orch.on_own_server(session):
            # the seat's own bar carries the same words its row does, on every draw;
            # a legacy seat lives on the user's own server, where nothing is written
            queued = [state for _, state in records if state.get("state") == "queued"
                      and run.launched_session(state) == session["name"]]
            orch.set_runs(session["name"], bar_tally(
                counts, queued, seat_estimate(session["name"], session=session)))
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


_ESTIMATES = {}          # repo -> (when its history was asked, what it answered)
_ESTIMATES_LOCK = threading.Lock()


def seat_estimate(seat_name, session=None, job=None):
    """Return the remaining-plan estimate used by both the row and the tmux bar.

    In the unit it reads in at a glance: minutes under an hour, hours under two days, else
    days -- `~45m left`, `~5h left`, `~36d left`.  A repo's history is asked once every
    ESTIMATE_EVERY seconds at most, whoever is drawing: the query reads records per row.
    """
    if session is None:
        try:
            session = orch.find(seat_name) or {}
        except (config.Error, OSError, ValueError):
            session = {}
    job = job_for_seat(seat_name) if job is None else job
    if not job or len(job) != 3 or not isinstance(job[1], int) or job[1] <= 0:
        return None
    done, total = job[0] or 0, job[1]
    if done >= total or not session.get("repo"):
        return None
    with _ESTIMATES_LOCK:
        asked, seconds = _ESTIMATES.get(session["repo"], (None, None))
        if asked is None or time.monotonic() - asked >= ESTIMATE_EVERY:
            asked, seconds = time.monotonic(), history.estimate_seconds(session["repo"])
            _ESTIMATES[session["repo"]] = asked, seconds
    if seconds is None:
        return None
    minutes = max(0, round(seconds * (total - done) / 300) * 5)
    if minutes < 60:
        return f"~{minutes}m left"
    if minutes < 2 * 24 * 60:
        return f"~{round(minutes / 60)}h left"
    return f"~{round(minutes / (24 * 60))}d left"


def silent_for_run(run_dir, state, now=None):
    """`2h` when a running run has had no write for more than an hour, else None.

    A run in `running` whose directory under ~/.agentkit/runs/<id> has had no write
    for more than an hour is stuck in one step. The age is the newest file under the
    run directory, whatever the step. Under an hour nothing changes.
    """
    from . import run as _run
    if state.get("state") not in ("running", "queued"):
        return None
    if _run.own_pr_wait_note(state) and record.process_active(state):
        return None  # the seat's push, not another loop write, ends this wait
    at = time.time() if now is None else now
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
    (`run.exhausted_wait`), which is no ending: told or old, it stays unfinished
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

    `index` is a `run.supersession_index` over the same states: pass it when testing
    many runs so one draw scans the records once instead of once per run per seat.
    """
    from . import gc, run as _run
    if state.get("recovery_acknowledged_at"):
        return False
    if state.get("state") in ("error", "exhausted") and _run.going(state, now=now):
        return False  # the tick owns its retry or its resume; nothing here needs him
    if state.get("state") == "exhausted":
        # no ending: a hand-back or its age settles nothing, but a later merged
        # run does -- the work is done, elsewhere. Without the records that
        # replacement cannot be read, and the run stays his.
        if index is not None:
            if _run.is_superseded(state, None, index, merged_only=True):
                return False
        elif all_states is not None and _run.is_superseded(state, all_states,
                                                           merged_only=True):
            return False
        return True
    if state.get("handed_back") or state.get("handback_pending"):
        return False
    if state.get("merged"):
        return False
    if state.get("state") not in ("fail", "error", "blocked", "interrupted", "pass"):
        return False
    at = time.time() if now is None else now
    ended = (state.get("finished_at") or state.get("interrupted_at")
             or state.get("started_at"))
    # Only a date we can read ages an ending out; an undated record stays his.
    if isinstance(ended, (int, float)) and not isinstance(ended, bool) and at - ended > gc.GC_AGE:
        return False
    if index is not None:
        if _run.is_superseded(state, None, index):
            return False
    elif all_states is not None and _run.is_superseded(state, all_states):
        return False
    if state.get("state") == "pass":
        return bool(state.get("repo")) and not (state.get("no_merge") or state.get("review_pr")
                                                or state.get("review_posted"))
    return True


def v5o_seat_info(cfg, number, session, records, silent_map, jobs_cache, now, index=None,
                  run_numbers=None, look=True):
    """Number, name, orchestrator, state and one last column for one offered seat.

    The word is `watch.session_state`'s and no screen's own: `working`, `needs you` or
    `done`. The last column is the reason for `needs you` and `done`, and for `working`
    the tasks bar from `seat_progress` -- its plan, else its unfinished jobs -- else
    empty -- never two state words on one row. Every seat `orch.listing` offers gets
    a row: the ones tmux holds, and the ones only their record does -- a seat whose tmux
    instance is gone keeps its row and its number opens the conversation where it stopped.
    Seats with nothing to resume into never reach `found`. `jobs_cache` and `run_numbers`
    are kept for callers that still hand them down; `seat_progress` reads the jobs itself and
    gone seats name their own number now.
    """
    name = session["name"]
    found = seat_row_state(cfg, session, look=look, records=records, now=now, number=number,
                           run_numbers=run_numbers, index=index, silent=silent_map)
    try:
        selection = config.load_session(cfg, name, required=False)
    except config.Error:
        selection = None
    orchestrator = selection["orchestrator"] if selection else "-"
    done, total = seat_progress(name)
    bar = (done, total) if total > 0 else None
    estimate = seat_estimate(name, session=session, job=(done, total, ""))
    word = found["word"]
    reason = found["reason"] or ""
    sentence = "" if word == "working" else reason
    return {"number": str(number), "name": name, "session": session,
            "count": word, "orchestrator": orchestrator, "worker": orchestrator,
            "sentence": sentence, "bar": bar, "estimate": estimate,
            "needs": reason if word == "needs you" else "",
            "word": word, "since": found["since"], "repo": session.get("repo")}


def v5o_groups(cfg, found, records=None, now=None, look=True):
    """The projects and their seats, needing projects first, seats by state within.

    A project is a checkout under ~/code, or agentkit's own at ~/agentkit -- one of
    `orch.checkouts()` -- and a seat is filed under the one its repo *is* (`orch.checkout_of`):
    the one `ak orch project` filed it under, else the project most of its runs vote for, a
    queued run's included (`run.join_session_project`), whether it works in one checkout or
    across them from ~/code. Only a seat nobody filed and none of whose runs votes files under
    the fallback heading.
    A run makes no project and no row: no worktree, no throwaway repo under
    ~/.agentkit/tmp and no run id is ever a heading. A project with no offered seat
    is not listed, unless its AGENTS.md names its feature switches: that one is listed
    whether or not a seat sits there, carrying `switches`, the rows its `list` last answered
    ([] before any). Under a heading seats sort needs you, then working, then
    done, then by name; numbers stay global by name.

    `found` is what `orch.listing` offers -- live seats and gone ones with a
    conversation to resume into -- and every one of them keeps its row and its
    global number.
    """
    from . import run as _run
    at = time.time() if now is None else now
    records = run_records() if records is None else list(records)
    all_states = [state for _, state in records]
    index = _run.supersession_index(all_states)
    silent_map = {}
    for run_dir, state in records:
        age = silent_for_run(run_dir, state, now=at)
        if age:
            silent_map[run_dir.name] = age
    jobs_cache = {}
    infos = []
    for number, session in enumerate(found, 1):
        infos.append(v5o_seat_info(cfg, number, session, records, silent_map, jobs_cache,
                                   at, index, None, look))
    # Grouped by the checkout the seat's repo is, so a project can never be listed
    # twice and a run can never make one.
    groups = {}
    for info in infos:
        checkout = orch.checkout_of(info["repo"])
        project = groups.setdefault(str(checkout) if checkout else None,
                                    {"name": orch.project_name(checkout), "seats": [],
                                     "checkout": checkout})
        project["seats"].append(info)
    for checkout in orch.checkouts():
        if switches_command(checkout):
            groups.setdefault(str(checkout), {"name": orch.project_name(checkout), "seats": [],
                                              "checkout": checkout})["switches"] = (
                switches(checkout) or [])
    for project in groups.values():
        project["seats"].sort(key=lambda info: (STATE_ORDER.index(info["word"]), info["name"]))
        project["needing"] = sum(1 for info in project["seats"] if info["word"] == "needs you")
        project["has_needs"] = bool(project["needing"])
        project["word"] = rollup([info["word"] for info in project["seats"]])
    ordered = sorted(groups.values(),
                     key=lambda project: (not project["has_needs"], project["name"]))
    total_needing = sum(project["needing"] for project in ordered)
    # The top line counts the seats whose word is `needs you`, each once, and says so once.
    return ordered, infos, total_needing, silent_map


def v5o_header(project, term_width):
    """`<project>`, the checkout's basename in the accent style.

    How many need him is said once, on the top line, so no heading says `needs you`
    at all; needing projects sort first, which is what carries the eye down to one.
    A project naming its feature switches says how many are hidden -- off for everyone --
    as `ACME · 2 hidden features`, and leaves room for the highlight's mark in front of it.
    """
    room = terminal.layout_width(term_width)
    if "switches" not in project:
        return terminal.styled(terminal.cut(project["name"], room), "accent")
    hidden = sum(1 for row in project["switches"] if not row.get("everyone"))
    count = f" · {hidden} hidden feature{'' if hidden == 1 else 's'}" if hidden else ""
    return terminal.styled(terminal.cut(project["name"] + count, max(1, room - 2)), "accent")


def _styled_cell(plain_text, width, kind=None, right=False):
    """Cut, then style, then pad: pads land outside escapes, so lines rstrip clean."""
    cut_text = terminal.cut(plain_text, width)
    styled = terminal.styled(cut_text, kind) if kind else cut_text
    space = " " * max(0, width - terminal.cells(styled))
    return space + styled if right else styled + space


def last_column(word, reason, done, total, estimate=None, narrow=False):
    """The one last column of a seat's row, and of its status bar.

    For `needs you` and `done` the reason from the state function; for `working`
    `tasks ` plus the bar plus ` <done>/<total>` when `seat_progress` finds a plan or
    an unfinished job, else empty -- never `N running`. The bar shortens to 4 cells on a
    narrow screen, and carries the remaining-plan estimate where history knows one.
    The row and the bar read this one function, so the two can never disagree.
    Never two state words on one row.
    """
    if word != "working":
        return terminal.plain(reason or "")
    if total > 0:
        text = terminal.progress_bar(done, total, narrow=narrow)
        return f"tasks {text} · {estimate}" if estimate else f"tasks {text}"
    return ""


def _last_text(info, narrow=False):
    """The row's one last column: reason, tasks bar, or empty.

    For `needs you` and `done` the reason from the state function; for `working`
    `tasks ` plus the bar plus ` <done>/<total>` when `seat_progress` finds a plan or
    an unfinished job, else empty. The bar shortens to 4 cells on a
    narrow screen, and carries the remaining-plan estimate where history knows one.
    Never two state words on one row.
    """
    bar = info.get("bar")
    done, total = bar if bar and len(bar) == 2 else (0, 0)
    text = last_column(info.get("word"), info.get("sentence"), done, total,
                       info.get("estimate"), narrow)
    return text


def redress(session, answer, cfg=None, records=None):
    """Write that seat's status bar and window title from the row's own values; never raises.

    The one writer: the watch tick, every menu draw and a seat's own hook come through here --
    all call `watch.announce_state`, which calls this -- so the bar says what the row says, in the
    same words, from the same function: the state function's word and reason, the session's
    workers, and `last_column` over `seat_progress`'s fraction and its estimate. A change of
    word or progress lands on the next tick or draw, whichever comes first. A legacy seat
    lives on the user's own server, where nothing is written; a seat tmux has lost, and a
    draw under test, fail their `set-option` quietly. `records` is kept for callers that
    still hand it down; the bar counts no runs.
    """
    try:
        if not orch.on_own_server(session):
            return
        name = session["name"]
        if cfg is None:
            cfg = config.load()
        try:
            selection = config.load_session(cfg, name, required=False)
        except config.Error:
            selection = None
        done, total = seat_progress(name)
        estimate = seat_estimate(name, session=session, job=(done, total, ""))
        last = last_column(answer.get("word"), answer.get("reason"), done, total, estimate)
        left, right, title = orch.bar(name, selection["orchestrator"] if selection else "-",
                                      answer.get("word"), last,
                                      selection["workers"] if selection else ())
        socket = orch.socket_name()
        # the line's layout rides every write, so a seat dressed before it came has it too
        for option, value in (("status-left", left), ("status-right", right),
                              ("set-titles-string", title), ("status-format[0]", orch.BAR_FORMAT)):
            orch.tmux_out("set-option", "-t", name, option, value, socket=socket)
    except Exception:  # noqa: BLE001 - dressing a bar never breaks the draw or the tick beneath it
        pass


def v5o_column_widths(infos, term_width):
    """Fixed columns sized once per draw from every row on screen.

    Number, name, orchestrator, state and the last-column room come from all infos,
    so the table does not step sideways between projects. `widths` rides into
    `v5o_seat_blocks`; callers that draw one group alone pass nothing and get
    widths sized from those rows.
    """
    room = terminal.content_width(term_width)
    num_w = min(max([terminal.cells(info["number"]) for info in infos] + [1]), 4)
    name_w = min(max([terminal.cells(info["name"]) for info in infos] + [1]), 24)
    orch_w = min(max([terminal.cells(info.get("orchestrator") or info.get("worker") or "")
                      for info in infos] + [0]), 14)
    count_w = min(max([terminal.cells(terminal.state_text(info["count"]))
                       for info in infos] + [1]), 16)
    fixed = 2 + num_w + 2 + name_w + 2 + orch_w + 2 + count_w + 2
    # The phone keeps the same fixed name column, capped to what fits beside
    # the orchestrator and state it always reserves, so those start at one offset.
    name_narrow = max(1, min(name_w, room - 2 - num_w - 2 - orch_w - 2 - count_w - 2))
    return {"room": room, "narrow": term_width < 60, "num": num_w, "name": name_w,
            "orch": orch_w, "count": count_w, "worker": orch_w, "bar": 0,
            "name_narrow": name_narrow, "sent": max(10, room - fixed)}


def v5o_seat_blocks(infos, term_width, widths=None):
    """One block of lines per seat, in order; no rendered line keeps trailing space.

    Fixed columns with two-space gutters, from `widths` (one `v5o_column_widths`
    per draw): number, name, orchestrator, state, and one last column. Content is
    capped at 100 columns. A long last column wraps at word boundaries onto one
    indented line, ending in ` …` only when more was cut. On a narrow phone the
    last column goes on its own line and the bar shortens to 4 cells. Never cut
    inside a glyph or a colour sequence.
    """
    if widths is None:
        widths = v5o_column_widths(infos, term_width)
    room, narrow = widths["room"], widths["narrow"]
    num_w, name_w, count_w = widths["num"], widths["name"], widths["count"]
    orch_w = widths.get("orch", widths.get("worker", 0))
    if not infos:
        return []
    blocks = []
    if narrow:
        for info in infos:
            num = _styled_cell(info["number"], num_w, "dim", right=True)
            name_cell = terminal.pad(terminal.cut(info["name"], widths["name_narrow"]),
                                     widths["name_narrow"])
            orch_cell = _styled_cell(info.get("orchestrator") or info.get("worker") or "",
                                     orch_w, "dim")
            count_cell = _styled_cell(terminal.state_text(info["count"]), count_w,
                                      terminal.state_colour(info["count"]))
            head = "  " + num + "  " + name_cell + "  " + orch_cell + "  " + count_cell
            block = [head]
            tail = _last_text(info, narrow=True)
            if tail:
                second_room = max(1, room - 4)
                block.append("    " + terminal.cut(tail, second_room))
            blocks.append(block)
        return [[line.rstrip() for line in block] for block in blocks]
    # Wide: fixed columns, the last column gets the remaining width.
    sent_room = widths["sent"]
    for info in infos:
        block = []
        num = _styled_cell(info["number"], num_w, "dim", right=True)
        name_cell = terminal.pad(terminal.cut(info["name"], name_w), name_w)
        orch_cell = _styled_cell(info.get("orchestrator") or info.get("worker") or "",
                                 orch_w, "dim")
        count_cell = _styled_cell(terminal.state_text(info["count"]), count_w,
                                  terminal.state_colour(info["count"]))
        last = _last_text(info, narrow=False)
        if not last:
            line = "  " + num + "  " + name_cell + "  " + orch_cell + "  " + count_cell
            line = line.rstrip()
            if terminal.cells(terminal.plain(line)) > room:
                # Cap without cutting escapes: plain-cut only when no colour would break.
                # Cells here are plain-measured; escapes add no width.
                plain = terminal.plain(line)
                line = terminal.cut(plain, room)
            block.append(line)
            blocks.append(block)
            continue
        if terminal.cells(last) <= sent_room:
            line = ("  " + num + "  " + name_cell + "  " + orch_cell + "  " +
                    count_cell + "  " + last)
            block.append(line)
            blocks.append(block)
            continue
        wrapped = terminal.wrap(last, sent_room)
        first, rest = wrapped[0], " ".join(wrapped[1:])
        line = ("  " + num + "  " + name_cell + "  " + orch_cell + "  " +
                count_cell + "  " + first)
        block.append(line)
        cont_room = max(1, room - 4)
        cont = terminal.cut(rest, cont_room) if terminal.cells(rest) > cont_room else rest
        if cont:
            block.append("    " + cont)
        blocks.append(block)
    return [[line.rstrip() for line in block] for block in blocks]


def draw(cfg, found, keys=KEYS, page=0, cursor=None, drawn=None, own=None, ask=None, look=True,
         records=None, groups=None, clock=None, updating=None):
    """The menu at rest, and (page, pages) as drawn.

    The frame is the header (`agentkit` at the left, the clock at the right),
    one dim rule the width of the layout, then the usage block and the keys line
    exactly as they are today, and between them one line that answers the
    question once (`your projects · nothing needs you` / `· N need you`), then
    the projects and their seats -- the needing ones first -- and nothing else.
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
    word.  A seat's state word, any other project's heading and a usage row are cells that only
    explain (`terminal.Spot`): with the pointer on one of those, a seat or a key-line item, the
    key line says what it is (terminal.TIPS).  A usage row under it with a bar also has a
    hairline tick at the share of its week that would be left had it been spent as fast as time
    passes (`usage_tip`), standing through a glide, and one light crosses that bar as the
    pointer comes onto it (`motion.glinting`).

    `x` acts on the highlighted seat, or on `own`, the popup's own, and the key line says
    `x close` while that seat is done.  `ask` is the seat `x` is asking about and the card it
    asks on (`terminal.confirm`): the card is drawn under its row, the rows below moving down,
    and `drawn["ask"]` is the screen row of its first line.

    `look` is whether the seats are looked at for this draw or drawn as recorded, and
    `records` the run records it is drawn from, read here when they are not handed in;
    `groups`, `v5o_groups`' answer already in hand, is drawn as it is, and nothing is read.

    `clock`, the menu's `motion.Clock`, is handed each working seat's `●` to breathe while the
    menu has the keyboard, and the news since the draw before: a `!` that turned `needs you`
    pulses, a `✓` that turned `done` settles and a usage or tasks bar that moved glides.  Their
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
    if owned and words.get(own or cursor) == "done":
        keys = keys.replace("x stop", "x close", 1)
    asking, card = ask or (None, ())
    asked = list(card) if asking in words else []
    # Seat columns are sized once per draw from every row on screen, so the
    # sentence column starts at the same column under every project.
    widths = v5o_column_widths([seat for project in ordered
                                for seat in project["seats"]], width)
    meters_full = usage_lines(cfg, layout)
    # Height is budgeted the way width is: the usage block gives way first, then
    # compact mode drops the frame and the blank lines so
    # every number stays reachable. Sized from the rows on screen, leaving one
    # line for the prompt and one to spare, exactly as the tests check.
    key_text = keys
    # With the keyboard the highlight turns the pages, so `j` and `k` are not offered then.
    page_keys = "" if owned else "   " + PAGE_KEYS
    tips = {}
    if owned and not asked:
        for info in infos:
            name, word = info["name"], info["word"]
            tips[name, None] = terminal.TIPS["session"].format(name=name)
            tips[name, ("state", word)] = terminal.TIPS[word]
        for project in ordered:
            checkout = project["checkout"]
            if "switches" in project:
                tips[checkout, None] = terminal.TIPS["switches"].format(name=checkout.name)
            elif checkout:
                tips[None, ("project", project["name"])] = terminal.TIPS["project"].format(
                    name=project["name"])
        tips.update({(None, ("usage", number)): usage_tip(cfg, number)[0]
                     for number in range(1, len(usage_rows(cfg)) + 1)})
    # A question under a row is budgeted with the key line, so it never pushes a row off.
    k_single = terminal.key_height(key_text, tips, width) + len(asked)
    k_paged = terminal.key_height(key_text + page_keys, tips, width) + len(asked)

    def _flat(blocks):
        flat = []
        for block in blocks:
            flat.extend(block)
            flat.append(("", None))  # one blank line between projects
        if flat:
            flat.pop()
        return flat

    # Every line travels with the name of the seat it draws, or None, so the highlight and a
    # click find a seat on whichever page it lands.
    seat_blocks = [[[(line, info["name"]) for line in block] for info, block in
                    zip(project["seats"], v5o_seat_blocks(project["seats"], width, widths))]
                   for project in ordered]

    def heading(project):
        # one naming no switches is no row, yet it explains the project it heads
        return v5o_header(project, width), (
            project["checkout"] if "switches" in project
            else ("project", project["name"]) if project["checkout"] else None)
    blocks = [[heading(project)] + [pair for block in own for pair in block]
              for project, own in zip(ordered, seat_blocks)]
    flat = _flat(blocks)

    def _room(meters, compact, paged):
        keys = k_paged if paged else k_single
        if compact:
            return max(1, height - 2 - (1 + keys))
        chrome = 2 + (len(meters) + 1 if meters else 0) + 2 + 1 + 1 + keys
        return max(1, height - 2 - chrome)

    def _seat_pages(room):
        # Collapsed overview first: every project header, no numbers. Then seat
        # blocks packed whole under their project header, so a seat's lines never
        # split across pages. An oversized block falls back
        # to bare line splits so tiny screens still fit. The overview is a page the
        # highlight is never on, so with the keyboard there is none.
        headers = [heading(project) for project in ordered]
        pages = [] if owned else (
            [headers[i:i + room] for i in range(0, len(headers), room)] or [[]])
        cur, cur_header = [], None
        for project, own in zip(ordered, seat_blocks):
            header = heading(project)
            for block in own or [[]]:     # a heading with no seat under it still has its place
                need = block if cur and cur_header == header else [header] + block
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

    meters, compact, pages = meters_full, False, [flat]
    # The usage block gives way first, then compact. The block stays only while
    # everything fits one page with it: once the menu pages, the rows keep the
    # room instead.
    # A page still holds a few rows' worth below that, else compact takes over.
    least = 3 * (2 if width < 60 else 1)
    decided = False
    for trial_meters in (meters_full, []):
        room = _room(trial_meters, False, False)
        if len(flat) <= room:
            meters, compact, pages = trial_meters, False, [flat]
            decided = True
            break
    if not decided:
        room = _room([], False, True)
        if room >= least:
            meters, compact, pages = [], False, _seat_pages(room)
            decided = True
    if not decided:
        meters, compact, pages = [], True, _seat_pages(_room([], True, True))
    key_lines = terminal.key_line(key_text + (page_keys if len(pages) > 1 else ""), width)
    if owned and cursor is not None:
        page = next((number for number, lines in enumerate(pages)
                     if any(name == cursor for _, name in lines)), page)
    # The layout is min(terminal width, 120); beyond that the margin grows, never the text.
    out = []
    # what may move: (key, what it shows -- a word, or a bar's value and its blocks -- its first
    # cell, highlighted, a bar's colour); a bar's news is its value, which rounding can hide
    moves = []
    bars = {}       # each usage row's number -> its screen row, blocks, first column and colour
    rows = {}       # ... and each usage row's screen row, a bar on it or not
    explains = {}   # each seat row's state word, a cell that explains it
    if not compact:
        out += [terminal.header_line("updating" if updating is not None else "",
                                     time.strftime("%H:%M"), width),
                terminal.rule_line(width, updating or 0)]
    if meters:
        if not compact:
            out.append("")
        for number, line in enumerate(meters):
            out.append(line)
            if number:            # its first line is the heading
                rows[number] = len(out)
            text = terminal.ANSI.sub("", line)
            bar, left = re.search("[█░]+", text), re.search(r"(\d+)% left", text)
            if bar and left:
                # its filled cells' colour, its company's as `usage_lines` drew it; one spent
                # has none drawn, and is red whoever's it is
                shade = next((kind for kind in (fill(int(left.group(1)), colour(cfg, name))
                                                for name in cfg["providers"])
                              if terminal.styled("█", kind).removesuffix("\033[0m") in line),
                             fill(int(left.group(1)), "accent"))
                moves.append((("usage", text[:bar.start()].strip()),
                              (int(left.group(1)) / 100, bar.group()),
                              (len(out), terminal.cells(text[:bar.start()]) + 1), False, shade))
                bars[number] = (len(out), bar.group(), terminal.cells(text[:bar.start()]) + 1,
                                shade)
    body = [("  no sessions; n starts one", None)]
    if ordered:
        # One blank line between projects; seat rows two under their project.
        # Rows keep their global numbers across pages, and the heading says which
        # page is up without moving any number.
        pages_count = len(pages)
        page = min(max(page, 0), pages_count - 1)
        # The question is answered once, here and nowhere else on the screen.
        if total_needing <= 0:
            base = "your projects · nothing needs you"
        elif total_needing == 1:
            base = "your projects · 1 needs you"
        else:
            base = f"your projects · {total_needing} need you"
        # The page is what m turns: it is never the part that is cut.
        suffix = "" if pages_count <= 1 else f" {page + 1}/{pages_count}"
        heading = terminal.cut(base, max(1, layout - terminal.cells(suffix))) + suffix
        if compact:
            # Compact: the heading, the rows, the keys and the prompt are all that is left.
            out.append(heading)
        else:
            # Section titles are plain words in the accent style, flush left, one blank above.
            out += ["", terminal.styled(heading, "accent"), ""]
        body = pages[page] or body
    else:
        out.append("")
    top, above = len(out), None
    at = max((number for number, (_, name) in enumerate(body, 1) if name == asking), default=0)
    if asked and at:
        body = body[:at] + [(line, None) for line in asked] + body[at:]
    else:
        at = 0
    for line, name in body:
        # while a question is up its first answer carries the mark, and the seat only its light;
        # a heading is flush left, so its mark goes in front of it
        lit = owned and name is not None and name == cursor and not terminal.away()
        out.append(terminal.highlight(("  " if isinstance(name, Path) else "") + line,
                                      mark=name != above and not at) if lit else line)
        above = name
        text, word = terminal.ANSI.sub("", line), words.get(name)
        if word and terminal.state_text(word) in text:
            first = terminal.cells(text[:text.index(terminal.state_text(word))]) + 1
            moves.append((("word", name), word, (len(out), first), lit, None))
            explains[len(out)] = [(first, first + terminal.cells(terminal.state_text(word)) - 1,
                                   ("state", word))]
        tasks = re.search(r"tasks ([█░]+|[#-]+) (\d+)/(\d+)", text)
        if tasks and word == "working":
            moves.append((("tasks", name), (int(tasks.group(2)) / int(tasks.group(3)),
                                            tasks.group(1)),
                          (len(out), terminal.cells(text[:tasks.start(1)]) + 1), lit, None))
    if not compact:
        out.append("")
    keys_top = len(out)
    out += key_lines
    if not owned:
        print("\n".join(out))
        return page, (len(pages) if ordered else 1)
    spots = {top + number: ((None, [(1, layout, name)]) if isinstance(name, tuple)
                            else (name, explains.get(top + number, [])))
             for number, (_, name) in enumerate(body, 1) if name}
    spots.update({row: (None, [(1, layout, ("usage", number))]) for number, row in rows.items()})
    spots.update(terminal.key_spots(key_lines, keys_top + 1))
    # a question under a row has the keys and the rows, and nothing is explained while it asks
    spot, glint = terminal.Spot() if asked else terminal.pointer_spot(spots), []
    kind, ticked = spot.cell[0] if isinstance(spot.cell, tuple) else None, None
    if kind == "usage":
        _, pace = usage_tip(cfg, spot.cell[1])
    if kind == "usage" and spot.cell[1] in bars:
        row, blocks, _, shade = bars[spot.cell[1]]
        glint = [terminal.styled(block, shade if block == "█" else "dim") for block in blocks]
        if pace is not None:
            tick = min(len(blocks) - 1, round(pace * len(blocks)))
            # a hairline across its cell, cut out of a filled one's colour so the fill reads on
            mark = "│" if terminal.utf8() else "|"
            glint[tick] = (terminal.styled(mark, shade).replace("\033[", "\033[7;", 1)
                           if blocks[tick] == "█" else mark)
            ticked = row, tick
            filled = blocks.count("█")
            out[row - 1] = out[row - 1].replace(
                terminal.styled("█" * filled, shade)
                + terminal.styled("░" * (len(blocks) - filled), "dim"), "".join(glint), 1)
    for number, (row, _, first, shade) in bars.items():
        # whether the pointer is on it: coming onto it is news, the light's to cross
        moves.append((("under", number), kind == "usage" and spot.cell[1] == number,
                      (row, first), False, shade))
    out = terminal.lit(out, spots, tips, keys_top + 1)
    moved, rising = "", False
    if clock is not None:
        clock.clear()
        rising = clock.rise(out)
        news = clock.look({key: shown for key, shown, _, _, _ in moves})
        for key, shown, cell, lit, shade in moves:
            since, before = news.get(key, (None, None))
            if shown == "working":
                clock.start([cell], motion.breathing(terminal.state_glyph(shown), shown, lit))
            elif since is None:
                continue
            elif key[0] == "under":
                if shown:             # the pointer came onto its row: one light across its bar
                    cells, until = motion.glinting(glint, since, shade)
                    for n, animation in enumerate(cells):
                        clock.start([(cell[0], cell[1] + n)], animation, until)
            elif shown in ("needs you", "done"):
                clock.start([cell], *(motion.pulsing if shown == "needs you" else motion.settling)(
                    terminal.state_glyph(shown), shown, since, lit))
            elif key[0] != "word" and len(before[1]) == len(shown[1]):
                # a cell each, so a frame rewrites only the cells that moved
                cells, until = motion.gliding(before[1], shown[1], since, shade, lit,
                                              sweep=shown[0] == 1 > before[0])
                if ticked and cell[0] == ticked[0]:   # the pointer's tick stands through it
                    cells[ticked[1]] = lambda now: glint[ticked[1]]
                for n, animation in enumerate(cells):
                    clock.start([(cell[0], cell[1] + n)], animation, until)
        moved = clock.frame()
    # Home and write over, each line cleared past its end and the screen below the last: one
    # write, so no draw ever shows a blank screen or a half-drawn one.  Lines that rise are
    # the frame's to write, from the background up, and never first as they are.
    sys.stdout.write("\033[H" + ("" if rising else "".join(f"\033[K{line}\n" for line in out))
                     + "\033[J" + moved)
    sys.stdout.flush()
    drawn.update(order=order, cursor=cursor, words=words, rule=not compact,
                 ask=top + at + 1 if at else None, spots=spots)
    return page, (len(pages) if ordered else 1)


def stop_session_runs(name, dry_run=False):
    """Stop every unfinished run that seat launched, before the seat itself ends.

    The same `ak run stop` a hand on the keyboard would reach for: deliberate ends,
    never accidents to resume. A run that refuses -- already finished between the
    listing and the stop -- is named and left; the seat still ends.
    """
    from . import run as run_mod
    for run_dir in session_runs(name):
        if dry_run:
            print(f"would stop {run_dir.name}")
            continue
        try:
            run_mod.cmd_stop([run_dir.name])
        except config.Error as exc:
            print(f"could not stop {run_dir.name}: {exc}")
        except (OSError, ValueError, KeyError, TypeError):
            print(f"could not stop {run_dir.name}")


def session_runs(name):
    """Every run that seat launched which stopping it stops: what `run.cmd_stop` takes -- each
    one not ended, as `orch.cmd_stop` stops them too, and an `error` still waiting on its
    owner, which the tick would retry."""
    from . import run as run_mod
    try:
        dirs = record.run_dirs()
    except OSError:
        return []
    found = []
    for run_dir in dirs:
        try:
            state = record.read_state(run_dir)
            word = state and state.get("state")
            if (state and run_mod.launched_session(state) == name
                    and (word not in run_mod.ENDED
                         or word == "error" and run_mod.unfinished(state))):
                found.append(run_dir)
        except (OSError, ValueError, config.Error):
            continue
    return found


def stop_means(runs):
    """What `Stop` means on the card `x` asks on: `runs`, how many runs stop with the seat, or
    None while they are counted, and that ak cannot reopen it: `orch.cmd_stop` removes the
    record a reopening would read."""
    stop = ("Its runs stop" if runs is None else "No runs stop" if not runs
            else "1 run stops" if runs == 1 else f"{runs} runs stop")
    return f"{stop} with it; ak cannot reopen the session: Stop removes its record."


def stop_question(name):
    """The one confirmation `x` asks: the seat, and everything that goes with it."""
    return f"stop {name} and everything it is running? [y/N] "


def close_seat(name, dry_run):
    """End that seat and everything it runs, asking nothing: `x` on a done seat, or `Stop`.

    Its runs stop first, as `stop_session` stops them, then `orch.cmd_stop` takes their
    checkouts, the conversation, the state files and the tmux session.
    """
    stop_session_runs(name, dry_run)
    if dry_run:
        print(f"would stop {name}")
        return
    try:
        orch.cmd_stop([name])
    except config.Error as exc:
        pause(f"stop: {exc}")


def stop_session(found, dry_run):
    """`x` read a line at a time -- a pipe, a file: which seat, then one question, and nothing else.

    With the keyboard `x` is the highlighted seat's instead (`loop`, `close_seat`).  The seat is
    picked by number or by name; Esc and an empty Enter go back
    to the menu, as does anything but `y` to the one question, which says, as the
    keyboard's card does, that nothing reopens the seat afterwards. Its runs stop
    first, the same way `ak run stop` stops one, so none is left to read as an
    accident afterwards. `ak orch stop` then removes the checkouts, the state files
    and the tabs.
    """
    if not found:
        pause("no session to stop")
        return
    terminal.frame("stop")
    choice = terminal.ask("Stop", found[0]["name"],
                          [session["name"] for session in found], read=read)
    if not choice:
        return
    session = next(session for session in found if session["name"] == choice)
    if dry_run:
        stop_session_runs(session["name"], dry_run=True)
        print(f"would stop {session['name']}")
        return
    terminal.frame("stop", terminal.wrap(stop_means(None), terminal.width()))
    if read(stop_question(session["name"]), "") != "y":
        return
    stop_session_runs(session["name"])
    orch.cmd_stop([session["name"]])


def rename_this_session(dry_run):
    """`r` in the overlay: rename the session this menu was opened from.

    `Name [<current>]:`, validated as `session_name`, against every taken name but its own;
    Esc goes back.  The rename is `orch.rename`'s -- the tmux session, the record, every
    state file, its runs' records and the bar -- and afterwards this process answers to the
    new name too, because the popup lives in the renamed session.
    """
    current = config.current_session()
    if not current:
        pause("rename: this menu was not opened from a session")
        return
    terminal.frame("rename")
    name = orch.ask_name(set(orch.taken_names()) - {current}, current)
    if name is None or name is orch.BACK:
        return
    if dry_run:
        pause(f"would rename {current} -> {name}")
        return
    messages = []
    try:
        renamed = orch.rename(current, name, log=messages.append)
    except config.Error as exc:
        pause(*messages, f"rename: {exc}")
        return
    os.environ[config.SESSION_ENV] = renamed
    pause(*messages, f"renamed {current} -> {renamed}")


def stop_this_session(dry_run):
    """`x` in the overlay read a line at a time: stop the session this menu was opened from,
    after the one question."""
    current = config.current_session()
    if not current:
        pause("stop: this menu was not opened from a session")
        return
    terminal.frame("stop", terminal.wrap(stop_means(None), terminal.width()))
    if dry_run:
        stop_session_runs(current, dry_run=True)
        print(f"would stop {current}")
        return
    if read(stop_question(current), "") != "y":
        return
    orch.cmd_stop([current])


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
        orch.attach(name, wait=True)
        return
    if dry_run:
        print(f"would resume {name}")
        return
    try:
        orch.resume(cfg, name, wait=True)
    except config.Error as exc:
        pause(f"resume: {exc}")


def new_session(cfg, dry_run, keyboard=None):
    """`n`: the name, then the orchestrator and both roles on one screen (`orch.pick`), both on
    the menu's `keyboard`, or from a pipe one question at a time; Esc goes back, nothing
    created. Enter at the name leaves it for the orchestrator to choose, and a dry run only
    says what it would start: it creates no session, so neither its record nor its harness's
    rulebook. The terminal is given back once all is chosen, for the seat to open on."""
    terminal.frame("new session")
    if not cfg:
        return None               # no configuration means no models to offer
    cfg = config.load()           # the last creation's [defaults], whichever process made it
    name = orch.ask_name(orch.taken_names(), auto=True, screen="new session")
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
    name = name or orch.unique_name("new", orch.taken_names())
    if dry_run:
        reviewers = selected[3] if len(selected) == 4 else cfg["defaults"].get("reviewers")
        print(f"would start {name}: {selected[0]}, workers {' '.join(selected[2])}"
              + (f", reviewers {' '.join(reviewers)}" if reviewers is not None else ""))
    elif orch.create(cfg, name, orch.seat_cwd(), prompting=True,
                     selection=(providers, selected), unnamed=unnamed) is None:
        return None
    open_session(cfg, {"name": name}, dry_run)
    return name


def smoke_run(state):
    """The suite's task or repo lives in its sandbox; a run's title proves nothing."""
    for key in ("task", "repo"):
        value = state.get(key)
        if not isinstance(value, str) or not value:
            continue
        try:
            path = Path(value).expanduser().resolve().relative_to(config.TMP.resolve())
        except (OSError, RuntimeError, ValueError):
            continue
        if path.parts and path.parts[0].startswith("smoke-"):
            return True
    return False


def run_records():
    """Every run's record, read once: the rows' tallies are drawn from one pass.

    Runs whose task or repo lives under ~/.agentkit/tmp/smoke-* are left out here, so a seat's
    tally never counts the toolkit testing itself.  So is a run marked `unattended`: a worker
    or a done-when command below another run started it, so it belongs to no seat and to no
    terminal, and there is nobody to offer it to.  A run launched by hand belongs to no seat
    either but does belong to the terminal it was started from.  Read-only: a bad record is
    skipped, never repaired.
    """
    found = []
    for run_dir in record.run_dirs():
        state = record.read_state(run_dir)
        if state is not None and not state.get("unattended") and not smoke_run(state):
            found.append((run_dir, state))
    return found


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
    out with it: `as of 14:02` beside a four-cell bar is worth having on a phone even where
    `resets Fri 14:00` will never fit.  Each note carries how much it is worth keeping when
    only some can be -- a spent 5h window first, then when the week is back, then why the
    reading may be wrong, then the 5h window, then the scoped cap -- and they are offered in
    that order and drawn in the row's.  The bar has already given way to its floor by the
    time anything is offered here.
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


def colour(cfg, name):
    """This provider's colour: its own `colour` key, else the shipped one, else the accent."""
    entry = cfg["providers"].get(name)
    own = entry.get("colour") if isinstance(entry, dict) else None
    if isinstance(own, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", own):
        return own
    return COLOURS.get(name, "accent")


def fill(left, own):
    """A usage bar's filled cells, from the whole percent it shows left: the company's `own`
    colour, then amber from 20% down and red from 5% down, whoever's meter it is."""
    return "FAIL" if left <= 5 else "amber" if left <= 20 else own


def hue(kind):
    """Where a colour sorts: red through violet by its hue, then the near-greys, lightest first.

    A grey's hue is noise, so the greys go by how light they are instead.
    """
    rgb = kind[1:] if kind.startswith("#") else terminal.STATE_STYLES["working"][2]
    shade, saturation, value = colorsys.rgb_to_hsv(*(int(rgb[i:i + 2], 16) / 255
                                                     for i in (0, 2, 4)))
    return (True, -value) if saturation < terminal.GREY else (False, shade)


def usage_rows(cfg):
    """Each usage row `usage_lines` draws, in its order: the provider, the row's label and the
    reading it is drawn from, out of the cached meters."""
    try:
        providers = json.loads((config.STATE / "usage.json").read_text())["providers"]
        if not isinstance(providers, dict):
            providers = {}
    except (OSError, ValueError, KeyError, TypeError):
        providers = {}
    rows = []
    for name in sorted(cfg["providers"], key=lambda name: hue(colour(cfg, name))):
        top = providers.get(name)
        top = top if isinstance(top, dict) else {}
        found = top.get("accounts") if isinstance(top.get("accounts"), dict) else {}
        shown = NAMES.get(name, name.title())
        for account in config.accounts(cfg, name) or [None]:
            rec = top if account is None else found.get(account)
            rows.append((name, shown if account is None else
                         config.account_label(cfg, name, account, shown),
                         rec if isinstance(rec, dict) else {}))
    return rows


def usage_tip(cfg, number, now=None):
    """What the key line says of usage row `number`, from 1, while the pointer is on it -- why
    it has no week to draw, where it has none -- and the share of its week that would be left
    had it been spent as fast as time passes, from the meter's window and reset, or None where
    there is no such week: `Acme II · 68% left · resets Thu
    20:00 (in 2 d 6 h) · lasts at this pace`, more left than that share lasting the week; a
    spent meter has nothing left to pace."""
    now = time.time() if now is None else now
    rows = usage_rows(cfg)
    if not 0 < number <= len(rows):
        return None, None
    name, label, prov = rows[number - 1]
    try:
        week = usage.shared_week(cfg, name, prov, now)
        why = week is None and unread(prov, [m for m in prov.get("meters") or []
                                             if m.get("window_secs") != usage.SESSION_SECS],
                                      usage.readable(prov, now), now)
    except (AttributeError, KeyError, TypeError, ValueError):
        week, why = None, "bad reading"
    if week is None:
        return terminal.TIPS["unread"].format(name=terminal.plain(label), why=why), None
    elapsed, at = usage._elapsed(week, now), usage._number(week.get("resets_at"))
    pace = None if elapsed is None else 1 - elapsed / 100
    resets, left = resets_note(week, now), percent_left(week)
    if resets and at and at > now:
        secs = int(at - now)
        resets += " (in " + (f"{secs // 86400} d {secs % 86400 // 3600} h" if secs >= 86400
                             else f"{secs // 3600} h" if secs >= 3600
                             else f"{max(1, secs // 60)} min") + ")"
    spent = None if pace is None or not left else terminal.TIPS[
        "slower" if left > round(100 * pace) else "faster" if left < round(100 * pace) else "even"]
    return " · ".join(part for part in (terminal.plain(label), f"{left}% left", resets, spent)
                      if part), pace


def usage_lines(cfg, width):
    """The cached weekly allowances, without probing adapters or spending a reset.

    A row is one account's shared weekly meter -- the one every model of it draws on -- that
    a bar can be drawn from: a numeric used% in a window that has not rolled over, as a bar
    and `NN% left`.  A provider that lists `accounts` has one row per account in config
    order, the provider's name numbered in roman numerals (`Claude I`, `Claude II`), each
    from its own reading; a provider without them keeps its single row.  After the percentage, joined with ` · ` and each only when it applies:
    `resets <weekday> <HH:MM>` from that meter, or `resets <day> <month>` more than six days
    out in a window longer than a week; one note per scoped meter whose figure differs
    (`Fable 41%`); `5h 40% left` for the 5-hour window, or `5h spent until 14:00` once it
    reads 100% used; `? <reason>` when the last probe errored although the meter it read
    still stands, and `as of HH:MM` beside it when the reading is older than half an hour,
    with the weekday when it is not from today.  A probe the endpoint refused to answer
    says nothing at all: the reading it could not replace stands as it was, and its age
    says the rest.  The filled cells are `fill`'s colour for what is left, the empty ones dim,
    and the rows run by the `hue` of the provider's `colour`.  `ak usage` keeps the rest --
    week elapsed, the resets in hand,
    headroom, budget, outlook -- and the picker keeps ranking on the tightest meter: only
    this display changed.  The bars are one column, sized once per draw from the row with the
    least room, down to four cells; the bar gives way to the notes first, and only then does
    each note that still will not fit give way on its own (`fitting`), so one long note never
    takes a short one with it.  An account whose every readable week is one model's own cap
    has no shared week to show and says so rather than wearing that cap's number.  A row with
    nothing to draw is `—` and the words that say why, never `—` alone.
    """
    rows = usage_rows(cfg)
    label_room = min(16, max((terminal.cells(terminal.plain(label)) for _, label, _ in rows),
                             default=0), max(1, width - 16))
    bar_width = min(12, max(1, width - label_room - 15))
    now = time.time()
    lines = [terminal.styled("  " + terminal.cut("usage left", width - 2), "dim")]
    pending = []
    # The bar never drops below this to keep a note; narrower notes give way first.
    floor = min(4, bar_width)
    for name, label, prov in rows:
        prefix = "  " + terminal.pad(label, label_room) + "  "
        why = None
        try:
            weekly = [m for m in prov.get("meters") or []
                      if m.get("window_secs") != usage.SESSION_SECS]
            readable = usage.readable(prov, now)
            week = usage.shared_week(cfg, name, prov, now)
        except (AttributeError, KeyError, TypeError, ValueError):
            weekly, readable, week, why = [], [], None, "bad reading"
        if week is None:
            why = why or unread(prov, weekly, readable, now)
            why = terminal.cut(why, max(0, width - terminal.cells(prefix) - 3))
            pending.append({"kind": "empty", "prefix": prefix, "why": why})
            continue
        left = max(0, min(100, 100 - week["used"]))
        shown_pct = percent_left(week)
        spent = shown_pct == 0
        five = session_note(prov, now)
        # In the order the row reads them, each with how much it is worth keeping (`fitting`).
        notes = [(rank, part) for rank, part in
                 [(0, resets_note(week, now)),
                  *((3, note) for note in scoped_notes(cfg, name, readable, week)),
                  *((five,) if five else ()),
                  (1, fault(prov)), (1, usage.as_of(prov, now))] if part]
        percent = f"{shown_pct:3d}% left"
        base = terminal.cells(prefix) + len(percent) + 2   # all but the bar and the notes
        parts = fitting(notes, width - base - floor - 3)   # what the bar gives way to
        taken = terminal.cells(" · ".join(parts)) + 3 if parts else 0
        affordable = min(bar_width, max(1, width - base - taken))
        pending.append({"kind": "bar", "prefix": prefix,
                        "colour": fill(shown_pct, colour(cfg, name)),
                        "left": left, "spent": spent,
                        "percent": percent, "base": base, "notes": notes,
                        "affordable": affordable})
    bars = [entry for entry in pending if entry["kind"] == "bar"]
    if bars:
        shared = min(entry["affordable"] for entry in bars)
        if bar_width >= 4:
            # Task-mandated floor, but never wider than the least room fits.
            least = min(width - entry["base"] for entry in bars)
            shared = min(max(4, shared), max(1, least))
    else:
        shared = bar_width
    for entry in pending:
        if entry["kind"] == "empty":
            lines.append(entry["prefix"] + terminal.styled("—", "dim") + "  " +
                         terminal.styled(entry["why"], "dim"))
            continue
        parts = fitting(entry["notes"], width - entry["base"] - shared - 3)
        # anything left keeps a cell, so the red of a week all but spent is there to be seen
        filled = max(0 if entry["spent"] else 1,
                     min(shared, round(shared * entry["left"] / 100)))
        bar = (terminal.styled("█" * filled, entry["colour"]) +
               terminal.styled("░" * (shared - filled), "dim"))
        line = (entry["prefix"] + bar + "  " +
                (terminal.styled(entry["percent"], "dim") if entry["spent"] else entry["percent"]))
        for part in parts:
            line += terminal.styled(" · ", "dim") + _note_styled(part)
        lines.append(line)
    return lines


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
    from . import run
    if state.get("state") == "waiting_login":
        return run.waiting_word(state)
    if run.going(state):
        return "working"
    if run.needs_recovery(state) or state.get("state") in ("fail", "error", "blocked"):
        return "needs you"
    return "done"


def run_age_secs(state):
    """The seconds the age column and the follow header read for a run."""
    from . import run
    now = time.time()
    started = state.get("started_at") or 0
    if run.needs_recovery(state):
        return max(0.0, now - (state.get("interrupted_at") or started or now))
    if state.get("state") in ("queued", "running"):
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


# The rows under the models, each running its own step; Providers two, `+ add` and `− remove`.
CONFIG_ROWS = ("+ add a model", "Providers", "Discord", "Version")
PROVIDERS = ("row", "Providers")
VERSION = ("row", "Version")    # agentkit's build, read and nothing more
PROVIDER_ACTS = (("+ add", "+ add"), ("− remove", "- remove"))   # and each without UTF-8
# What `+ add` offers each provider the shipped default has as: its company, and the harness it
# runs on; any other is its name on the Providers row.
COMPANIES = {"anthropic": "Anthropic / Claude Code", "openai": "OpenAI / Codex",
             "meta": "Meta / Muse", "xai": "xAI / Grok Build", "google": "Google / Antigravity",
             "mimo": "Xiaomi / MiMo through OpenCode"}
# What `− remove` asks, and what it means; then the same about one subscription of a provider.
REMOVE_PROVIDER_ASK = ("Remove {} and its models?",
                       "Its models leave the config with it; its login stays on this machine.")
REMOVE_SUBSCRIPTION_ASK = ("Remove {}?",
                           "Nothing new starts on it; its login stays on this machine.")
# Short headings leave room for both roles and the effort on a phone.
CONFIG_HEADS = (*orch.ROLE_HEADS, "effort")
# The key line for the cell the highlight is on, and the same without UTF-8.
CONFIG_KEYS = {"mark": ("↑↓←→ move   ⏎ mark", "arrows move   enter mark"),
               "effort": ("↑↓←→ move   ⏎ effort", "arrows move   enter effort"),
               "row": ("↑↓ move   ⏎ open", "arrows move   enter open"),
               "still": ("↑↓ move", "arrows move"),
               "label": ("↑↓←→ move   ⏎ open", "arrows move   enter open")}
# A model's own screen: the two values ←/→ step, then the one that asks first.
MODEL_ROWS = ("model id", "effort", "Remove")
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


def _cancelled(answer):
    """Esc or an arrow key at a question with nothing to ask again: out, writing nothing."""
    return (answer is None or terminal.is_esc(answer)
            or terminal.is_sequence(answer))


def _secret(name):
    """What ~/.agentkit/secrets/<name> holds, or "": the file install.sh and `Discord` write."""
    try:
        return (config.SECRETS / name).read_text().strip()
    except OSError:
        return ""


def discord_value():
    """`Discord`'s value: who a card pings and where it goes, `@acme-owner · webhook …a1B2c3`.

    The name is the one a delivered card's receipt gave this user id (notify.pinged), the id's
    last 4 digits until one has; of the webhook only its last 6 characters are ever shown.
    """
    hook, user = _secret("discord_webhook"), _secret("discord_user_id")
    if not hook:
        return "not connected"
    name = notify.pinged(user) if user else None
    who = f"@{name}" if name else f"id …{user[-4:]}" if user else ""
    return " · ".join(filter(None, (who, f"webhook …{hook[-6:]}")))


def config_models(cfg):
    """The offered models in the order the `c` screen lists them: config.offered's, under their
    providers."""
    return config.offered(cfg)


def model_label(name, width):
    """The configured name on `c` and `n`, cut only to the space its row has."""
    return terminal.cut(name, width)


def model_heading(provider):
    """The same provider heading over the models on `c` and `n`."""
    return terminal.styled(NAMES.get(provider, provider.title()), "accent")


def config_body(cfg, version, at=None, column=0, selected=None, providers=None, moves=None):
    """The `c` screen's lines, and where its rows sit on them: {line: (row, cells)}.

    Every offered model once, under its provider's name: label, harness (dim), the three role
    marks of `selected` -- a session's record, whose missing reviewers are its workers -- and
    its effort between the arrows that step it, then its strength, a bar a level it offers
    (terminal.signal, effort_levels); a model with one effort is its word alone.  With no
    session, only the effort, still column 3.  `moves`, a list, is handed each mark's line, key,
    glyph and how it moves once flipped or refused (motion.toggled), and each effort's line,
    key, word and how its cells move once a step changed it (_effort_moves), for the clock.
    A model `providers` read as spent is dim, its reset note beside it or, on a
    phone, under it.  Under them `+ add a model`, `Providers`
    (providers_lines), `Discord` and `Version` with their values. A row is
    `("model", name)` or `("row", one of CONFIG_ROWS)`, so a model that happens to be called
    `Discord` is still a model; `at` is the highlighted one and `column` the cell on it the keys
    act on, -1 its label, and on Providers 0 or less `+ add` and 1 or more `− remove`.  `cells`
    are a model row's (first, last, column), or Providers' acts, for a click, counted from 1 as
    the terminal counts. On a phone the harness gives way, then the bars, then the label.
    """
    room, utf = terminal.layout_width(), terminal.utf8()
    marks = "●○■□" if utf else "*.x."
    names, models = config_models(cfg), cfg["models"]
    levels = {name: effort_levels(models[name]) for name in names}
    efforts, signals = {}, {}
    for name in names:
        effort, taken = models[name].get("effort", "?"), levels[name]
        # one effort is nothing to step to and no strength to show
        arrows = ("‹ {} ›" if utf else "< {} >") if len(taken) > 1 else "{}"
        efforts[name] = arrows.format(effort)
        signals[name] = terminal.signal(len(taken), taken.index(effort) + 1 if effort in taken
                                        else 0) if len(taken) > 1 else []
    label = max(terminal.cells(name) for name in names)
    harness = max(terminal.cells(str(models[name].get("harness", ""))) for name in names)
    heads = CONFIG_HEADS if selected else CONFIG_HEADS[3:]
    widths = [terminal.cells(head) for head in heads[:-1]]
    widths.append(max(terminal.cells(text) for text in (heads[-1], *efforts.values())))
    rest = sum(2 + width for width in widths)
    tall = max(len(bars) for bars in signals.values())    # the bars, a cell past the efforts
    tall = tall if 2 + label + rest + 1 + tall <= room else 0
    rest += 1 + tall if tall else 0
    label = min(label, max(1, room - 2 - rest))
    harness = min(harness, max(0, room - 2 - label - 2 - rest))
    left = 2 + label + (2 + harness if harness else 0)     # the columns before the marks
    lines = [terminal.styled((" " * left + "".join(
        "  " + terminal.pad(head, width) for head, width in zip(heads, widths))).rstrip(), "dim")]
    places = {}
    for provider in dict.fromkeys(models[name]["provider"] for name in names):
        lines.append(model_heading(provider))
        for name in (name for name in names if models[name]["provider"] == provider):
            texts, builds = orch.role_texts(selected, name, marks) if selected else ((), False)
            texts += (efforts[name],)
            note = orch.spent_note(cfg, name, providers) if providers else ""
            shown = model_label(name, label)
            kind = "reverse" if at == ("model", name) and column < 0 else "dim" if note else None
            line = "  " + (terminal.styled(shown, kind) if kind else shown) + " " * (
                label - terminal.cells(shown))
            cells, first = [(3, 2 + terminal.cells(shown), -1)], left + 1
            if harness:
                line += "  " + terminal.styled(terminal.pad(str(models[name].get("harness", "")),
                                                            harness), "dim")
            for number, text, width in zip(range(4 - len(texts), 4), texts, widths):
                kind = ("reverse" if at == ("model", name) and number == column else
                        "dim" if note or text in (marks[1], marks[3]) or builds and number == 1
                        else None)
                line += "  " + (terminal.toggle(text, width, kind) if number < 3 else
                                (terminal.styled(text, kind) if kind else text)
                                + " " * (width - terminal.cells(text)))
                if number < 3 and moves is not None:
                    moves.append((len(lines), ("mark", name, number), text, motion.toggled(
                        text, width, kind, at == ("model", name), first + 2)))
                # a mark is its whole column; an effort is its own text, arrows and all
                cells.append((first + 2, first + 1 + (width if number < 3
                                                      else terminal.cells(text)), number))
                if number == 3 and moves is not None and len(levels[name]) > 1:
                    moves.append((len(lines), ("effort", name), models[name].get("effort"),
                                  _effort_moves(levels[name], models[name].get("effort"), kind,
                                                at == ("model", name), first + 4,
                                                first + 3 + width if tall and utf else None)))
                first += 2 + width
            if tall and signals[name]:
                line += " " + "".join(signals[name])
            parts = [line.rstrip()]
            if note and terminal.cells(parts[0]) + 2 + terminal.cells(note) <= room:
                parts[0] += "  " + terminal.styled(note, "dim")
            elif note:
                parts += [terminal.styled("    " + part, "dim")
                          for part in terminal.wrap(note, room - 4)]
            for number, part in enumerate(parts):
                places[len(lines)] = (("model", name), cells if number == 0 else [])
                lines.append(terminal.highlight(part, number == 0) if at == ("model", name)
                             else part)
    lines.append("")
    wide = max(terminal.cells(row) for row in CONFIG_ROWS)
    values = ("", "", discord_value(), version or "?")
    for row, value in zip(CONFIG_ROWS, values):
        if ("row", row) == PROVIDERS:
            chosen = min(max(column, 0), 1) if at == PROVIDERS else None
            drawn = providers_lines(cfg, wide, room - 2 - wide - 2, chosen)
            for number, (line, cells) in enumerate(drawn):
                places[len(lines)] = (PROVIDERS, cells)
                lines.append(terminal.highlight(line, number == 0) if chosen is not None
                             else line)
            continue
        # the value wraps once at a word under itself, and is cut only past that
        for number, part in enumerate(terminal.title_lines(value, room - 2 - wide - 2) or [""]):
            line = terminal.table_row([row if number == 0 else "", part],
                                      [wide, room - 2 - wide - 2], indent="  ")
            places[len(lines)] = (("row", row), [])
            lines.append(terminal.highlight(line, number == 0) if at == ("row", row) else line)
    return lines, places


def effort_levels(entry):
    """The efforts a model's bars count, as config.efforts gives them off the catalog its harness
    last listed -- what a step on it walks once that is in hand (config_effort), and what `add a
    model` and a model's own screen fetched -- else off its manifest's table.  Read from
    config's own cache: asking catalog() could start the listing, and a draw asks no harness and
    waits on none.  None where they cannot be read."""
    harness, model = entry.get("harness"), entry.get("model")
    try:
        cached = config._CATALOGS.get(harness)
        listed = cached[1] if cached else config.catalog_table(harness)
        return next((list(item["efforts"]) for item in listed
                     if item["id"] == model and item["efforts"]), None) or config.efforts(harness)
    except config.Error:
        return []


def _effort_moves(levels, effort, kind, bright, word, bars):
    """How an effort's cells move on the `c` screen's clock once a step changed it to `effort`:
    each of its bars the step filled rises into place and each it emptied lowers
    (motion.rising), where they stand from column `bars`, or None; and a step onto the model's
    highest sends one light through the word from column `word` (motion.shimmering), `kind`
    and `bright` as the draw styled it.  A function of the clock, the screen row, when the step
    was and the effort before it."""
    def start(clock, row, since, before):
        was, filled = (levels.index(value) + 1 if value in levels else 0
                       for value in (before, effort))
        for n, bar in enumerate(terminal.signal(len(levels), len(levels)) if bars else ()):
            if (n < was) != (n < filled):
                clock.start([(row, bars + n)], *motion.rising(bar, n < filled, since, bright))
        if effort == levels[-1]:
            clock.start([(row, word)], *motion.shimmering(effort, since, kind, bright))
    return start


def providers_lines(cfg, wide, room, chosen=None):
    """The Providers row's lines, each with the (first, last, act) of the acts on it for a
    click, counted from 1: every provider the config has, by its name and in its colour -- a
    cell that only explains it, `("account", name)` -- then `+ add` (act 0) and `− remove`
    (act 1), wrapped at an item under themselves in `room`.
    `chosen` is the act the highlight is on, reversed, or bracketed with no colour to reverse."""
    items = [(terminal.cut(NAMES.get(name, name.title()), room), colour(cfg, name),
              ("account", name)) for name in cfg["providers"]]
    for number, texts in enumerate(PROVIDER_ACTS):
        text = texts[0 if terminal.utf8() else 1]
        if number == chosen:
            items.append((text if terminal.colour_depth() else f"[{text}]", "reverse", number))
        else:
            items.append((text, None, number))
    drawn, used = [], room
    for text, kind, act in items:
        if used + 2 + terminal.cells(text) > room:        # on a line of its own from here
            drawn.append(("  " + terminal.pad("" if drawn else CONFIG_ROWS[1], wide), []))
            used = -2
        line, cells = drawn[-1]
        first = 5 + wide + used + 2      # counted from 1, past the gutter and what is drawn
        if act is not None:
            cells.append((first, first + terminal.cells(text) - 1, act))
        drawn[-1] = (line + "  " + (terminal.styled(text, kind) if kind else text), cells)
        used += 2 + terminal.cells(text)
    return drawn


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


def config_effort(cfg, name, step, wrap=False):
    """`name`'s effort one step along that model's own efforts (config.efforts), never past
    either end unless `wrap` takes it round to the other, and saved; one set to an effort it
    does not take lands on its first.  The efforts are read `now`, off the catalog already in
    hand (config.catalog_now): a listing never stands between the key and its frame.  What to
    say under the matrix, or ""."""
    entry = cfg["models"][name]
    try:
        levels = config.efforts(entry.get("harness"), entry.get("model"), now=True)
    except config.Error as exc:
        return f"config: {exc}"
    current = entry.get("effort")
    at = levels.index(current) + step if current in levels else 0
    at = at % len(levels) if wrap else at
    if not 0 <= at < len(levels) or levels[at] == current:
        return ""
    before = dict(entry)
    entry["effort"] = levels[at]
    return _saved(cfg, entry, before)


def _nearest(effort, levels):
    """`effort` where `levels` hold it, else the one of them nearest it in EFFORT_RANK, the
    weaker of two as near; the first of them for a word the ranking does not know."""
    if effort in levels:
        return effort
    if effort not in EFFORT_RANK:
        return levels[0]
    return min(levels, key=lambda word: abs(EFFORT_RANK.index(word) - EFFORT_RANK.index(effort))
               if word in EFFORT_RANK else len(EFFORT_RANK))


def _offered(harness, *screen):
    """Every model that harness's catalog lists, asked while `screen` waits on it (`waited`),
    each with the efforts it is offered at (config.efforts): the catalog's own, or for one
    whose efforts it does not say -- a model newer than its adapter's table -- the harness's
    `[effort] levels`, read without asking the catalog a second time."""
    return [dict(model, efforts=model["efforts"] or config.efforts(harness))
            for model in waited(lambda: config.catalog(harness), *screen)]


def config_model_id(cfg, name, step, screen):
    """`name`'s model id one step along the models its harness's catalog lists (_offered),
    never past either end, and saved with the effort that follows it (_nearest); an id not
    among them lands on the first.  `screen` is what waits on the catalog (`waited`).  What to
    say under the screen, or ""."""
    entry = cfg["models"][name]
    try:
        models = _offered(entry.get("harness"), *screen)
    except config.Error as exc:
        return f"config: {exc}"
    if not models:
        return f"the {entry.get('harness')} catalog names no model"
    ids, current = [model["id"] for model in models], entry.get("model")
    at = ids.index(current) + step if current in ids else 0
    if not 0 <= at < len(ids) or ids[at] == current:
        return ""
    before, levels = dict(entry), models[at]["efforts"]
    entry["model"], entry["effort"] = ids[at], _nearest(entry.get("effort"), levels)
    return _saved(cfg, entry, before)


def model_body(cfg, name, at=None):
    """A model's own screen's lines, and where its rows sit on them: {line: (row, cells)}, the
    cells `left` and `right` the arrows of the value on that line, counted from 1 (`under`).

    Its model id and its effort, each between the arrows that step it, then `Remove`;
    `at` is the highlighted row.  On a phone, where a label and its value do not fit on
    one line, the value goes under its label.
    """
    entry, room = cfg["models"][name], terminal.layout_width()
    arrows = "‹ {} ›" if terminal.utf8() else "< {} >"
    values = [arrows.format(value) for value in (
        entry.get("model", "?"), entry.get("effort", "?"))] + [""]
    wide = max(terminal.cells(row) for row in MODEL_ROWS)
    under = 2 + wide + 2 + max(terminal.cells(value) for value in values) > room
    lines, places = [], {}
    for row, value in zip(MODEL_ROWS, values):
        value = terminal.cut(value, room - 4 - (0 if under else wide))
        first = 5 + (0 if under else wide)
        parts = ([f"  {row}", f"    {value}"] if under and value
                 else [f"  {terminal.pad(row, wide)}  {value}".rstrip()])
        last = first + terminal.cells(value) - 1
        for number, line in enumerate(parts):
            places[len(lines)] = (row, [(first, first + 1, "left"), (last - 1, last, "right")]
                                  if number == len(parts) - 1 and value else [])
            lines.append(terminal.highlight(line, number == 0) if row == at else line)
    return lines, places


@terminal.clicks_its_own
def config_model(cfg, name):
    """`config · <name>`: one model's id and effort, and `Remove`, read with the matrix's
    keys until Esc, each change saved and drawn at once.

    ↑/↓, k/j and the wheel move between rows and ←/→ step the value on one: the id through
    its harness's catalog (config.catalog) and nothing else, the effort through that model's
    own (config.efforts).  Nothing is typed, so no id or effort ak does not offer is ever
    written.  Enter on `Remove` asks `Keep` or `Remove` under it, `Keep` picked and Esc
    keeping it; the last model is refused without asking, and one removed goes back to the
    matrix at once.
    """
    here, note, title = MODEL_ROWS[0], "", f"config · {name}"
    while name in cfg["models"]:
        keys = (MODEL_KEYS["remove" if here == "Remove" else "step"][0 if terminal.utf8() else 1]
                + "   esc back")
        body, places = model_body(cfg, name, None if terminal.away() else here)
        shown = body + (["", *(terminal.styled("  " + part, "dim") for part in terminal.wrap(
            note, terminal.layout_width() - 2))] if note else [])
        entry = cfg["models"][name]
        spots = terminal.frame(title, shown, keys, places=places, tips={
            ("model id", None): terminal.TIPS["model id"].format(harness=entry.get("harness")),
            ("effort", None): terminal.TIPS["effort"].format(name=name)})
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
            if terminal.confirm(REMOVE_ASK[0].format(name), REMOVE_ASK[1], "Remove", around):
                before = copy.deepcopy(cfg)
                config.remove_model(cfg, name)
                note = _saved(cfg, cfg, before)
        elif here in MODEL_ROWS[:2] and act in ("left", "right") and not terminal.unseen():
            step = 1 if act == "right" else -1
            try:
                note = (config_model_id(cfg, name, step, (
                    title, lambda: model_body(cfg, name, here)[0], keys))
                        if here == "model id"
                        else config_effort(cfg, name, step))
            except Back:
                return                # Esc while the catalog was asked


def matrix_key(title, body, places, rows, here, top, note, keys, timeout=None, marks=2,
               fetched=None, clock=None, moves=(), tips=None):
    """One draw of a matrix screen and the key read on it: (act, here, column, top).

    The `c` screen and a project's feature switches are read this way: rows the highlight moves
    through, and on a row cells, one a column.  `places` is {line: (row, cells)}, each cell
    (first, last, column) counted from 1 as the terminal counts.  On a screen too short for
    every row the part the highlight is on is shown, and `note` has lines of its own under it,
    whatever the height.  ↑/↓, k/j and the wheel move `here` through `rows`.  A click on a row
    makes it `here`, and one on a cell makes that the column, acting `enter` on the first
    `marks` columns and `less` or `more` on another's arrows; `column` is None where no cell was
    clicked; a cell that only explains is none.  The pointer does the same and acts on nothing,
    the cell it is on lit and the key line saying what `tips` have for it.  `act` is
    `back` for Esc or a click on `esc back`, None when the screen wants drawing again -- a
    resize, the pointer, or `timeout` seconds with no key -- and the key's name otherwise.
    `fetched()` says since when the screen's content is being fetched, or None: while it is, the
    rule under the header glides (`motion.fetching`) and the read ends, None, once it lands.
    `clock` moves what `moves` -- (line, key, value, start) -- says is news (`motion.Clock.look`)
    on the lines shown, each by `start(clock, row, since, before)`, its frames drawn while the
    key is waited for; a key, not the pointer, ends them on their last frames.
    """
    said = ["", *(terminal.styled("  " + part, "dim") for line in note.splitlines()
                  for part in terminal.wrap(line, terminal.layout_width() - 2))] if note else []
    room = max(1, terminal.height() - 5 - terminal.key_height(keys, tips) - len(said))
    drawn = [number for number, (row, _) in places.items() if row == here] or [0]
    top = max(0, min(max(top, drawn[-1] - room + 1), drawn[0], len(body) - room))
    shown = body[top:top + room]
    spots = terminal.frame(title, shown + said, keys, places={
        line - top: place for line, place in places.items() if top <= line < top + room},
        tips=tips)
    if clock is not None:
        sys.stdout.write(clock.drawn(moves, lambda line: 3 + line - top
                                     if top <= line < top + room else None))
        sys.stdout.flush()
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
    act, column = key.name, None
    if act in ("click", "point"):
        spot = terminal.under(key, spots)
        if spot.what is not None:
            here, column = spot.what, None if isinstance(spot.cell, tuple) else spot.cell
        if act == "point":
            return None, here, column, top
        if spot.what is None:
            return "back" if spot.cell == "esc" else "", here, None, top
        # a row runs its step; on Providers only a click on one of its two acts does
        act = "enter" if here[0] == "row" and here != PROVIDERS else ""
        if column is not None:
            act = ("enter" if column < marks else "less" if key.col <= spot.first + 1
                   else "more" if key.col >= spot.last - 1 else "")
    if act in ("esc", "eof"):
        return "back", here, column, top
    if terminal.step(key) and rows:
        here = rows[min(max(rows.index(here) + terminal.step(key), 0), len(rows) - 1)]
    return act, here, column, top


def model_tip(name, entry):
    """What the key line says of model `name`, its config entry, on any screen listing it."""
    return terminal.TIPS["model"].format(name=name, model=entry.get("model", "?"),
                                         harness=entry.get("harness", "?"),
                                         effort=entry.get("effort", "?"))


def config_tips(cfg, token=None):
    """What the `c` screen's key line says of what the pointer is on (terminal.TIPS), {(row,
    cell): sentence}: each model's row, its label with it, its marks and its effort, and each
    provider's name on Providers -- `token`, the worker token's note, said of the provider whose
    harness it is minted for."""
    tips, harness = {}, token and token.split()[0]
    for name in config_models(cfg):
        entry, row = cfg["models"][name], ("model", name)
        tips[row, None] = model_tip(name, entry)
        tips.update({(row, column): terminal.TIPS[head]
                     for column, head in enumerate(orch.ROLE_HEADS)})
        tips[row, 3] = terminal.TIPS["effort"].format(name=name)
    for provider in cfg["providers"]:
        shown = NAMES.get(provider, provider.title())
        tips[PROVIDERS, ("account", provider)] = (
            terminal.TIPS["token"].format(name=shown, note=token.split(" ", 1)[1])
            if any(entry.get("provider") == provider and entry.get("harness") == harness
                   for entry in cfg["models"].values())
            else terminal.TIPS["account"].format(name=shown))
    return tips


@terminal.clicks_its_own
def config_matrix(cfg, keyboard, version, session=None, selected=None, providers=None, note=""):
    """The `c` screen read with the keys until Esc; the config as it left it.

    `selected` is `session`'s record, and its role marks are that seat's models: Enter, space or
    a click flips one (session_mark), the orchestrator moving the seat at once, the roles saved
    to the record for the runs it launches next, the mark filling or emptying over two frames
    and one refused shaking (motion.toggled).  With no session there are no marks.
    ↑/↓, k/j and the wheel move between rows and ←/→ between columns, the effort's too.  Enter
    or space on an effort steps it up, from its highest round to its lowest, and a click on its
    arrow steps it that way: each change is saved and drawn at once, the bar it fills rising
    into place or the one it empties lowering, and a step onto the model's highest sends a
    light through its word (config_body, on the clock); nothing replays after another screen.
    Enter or a click on a model's label, left of its marks, opens that model's own screen
    (config_model), and Esc there comes back to its row.  Enter or a click
    on `+ add a model` opens its screen (config_add), and a model added there is the row
    highlighted after it.  On `Providers` ←/→ move between `+ add` and `− remove`, and Enter or
    a click on one runs it (config_add_provider, config_remove_provider); the row a model, a
    provider or a subscription was just added on glows (motion.glowing); on `Discord` its two
    secrets are typed on the same keys (config_discord).  `Version` is read, and does nothing.
    On a screen too short for every row the part the highlight is on is shown, and what the
    last key could not do -- the last worker, a switch, a save or a catalog that failed -- has
    lines of its own under it, whatever the height, until the next key; `note` is said so
    before the first.  With the pointer on a model, a mark, an effort or a provider's name the
    key line says what it is (config_tips); the worker token's date is said of its provider's,
    and from TOKEN_WARN_DAYS out it stands under the rows whatever the pointer is on.
    """
    from . import watch   # here, not at the top: the menu draws without the tick
    token = watch.worker_token_note()       # a file's date, read once a visit
    days = re.search(r"\(in (\d+) days\)", token or "")
    standing = token if token and ("expired" in token or days and int(days.group(1))
                                   <= watch.TOKEN_WARN_DAYS) else ""
    columns = (-1, 0, 1, 2, 3) if selected else (-1, 3)    # the label, the marks, the effort
    title = f"config · {session}" if selected else "config"
    here, column, top, clock = None, columns[1], 0, motion.Clock()
    while True:
        rows = [*(("model", name) for name in config_models(cfg)),
                *(("row", row) for row in CONFIG_ROWS)]
        here = here if here in rows else rows[0]      # the highlight is the row itself
        if here[0] == "model" and column not in columns:
            column = columns[-1]      # up from Providers' acts onto a row without marks
        if here == PROVIDERS and column == 3 and not selected:
            column = 0                # the one cell leads to `+ add`, as the first mark does
        where = ("label" if here == PROVIDERS else "still" if here == VERSION else "row"
                 if here[0] == "row" else "effort" if column == 3 else "label" if column < 0
                 else "mark")
        keys = CONFIG_KEYS[where][0 if terminal.utf8() else 1] + "   esc back"
        moves = []
        body, places = config_body(cfg, version, None if terminal.away() else here, column,
                                   selected, providers, moves)
        moves += [(line, here, None, motion.glowing(body[line]))     # a row just added glows
                  for line, (row, _) in places.items() if row == here]
        act, here, clicked, top = matrix_key(title, body, places, rows, here, top,
                                            note or standing, keys, marks=3,
                                            clock=clock, moves=moves, tips=config_tips(cfg, token))
        column = column if clicked is None else clicked
        if act is None:
            continue                  # a resize or the pointer: drawn again
        note = ""
        if act == "back":
            return cfg
        if act in ("enter", "space") and (here[0] == "row" or column < 0):
            clock.forget()            # another screen: the matrix back from it replays nothing
        if here == ("row", CONFIG_ROWS[0]):
            if act in ("enter", "space"):
                added = config_add(cfg)
                here = ("model", added) if added else here    # the highlight on its new row
                if added:
                    clock.touch(here)
        elif here == PROVIDERS:
            if act in ("left", "right"):
                column = 1 if act == "right" else 0
            elif act in ("enter", "space") and column >= 1:
                note = config_remove_provider(cfg)
            elif act in ("enter", "space"):
                before = copy.deepcopy(cfg["providers"])
                note = config_add_provider(cfg, keyboard)
                if cfg["providers"] != before:  # a provider or a subscription just added
                    clock.touch(here)
        elif here[0] == "row":
            if here != VERSION and act in ("enter", "space"):
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
            note = session_mark(cfg, session, selected, here[1], column, providers)
            if note:
                clock.touch(("mark", here[1], column))    # refused: the mark shakes
        elif act in ("enter", "space", "less", "more"):     # the effort column
            note = config_effort(cfg, here[1], -1 if act == "less" else 1,
                                 wrap=act in ("enter", "space"))


def _runs(cfg, harness, model, effort=None):
    """The names the config runs that harness's `model` under, at `effort` if one is given."""
    return [name for name, entry in cfg["models"].items() if isinstance(entry, dict)
            and (entry.get("harness"), entry.get("model")) == (harness, model)
            and effort in (None, entry.get("effort"))]


def _add_choices(cfg, picked, screen):
    """The choices of `add a model`'s step after the values `picked`, each (value, the columns
    it shows).

    The harnesses of the providers the config has (config.provider_harnesses), with their
    providers' names; then every model that harness's catalog lists, as config_model_id offers
    them (_offered), each id beside its label where the two differ; then that model's efforts.
    A model the config runs already, or an effort it runs it at, is marked with the names it
    runs under.  `screen` is what waits on a catalog (`waited`).
    """
    def mark(names):
        return f"{terminal.glyph('done')} {', '.join(names)}" if names else ""

    if not picked:
        return [((harness, provider), [harness, NAMES.get(provider, provider.title())])
                for provider in cfg["providers"]
                for harness in config.provider_harnesses(cfg, provider)]
    harness = picked[0][0]
    if len(picked) == 1:
        return [(model, [model["label"], "" if model["id"] == model["label"] else model["id"],
                         mark(_runs(cfg, harness, model["id"]))])
                for model in _offered(harness, *screen)]
    model = picked[1]["id"]
    return [(effort, [effort, mark(_runs(cfg, harness, model, effort))])
            for effort in picked[1]["efforts"]]


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


def add_body(picked, choices, at):
    """`add a model`'s lines, and the choice each list row is: {line: index}.

    Each step chosen so far on a line of its own -- `harness  claude · Claude` -- and under
    them the step being chosen, its name, then its choices in columns with `at` highlighted:
    the steps stack up as they are chosen.  On a phone a model's id gives way first, then its
    label, and its mark keeps up to half the row.
    """
    room = terminal.layout_width()
    wide = max(terminal.cells(step) for step in ADD_STEPS)
    lines = [f"  {terminal.pad(step, wide)}  "
             + terminal.cut(" · ".join(filter(None, texts[:2])), room - 4 - wide)
             for step, (_, texts) in zip(ADD_STEPS, picked)]
    lines.append(f"  {ADD_STEPS[len(picked)]}")
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
def config_add(cfg):
    """`config · add a model`: a harness, then a model its catalog offers, then an effort that
    model takes, each picked from a list with the matrix's keys; the name it was added under,
    or None.

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
    while True:
        try:
            choices = _add_choices(cfg, [value for value, _ in picked], (
                "config · add a model", lambda: add_body(picked, [], 0)[0]))
        except config.Error as exc:
            choices, note = [], f"config: {exc}"
        except Back:                  # Esc while the harness's catalog was asked: back one list
            picked.pop()
            ats.pop()
            continue
        if not choices and not note:
            note = (f"the {picked[0][0][0]} catalog names no model" if picked
                    else "no provider the config has names a harness")
        adding = len(picked) == len(ADD_STEPS) - 1
        keys = ADD_KEYS["add" if adding else "choose"][0 if terminal.utf8() else 1] + "   esc back"
        at = min(ats[-1], max(0, len(choices) - 1))
        body, places = add_body(picked, choices, None if terminal.away() else at)
        said = ["", *(terminal.styled("  " + part, "dim")
                      for part in terminal.wrap(note, terminal.layout_width() - 2))] if note else []
        room = max(1, terminal.height() - 5 - terminal.key_height(keys) - len(said))
        drawn = next((line for line, number in places.items() if number == at), len(body) - 1)
        top = max(0, min(max(top, drawn - room + 1), drawn, len(body) - room))
        shown = body[top:top + room]
        spots = terminal.frame("config · add a model", shown + said, keys, places={
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
        if act == "esc":
            if not picked:
                return None
            picked.pop()
            ats.pop()
        elif terminal.step(key):
            ats[-1] = min(max(at + terminal.step(key), 0), max(0, len(choices) - 1))
        elif act in ("enter", "space") and choices:
            ats[-1] = at
            if not adding:
                picked.append(choices[at])
                ats.append(0)
                continue
            ((harness, provider), _), (model, _) = picked
            effort, taken = choices[at][0], _runs(cfg, harness, model["id"], choices[at][0])
            if taken:
                note = f"{', '.join(taken)} runs {model['id']} at {effort} already"
                continue
            name, before = _short_name(cfg, model["label"]), copy.deepcopy(cfg)
            cfg["models"][name] = {"harness": harness, "model": model["id"], "effort": effort,
                                   "provider": provider}
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


def _adapter_verbs(keyboard, harness, verbs, picked, account=None):
    """Each of `verbs` of `harness`'s adapter, run as install.sh runs them, for `account`'s
    login when one is named, with the terminal given back for them and taken again after.  The
    first that fails ends them, and waits until what it said has been read: what to say about
    it under the matrix, or "".  No verbs is nothing to run, and the terminal stays."""
    if not verbs:
        return ""
    keyboard.give()
    failed = ""
    for verb in verbs:
        try:
            code = subprocess.run([str(config.adapter(harness)), verb],
                                  env={**config.child_env(), **config.account_env(account)}
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
    failed = _adapter_verbs(keyboard, harnesses[0], verbs, picked, listed[-1])
    if failed:
        return failed
    before = copy.deepcopy(cfg)
    cfg["providers"][provider]["accounts"] = listed
    return _saved(cfg, cfg, before)


@terminal.clicks_its_own
def config_add_provider(cfg, keyboard):
    """`+ add` on the Providers row: a provider the shipped default has and the config has not,
    picked from a list, then put in the way it ships, so nothing is typed; or, listed after
    them as the name it will get (`ChatGPT II`, config.account_label), another subscription
    of a provider the config has, which is only logged in and listed (_add_subscription); or,
    last, `Use <who>`, a login `− remove` left on disk (config.kept_logins) whose adapter's
    `auth` still passes, put back with no login: into its provider's `accounts` under its old
    name, or, its provider gone too, with that provider as it ships, a subscription as its one
    login.  <who> is who that `auth` says it is `; logged in as`, else the name the login's
    usage row had; one several share is followed by that row, then by a number (` (2)`), so
    every such login is listed, each as itself.

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
    shipped = config.shipped()
    labels = _by_label([name for name in shipped.get("providers") or {}
                        if name not in cfg["providers"]],
                       lambda name: COMPANIES.get(name, NAMES.get(name, name.title())))
    more = {}
    for text, name in _by_label(list(cfg["providers"]),
                                lambda name: NAMES.get(name, name.title())).items():
        # A random name, never the next free one: a removed subscription's login stays on
        # disk, and a `login` under its old name would find it and call the new one logged in.
        after = [*(config.accounts(cfg, name) or [config.DEFAULT_ACCOUNT]), os.urandom(3).hex()]
        more[config.account_label({"providers": {name: {"accounts": after}}}, name, after[-1],
                                  text)] = (name, after)
    offers = []
    for name, account, label in config.kept_logins():
        listed = config.accounts(cfg, name) or [config.DEFAULT_ACCOUNT]
        if name in labels.values():
            after = None if account == config.DEFAULT_ACCOUNT else [account]
        elif name in cfg["providers"] and account not in listed:
            after = [*listed, account]
        else:
            continue       # it is in ak again, or has no provider to go back to
        # its provider's harness even with none of its models left, as _add_subscription finds it
        harnesses = config.provider_harnesses(cfg, name)
        passed, said = worker.auth_ok(harnesses[0], account=account) if harnesses else (0, "")
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
        terminal.frame("config · add a provider", [""] * (len(labels) + len(more) + len(kept)),
                       keys)
        return 3
    picked = terminal.choose([*labels, *more, *kept], around=around, tips={
        **{text: terminal.TIPS["provider"].format(name=text) for text in labels},
        **{text: terminal.TIPS["subscription"].format(name=text) for text in more},
        **{text: terminal.TIPS["account"].format(name=NAMES.get(provider, provider.title()))
           for text, (provider, _) in kept.items()}})
    if picked is None:
        return ""
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
    program = (harness_plugin(harness).update["version"] or [harness])[0]
    verbs = () if config.harness_binary(program) else ("install",)
    failed = _adapter_verbs(keyboard, harness, verbs if picked in kept else (*verbs, "login"),
                            picked)
    if failed:
        return failed
    try:
        models = _offered(harness, "config · add a provider")
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
def config_remove_provider(cfg):
    """`− remove` on the Providers row: a provider the config has, each followed by its
    subscriptions when it has several, picked from a list, then `Remove <provider> and its
    models?` or `Remove <subscription>?` asked under it, `Keep` picked and Esc keeping it.
    config.remove_provider takes a provider's table, its models and their places in
    [defaults], and with its table goes its usage row.  A subscription, named as its usage row
    is (config.account_label), leaves only the provider's `accounts`; the usual login is never
    offered.  The last provider is not offered either, and with nothing to offer it is refused
    without asking.  Either way no login file goes: the login taken out, the provider's usual
    one for a provider, is recorded (config.keep_login) for `+ add` to offer back.  What to say
    under the matrix, or "".
    """
    labels = {}
    for text, name in _by_label(list(cfg["providers"]),
                                lambda name: NAMES.get(name, name.title())).items():
        if len(cfg["providers"]) > 1:
            labels[text] = (name, None)
        listed = config.accounts(cfg, name)
        labels.update({config.account_label(cfg, name, account, text): (name, account)
                       for account in listed
                       if len(listed) > 1 and account != config.DEFAULT_ACCOUNT})
    if not labels:
        return "the config needs one provider"
    title, keys = "config · remove a provider", ADD_KEYS["choose"][0 if terminal.utf8() else 1]

    def listed():     # the screens the two lists are drawn on, drawn again on a resize
        terminal.frame(title, [""] * len(labels), keys + "   esc back")
        return 3
    picked = terminal.choose(list(labels), around=listed, tips={
        text: terminal.TIPS["account"].format(name=text) for text in labels})
    if picked is None:
        return ""
    name, account = labels[picked]
    question, means = REMOVE_PROVIDER_ASK if account is None else REMOVE_SUBSCRIPTION_ASK

    def asked(card):
        terminal.frame(title, card, "esc back")
        return 3
    if not terminal.confirm(question.format(picked), means, "Remove", asked):
        return ""
    before = copy.deepcopy(cfg)
    try:
        # first, so nothing leaves ak unrecorded; a removal that fails below leaves its login
        # in ak, and a login in ak is never offered
        config.keep_login(name, account or config.DEFAULT_ACCOUNT, picked if account else
                          config.account_label(cfg, name, config.DEFAULT_ACCOUNT, picked))
        if account is not None:
            cfg["providers"][name]["accounts"].remove(account)
        else:
            config.remove_provider(cfg, name)
    except (config.Error, OSError) as exc:
        return str(exc)
    return _saved(cfg, cfg, before)


def config_discord():
    """`Discord`: the two secrets, shown as its row shows them and written the way install.sh
    writes them.

    An empty answer keeps what is there, so one secret can be changed without retyping the
    other; install.sh asks the same way, once, when there is someone to ask.  Esc at either
    goes back with nothing written.
    """
    terminal.frame("config · discord", [f"  {discord_value()}"])
    webhook = read("Webhook URL: ", "")
    if _cancelled(webhook):
        return
    user = read("User id: ", "")
    if _cancelled(user):
        return
    try:
        config.ensure_dirs()
        for name, value in (("discord_webhook", webhook), ("discord_user_id", user)):
            if value:
                path = config.SECRETS / name
                path.write_text(value + "\n")
                os.chmod(path, 0o600)
    except OSError as exc:
        pause(f"discord: {exc}")


def show_config(dry_run=False, keyboard=None, session=None):
    """`c`: every model in one matrix of `session`'s roles -- the seat highlighted on the main
    screen, read from its own record -- and the efforts, then `+ add a model`, `Providers`,
    `Discord` and `Version`, read with the menu's keyboard (config_matrix), so nothing is typed.
    On a heading, with no seats, or for a seat with no record, the matrix is the efforts alone,
    and so it is for a record naming a model removed here, saying so under the rows: the
    screen that adds it back still opens.

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
    try:                      # what a flip is refused on, and spent; Esc while it is read
        providers = waited(lambda: usage.collect(cfg), f"config · {session}",
                           keyboard=keyboard) if selected else {}
    except Back:
        return cfg
    # one git call a visit, not a draw; nothing about a harness and nothing over the network
    version = update.agentkit_version()
    if dry_run or keyboard is None or not keyboard.take():
        terminal.frame(f"config · {session}" if selected else "config",
                       config_body(cfg, version, selected=selected, providers=providers)[0],
                       "esc back")
        return cfg
    return config_matrix(cfg, keyboard, version, session, selected, providers, note)


def session_mark(cfg, name, selected, model, column, providers):
    """Act on one of a session's marks, saving it to the session's record at once.

    `column` is 0 for the orchestrator and 1 for executes and 2 for reviews, as
    `orch.role_mark` numbers them. The orchestrator moves the seat to that model at once,
    under the same name, and a harness that is not installed or not logged in, or a meter
    that is spent, is refused in one line with the seat as it was. Each role group keeps
    one model, and a flip leaving no allowed executor/reviewer pair is refused. A run
    launched afterwards reads the record as left here; one already going keeps the groups
    its receipt saved. A refusal or a save that fails leaves the record, and `selected`,
    alone. What to say under the rows, or "".
    """
    if column == 0:
        note = orch.switch_orchestrator(cfg, name, model, providers)
        if not note:
            selected["orchestrator"] = model
        return note
    try:
        changed, note = orch.role_mark(cfg, selected, model, column, providers)
    except config.Error as exc:     # the record names a model removed on this screen
        return str(exc)
    if note:
        return note
    try:
        saved = config.update_session(name, workers=changed["workers"],
                                      reviewers=changed["reviewers"])
    except OSError as exc:
        return f"session: {exc}"
    if saved is None:
        return f"session: {name} has no saved models"
    selected.update(changed)
    return ""


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
    from . import run   # here, not at the top: run.py is the whole loop, and a menu draws without it
    return run.declared(checkout, "features")


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


def _list_switches(checkout, entry):
    asked = time.monotonic()
    answer, why = features_run(checkout, "list")
    rows = ([row for row in answer if isinstance(row, dict) and "id" in row]
            if isinstance(answer, list) else None)
    with _SWITCHES_LOCK:
        entry["going"] = False
        if entry["set"] > asked:
            return          # a flip answered while this was asked: this list is older than it
        if rows is not None:
            entry["rows"] = rows      # a new list, never the old one changed: Live.watch compares
        entry["error"] = "" if rows is not None else why or "list answered no list"


def features_body(rows, at=None, column=0, moves=None):
    """A project's switches' lines, and where its features sit on them: {line: (row, cells)}.

    Every feature once, its name, then a mark under `you` and under `everyone`: `●` on and `○`
    (dim) off.  One on for everyone is on for you too, and one the project does not let you
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
                    "dim" if text in (off, fixed) else None)
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
    here, column, top, note, clock = None, 0, 0, "", motion.Clock()
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


def move_keys():
    """The key line's first two items while the menu has the keyboard; ASCII without UTF-8."""
    return "↑↓ move   ⏎ open" if terminal.utf8() else "j/k move   enter open"


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
            return item if len(item) == 1 else ""
        key = terminal.Key({"⏎": "enter"}.get(item, item))
    if key.name == "enter":
        return opens(drawn["cursor"])
    if key.name in ("esc", "eof"):
        return terminal.ESC
    return key.char if key.name == "char" else ""


def loop(cfg, client=False, dry_run=False, overlay=False, tidy=None):
    """The menu until Esc, or from a pipe until an empty line or the end of input.

    `overlay` is the menu as a tmux popup over a running seat, offering the five keys and
    the numbers.  A number and `n` both hand this client to a session, and the popup has
    to come down for it to be seen, so those two return; `r` and `x` rename and stop this
    session and leave it up, `x` acting on this session wherever the highlight is.  `c` is not
    offered here.  Read a line at a time, `j` and `k` turn the pages of a list
    longer than the screen, and a number is answered from whichever page is up.

    The main screen is live: the read waits at most TICK seconds, and a wait that ends with
    nothing typed draws again, so the clock, the seat rows, the counts on the top line and the
    usage stay true in front of whoever left it open -- and it ends within STIR of any seat's
    record or the usage cache changing, so a row never says for longer what its bar no longer
    does.  Nothing is read between a key and its frame: the seats, their runs and their rows
    are read once before the first draw, then in `Live`'s thread -- on the clock, after a key
    that did more than move the highlight, and within STIR of a record changing -- and every
    draw is what the last read left, drawn again when the next one lands.  The clock and those
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
    on a row moves the highlight there, and on a key-line item lights it, the key line saying
    what either means while it rests there (terminal.TIPS, `draw`).  A digit
    waits half a second for a second one, a resize or not, and a key read while it waits is
    kept for after, with the screen it was read on.  The highlight is the seat's name, so it
    stays on its seat whatever comes or goes above it.  A key that does nothing here is let
    go without a word, `i` among them, and every key that does something gives the terminal back
    before it does it -- but `c`, `n`, `r` and `x`'s question, which are read with the keys on
    the screen the menu has: `x` on a done seat closes it at once, and on any other asks `Keep`
    or `Stop` under its row, Enter or a click answering and Esc keeping it.  Esc, and a click
    on `esc leave`, leaves at once, whatever a thread is doing (`Live.close`); `q` is no key.
    """
    keys = OVERLAY_KEYS if overlay else KEYS
    actions = ("n", "x", "r") if overlay else ("n", "x", "c")
    cursor = os.environ.pop("AK_MENU_CURSOR", "") or None
    if cursor and cursor.startswith("/"):
        cursor = Path(cursor)
    page, ahead, look, updating, updated = 0, None, False, None, False
    updates = []                         # this loop's inbox, independent of the usage/read worker
    start_update = not (dry_run or overlay)
    last = [[], None]                     # what the last read left: the seats and their groups
    clock = motion.Clock(fade=overlay)    # what moves between draws: the dots, news, and
                                          # the popup's first draw coming up
    with closing(Live(cfg)) as live, closing(terminal.Keyboard()) as keyboard:
        if keyboard.take():
            terminal.sense()              # true colour and the background, once, before a draw
        live.watch(last)                  # read once before the first draw, looked at behind it
        while True:
            if look:
                live.ask(look=True)       # read and looked at again, off the draw
            messages = orch.job_notices() + live.heard()
            if updates:
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
            if updated:
                keyboard.give()
                live.close()
                sys.stdout.flush()
                os.execve(sys.executable, [sys.executable, *sys.argv],
                          {**os.environ, "AK_MENU_CURSOR": str(cursor or "")})
            found, groups = last          # after any notice: what changed under it is drawn as is
            drawn = {} if keyboard.take() else None
            own = config.current_session() if overlay else None
            listed = keys if drawn is None else f"{move_keys()}   {keys}"
            page, pages = draw(cfg, found, listed, page, cursor, drawn, own, look=False,
                               groups=groups, clock=clock, updating=updating)
            cursor = drawn["cursor"] if drawn else cursor   # the seat he sees highlighted
            if start_update:
                update_first(live, updates=updates)    # detached, after the first frame
                start_update = False
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
                key, shown = moving(clock, live.reader, timeout=0 if updates else TICK), drawn
            if key is None:
                # the wait ended on the clock, which looks again, or on news already written down
                look = not live.drain()
                continue
            look = True
            if isinstance(key, terminal.Key):
                order = drawn["order"]
                if key.name == "point":
                    cursor = terminal.under(key, shown["spots"]).what or cursor
                    look = False          # the highlight moves over what is in hand
                    continue
                if terminal.step(key):
                    if order:
                        at = order.index(cursor) + terminal.step(key)
                        cursor = order[min(max(at, 0), len(order) - 1)]
                    look = False          # the highlight moves over what is in hand
                    continue
                clock.forget()            # whatever the key opens, the menu back replays nothing
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
                            cursor, more = terminal.under(more, drawn["spots"]).what or cursor, None
                        if more is None and time.monotonic() < until:
                            # a resize or the pointer: drawn anew, so the dots breathe on where
                            # they now are
                            page, pages = draw(cfg, found, listed, page, cursor, drawn, own,
                                               look=False, groups=groups, clock=clock,
                                               updating=updating)
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
            if key in ("x", "c") and not overlay and terminal.unseen():
                continue          # it acts on the highlighted seat: brought back, to be seen first
            seat = own if overlay else cursor
            if key == "x" and isinstance(seat, Path):
                continue          # a heading is no seat to stop
            if key == "x" and drawn is not None and seat in drawn["words"]:
                # the seat it acts on: a done one closes at once, any other is asked under its row
                if drawn["words"][seat] != "done":
                    cursor = seat

                    # its runs are counted off the draw, so the card is up at once whatever
                    # the disk; one counted within a frame is simply had, a later one drawn in
                    runs, counted = Fetch(lambda: len(session_runs(seat))), [False]
                    runs.join(motion.FRAME)

                    def means():
                        counted[0] = not runs.is_alive()
                        return stop_means(runs.got.get("answer"))

                    def around(card):     # the menu around the card, drawn again on a resize
                        draw(cfg, found, "esc back", page, cursor, drawn, own, ask=(seat, card),
                             look=False, groups=groups, clock=clock)
                        return drawn["ask"]
                    if not terminal.confirm(
                            STOP_ASK.format(seat), means, "Stop", around, wait=lambda: moving(
                                clock, going=None if counted[0] else runs.is_alive)):
                        continue
                keyboard.give()
                close_seat(seat, dry_run)
                continue
            if key not in ("c", "n", "r"):
                keyboard.give()           # whatever the key opens has the terminal as it was
            if key.isdigit():
                if 1 <= int(key) <= len(found):
                    open_session(cfg, found[int(key) - 1], dry_run)
                    if overlay:
                        return 0
                else:
                    pause(f"no session {key}")
            elif key == "n":
                try:
                    if new_session(cfg, dry_run, keyboard) and overlay:
                        return 0
                except config.Error as exc:
                    pause(f"new session: {exc}")
            elif key == "x":
                if overlay:
                    stop_this_session(dry_run)
                else:
                    stop_session(found, dry_run)
            elif key == "r" and overlay:
                rename_this_session(dry_run)
            elif key == "c" and not overlay:
                # read with the keys, too; the looks and probes go on with what it saved
                cfg = live.cfg = show_config(dry_run, keyboard,
                                             seat if isinstance(seat, str) else None) or cfg
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
    menu never updates the live checkout under it, as with the tick (update.go_live).
    """
    if update.agentkit_dir().resolve() != config.REPO:
        return
    try:
        proc = subprocess.Popen([sys.executable, "-m", "agentkit.update", "--agentkit"],
                                cwd=config.REPO, env=config.child_env(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE if live else subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                start_new_session=True)
    except OSError as exc:
        if live:
            live.say(f"update: {exc}")
        return
    if live:
        updates = [] if updates is None else updates
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
                updates.append({"moved": False, "lines": [
                    f"update: agentkit update exited {code} without a result"]})
                live._wake()        # the main screen clears progress through the same completion path
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
    return loop(config.load(), flags["--client"], flags["--dry-run"], flags["--overlay"], tidy)
