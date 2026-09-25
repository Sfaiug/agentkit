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

      ↑↓ move   ⏎ open   n new   x stop   c config   i info   q leave

`n` is one screen: the orchestrator and the workers, the defaults chosen already, so Enter
starts a session.  It is named for its orchestrator, and that name is the row, the status bar
and the title of every message it sends until `r` renames it.

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
opening the menu, like drawing it, calls git for nothing at all.  A usage row is the provider's
*shared* weekly meter -- the one every model of it draws on: a bar and `NN% left`, then
`resets <weekday> <HH:MM>` in local time, then `Fable 41%` for a scoped cap that reads
differently, then `? <reason>` when the last probe errored though the meter it read still
stands, or `rate limited` / `unavailable` when the endpoint would not answer it at all and this
reading stood in.  No row says how old its reading is: the readings are kept current instead.
The bar's filled cells are the company's own colour (`COLOURS`, or the provider's `colour` key),
and the rows run red through violet by that colour's hue, the near-greys last.  `—` is drawn
only when there is no shared week to draw -- no reading at all, or nothing but one model's
private cap -- and the words after it say why.  Everything else `ak usage` knows -- week
elapsed, session, the resets in hand, headroom, budget, outlook -- stays in `ak usage`.

The main screen is live.  It draws at once from the cached meters, then probes every provider
in the background and draws again when the answer lands, and again every ten seconds after
that, so the clock, the seat rows, the counts and the usage stay true while it is open.  A
reading younger than `usage.PROBE_EVERY` is fresh, so the probe asks an adapter at most once a
minute -- the cadence is the host's and not this screen's -- and never blocks a keypress or a
draw; Muse's adapter keeps its own ten-minute cache, because its probe is a billed request.
Those ten seconds hold whatever stdin is, a script's half-written line included, and a key typed
during a draw is read by the next wait.  The sub-screens are not live: they
are read once, like any other question -- but a project's feature switches, which draw again
within a second of their `list` landing.

Six keys: the numbers, `n`, `x`, `c` (models, providers, effort, discord, update), `i`, `q`.
On a terminal one seat row is highlighted as well: ↑/↓, k/j and the wheel move it, Enter or a
click opens a seat, and a click on the key line does what its key does (`loop`,
`terminal.Keyboard`).  `x` is
the highlighted seat's: a done one is closed at once, and any other is asked about under its row,
`Keep` or `Stop` -- so the key line says `x close` while a done seat is highlighted.  `i` is one
screen read with the same keys, back on Esc.
`ak run status` and `ak browser` stay as commands for
orchestrators; the menu no longer offers them. A gone session reads `session closed: press N
to reopen`; an ended run is its orchestrator's business, so no row ever says `press r`.

The screen is budgeted by height as well as width: a list of seats longer than the
screen is drawn a page at a time -- on a terminal the page the highlight is on, from a pipe the
one `m` and `k` turn to -- and a row keeps the number it has in the whole list on whichever page
it is drawn, so what a number opens never depends on the page that is up.

`ak attach --overlay` is the same menu inside a seat, where `ak orch` binds it to `Ctrl-b m` as
a tmux popup: a number switches this client to that session and `n` starts one and switches to
it, both of which close the popup, `r` renames this session, `x` stops this session -- or,
done, closes it at once -- and `q` closes the popup.  The popup offers those four keys and the
numbers; `c` and `i` live on the menu outside.

On the server the menu is this process.  On a client -- a machine where install.sh recorded the
server's ssh alias in ~/.agentkit/state/server -- `ak` runs the same menu over `ssh -t <alias>
ak --client`.  `ak attach` is the same menu under the name the phone
key uses.
"""

import colorsys
import copy
import io
import json
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path

from . import command_help, config, history, notify, orch, terminal, update, usage
from .harness import load as harness_plugin

KEYS = "n new   x stop   c config   i info   q leave"
# What `i` says about the keys and the states, in the README's own words: the page and the
# screen are one text, and tests/test_docs.py holds README.md to these lines.
INFO_KEYS = ("1 2 3   open that session",
             "n       start a session",
             "x       stop a session, or close a done one",
             "c       change the config",
             "i       show info",
             "q       leave")
INFO_STATES = (("needs you", "it asked you something, or it cannot go on without you"),
               ("working", "a run of its own is going, or a turn is"),
               ("done", "it said so, and the row carries its summary"))
OVERLAY_KEYS = "n start a session   r rename this session   x stop this session   q close"
STOP_ASK = "Stop {} and everything it runs?"   # what `x` asks under a seat that is not done
PAGE_KEYS = "m more   k previous"   # added to the key line when the list runs to more pages
LEAST = 3                # rows a page keeps; the usage block gives way before it holds fewer
# The whole vocabulary, worst first: a rollup of seats says the one that wants him.
# `watch.session_state` is what decides which of the three a seat is.
STATE_ORDER = ("needs you", "working", "done")
RUNS_RECENT = 6 * 3600   # how long a finished run stays recent for `ak run status`
# Each company's own colour, for the filled cells of its usage bar: a provider's `colour` key in
# config.toml wins, and a provider named in neither is drawn in the accent.
COLOURS = {"anthropic": "#D97757", "openai": "#FFFFFF", "meta": "#3E9EFB", "xai": "#FCFCFC",
           "google": "#203B9B", "mimo": "#FB8046"}
# Each company's own name, on its usage row and over its models on the `c` screen; any other
# provider is its own name, capitalised.
NAMES = {"anthropic": "Claude", "openai": "ChatGPT", "meta": "Muse", "xai": "Grok",
         "google": "Gemini", "mimo": "MiMo"}
GREY = 0.15              # saturation under which a colour is a grey, sorted after every hue
TICK = 10.0              # the longest the main screen waits for a key before drawing itself again
STIR = 1.0               # ... and how often it looks for a seat's word or the meters having moved
LOOK_WAIT = 0.5          # ... and the longest a draw waits for the looks the clock or a key began
# What the `—` says, from the error the last probe left; the first match wins.  No pattern here
# guesses at a login: `token`, `401` and `login` turn up in lines a logged-in seat produces too,
# and the one party that can say is the harness's `auth` verb, which the probe asks and records.
UNREAD = ((re.compile(r"already reset"), "window reset"),
          (re.compile(r"without a name"), "bad reading"),
          (re.compile(r"returned no meters"), "no reading yet"))
USAGE = ("usage: ak [--client] [--overlay] [--dry-run]   "
         "(the menu; `ak attach` is the same)")


def read(prompt, default=None):
    """One line, stripped; `default` at end of input, which is how a script says `q`.

    `terminal.readline` is where the line actually comes off stdin -- for every screen here
    and for the questions `orch` asks under them -- so the main screen's bounded wait and the
    sub-screens read the same stdin one after another with nothing stranded between them.
    """
    answer = terminal.readline(prompt)
    if not sys.stdout.isatty():
        print()    # the prompt was answered from a pipe: keep the transcript on separate lines
    return default if answer is None else answer.strip()


class Live:
    """The main screen's usage probe, off the thread that draws, and its way of asking for one.

    The menu never waits for an adapter: it draws from state/usage.json, and this starts
    `usage.collect(refresh=True)` in a thread that writes that same file, so the *next* draw
    is the one that shows fresh meters.  A finished probe writes a byte to a pipe the read is
    already selecting on, so that next draw happens the moment the answer lands rather than at
    the following tick.  Every open menu on the box shares one cadence with the tick and with
    `ak usage` -- `usage.PROBE_EVERY` -- so a second seat's screen costs no adapter request at
    all; Muse's adapter keeps its own ten-minute cache besides.  The same pipe is how a seat's
    word moving anywhere asks for a draw: see `watch`.
    """

    def __init__(self, cfg, every=None):
        self.cfg = cfg
        self.every = usage.PROBE_EVERY if every is None else every
        self.started = None          # when the probe now running was started, or None
        self.thread = None
        self.lock = threading.Lock()   # so the pipe is never given back under a probe's write
        self.reader, self.writer = os.pipe()
        os.set_blocking(self.reader, False)
        os.set_blocking(self.writer, False)
        self.watcher, self.done = None, threading.Event()
        self.seen = None                 # the records the screen was drawn from, as they stood
        self.looker = None               # the pass looking at every seat, while one is going

    def close(self):
        """Give the pipe back, once nothing can still be writing to it.

        The lock is the whole point: a descriptor closed while a finished probe is writing
        could already be somebody else's file, and a byte in the wrong file is worse than a
        draw nobody asked for.
        """
        self.done.set()
        if self.looker is not None:
            self.looker.join(TICK)       # nothing a pass still going reads is taken away under it
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

    def look(self, found):
        """Look at every seat again, off the draw, and wait LOOK_WAIT for that at most.

        The looks are `v5o_groups`' own -- each seat captured, decided, and written to its record
        and its bar -- in a thread of their own, so a seat whose capture hangs holds up no draw:
        the draw is the records as they stand, and a look that lands after it is news `watch`
        wakes the read for.  One pass at a time; one still going is waited on, not doubled.
        """
        if self.looker is None or not self.looker.is_alive():
            self.looker = threading.Thread(target=self._look, args=(found,), daemon=True)
            self.looker.start()
        self.looker.join(LOOK_WAIT)

    def _look(self, found):
        try:
            v5o_groups(self.cfg, found)
        except (config.Error, OSError, ValueError, TypeError, KeyError):
            pass    # a seat that cannot be looked at keeps what its record says

    def watch(self):
        """Have the read woken within STIR of any seat's record, or the meters, changing.

        Whatever decides a seat -- its own hook, the tick, `ak orch`, another menu -- writes the
        word to that seat's record and to its bar in one go, so a screen that draws again when a
        record changes, as recorded, never shows a row its bar contradicts for longer than this.
        Called before every draw, so a record written while the screen is being drawn is still
        news.  Looking is a `stat` per file -- its inode as well as its mtime, since every write
        replaces the file -- and nothing here captures a pane or reads a record.  The draw a wake
        asks for writes nothing either, so no menu's draw ever wakes another, or itself.
        """
        self.seen = self.recorded()
        if self.watcher is None:
            self.watcher = threading.Thread(target=self._watch, daemon=True)
            self.watcher.start()

    def recorded(self):
        """usage.json and every seat record: each one's name, inode and mtime; and each
        project's feature switches as its `list` last answered, so their landing is news too."""
        found = []
        for path in [config.STATE / "usage.json", *sorted(config.STATE.glob("seat-*.json"))]:
            try:
                stat = path.stat()
            except OSError:
                continue
            found.append((path.name, stat.st_ino, stat.st_mtime_ns))
        with _SWITCHES_LOCK:
            found += [(key, entry["rows"], entry["error"]) for key, entry in _SWITCHES.items()]
        return found

    def _watch(self):
        while not self.done.wait(STIR):
            now = self.recorded()
            if now != self.seen:
                self.seen = now
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
        return read(prompt, "q")
    try:
        keyboard = sys.stdin.fileno()
        terminal_input = sys.stdin.isatty()
    except (OSError, ValueError):
        return read(prompt, "q")   # nothing to select on; the prompt has not been printed yet
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
        return read("", "q")       # the prompt is already on screen
    if not waiting:
        print()                    # the prompt this leaves behind belongs to the draw, not him
        return None
    return read("", "q")


def pause(*lines):
    """Say something and, when someone is there to read it, wait until they have."""
    for line in lines:
        print(line)
    if sys.stdin.isatty() and sys.stdout.isatty():
        read("q back ", "")


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


def project_header(project, width):
    amounts = ((len(project["rows"]), "seat"), (len(project["runs"]), "run"))
    counts = " · ".join(f"{n} {label}{'' if n == 1 else 's'}" for n, label in amounts)
    suffix = f" · {terminal.state_label(project['word'])} · {counts}"
    room = width - terminal.cells(suffix)
    if room < terminal.cells(project["name"]):
        counts = " · ".join(f"{n} {label}{'' if n == 1 else 's'}" for n, label in amounts if n)
        suffix = f" · {terminal.state_label(project['word'])} · {counts}"
        room = width - terminal.cells(suffix)
    if room < 1:
        counts = f"{len(project['rows'])}s/{len(project['runs'])}r"
        suffix = f" {terminal.state_label(project['word'])} {counts}"
        room = width - terminal.cells(suffix)
    text = terminal.cut(project["name"], max(1, room)) + suffix
    return terminal.styled(terminal.cut(text, width), project["word"])


def project_run(directory, state, width):
    rnd, total, word, elapsed = run_progress(state)
    filled = min(4, round(4 * rnd / total)) if total else 0
    bar = ("█" * filled + "░" * (4 - filled)) if terminal.utf8() else ("#" * filled + "-" * (4 - filled))
    suffix = (f" · {state.get('executor') or '?'}/{state.get('reviewer') or '?'}"
              f" · {bar} {rnd}/{total or '?'} · {elapsed} · {terminal.state_label(word)}")
    prefix = "    ↳ " if terminal.utf8() else "    > "
    title = terminal.cut(state.get("title") or directory.name,
                         width - terminal.cells(prefix + suffix))
    return terminal.styled(prefix + title + suffix, run_style(word))


# --- v5o: the menu at rest answers one question ---------------------------------
#
# The menu at rest is the header, the usage block and the keys line exactly as
# they are today, and between them one line that answers the question
# (`nothing needs you` / `N need you`), then the projects. A seat row is who,
# how many, worker, sentence, progress. Run rows only when they are somebody's
# problem. See docs/cli-design.md for the visual system; every helper it names
# lives in agentkit/terminal.py and is used here, never re-implemented.


def jobs_root():
    """Where job receipts live: ~/.agentkit/jobs/*/job.json (v5q)."""
    return config.HOME / "jobs"


def job_for_seat(seat_name):
    """(done, total, waiting_on) over the seat's unfinished jobs, or None without one. No fake bar.

    Reads ~/.agentkit/jobs/*/job.json when present, nothing when absent. A job is the seat's
    until it records `finished_at`, when the seat it names leads here through rename
    pointers: an orchestrator renamed since launched it under its old name. `done` is
    tasks merged, passed or skipped of all those jobs' tasks; `waiting_on` is the first
    job's `waiting on <dep>` sentence. Unreadable or task-less jobs are no job at all.
    """
    root = jobs_root()
    try:
        candidates = sorted(root.iterdir()) if root.exists() else []
    except OSError:
        return None
    done = total = 0
    waiting = ""
    for entry in candidates:
        path = entry / "job.json" if entry.is_dir() else entry
        if path.suffix != ".json":
            continue
        try:
            job = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(job, dict) or job.get("finished_at"):
            continue
        owner = job.get("seat") or job.get("session") or job.get("owner")
        try:
            owner = config.resolve_session(owner) if isinstance(owner, str) else owner
        except config.Error:
            pass
        if owner != seat_name and entry.name != seat_name:
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


def seat_estimate(seat_name, session=None, job=None):
    """Return the remaining-plan estimate used by both the row and the tmux bar.

    In the unit it reads in at a glance: minutes under an hour, hours under two days, else
    days -- `~45m left`, `~5h left`, `~36d left`.
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
    seconds = history.estimate_seconds(session["repo"])
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
    at = time.time() if now is None else now
    try:
        from . import watch as _watch
        newest = _watch.run_last_write(Path(run_dir))
    except (OSError, ValueError, AttributeError):
        newest = 0.0
    if not newest:
        try:
            newest = _run.read_state(Path(run_dir)).get("started_at") or 0
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
    and a PASS nobody merged -- and nothing else is, and only while nobody else has
    it. A run
    parked `exhausted` or `stalled` is the
    loop's, the tick's or the seat's to take on when a window refills or a stall
    is recovered, an error with a scheduled retry is the tick's the same way, and
    a `queued` or `running` one is nobody's problem yet. An
    ending older than run.GC_AGE has aged out and counts for nobody, acknowledged
    or not; `ak run status` still lists it.

    An ending handed back to the seat that launched it is that orchestrator's from then on,
    and one waiting for that seat's next quiet prompt is about to be: neither is his, so
    neither is in a tally.

    `index` is a `run.supersession_index` over the same states: pass it when testing
    many runs so one draw scans the records once instead of once per run per seat.
    """
    from . import run as _run
    if state.get("recovery_acknowledged_at"):
        return False
    if state.get("state") == "error" and _run.going(state, now=now):
        return False  # the tick owns its retry; nothing here needs him
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
    if isinstance(ended, (int, float)) and not isinstance(ended, bool) and at - ended > _run.GC_AGE:
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


def _progress_text(info, narrow=False):
    if not info.get("bar"):
        return ""
    text = terminal.progress_bar(info["bar"][0], info["bar"][1], narrow=narrow)
    return f"{text} · {info['estimate']}" if info.get("estimate") else text


def v5o_groups(cfg, found, records=None, now=None, look=True):
    """The projects and their seats, needing projects first, seats by state within.

    A project is a checkout under ~/code, or agentkit's own at ~/agentkit -- one of
    `orch.checkouts()` -- and a seat is filed under the one its repo *is* (`orch.checkout_of`);
    a seat working across projects from ~/code files under the fallback heading.
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
    return last_column(info.get("word"), info.get("sentence"), done, total,
                       info.get("estimate"), narrow)


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


def v5o_format_seats(infos, term_width, widths=None):
    """Rows are tables: number, name, orchestrator, state, one last column.

    Fixed columns with two-space gutters, sized once per draw from the rows on
    screen. Content is capped at 100 columns. A long last column wraps at word
    boundaries onto one indented line, ending in ` …` only when more was cut.
    On a narrow phone the last column goes on its own line and the bar shortens
    to 4 cells. Never cut inside a glyph or a colour sequence.
    """
    return [line for block in v5o_seat_blocks(infos, term_width, widths)
            for line in block]


def draw(cfg, found, keys=KEYS, page=0, cursor=None, drawn=None, own=None, ask=None, look=True):
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
    filled with what a key or a click is read against: `order`, the seats' names top to
    bottom, with the checkout of a project naming its feature switches where its heading is;
    `cursor`, the one highlighted; `rows`, the seat or heading on each screen row; `spans`, the
    key-line item under each column; `words`, each seat's word.

    `x` acts on the highlighted seat, or on `own`, the popup's own, and the key line says
    `x close` while that seat is done.  `ask` is the seat `x` is asking about: the question
    is drawn under its row, its two answers left for `terminal.choose` to draw on the two
    lines under that, and `drawn["ask"]` is the screen row of the first.

    `look` is whether the seats are looked at for this draw or drawn as recorded.
    """
    owned = drawn is not None
    if (not owned and sys.stdout.isatty() and os.environ.get("TERM", "dumb") != "dumb"
            and "NO_COLOR" not in os.environ):
        print("\033[2J\033[H", end="")
    width, height = terminal.width(), terminal.height()
    layout = terminal.layout_width(width)
    ordered, infos, total_needing, _silent = v5o_groups(cfg, found, look=look)
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
    asked = ([f"  {line}" for line in terminal.wrap(STOP_ASK.format(ask), layout - 2)] + ["", ""]
             if ask in words else [])
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
    # With the keyboard the highlight turns the pages, so `m` and `k` are not offered then.
    page_keys = "" if owned else "   " + PAGE_KEYS
    # A question under a row is budgeted with the key line, so it never pushes a row off.
    k_single = len(terminal.key_line(key_text, width)) + len(asked)
    k_paged = len(terminal.key_line(key_text + page_keys, width)) + len(asked)

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
        return v5o_header(project, width), project["checkout"] if "switches" in project else None
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
    clock = time.strftime("%H:%M")
    out = []
    if not compact:
        out += [terminal.header_line("", clock, width), terminal.rule_line(width)]
    if meters:
        if not compact:
            out.append("")
        out += meters
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
    at = max((number for number, (_, name) in enumerate(body, 1) if name == ask), default=0)
    if asked and at:
        body = body[:at] + [(line, None) for line in asked] + body[at:]
    else:
        at = 0
    for line, name in body:
        # while a question is up its first answer carries the mark, and the seat only its light;
        # a heading is flush left, so its mark goes in front of it
        out.append(terminal.highlight(("  " if isinstance(name, Path) else "") + line,
                                      mark=name != above and not at)
                   if owned and name is not None and name == cursor else line)
        above = name
    if not compact:
        out.append("")
    keys_top = len(out)
    out += key_lines
    if not owned:
        print("\n".join(out))
        return page, (len(pages) if ordered else 1)
    # Home and write over, each line cleared past its end and the screen below the last: one
    # write, so no draw ever shows a blank screen or a half-drawn one.
    sys.stdout.write("\033[H" + "".join(f"{line}\033[K\n" for line in out) + "\033[J")
    sys.stdout.flush()
    drawn.update(order=order, cursor=cursor, words=words,
                 ask=top + at + len(asked) - 1 if at else None,
                 rows={top + number: name for number, (_, name) in enumerate(body, 1) if name},
                 spans=[(keys_top + number, first, last, key)
                        for number, line in enumerate(key_lines, 1)
                        for first, last, key in terminal.key_spans(line)])
    return page, (len(pages) if ordered else 1)


def stop_session_runs(name, dry_run=False):
    """Stop every unfinished run that seat launched, before the seat itself ends.

    The same `ak run stop` a hand on the keyboard would reach for: deliberate ends,
    never accidents to resume. A run that refuses -- already finished between the
    listing and the stop -- is named and left; the seat still ends.
    """
    from . import run as run_mod
    try:
        dirs = run_mod.run_dirs()
    except OSError:
        return
    for run_dir in dirs:
        try:
            state = run_mod.read_state(run_dir)
        except (OSError, ValueError):
            continue
        if not state:
            continue
        try:
            if run_mod.launched_session(state) != name:
                continue
        except config.Error:
            continue
        if not run_mod.unfinished(state):
            continue
        if dry_run:
            print(f"would stop {run_dir.name}")
            continue
        try:
            run_mod.cmd_stop([run_dir.name])
        except config.Error as exc:
            print(f"could not stop {run_dir.name}: {exc}")
        except (OSError, ValueError, KeyError, TypeError):
            print(f"could not stop {run_dir.name}")


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
    picked by number or by name; `q`, Esc and an empty Enter go back
    to the menu, as does anything but `y` to the one question. Stopping is the only
    thing that ends a seat: the conversation is saved, and the seat's number opens
    it again later. Its runs stop first, the same way `ak run stop` stops one, so
    none is left to read as an accident afterwards. `ak orch stop` then removes
    the checkouts, the state files and the tabs.
    """
    if not found:
        pause("no session to stop")
        return
    terminal.frame("stop", [], "q back")
    choice = terminal.ask("Stop", found[0]["name"],
                          [session["name"] for session in found], read=read)
    if not choice:
        return
    session = next(session for session in found if session["name"] == choice)
    if dry_run:
        stop_session_runs(session["name"], dry_run=True)
        print(f"would stop {session['name']}")
        return
    terminal.frame("stop", terminal.wrap("The conversation is saved and the seat's number "
                                           "reopens it later.", terminal.width()), "q back")
    if read(stop_question(session["name"]), "") != "y":
        return
    stop_session_runs(session["name"])
    orch.cmd_stop([session["name"]])


def rename_this_session(dry_run):
    """`r` in the overlay: rename the session this menu was opened from.

    `Name [<current>]:`, validated as `session_name`, against every taken name but its own;
    `q` goes back.  The rename is `orch.rename`'s -- the tmux session, the record, every
    state file, its runs' records and the bar -- and afterwards this process answers to the
    new name too, because the popup lives in the renamed session.
    """
    current = config.current_session()
    if not current:
        pause("rename: this menu was not opened from a session")
        return
    terminal.frame("rename", [], "q back")
    name = orch.ask_name(set(orch.taken_names()) - {current}, current)
    if name is None or name is orch.BACK:
        return
    if dry_run:
        print(f"would rename {current} -> {name}")
        return
    try:
        renamed = orch.rename(current, name)
    except config.Error as exc:
        pause(f"rename: {exc}")
        return
    os.environ[config.SESSION_ENV] = renamed
    print(f"renamed {current} -> {renamed}")


def stop_this_session(dry_run):
    """`x` in the overlay read a line at a time: stop the session this menu was opened from,
    after the one question."""
    current = config.current_session()
    if not current:
        pause("stop: this menu was not opened from a session")
        return
    terminal.frame("stop", terminal.wrap("The conversation is saved and the seat's number "
                                         "reopens it later.", terminal.width()), "q back")
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


def new_session(cfg, dry_run):
    """`n`: the orchestrator and the workers on one screen, Enter starting it with what is
    chosen there (`orch.pick`), or from a pipe the two questions; Esc or `q` goes back, nothing
    created.  The seat is named for its orchestrator, and a dry run only says what it would
    start: it creates no session, so neither its record nor its harness's rulebook."""
    terminal.frame("new session", [], "q back")
    if not cfg:
        return None               # no configuration means no models to offer
    providers = usage.collect(cfg)
    selected = orch.select(cfg, providers, prompting=True)
    if selected is orch.BACK:
        return None
    name = orch.default_name(selected[0], orch.taken_names())
    if dry_run:
        print(f"would start {name}: {selected[0]}, workers {' '.join(selected[2])}")
    elif orch.create(cfg, name, orch.seat_cwd(), prompting=True,
                     selection=(providers, selected)) is None:
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
    from . import run   # here, not at the top: run.py is the whole loop, and a menu draws without it
    found = []
    for run_dir in run.run_dirs():
        state = run.read_state(run_dir)
        if state is not None and not state.get("unattended") and not smoke_run(state):
            found.append((run_dir, state))
    return found


def run_style(word):
    """The vocabulary word a run's own progress word draws as.

    `run_progress` says how a run is getting on -- `waiting`, `silent 4m`, `stalled`,
    `FAIL` -- and rollups and coloured draws read that as one of the three words
    everything here says: work still moving is `working`, an ending nobody can take
    up again is his. The row itself keeps saying the run's own word.
    """
    if word in ("done", "needs you", "working"):
        return word
    if word in ("FAIL", "interrupted", "stalled"):
        return "needs you"
    return "working"


def run_progress(state):
    """Round, budget, state and elapsed for one run's drill-down."""
    from . import run
    going = state.get("state") in ("queued", "running")
    started = state.get("started_at") or 0
    finished = state.get("finished_at") or 0
    done = len(state.get("round_summaries") or [])
    total = state.get("rounds")
    # a running run is in the round after the last one it finished, and never past its budget
    rnd = min(done + 1, total) if going and total else done
    if state.get("state") == "queued":
        word = "waiting"
    elif state.get("state") == "stalled":
        word = "stalled"
    elif going and state.get("stalls"):
        word = "working"
        stalls = state["stalls"]
        last = stalls[-1].get("time") if isinstance(stalls[-1], dict) else None
        if isinstance(last, (int, float)) and not isinstance(last, bool):
            try:
                from . import watch
                wrote = watch.run_last_write(config.RUNS / state["run_id"])
            except (OSError, ValueError, KeyError, AttributeError):
                wrote = 0.0
            # The tick stamps each entry off its own finished writes, so anything newer
            # is the run's own progress since: recovered, and working again. (A second
            # covers mtime granularity.)
            if not wrote or wrote <= last + 1:
                word = f"silent {orch.span(time.time() - last)}"
    else:
        word = ("working" if going else "done" if state.get("state") in ("pass", "stopped") else
                "interrupted" if state.get("state") == "interrupted" else "FAIL")
    elapsed = (orch.span(time.time() - (state.get("interrupted_at") or started)
                         if run.needs_recovery(state) else time.time() - started
                         if going else max(0.0, finished - started))
               if started else "-")
    return rnd, total, word, elapsed


_INSTALLED = None   # the version this used to title the menu with, cached across calls


def installed(refresh=False):
    """What this menu runs from: the checkout's short commit and its date, or "" without git.

    Only the `i` screen calls it; opening the menu and drawing it ask git for nothing.
    """
    global _INSTALLED
    if _INSTALLED is not None and not refresh:
        return _INSTALLED
    _INSTALLED = ""
    try:
        proc = subprocess.run(["git", "-C", str(config.REPO), "log", "-1", "--format=%h %ct"],
                              capture_output=True, encoding="utf-8", errors="replace", timeout=10)
        if proc.returncode == 0:
            sha, stamp = proc.stdout.split()
            _INSTALLED = time.strftime(f"{sha} · %d %b", time.localtime(int(stamp)))
    except (OSError, ValueError, OverflowError, subprocess.TimeoutExpired):
        pass
    return _INSTALLED


def unread(prov, weekly, readable, now):
    """Why a usage row has no reading to draw: the two or three words after the `—`.

    `readable` with no shared week among it is the one case where a number *was* read and
    still cannot be drawn: every week this provider reports is some model's own cap, and a
    private cap is never shown as the provider's.

    `no login` is said here and nowhere else, and only on the harness's own `auth` verb saying
    no: the seat's credentials are absent or expired, and the remedy is to log in.  A probe the
    endpoint refused says `rate limited` or `unavailable` instead, because the credentials it
    went out with were never the question.
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
    if refusal(prov):
        return refusal(prov)
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


def fault(prov):
    """`? <reason>`: the adapter's own one line for a probe that failed, or "" when it did not.

    The meter the failed probe read still stands, so the row keeps its bar; the reason is
    beside it because a bare `?` sends the reader to `ak usage` to learn a single sentence.
    """
    reason = " ".join(str(prov.get("error") or "").split()).removeprefix("unknown: ")
    return ("? " + reason).strip() if prov.get("error") else ""


def refusal(prov):
    """`rate limited` or `unavailable`: the last probe was refused and this reading stood in.

    Two dim words beside the reading, never a `?` and never `no login`: a 429 from a usage
    endpoint, or one briefly unreachable, is not a word about the credentials it was asked
    with.  The reading itself is the one that was really taken, which is why the row keeps its
    bar.
    """
    return usage.probe_refused(prov.get("probe_error")) or ""


def fitting(notes, room):
    """Which of these notes fit in `room` cells, drawn in the order the row reads them.

    A note too long for the room gives way on its own, and the ones after it are not thrown
    out with it: `rate limited` beside a four-cell bar is worth having on a phone even where
    `resets Fri 14:00` will never fit.  Each note carries how much it is worth keeping when
    only some can be -- when the week is back, then why the reading may be wrong, then the
    scoped cap -- and they are offered in that order and drawn in the row's.  The bar has
    already given way to its floor by the time anything is offered here.
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
    """This provider's bar colour: its own `colour` key, else the shipped one, else the accent."""
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
    return (True, -value) if saturation < GREY else (False, shade)


def usage_lines(cfg, width):
    """The cached weekly allowances, without probing adapters or spending a reset.

    A row is the provider's shared weekly meter -- the one every model of it draws on -- that
    a bar can be drawn from: a numeric used% in a window that has not rolled over, as a bar
    and `NN% left`.  After the percentage, joined with ` · ` and each only when it applies:
    `resets <weekday> <HH:MM>` from that meter, or `resets <day> <month>` more than six days
    out in a window longer than a week; one note per scoped meter whose figure differs
    (`Fable 41%`); `? <reason>` when the last probe errored although the meter it read still
    stands, or `rate limited` / `unavailable` when the endpoint refused to answer the last probe
    at all and this reading is the one it could not replace.  Nothing says how old a reading is:
    the probe cadence keeps them current, and a refused probe says so in its own words.  The
    filled cells are the provider's `colour`, the empty ones dim, and the rows run by that
    colour's `hue`.  `ak usage` keeps the rest -- week elapsed, session, the resets in hand,
    headroom, budget, outlook -- and the picker keeps ranking on the tightest meter: only
    this display changed.  The bars are one column, sized once per draw from the row with the
    least room, down to four cells; the bar gives way to the notes first, and only then does
    each note that still will not fit give way on its own (`fitting`), so one long note never
    takes a short one with it.  A provider whose every readable week is one model's own cap
    has no shared week to show and says so rather than wearing that cap's number.  A row with
    nothing to draw is `—` and the words that say why, never `—` alone.
    """
    try:
        providers = json.loads((config.STATE / "usage.json").read_text())["providers"]
        if not isinstance(providers, dict):
            providers = {}
    except (OSError, ValueError, KeyError, TypeError):
        providers = {}
    order = sorted(cfg["providers"], key=lambda name: hue(colour(cfg, name)))
    names = {name: NAMES.get(name, name.title()) for name in order}
    label_room = min(16, max((terminal.cells(terminal.plain(n)) for n in names.values()),
                             default=0), max(1, width - 16))
    bar_width = min(12, max(1, width - label_room - 15))
    now = time.time()
    lines = [terminal.styled("  " + terminal.cut("usage left", width - 2), "dim")]
    pending = []
    # The bar never drops below this to keep a note; narrower notes give way first.
    floor = min(4, bar_width)
    for name, label in names.items():
        prefix = "  " + terminal.pad(label, label_room) + "  "
        prov = providers.get(name)
        prov = prov if isinstance(prov, dict) else {}
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
        shown = percent_left(week)
        spent = shown == 0
        # In the order the row reads them, each with how much it is worth keeping (`fitting`).
        notes = [(rank, part) for rank, part in
                 [(0, resets_note(week, now)),
                  *((2, note) for note in scoped_notes(cfg, name, readable, week)),
                  (1, fault(prov) or refusal(prov))] if part]
        percent = f"{shown:3d}% left"
        base = terminal.cells(prefix) + len(percent) + 2   # all but the bar and the notes
        parts = fitting(notes, width - base - floor - 3)   # what the bar gives way to
        taken = terminal.cells(" · ".join(parts)) + 3 if parts else 0
        affordable = min(bar_width, max(1, width - base - taken))
        pending.append({"kind": "bar", "prefix": prefix, "colour": colour(cfg, name),
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
        filled = max(0, min(shared, round(shared * entry["left"] / 100)))
        bar = (terminal.styled("█" * filled, entry["colour"]) +
               terminal.styled("░" * (shared - filled), "dim"))
        line = (entry["prefix"] + bar + "  " +
                (terminal.styled(entry["percent"], "dim") if entry["spent"] else entry["percent"]))
        for part in parts:
            line += terminal.styled(" · ", "dim") + _note_styled(part)
        lines.append(line)
    return lines


RUNS_HEADERS = ["#", "title", "seat", "worker", "round", "age", "state"]


def run_state_word(state):
    """The listings' word for a run, read from terminal.STATES.

    A run is working, needs you or done, like everything else here. Still queued or
    running, and parked on a provider window, a stall or a scheduled error retry it
    resumes itself from, is `working`; an interruption, a FAIL, an unscheduled error
    and a `blocked` are `needs you`, because nobody is going to take them up unless
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


def run_cells(number, run_dir, state, providers=None, cfg=None):
    """One run's table cells: number, title, seat, worker, round, age, state word.

    The number, title and seat are run_row's own cells, so the row the tests
    pin feeds the table the screen draws; the worker and round split out of
    run_progress, the age reads format_age like every listing, and the state
    reads the table's word from terminal.STATES. `providers` and `cfg` are one
    draw's usage cache and config, handed down so a waiting run's drill-down
    does not re-read them per row.
    """
    from . import run
    row = run_row(number, run_dir, state, providers=providers, cfg=cfg)
    rnd, total, _, _ = run_progress(state)
    return [row[0], row[1], "—" if row[2] == "-" else row[2],
            f"{state.get('executor') or '?'}/{state.get('reviewer') or '?'}",
            f"{rnd}/{total or '?'}", terminal.format_age(run_age_secs(state)),
            runs_word(state)]


def runs_word(state):
    """`r`'s word for a run, which is `run_state_word`'s and nobody else's.

    A run sitting out a provider window resumes itself when the window refills, and a
    stalled one is the tick's or the seat's to recover: both are still `working`, and
    what each waits for is on its note line. A run parked on an expired login says so
    in the column instead. `ak run status` reads the same word.
    """
    return run_state_word(state)


def run_row(number, run_dir, state, providers=None, cfg=None):
    """One run on the list: what it is, whose it is, who is on it, and how far it has got.

    `providers` and `cfg` are one draw's usage cache and config; a caller
    drawing many rows hands them down so an exhausted run's waiting word does
    not re-read both per row. Left out, the row reads them itself.
    """
    from . import run
    rnd, total, word, elapsed = run_progress(state)
    details = (f"{state.get('executor') or '?'}/{state.get('reviewer') or '?'} "
               f"{rnd}/{total or '?'}")
    outcome = (run.whereabouts(state, short=True) if word == "done" else
               state.get("state") or "" if word != "working" else "")
    if state.get("state") in ("exhausted", "waiting_login"):
        # the run waits for a provider window or an expired login, and lifts by itself;
        # its drill-down keeps the state word
        outcome = run.waiting_word(state, providers=providers, cfg=cfg)
    elif state.get("state") == "queued":
        # The host reason belongs to `ak run status`; menu rows retain only `waiting`.
        outcome = "waiting"
    if outcome:
        details += f" · {outcome}"
    return [str(number), state.get("title") or run_dir.name,
            run.launched_session(state) or "-", word, details,
            elapsed]


def table(rows):
    """The same six columns as the sessions, with details below on a phone."""
    print("\n".join(terminal.seats(rows, terminal.width())))


def _runs_table(found, width, room):
    """The runs table: a dim column-header line, then one row per run.

    Fixed columns with two-space gutters, sized once from the rows on screen:
    number, title (all the remaining width, wrapped once at a word onto an
    indented continuation, cut with ` \u2026` only past that), seat (the full name;
    `\u2014` for a run of nobody's), worker, round, age, state (glyph and word from
    terminal.STATES, on every row because the list exists to show it). A run
    that needs a look keeps one dim line under its row saying what and what to
    do about it, never the whole diagnostic: the number is the way to that.
    A blocked run's line says why instead, because it has no resume to offer.
    A failed run a later run merged names its replacement as
    `superseded by <run id>`.

    Returns (header, blocks): the header drawn above the listing, each block
    one run's lines. `room` gates the notes, like the menu's
    rows always did: a note is kept where the page has more lines than the row.
    """
    from . import run
    # one draw's usage cache and config for the waiting notes and drill-downs:
    # read once here, never per row. Nothing is read when no run waits.
    if any(run.needs_recovery(state) for _, state in found):
        try:
            scope_cfg = config.load()
        except config.Error:
            scope_cfg = None
        scope_providers = run._cached_providers()
    else:
        scope_cfg, scope_providers = None, {}
    rows = [run_cells(n, run_dir, state, providers=scope_providers, cfg=scope_cfg)
            for n, (run_dir, state) in enumerate(found, 1)]
    texts = [terminal.state_text(row[6]) for row in rows]
    natural = [max([terminal.cells(row[i]) for row in rows] + [terminal.cells(RUNS_HEADERS[i])])
               if i != 1 else 0 for i in range(7)]
    natural[6] = max([terminal.cells(line) for line in texts] +
                     [terminal.cells(RUNS_HEADERS[6])])
    # The seat and the state stay whole; the title takes all the remaining width.
    gutter, indent = 2, "  "
    fixed = sum(natural[i] for i in (0, 2, 3, 4, 5, 6)) + gutter * 6 + len(indent)
    title_room = width - fixed
    narrow = title_room < 12
    if not narrow:
        natural[1] = title_room
    kinds = ["dim", None, None, None, None, None, None]
    first_room = max(1, width - len(indent) - natural[0] - gutter)
    if narrow:
        # The seven columns cannot stand side by side here: the header names
        # the number and the title, and the seat, worker, round, age and state
        # ride on their own lines under each title.
        header = terminal.table_row(RUNS_HEADERS[:2], [natural[0], first_room],
                                    indent, ["dim"] * 2)
    else:
        header = terminal.table_row(RUNS_HEADERS, [natural[0], max(1, title_room),
                                                   natural[2], natural[3], natural[4],
                                                   natural[5], natural[6]],
                                    indent, ["dim"] * 7)
    all_states = [state for _, state in found]
    blocks = []
    for (run_dir, state), row in zip(found, rows):
        word = row[6]
        kinds[6] = terminal.state_colour(word)
        if not narrow:
            titled = terminal.title_lines(row[1], title_room)
            cells = [row[0], titled[0], row[2], row[3], row[4], row[5],
                     terminal.state_text(word)]
            block = [terminal.table_row(cells, natural, indent, kinds, right=(0,))]
            if len(titled) > 1:
                block.append(" " * (len(indent) + natural[0] + gutter) + titled[1])
        else:
            titled = terminal.title_lines(row[1], first_room)
            block = [terminal.table_row([row[0], titled[0]], [natural[0], first_room],
                                        indent, kinds[:2], right=(0,))]
            if len(titled) > 1:
                block.append(" " * (len(indent) + natural[0] + gutter) + titled[1])
            # cells() skips ANSI escapes, so the state cell is coloured before
            # measuring; a cut below only ever touches the plain seat
            tail = [row[2], row[3], row[4], row[5], terminal.state_cell(word)]
            line = "  " + "  ".join(tail)
            if terminal.cells(line) > width:
                # The tail cannot stand on one line here: seat and worker above,
                # round, age and state below, every name whole on a phone.
                head = [row[2], row[3]]
                rest = [row[4], row[5], terminal.state_cell(word)]
                head_line = "  " + "  ".join(head)
                if terminal.cells(head_line) > width:
                    over = terminal.cells(head_line) - width
                    head[0] = terminal.cut(head[0], max(1, terminal.cells(head[0]) - over))
                    head_line = ("  " + "  ".join(head)).rstrip()
                block.append(head_line)
                block.append(("  " + "  ".join(rest)).rstrip())
            else:
                block.append(line)
        if len(block) < room:
            replacement = run.superseded_by(state, all_states)
            if replacement:
                block.append("  " + terminal.cut(f"superseded by {replacement}",
                                                 max(1, width - 2)))
            if state.get("state") == "blocked":
                # a blocked run is final: the line says what stopped it, and offers no number
                # to resume from, because `ak run resume` refuses it
                block.append("  " + terminal.styled(
                    terminal.cut(run.blocked_note(state), max(1, width - 2)), "dim"))
            elif run.needs_recovery(state) or state.get("state") == "queued":
                number = row[0]
                # A queued run is in line, not to recover: its note is the bare
                # waiting word, and the reason stays in `ak run status`.
                wait = ("waiting" if state.get("state") == "queued" else
                        run.waiting(state, providers=scope_providers, cfg=scope_cfg))
                # one shape for every note here: glyph, word, then what the
                # number is for. A run sitting out a provider window resumes
                # itself, so its line carries the provider and the hour where
                # another run's offers resume -- and the note's glyph and word
                # are the row's own, so it never contradicts the column above it.
                note = (f"{terminal.state_glyph(word)} {wait}" if wait else
                        f"{terminal.state_glyph(word)} {word} \u00b7 "
                        f"{number} offers resume")
                block.append("  " + terminal.styled(
                    terminal.cut(note, max(1, width - 2)), "dim"))
        blocks.append(block)

    return header, blocks


def run_blocks(found, width, room):
    """The lines each run takes on the list: its row, the note of one to recover,
    and the replacement a later run merged.

    A failed run a later run merged names its replacement as `superseded by <run id>`.
    The last six hours are today's runs.
    """
    return _runs_table(found, width, room)[1]


def show_notices(messages):
    """Read maintenance and job messages once, before the main screen clears them."""
    if messages:
        pause(*(" " + part for message in messages for part in terminal.wrap(
            message.replace(os.path.expanduser("~") + "/", "~/"), terminal.width() - 1)))


# The rows under the models, each running its own step; Providers two, `+ add` and `− remove`.
CONFIG_ROWS = ("+ add a model", "Providers", "Discord", "Update")
PROVIDERS = ("row", "Providers")
PROVIDER_ACTS = (("+ add", "+ add"), ("− remove", "- remove"))   # and each without UTF-8
# What `+ add` offers each provider the shipped default has as: its company, and the harness it
# runs on; any other is its name on the Providers row.
COMPANIES = {"anthropic": "Anthropic / Claude Code", "openai": "OpenAI / Codex",
             "meta": "Meta / Muse", "xai": "xAI / Grok Build", "google": "Google / Antigravity",
             "mimo": "Xiaomi / MiMo through OpenCode"}
REMOVE_PROVIDER_ASK = "Remove {} and its models?"   # what `− remove` asks, `Keep` picked first
# The matrix's three columns: in full where they fit, short on a phone.
CONFIG_HEADS = (("orchestrator", "worker", "effort"), ("orch", "work", "effort"))
# The key line for the cell the highlight is on, and the same without UTF-8.
CONFIG_KEYS = {"mark": ("↑↓←→ move   ⏎ mark", "arrows move   enter mark"),
               "effort": ("↑↓←→ move   ⏎ effort", "arrows move   enter effort"),
               "row": ("↑↓ move   ⏎ open", "arrows move   enter open"),
               "label": ("↑↓←→ move   ⏎ open", "arrows move   enter open")}
CONFIG_TAIL = 10   # how many of an update's last lines the `c` screen shows
# A model's own screen: the three values ←/→ step, then the one that asks first.
MODEL_ROWS = ("model id", "effort", "Reviews its own company's work", "Remove")
MODEL_KEYS = {"step": ("↑↓ move   ←→ choose", "arrows move   left/right choose"),
              "remove": ("↑↓ move   ⏎ remove", "arrows move   enter remove")}
REMOVE_ASK = "Remove {} from the config?"   # what `Remove` asks, `Keep` picked until moved
# Every effort word, weakest first -- the widest list a manifest names (adapters/muse.toml) --
# so a new model id that does not take its model's effort takes the nearest one it does.
EFFORT_RANK = ("none", "minimal", *config.EFFORTS)
ADD_STEPS = ("harness", "model", "effort")   # `add a model`'s lists, each opening under the last
ADD_KEYS = {"choose": ("↑↓ move   ⏎ choose", "arrows move   enter choose"),
            "add": ("↑↓ move   ⏎ add", "arrows move   enter add")}


def _cancelled(answer):
    """`q`, Esc or an arrow key at a question with nothing to ask again: out, writing nothing."""
    return (answer is None or answer.lower() == "q" or terminal.is_esc(answer)
            or terminal.is_sequence(answer))


def _secret_set(name):
    """Whether ~/.agentkit/secrets/<name> holds anything: install.sh's `-s`, read the same way."""
    try:
        return (config.SECRETS / name).stat().st_size > 0
    except OSError:
        return False


def _harness_versions(cfg):
    """`claude 2.1.0 codex 0.153`: one short version per updatable harness, in config order."""
    bits = []
    for harness in update.harnesses(cfg):
        match = update.VERSION.search(update.version(harness) or "")
        bits.append(harness["name"] + (f" {match.group(0)}" if match else " ?"))
    return " ".join(bits) or "none"


def _update_value(cfg):
    """The Update row's value: agentkit's build, `up to date` or the newer commit origin has,
    and one short version per harness.

    A subprocess per harness plus three for git, so show_config reads it once per visit rather
    than on every draw; Update reads it again afterwards, because that is what moves them.
    """
    build = update.agentkit_version()
    newer = update.agentkit_newer() if build else ""
    said = f" · {newer} available" if newer else " · up to date" if build else ""
    return f"{build or '?'}{said} · harnesses {_harness_versions(cfg)}"


def config_models(cfg):
    """The offered models in the order the `c` screen lists them: under their providers, each
    provider where its first model is in the file."""
    names = config.offered(cfg)
    providers = dict.fromkeys(cfg["models"][name]["provider"] for name in names)
    return [name for provider in providers for name in names
            if cfg["models"][name]["provider"] == provider]


def config_body(cfg, update_row, at=None, column=0):
    """The `c` screen's lines, and where its rows sit on them: {line: (row, cells)}.

    Every offered model once, under its provider's name: label, harness (dim), then a mark in
    the orchestrator and the worker column -- `●` the one default orchestrator, `■` each
    default worker -- and its effort between the arrows that step it.  Under them `+ add a
    model`, `Providers` (providers_lines), `Discord` and `Update` with their values.  A row is
    `("model", name)` or `("row", one of CONFIG_ROWS)`, so a model that happens to be called
    `Update` is still a model; `at` is the highlighted one and `column` the cell on it the keys
    act on, -1 its label, and on Providers 0 or less `+ add` and 1 or more `− remove`.  `cells`
    are a model row's (first, last, column), or Providers' acts, for a click, counted from 1 as
    the terminal counts.  On a phone the columns take their short names, then the harness gives
    way, then the label.
    """
    room, utf, colour = terminal.layout_width(), terminal.utf8(), terminal.colour_depth()
    marks = "●○■□" if utf else "*.x."
    names = config_models(cfg)
    defaults, models = cfg["defaults"], cfg["models"]
    efforts = {name: ("‹ {} ›" if utf else "< {} >").format(models[name].get("effort", "?"))
               for name in names}
    label = max(terminal.cells(name) for name in names)
    harness = max(terminal.cells(str(models[name].get("harness", ""))) for name in names)
    for heads in CONFIG_HEADS:
        widths = [terminal.cells(head) for head in heads[:2]]
        widths.append(max(terminal.cells(text) for text in (heads[2], *efforts.values())))
        rest = sum(2 + width for width in widths)
        if 2 + label + 2 + harness + rest <= room:
            break
    label = min(label, max(1, room - 2 - rest))
    harness = min(harness, max(0, room - 2 - label - 2 - rest))
    left = 2 + label + (2 + harness if harness else 0)     # the columns before the marks
    lines = [terminal.styled((" " * left + "".join(
        "  " + terminal.pad(head, width) for head, width in zip(heads, widths))).rstrip(), "dim")]
    places = {}
    for provider in dict.fromkeys(models[name]["provider"] for name in names):
        lines.append(terminal.styled(NAMES.get(provider, provider.title()), "accent"))
        for name in (name for name in names if models[name]["provider"] == provider):
            texts = (marks[0] if defaults["orchestrator"] == name else marks[1],
                     marks[2] if name in defaults["workers"] else marks[3], efforts[name])
            shown = terminal.cut(name, label)
            line = "  " + (terminal.styled(shown, "reverse") if at == ("model", name)
                           and column < 0 else shown) + " " * (label - terminal.cells(shown))
            cells, first = [(3, 2 + terminal.cells(shown), -1)], left + 1
            if harness:
                line += "  " + terminal.styled(terminal.pad(str(models[name].get("harness", "")),
                                                            harness), "dim")
            for number, (text, width) in enumerate(zip(texts, widths)):
                shown, lead = (f" {text} ", (width - 3) // 2) if number < 2 else (text, 0)
                kind = ("reverse" if at == ("model", name) and number == column else
                        "dim" if text in (marks[1], marks[3]) else None)
                if kind == "reverse" and number < 2 and not colour:
                    shown = f"[{text}]"        # with no colour to reverse, brackets say where
                line += ("  " + " " * lead + (terminal.styled(shown, kind) if kind else shown)
                         + " " * (width - lead - terminal.cells(shown)))
                # a mark is its whole column; an effort is its own text, arrows and all
                cells.append((first + 2, first + 1 + (width if number < 2
                                                      else terminal.cells(text)), number))
                first += 2 + width
            places[len(lines)] = (("model", name), cells)
            line = line.rstrip()
            lines.append(terminal.highlight(line) if at == ("model", name) else line)
    lines.append("")
    wide = max(terminal.cells(row) for row in CONFIG_ROWS)
    values = ("", "", "connected" if _secret_set("discord_webhook") else "not connected",
              update_row)
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


def providers_lines(cfg, wide, room, chosen=None):
    """The Providers row's lines, each with the (first, last, act) of the acts on it for a
    click, counted from 1: every provider the config has, by its name and in its colour, then
    `+ add` (act 0) and `− remove` (act 1), wrapped at an item under themselves in `room`.
    `chosen` is the act the highlight is on, reversed, or bracketed with no colour to reverse."""
    items = [(terminal.cut(NAMES.get(name, name.title()), room), colour(cfg, name), None)
             for name in cfg["providers"]]
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


def config_mark(cfg, name, column):
    """A mark flipped and saved: `name` is the orchestrator now, or joins or leaves the workers.

    There is always one orchestrator, so choosing another is the only way to move it.  The
    workers keep one model at least: a new seat takes them with Enter, and an empty list would
    give it nobody to work.  What to say under the matrix, or "".
    """
    defaults = cfg["defaults"]
    workers, before = defaults["workers"], dict(defaults)
    if column == 0:
        if defaults["orchestrator"] == name:
            return ""
        defaults["orchestrator"] = name
    elif name not in workers:
        defaults["workers"] = [*workers, name]
    elif len(workers) == 1:
        return "the default workers need one model"
    else:
        defaults["workers"] = [peer for peer in workers if peer != name]
    return _saved(cfg, defaults, before)


def config_effort(cfg, name, step, efforts=config.efforts, wrap=False):
    """`name`'s effort one step along that model's own efforts (config.efforts, or a model's
    own screen's _catalog_efforts), never past either end unless `wrap` takes it round to the
    other, and saved; one set to an effort it does not take lands on its first.  What to say
    under the matrix, or ""."""
    entry = cfg["models"][name]
    try:
        levels = efforts(entry.get("harness"), entry.get("model"))
    except config.Error as exc:
        return f"config: {exc}"
    if not levels:
        return f"the catalog names no efforts for {entry.get('model')}"
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


def _catalog_efforts(harness, model):
    """The efforts the catalog lists for that model id, and [] for one it names none for or
    does not list: never config.efforts' vocabulary, which is no catalog's offer."""
    return next((list(entry["efforts"]) for entry in config.catalog(harness)
                 if entry["id"] == model), [])


def config_model_id(cfg, name, step):
    """`name`'s model id one step along the models its harness's catalog lists efforts for,
    never past either end, and saved with the effort that follows it (_nearest); an id not
    among them lands on the first.  One whose efforts the catalog does not say -- OpenCode's
    -- has none to follow with, and is not offered.  What to say under the screen, or ""."""
    entry = cfg["models"][name]
    try:
        models = [model for model in config.catalog(entry.get("harness")) if model["efforts"]]
    except config.Error as exc:
        return f"config: {exc}"
    if not models:
        return f"the {entry.get('harness')} catalog names no model with its efforts"
    ids, current = [model["id"] for model in models], entry.get("model")
    at = ids.index(current) + step if current in ids else 0
    if not 0 <= at < len(ids) or ids[at] == current:
        return ""
    before, levels = dict(entry), models[at]["efforts"]
    entry["model"], entry["effort"] = ids[at], _nearest(entry.get("effort"), levels)
    return _saved(cfg, entry, before)


def config_review(cfg, name):
    """`name`'s `reviews_own_provider` flipped and saved; a model without it reviews its own
    company's work, the way run.py reads it.  What to say under the screen, or ""."""
    entry = cfg["models"][name]
    before = dict(entry)
    entry["reviews_own_provider"] = not entry.get("reviews_own_provider", True)
    return _saved(cfg, entry, before)


def model_body(cfg, name, at=None):
    """A model's own screen's lines, and where its rows sit on them: {line: (row, first,
    last)}, the columns of the value on that line, counted from 1, for a click.

    Its model id, its effort and whether it reviews its own company's work, each between the
    arrows that step it, then `Remove`; `at` is the highlighted row.  On a phone, where a
    label and its value do not fit on one line, the value goes under its label.
    """
    entry, room = cfg["models"][name], terminal.layout_width()
    arrows = "‹ {} ›" if terminal.utf8() else "< {} >"
    values = [arrows.format(value) for value in (
        entry.get("model", "?"), entry.get("effort", "?"),
        "yes" if entry.get("reviews_own_provider", True) else "no")] + [""]
    wide = max(terminal.cells(row) for row in MODEL_ROWS)
    under = 2 + wide + 2 + max(terminal.cells(value) for value in values) > room
    lines, places = [], {}
    for row, value in zip(MODEL_ROWS, values):
        value = terminal.cut(value, room - 4 - (0 if under else wide))
        first = 5 + (0 if under else wide)
        parts = ([f"  {row}", f"    {value}"] if under and value
                 else [f"  {terminal.pad(row, wide)}  {value}".rstrip()])
        for number, line in enumerate(parts):
            places[len(lines)] = ((row, first, first + terminal.cells(value) - 1)
                                  if number == len(parts) - 1 else (row, 0, -1))
            lines.append(terminal.highlight(line, number == 0) if row == at else line)
    return lines, places


@terminal.clicks_its_own
def config_model(cfg, name):
    """`config · <name>`: one model's id, effort and review rule, and `Remove`, read with the
    matrix's keys until Esc or `q`, each change saved and drawn at once.

    ↑/↓, k/j and the wheel move between rows and ←/→ step the value on one: the id through
    its harness's catalog (config.catalog) and nothing else, the effort through the efforts
    that catalog lists for it, and `Reviews its own company's work` -- `reviews_own_provider`
    -- flips, as it does with Enter, space or a click.  Nothing is typed, so no id or effort
    the catalog does not offer is ever written.  Enter on `Remove` asks `Keep` or `Remove` under it, `Keep`
    picked and Esc keeping it; the last model is refused without asking, and one removed goes
    back to the matrix at once.
    """
    here, note, title = MODEL_ROWS[0], "", f"config · {name}"
    while name in cfg["models"]:
        keys = (MODEL_KEYS["remove" if here == "Remove" else "step"][0 if terminal.utf8() else 1]
                + "   esc back")
        body, places = model_body(cfg, name, here)
        shown = body + (["", *(terminal.styled("  " + part, "dim") for part in terminal.wrap(
            note, terminal.layout_width() - 2))] if note else [])
        terminal.frame(title, shown, keys)
        key = terminal.read_key()
        if key is None:
            continue                  # a resize: drawn again at the new size
        act, note = key.name, ""
        if act == "click":
            place = places.get(key.row - 3)
            if place is None:
                if any((4 + len(shown) + number, item) == (key.row, "esc")
                       and first <= key.col <= last
                       for number, text in enumerate(terminal.key_line(keys))
                       for first, last, item in terminal.key_spans(text)):
                    return
                continue
            here, first, last = place
            inside = first <= key.col <= last     # on the value: an arrow steps it, yes/no flips
            act = ("enter" if here == "Remove" or here == MODEL_ROWS[2] and inside
                   else "left" if inside and key.col <= first + 1
                   else "right" if inside and key.col >= last - 1 else "")
        if act in ("esc", "eof") or key.char in ("q", "Q"):
            return
        if terminal.step(key):
            here = MODEL_ROWS[min(max(MODEL_ROWS.index(here) + terminal.step(key), 0),
                                  len(MODEL_ROWS) - 1)]
        elif here == "Remove" and act in ("enter", "space"):
            if config.offered(cfg) == [name]:
                note = "the config needs one model"
                continue

            def around():     # the screen around the question, drawn again on a resize
                lines = [*model_body(cfg, name)[0], *(f"  {line}" for line in terminal.wrap(
                    REMOVE_ASK.format(name), terminal.layout_width() - 2))]
                terminal.frame(title, [*lines, "", ""], "esc keep")
                return 3 + len(lines)
            if terminal.choose(["Keep", "Remove"], "Keep", around=around) == "Remove":
                before = copy.deepcopy(cfg)
                config.remove_model(cfg, name)
                note = _saved(cfg, cfg, before)
        elif here == MODEL_ROWS[2] and act in ("left", "right", "enter", "space"):
            note = config_review(cfg, name)
        elif here in MODEL_ROWS[:2] and act in ("left", "right"):
            step = 1 if act == "right" else -1
            note = (config_model_id(cfg, name, step) if here == "model id"
                    else config_effort(cfg, name, step, _catalog_efforts))


def matrix_key(title, body, places, rows, here, top, note, keys, timeout=None):
    """One draw of a matrix screen and the key read on it: (act, here, column, top).

    The `c` screen and a project's feature switches are read this way: rows the highlight moves
    through, and on a row cells, one a column.  `places` is {line: (row, cells)}, each cell
    (first, last, column) counted from 1 as the terminal counts.  On a screen too short for
    every row the part the highlight is on is shown, and `note` has lines of its own under it,
    whatever the height.  ↑/↓, k/j and the wheel move `here` through `rows`.  A click on a row
    makes it `here`, and one on a cell makes that the column, acting `enter` on a mark (column
    0 or 1) and `less` or `more` on another's arrows; `column` is None where no cell was
    clicked.  `act` is `back` for Esc, `q` or a click on `esc back`, None when the screen wants
    drawing again -- a resize, or `timeout` seconds with no key -- and the key's name otherwise.
    """
    said = ["", *(terminal.styled("  " + part, "dim")
                  for part in terminal.wrap(note, terminal.layout_width() - 2))] if note else []
    room = max(1, terminal.height() - 5 - len(terminal.key_line(keys)) - len(said))
    drawn = [number for number, (row, _) in places.items() if row == here] or [0]
    top = max(0, min(max(top, drawn[-1] - room + 1), drawn[0], len(body) - room))
    shown = body[top:top + room]
    terminal.frame(title, shown + said, keys)     # its first line is the terminal's third
    key = terminal.read_key(timeout)
    if key is None:
        return None, here, None, top
    act, column = key.name, None
    if act == "click":
        place = places.get(top + key.row - 3) if 0 <= key.row - 3 < len(shown) else None
        if place is None:
            back = any((row, item) == (key.row, "esc") and first <= key.col <= last
                       for row, first, last, item in (
                           (4 + len(shown) + len(said) + number, *span)
                           for number, text in enumerate(terminal.key_line(keys))
                           for span in terminal.key_spans(text)))
            return "back" if back else "", here, None, top
        # a row runs its step; on Providers only a click on one of its two acts does
        here, act = place[0], "enter" if place[0][0] == "row" and place[0] != PROVIDERS else ""
        for first, last, number in place[1]:
            if first <= key.col <= last:
                column = number
                act = ("enter" if number < 2 else "less" if key.col <= first + 1
                       else "more" if key.col >= last - 1 else "")
    if act in ("esc", "eof") or key.char in ("q", "Q"):
        return "back", here, column, top
    if terminal.step(key) and rows:
        here = rows[min(max(rows.index(here) + terminal.step(key), 0), len(rows) - 1)]
    return act, here, column, top


@terminal.clicks_its_own
def config_matrix(cfg, keyboard, update_row):
    """The `c` screen read with the keys until Esc or `q`; the config as it left it.

    ↑/↓, k/j and the wheel move between rows and ←/→ between columns, the effort's too.  Enter,
    space or a click flips a mark; Enter or space on an effort steps it up, from its highest
    round to its lowest, and a click on its arrow steps it that way: each change is saved and
    drawn at once.
    Enter or a click on a model's label, left of its marks, opens that model's own screen
    (config_model), and Esc there comes back to its row.  Enter or a click
    on `+ add a model` opens its screen (config_add), and a model added there is the row
    highlighted after it.  On `Providers` ←/→ move between `+ add` and `− remove`, and Enter or
    a click on one runs it (config_add_provider, config_remove_provider); on `Discord` or
    `Update` it gives the terminal back for that row's step, which reads its lines as it always
    has, then takes it again.  On a screen too short
    for every row the part the highlight is on is shown, and what the last key could not do --
    the last worker, a save or a catalog that failed -- has lines of its own under it, whatever
    the height, until the next key.
    """
    here, column, top, note = None, 0, 0, ""
    while True:
        rows = [*(("model", name) for name in config_models(cfg)),
                *(("row", row) for row in CONFIG_ROWS)]
        here = here if here in rows else rows[0]      # the highlight is the row itself
        where = ("label" if here == PROVIDERS else "row" if here[0] == "row" else "effort"
                 if column == 2 else "label" if column < 0 else "mark")
        keys = CONFIG_KEYS[where][0 if terminal.utf8() else 1] + "   esc back"
        body, places = config_body(cfg, update_row, here, column)
        act, here, clicked, top = matrix_key("config", body, places, rows, here, top, note, keys)
        if act is None:
            continue                  # a resize: drawn again at the new size
        note, column = "", column if clicked is None else clicked
        if act == "back":
            return cfg
        if here == ("row", CONFIG_ROWS[0]):
            if act in ("enter", "space"):
                added = config_add(cfg)
                here = ("model", added) if added else here    # the highlight on its new row
        elif here == PROVIDERS:
            if act in ("left", "right"):
                column = 1 if act == "right" else 0
            elif act in ("enter", "space"):
                note = (config_remove_provider(cfg) if column >= 1
                        else config_add_provider(cfg, keyboard))
        elif here[0] == "row":
            if act in ("enter", "space"):
                keyboard.give()       # the step reads lines, on the terminal as it was
                if here[1] == "Discord":
                    config_discord()
                else:
                    config_update(cfg)
                try:
                    cfg = config.load()
                except config.Error as exc:
                    pause(f"config: {exc}")
                    return cfg
                if here[1] == "Update":
                    update_row = _update_value(cfg)
                keyboard.take()
        elif act in ("left", "right"):
            column = min(max(column + (1 if act == "right" else -1), -1), 2)
        elif act in ("enter", "space") and column < 0:
            config_model(cfg, here[1])
            if here[1] not in cfg["models"]:
                here = rows[rows.index(here) + 1]     # removed: the row under it is highlighted
        elif act in ("enter", "space") and column < 2:
            note = config_mark(cfg, here[1], column)
        elif act in ("enter", "space", "less", "more"):     # the effort column
            note = config_effort(cfg, here[1], -1 if act == "less" else 1,
                                 wrap=act in ("enter", "space"))


def _runs(cfg, harness, model, effort=None):
    """The names the config runs that harness's `model` under, at `effort` if one is given."""
    return [name for name, entry in cfg["models"].items() if isinstance(entry, dict)
            and (entry.get("harness"), entry.get("model")) == (harness, model)
            and effort in (None, entry.get("effort"))]


def _add_choices(cfg, picked):
    """The choices of `add a model`'s step after the values `picked`, each (value, the columns
    it shows).

    The harnesses of the providers the config has (config.provider_harnesses), with their
    providers' names; then the models that harness's catalog lists efforts for, as
    config_model_id offers them, each id beside its label where the two differ; then that
    model's efforts.  A model the config runs already, or an effort it runs it at, is marked
    with the names it runs under.
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
                for model in config.catalog(harness) if model["efforts"]]
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
    added at another effort, never at one it runs it at.  Esc or `q` steps back one level, and
    out from the harnesses.  Nothing is typed, so no harness, model or effort the catalog does
    not offer is ever written.  The new model is offered as orchestrator and as worker at
    once, and joins neither default until it is chosen there.
    """
    picked, ats, top, note = [], [0], 0, ""   # (value, texts) of each step chosen; its highlight
    while True:
        try:
            choices = _add_choices(cfg, [value for value, _ in picked])
        except config.Error as exc:
            choices, note = [], f"config: {exc}"
        if not choices and not note:
            note = (f"the {picked[0][0][0]} catalog names no model with its efforts" if picked
                    else "no provider the config has names a harness")
        adding = len(picked) == len(ADD_STEPS) - 1
        keys = ADD_KEYS["add" if adding else "choose"][0 if terminal.utf8() else 1] + "   esc back"
        at = min(ats[-1], max(0, len(choices) - 1))
        body, places = add_body(picked, choices, at)
        said = ["", *(terminal.styled("  " + part, "dim")
                      for part in terminal.wrap(note, terminal.layout_width() - 2))] if note else []
        room = max(1, terminal.height() - 5 - len(terminal.key_line(keys)) - len(said))
        drawn = next((line for line, number in places.items() if number == at), len(body) - 1)
        top = max(0, min(max(top, drawn - room + 1), drawn, len(body) - room))
        shown = body[top:top + room]
        terminal.frame("config · add a model", shown + said, keys)
        key = terminal.read_key()
        if key is None:
            continue                  # a resize: drawn again at the new size
        act, note = key.name, ""
        if act == "click":
            number = places.get(top + key.row - 3) if 0 <= key.row - 3 < len(shown) else None
            if number is not None:
                at, act = number, "enter"
            elif any((4 + len(shown) + len(said) + line, item) == (key.row, "esc")
                     and first <= key.col <= end
                     for line, text in enumerate(terminal.key_line(keys))
                     for first, end, item in terminal.key_spans(text)):
                act = "esc"
        if act == "eof":
            return None
        if act == "esc" or key.char in ("q", "Q"):
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


@terminal.clicks_its_own
def config_add_provider(cfg, keyboard):
    """`+ add` on the Providers row: a provider the shipped default has and the config has not,
    picked from a list, then put in the way it ships, so nothing is typed.

    Its harness, the shipped default's for it, is installed when its program is nowhere to be
    found, then logged in: each its adapter's own verb, run as install.sh runs them, with the
    terminal given back for it and taken again after.  Then its shipped [providers.*] table
    goes in, with the first model its harness's catalog lists efforts for, under the name and
    at the effort the shipped default gives that provider's first model -- `spark`, and the
    effort or the nearest one it takes -- so a `usage_model` in that table names it.  It joins
    neither default until it is chosen there.  Where a model of that name is here already
    nothing is installed or added, since the table would name that model instead.  A verb that
    fails adds nothing, and waits until what it said has been read.  Esc or `q` goes back with
    nothing done.  What to say under the matrix, or "".
    """
    shipped = config.shipped()
    labels = _by_label([name for name in shipped.get("providers") or {}
                        if name not in cfg["providers"]],
                       lambda name: COMPANIES.get(name, NAMES.get(name, name.title())))
    if not labels:
        return "every provider agentkit ships is added"
    keys = ADD_KEYS["add"][0 if terminal.utf8() else 1] + "   esc back"

    def around():     # the screen the list is drawn on, drawn again on a resize
        terminal.frame("config · add a provider", [""] * len(labels), keys)
        return 3
    picked = terminal.choose(list(labels), around=around)
    if picked is None:
        return ""
    name = labels[picked]
    try:
        harness, first = config.provider_harness(shipped, name)
    except config.Error as exc:
        return f"config: {exc}"
    if first in cfg["models"]:
        return f"{picked} adds its model as {first}, and a model has that name; nothing added"
    program = (harness_plugin(harness).update["version"] or [harness])[0]
    keyboard.give()
    failed = ""
    for verb in ("login",) if config.harness_binary(program) else ("install", "login"):
        try:
            code = subprocess.run([str(config.adapter(harness)), verb],
                                  env=config.child_env()).returncode
        except (config.Error, OSError) as exc:
            print(f"{harness}: {exc}")
            code = 1
        if code:
            failed = f"{harness} {verb} did not finish; {picked} is not added"
            pause()
            break
    keyboard.take()
    if failed:
        return failed
    models = [model for model in config.catalog(harness) if model["efforts"]]
    if not models:
        return f"the {harness} catalog names no model with its efforts; {picked} is not added"
    model, before = models[0], copy.deepcopy(cfg)
    cfg["providers"][name] = shipped["providers"][name]
    cfg["models"][first] = {
        "harness": harness, "model": model["id"],
        "effort": _nearest(shipped["models"][first].get("effort"), model["efforts"]),
        "provider": name}
    return _saved(cfg, cfg, before)


@terminal.clicks_its_own
def config_remove_provider(cfg):
    """`− remove` on the Providers row: a provider the config has, picked from a list, then
    `Remove <provider> and its models?` asked under it, `Keep` picked and Esc keeping it.
    config.remove_provider takes its table, its models and their places in [defaults], and
    with its table goes its usage row.  The last provider is refused without asking.  What to
    say under the matrix, or "".
    """
    if len(cfg["providers"]) == 1:
        return "the config needs one provider"
    labels = _by_label(list(cfg["providers"]), lambda name: NAMES.get(name, name.title()))
    title, keys = "config · remove a provider", ADD_KEYS["choose"][0 if terminal.utf8() else 1]

    def listed():     # the screens the two lists are drawn on, drawn again on a resize
        terminal.frame(title, [""] * len(labels), keys + "   esc back")
        return 3
    picked = terminal.choose(list(labels), around=listed)
    if picked is None:
        return ""

    def asked():
        lines = [f"  {line}" for line in terminal.wrap(REMOVE_PROVIDER_ASK.format(picked),
                                                      terminal.layout_width() - 2)]
        terminal.frame(title, [*lines, "", ""], "esc keep")
        return 3 + len(lines)
    if terminal.choose(["Keep", "Remove"], "Keep", around=asked) != "Remove":
        return ""
    before = copy.deepcopy(cfg)
    try:
        config.remove_provider(cfg, labels[picked])
    except config.Error as exc:
        return str(exc)
    return _saved(cfg, cfg, before)


def config_discord():
    """`Discord`: the two secrets, written the way install.sh writes them.

    An empty answer keeps what is there, so one secret can be changed without retyping the
    other; install.sh asks the same way, once, when there is someone to ask.
    """
    tick, cross = terminal.glyph("done"), terminal.glyph("FAIL")
    body = [f"  webhook {tick if _secret_set('discord_webhook') else cross}",
            f"  user id {tick if _secret_set('discord_user_id') else cross}"]
    terminal.frame("config · discord", body, "q back")
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


def _working_sessions(cfg):
    """The sessions whose word is `working` now: an update runs only when there are none."""
    return update.working_sessions(cfg)


def _show_tail(func, *args):
    """Run one update step, showing the last lines of what it said."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        try:
            code = func(*args)
        except config.Error as exc:
            print(f"update: {exc}")
            code = 1
    for line in buf.getvalue().splitlines()[-CONFIG_TAIL:]:
        print(line)
    return code


def config_update(cfg):
    """`Update`: the same `ak update` the shell runs, while nothing is working."""
    terminal.frame("config · update", [], "q back")
    working = _working_sessions(cfg)
    if working:
        pause(f"{len(working)} sessions are working; try when they are done")
        return
    _show_tail(update.main, [])
    pause()


def show_config(dry_run=False, keyboard=None):
    """`c`: every model in one matrix of the defaults and the efforts, then `+ add a model`,
    `Providers`, `Discord` and `Update`, read with the menu's keyboard (config_matrix), so
    nothing is typed.

    Providers, models, the defaults a new seat takes, efforts and the two Discord secrets live
    here, the way they live in ~/.agentkit/config.toml and ~/.agentkit/secrets, so nobody opens
    either file.  A dry run, and a menu with no keyboard to read -- a pipe -- draw it once and read
    nothing.  Returns the config as the screen left it, for the menu to go on with; None when
    there was nothing to show.
    """
    try:
        cfg = config.load()
    except config.Error as exc:
        if keyboard is not None:
            keyboard.give()
        pause(f"config: {exc}")
        return None
    update_row = _update_value(cfg)
    if dry_run or keyboard is None or not keyboard.take():
        terminal.frame("config", config_body(cfg, update_row)[0], "esc back")
        return cfg
    return config_matrix(cfg, keyboard, update_row)


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
                                                     "going": False, "set": 0})
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


def features_body(rows, at=None, column=0):
    """A project's switches' lines, and where its features sit on them: {line: (row, cells)}.

    Every feature once, its name, then a mark under `you` and under `everyone`: `●` on and `○`
    (dim) off.  One on for everyone is on for you too, and one the project does not let you
    switch for yourself has `—` under `you`.  `at` is the highlighted feature's id and `column`
    its cell the keys act on; `cells` are config_body's, for a click.
    """
    room, utf, colour = terminal.layout_width(), terminal.utf8(), terminal.colour_depth()
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
            mark, lead = f" {text} ", (width - 3) // 2
            kind = ("reverse" if at == row["id"] and number == column else
                    "dim" if text in (off, fixed) else None)
            if kind == "reverse" and not colour:
                mark = f"[{text}]"        # with no colour to reverse, brackets say where
            line += ("  " + " " * lead + (terminal.styled(mark, kind) if kind else mark)
                     + " " * (width - lead - 3))
            cells.append((first + 2, first + 1 + width, number))
            first += 2 + width
        places[len(lines)] = (("feature", row["id"]), cells)
        line = line.rstrip()
        lines.append(terminal.highlight(line) if at == row["id"] else line)
    return lines, places


def features_flip(checkout, feature, column):
    """One mark flipped by the project's own `set`, and the row it answers with drawn; what to
    say under the rows, or "".  A failed `set` changes no mark and says why in one line."""
    with _SWITCHES_LOCK:
        entry = _SWITCHES[str(checkout)]
        row = next((row for row in entry["rows"] or () if row["id"] == feature), None)
    if row is None or column == 0 and row.get("you_switchable") is False:
        return ""
    on = not (row.get("everyone") or column == 0 and row.get("you"))
    answer, why = features_run(checkout, "set", feature, FEATURES_HEADS[column],
                               "on" if on else "off")
    if not isinstance(answer, dict) or answer.get("id") != feature:
        return why or "set answered no row"
    with _SWITCHES_LOCK:
        entry["rows"] = [answer if row["id"] == feature else row for row in entry["rows"]]
        entry["set"] = time.monotonic()
    return ""


@terminal.clicks_its_own
def show_features(checkout, dry_run=False):
    """`agentkit · <project>`: its feature switches, flipped with the matrix's keys until Esc.

    The rows are the project's `list` as last answered (`switches`), asked again every TICK
    while the screen is open and drawn within STIR of landing, so the screen never waits on
    it.  ↑/↓ move between features and ←/→ between `you` and `everyone`; Enter, space or a
    click flips a mark by calling the project's `set` at once, and draws the row it answers
    with.  What a `set` could not do is one dim line under the rows, the mark as it was, until
    the next key; a `list` that failed is one too, for as long as the rows drawn are older than
    it.  A dry run draws it once.
    """
    here, column, top, note = None, 0, 0, ""
    keys = FEATURES_KEYS[0 if terminal.utf8() else 1] + "   esc back"
    while True:
        features = switches(checkout, TICK)
        rows = [("feature", row["id"]) for row in features or ()]
        here = here if here in rows else rows[0] if rows else None
        body, places = features_body(features, here[1], column) if features else ([], {})
        said = (_SWITCHES[str(checkout)]["error"] or ("" if features else "no features"
                if features == [] else "asking for its features"))
        if said:
            body.append(terminal.styled("  " + terminal.cut(said, terminal.layout_width() - 2),
                                        "dim"))
        if dry_run:
            terminal.frame(checkout.name, body, "esc back")
            return
        # one line whatever it says, so the rows stay where a click is read against them
        act, here, clicked, top = matrix_key(checkout.name, body, places, rows, here, top,
                                             terminal.cut(note, terminal.layout_width() - 2),
                                             keys, STIR)
        if act is None:
            continue                  # a resize, or a look at whether the answer has landed
        note, column = "", column if clicked is None else clicked
        if act == "back":
            return
        if act in ("left", "right"):
            column = 1 if act == "right" else 0
        elif act in ("enter", "space") and here:
            note = features_flip(checkout, here[1], column)


def info_states():
    """The three state lines as the README prints them: the glyph and the word, padded to
    one column, then what the word means."""
    labels = [terminal.state_text(word) for word, _ in INFO_STATES]
    width = max(terminal.cells(label) for label in labels)
    return [f"{terminal.pad(label, width)}   {why}"
            for label, (_, why) in zip(labels, INFO_STATES)]


def show_info(dry_run=False):
    """`i`: one calm screen -- what agentkit is, the three states, the keys, the worker token's
    date and the build -- and nothing else.  It is read with the keys: it scrolls where it does
    not fit, and Esc, `q` or a click on `esc back` go back.  A dry run draws it and goes on."""
    from . import watch   # here, not at the top: the menu draws without the tick
    note = watch.worker_token_note()
    sections = (("States", info_states()), ("Keys", INFO_KEYS),
                ("Installed", [*([note] if note else []),
                               f"agentkit {installed() or 'build unknown'}"]))

    def body(room):       # wrapped again for every draw, so a resize reflows it
        lines = terminal.wrap("agentkit: you talk to one orchestrator; it works until it is "
                              "done or it needs you.", room)
        for title, rows in sections:
            lines += ["", terminal.styled(title, "accent"),
                      *(f"  {part}" for row in rows for part in terminal.hang(row, room - 2))]
        return lines
    if dry_run:
        terminal.frame("info", body(terminal.layout_width()), "esc back")
    else:
        terminal.scroll("info", body, "esc back")


def move_keys():
    """The key line's first two items while the menu has the keyboard; ASCII without UTF-8."""
    return "↑↓ move   ⏎ open" if terminal.utf8() else "j/k move   enter open"


def pressed(key, drawn, found):
    """What one `terminal.Key` asks of the main screen, in the line menu's own words.

    Enter is the highlighted seat's number, and a click on any line of a seat is that seat's;
    on a project's heading either is that project's checkout, whose switches it opens.
    A click on the key line is the key of the item under it, `⏎ open` being Enter; Esc and a
    keyboard that is gone are `q`; a character is itself; anything else is "", which asks for
    nothing.  `drawn` is the layout on the screen when the key was read, so a click lands where
    he saw, and `found` the seats now, so a seat is opened by the number it has now.
    """
    numbers = {session["name"]: str(number) for number, session in enumerate(found, 1)}

    def opens(name):
        return name if isinstance(name, Path) else numbers.get(name, "")
    if key.name == "click":
        if key.row in drawn["rows"]:
            return opens(drawn["rows"][key.row])
        item = next((item for row, first, last, item in drawn["spans"]
                     if row == key.row and first <= key.col <= last), "")
        if item not in ("⏎", "enter"):
            return item if len(item) == 1 else ""
        key = terminal.Key("enter")
    if key.name == "enter":
        return opens(drawn["cursor"])
    if key.name in ("esc", "eof"):
        return "q"
    return key.char if key.name == "char" else ""


def loop(cfg, client=False, dry_run=False, overlay=False):
    """The menu until `q` or end of input.

    `overlay` is the menu as a tmux popup over a running seat, offering the four keys and
    the numbers.  A number and `n` both hand this client to a session, and the popup has
    to come down for it to be seen, so those two return; `r` and `x` rename and stop this
    session and leave it up, `x` acting on this session wherever the highlight is.  `c` and
    `i` are not offered here.  Read a line at a time, `m` and `k` turn the pages of a list
    longer than the screen, and a number is answered from whichever page is up.

    The main screen is live: the read waits at most TICK seconds, and a wait that ends with
    nothing typed draws again, so the clock, the seat rows, the counts on the top line and the
    usage stay true in front of whoever left it open -- and it ends within STIR of any seat's
    record or the usage cache changing, so a row never says for longer what its bar no longer
    does.  The first draw, one on the clock and one after a key have every seat looked at again
    in a thread (`Live.look`) and wait LOOK_WAIT for it at most; every draw is the records as
    they stand and captures nothing, so no seat's capture holds up a draw.  The first draw's
    meters are the cache's, and the probe that follows it runs in a thread and asks for one
    more draw when it lands.
    Nothing here waits on an adapter, and a key typed during a draw is read by the next wait.

    On a terminal the menu has the keyboard (`terminal.Keyboard`) and there are no lines: a
    key acts the moment it is pressed.  One seat row is highlighted; ↑/↓, k/j and the wheel
    move it and the page up follows it; Enter opens it.  A click on a row opens that seat and
    a click on the key line does what its key does, each once the button is up.  A digit
    waits half a second for a second one, a resize or not, and a key read while it waits is
    kept for after, with the screen it was read on.  The highlight is the seat's name, so it
    stays on its seat whatever comes or goes above it.  A key that does nothing here is let
    go without a word, and every key that does something gives the terminal back before it
    does it -- but `i`, `c` and `x`'s question, which are read with the keys on the screen
    the menu has: `x` on a done seat closes it at once, and on any other asks `Keep` or `Stop`
    under its row, Enter or a click answering and Esc keeping it.
    """
    keys = OVERLAY_KEYS if overlay else KEYS
    actions = ("n", "x", "r") if overlay else ("n", "x", "c", "i")
    page, cursor, ahead, look = 0, None, None, True
    with closing(Live(cfg)) as live, closing(terminal.Keyboard()) as keyboard:
        while True:
            found = orch.listing()
            messages = orch.job_notices()
            if messages:
                keyboard.give()           # a notice waits for its Enter, like any sub-screen
                show_notices(messages)
            drawn = {} if keyboard.take() else None
            own = config.current_session() if overlay else None
            if look:
                live.look(found)          # the clock's or a key's looks, LOOK_WAIT at most
            live.watch()                  # before the draw: a word that moves during it is news
            page, pages = draw(cfg, found, keys if drawn is None else f"{move_keys()}   {keys}",
                               page, cursor, drawn, own, look=False)
            cursor = drawn["cursor"] if drawn else cursor   # the seat he sees highlighted
            live.probe()                  # after the draw, never before it: the cache is enough
            if ahead is not None:
                (key, shown), ahead = ahead, None
            else:
                key, shown = wait_key("> ", TICK, live.reader), drawn
            if key is None:
                # the wait ended on the clock, which looks again, or on news already written down
                look = not live.drain()
                continue
            look = True
            if isinstance(key, terminal.Key):
                order = drawn["order"]
                if terminal.step(key):
                    if order:
                        at = order.index(cursor) + terminal.step(key)
                        cursor = order[min(max(at, 0), len(order) - 1)]
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
                        more = wait_key("", until - time.monotonic())
                    if isinstance(more, terminal.Key) and "0" <= more.char[:1] <= "9":
                        key += more.char
                    elif more is not None:
                        ahead = (more, drawn)     # read early: kept, with the screen it was read on
                if key.isdecimal() and key.isascii() and 1 <= int(key) <= len(found):
                    cursor = found[int(key) - 1]["name"]   # and highlighted when he is back
                elif key != "q" and key not in actions:
                    continue
            if terminal.is_esc(key):
                key = "q"         # Esc leaves the menu, the same as `q`
            elif terminal.is_sequence(key):
                continue          # an arrow key is neither Esc nor a key: draw again, silently
            key = key.lower()
            if key == "q":
                return 0
            seat = own if overlay else cursor
            if key == "x" and isinstance(seat, Path):
                continue          # a heading is no seat to stop
            if key == "x" and drawn is not None and seat in drawn["words"]:
                # the seat it acts on: a done one closes at once, any other is asked under its row
                if drawn["words"][seat] != "done":
                    cursor = seat

                    def around():     # the menu around the question, drawn again on a resize
                        draw(cfg, found, "esc keep", page, cursor, drawn, own, ask=seat,
                             look=False)
                        return drawn["ask"]
                    if terminal.choose(["Keep", "Stop"], "Keep", around=around) != "Stop":
                        continue
                keyboard.give()
                close_seat(seat, dry_run)
                continue
            if key not in ("i", "c"):
                keyboard.give()           # whatever the key opens has the terminal as it was
            if key.isdigit():
                if 1 <= int(key) <= len(found):
                    open_session(cfg, found[int(key) - 1], dry_run)
                    if overlay:
                        return 0
                else:
                    pause(f"no session {key}")
            elif key == "n":
                if new_session(cfg, dry_run) and overlay:
                    return 0
            elif key == "x":
                if overlay:
                    stop_this_session(dry_run)
                else:
                    stop_session(found, dry_run)
            elif key == "r" and overlay:
                rename_this_session(dry_run)
            elif key == "c" and not overlay:
                # read with the keys, too; the looks and probes go on with what it saved
                cfg = live.cfg = show_config(dry_run, keyboard) or cfg
            elif key == "i" and not overlay:
                show_info(dry_run)        # read with the keys, on the screen the menu has
            elif key in ("m", "k") and pages > 1:
                page = (page + (1 if key == "m" else -1)) % pages
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


def main(argv):
    """The menu.  `--overlay` is the popup inside a seat, and never leaves this machine.

    A popup is opened over tmux sessions that are here, so it neither hops to the server the
    way a client's menu does nor runs the maintenance that a menu opening a seat runs: reaping
    runs and retiring seats over a session the user is sitting in is not what `Ctrl-b m` was
    pressed for.
    """
    if command_help.show("attach", argv):
        return 0
    flags = {"--client": False, "--overlay": False, "--dry-run": False}
    for arg in argv:
        if arg not in flags:
            raise config.Error(f"{USAGE}  (got {arg!r})")
        flags[arg] = True
    if not flags["--dry-run"]:
        from . import macbridge
        macbridge.start_background()
    alias = config.server_alias()
    if alias and not (flags["--client"] or flags["--overlay"]):
        return client(alias, flags["--dry-run"])
    from . import watch
    messages = []
    watch.resume_after_boot(config.load(), dry_run=flags["--dry-run"], log=messages.append)
    if not (flags["--dry-run"] or flags["--overlay"]):
        # what `ak orch` does on the way into a seat: gc, and the runs nobody was told about
        orch.maintenance(messages.append)
    show_notices(messages)
    return loop(config.load(), flags["--client"], flags["--dry-run"], flags["--overlay"])
