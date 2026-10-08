"""A seat's status bar: what each of its two lines says, and how tmux draws them.

Line one opens with the seat's state as a chip -- `● working`, `! needs you` or `✓ done`, in
dark bold text on that word's colour -- then the seat's name in bold, then `<model>
orchestrates` with the model in its company's colour, then a working seat's tasks bar, as its
menu row draws it, as wide as `BARS` lets it be.  Its right end is the owner's other seats on
ak's own server: each that needs you by name, a click away, then how many others are working
and done.  Where they do not fit beside the left part the bar narrows, then the names fold into
a count, then only the count of those that need you stays, and only then is the left part cut.
Line two carries why a seat needs you or is done, the question or the summary, or a working
seat's live runs (`live`), with the one key at its right end: `Ctrl-b m  menu`, or `Ctrl-b m
x close` once done.

The bar draws on the terminal's own background and foreground and never tmux's green.  The
chips and the tasks bar carry their own background, so they read on any terminal; the rest is
the terminal's foreground or ak's dim, which read on a dark one and a light one alike.  tmux
cannot say which a client is, and the tick that writes most bars has no terminal to ask, so a
company colour that a light terminal draws in its mirror tone (a white one) is the terminal's
own foreground, which is that tone wherever the bar is drawn.

The text is data: each write puts it in the session's own options (`@ak_top` at each bar
width, `@ak_seats`, `@ak_fold`, `@ak_need`, `@ak_why` and its folded versions, `@ak_key`), and
two fixed formats draw them, so nothing a reason says is ever read as a format and each client
picks what fits its own width.  Only ak's own tmux server is written to.

A name is drawn in a `range=right`, which nothing else on a bar draws and no key of tmux's own
is bound to, and the one key ak binds there is a click (CLICK): `@ak_hit` finds the seat whose
name is under the pointer and the click switches that client to it.  The wheel and every other
click over a name do what they do anywhere else on the bar, which is nothing.
"""

import fcntl
import time

from . import config, menu, orch, terminal

HINT = "Ctrl-b m  menu"            # line two's right end: the one key
CLOSE_HINT = "Ctrl-b m  x close"   # ... and a done seat's, which that menu's `x` closes at once
TOP, WHY, KEY = "@ak_top", "@ak_why", "@ak_key"   # line one, line two, and line two's key
# line one's right end: the other seats, their names folded, and who needs you alone
SEATS, FOLD, NEED = "@ak_seats", "@ak_fold", "@ak_need"
HIT = "@ak_hit"   # the session id of the name under the pointer, or nothing
# Where a name is: its cells counted from the client's right edge, the right end's own edge.
AT = "#{e|-:#{client_width},#{mouse_x}}"
CLICK = ("bind-key", "-n", "MouseDown1StatusRight", "if-shell", "-F", "#{E:" + HIT + "}",
         # a target is not a format, and the command run-shell -C runs is
         "run-shell -C \"switch-client -t '#{E:" + HIT + "}'\"")
INK = terminal.BAR_TONES["ink"][0]  # the chip's dark text, Mocha's crust
CELLS = 36                         # a working seat's tasks bar, its ticks there up to eighteen tasks
BARS = (CELLS, 2 * CELLS // 3, CELLS // 3)   # ... and narrower, where line one is short of room
TOPS = (TOP, *(f"{TOP}{n}" for n in range(1, len(BARS))))   # line one's left part at each
DIM = terminal.STATE_STYLES["dim"][2]
# Line two, then each version of it with one more of what runs do (`menu.DOING`) folded into its
# count, and last the counts alone (`live`).
WHYS = (WHY, *(f"{WHY}{n}" for n in range(1, len(menu.DOING) + 2)))


def _cut(option, room):
    """`option` cut with one `…` to `room` cells -- to one at the least, since tmux reads a limit
    of 0 as none and a negative one as the line's tail.  Only a text that does not fit goes
    through it: tmux marks one that fills its room to the cell cut too, as it drops the styles
    after its last cell."""
    return "#{=/#{?#{e|>:" + room + ",0}," + room + ",1}/…:" + option + "}"


def _line_one():
    """The widest tasks bar beside the other seats by name that fits the client, else beside
    them folded, else beside who needs you alone, each drawn whole; else the narrowest cut a
    space short of who needs you."""
    room = "#{e|-:#{client_width},#{e|+:#{w:" + NEED + "},2}}"
    found = "#[align=left]" + _cut(TOPS[-1], room) + " #[align=right]#{" + NEED + "}"
    for left, right in reversed([(left, right) for right in (SEATS, FOLD, NEED) for left in TOPS]):
        fits = "#{e|<=:#{e|+:#{w:" + left + "},#{e|+:#{w:" + right + "},2}},#{client_width}}"
        whole = "#[align=left]#{" + left + "} #[align=right]#{" + right + "}"
        found = "#{?" + fits + "," + whole + "," + found + "}"
    return found


def _first_fitting(options, room):
    """The first of `options` whose text fits in `room` cells, drawn whole, else the last cut
    to it."""
    found = _cut(options[-1], room)
    for option in reversed(options):
        found = "#{?#{e|<=:#{w:" + option + "}," + room + "},#{" + option + "}," + found + "}"
    return found


# Each line as tmux draws it from those options, cut with one `…` where it would run off the
# client drawing it -- line one's (`_line_one`) beside the other seats; line two's the first
# version that fits a space short of the key, so the key stays whole on every client, a phone's
# included.  tmux cuts by cells and steps over the styles.  An option is drawn as it is and never
# expanded again, so its doubled `#` is one escape: a second pass would halve `##` again and
# draw `## heading` as `# heading`.
FORMATS = (_line_one(),
           "#[align=left]" + _first_fitting(WHYS, "#{e|-:#{client_width},#{e|+:#{w:" + KEY + "},2}}")
           + " #[align=right]#{" + KEY + "}")
# What every write sets beside the text, so a seat dressed before this layout came has it too:
# its two lines among them.  tmux resizes a pane only when the height changes, so a seat's
# pane changes size once -- when it is dressed, or a seat dressed with one line at its first
# write since -- and never later.
LAYOUT = (("set-titles", "on"), ("status", "2"), ("status-style", "default"),
          ("status-format[0]", FORMATS[0]), ("status-format[1]", FORMATS[1]))


def company(cfg, model):
    """The colour `model`'s company is drawn in, as on its usage bar (`menu.model_colour`), for
    tmux."""
    return tone(menu.model_colour(cfg, model))


def tone(kind):
    """A colour as `terminal.styled` takes one -- a kind, `#RRGGBB` or None for none -- for tmux.

    A light grey is `default`, the terminal's own foreground: the colour itself on a dark
    terminal, and on a light one its mirror tone, as the usage rows draw it there.
    """
    if not kind:
        return "default"
    rgb = kind[1:] if kind.startswith("#") else terminal.STATE_STYLES[terminal.KINDS.get(kind,
                                                                                         kind)][2]
    return "default" if terminal.light_grey(rgb) else f"#{rgb}"


def chip(word):
    """The state as a chip: `● working` in dark bold text on the word's colour."""
    rgb = "#" + terminal.STATE_STYLES[word][2]
    left, right = ("▐", "▌") if terminal.utf8() else ("", "")
    said = orch.tmux_text(terminal.state_text(word))
    return (f"#[fg={rgb}]{left}#[fg=#{INK},bg={rgb},bold]{said}"
            f"#[default]#[fg={rgb}]{right}#[default]")


def lines(name, model, colour, word=None, last=""):
    """(line one, line two, its key, the window title): the seat's bar, as tmux text.

    `last` is the seat's last column (`menu.last_column`): a working seat's tasks bar, tmux text
    already, or its place in the landing line, which line one carries, or the reason a seat
    needs you or is done, which line two does; a sentence is made text here.  Before its first
    word a seat's bar is its name and who orchestrates it, and its title the name.
    """
    top = f" {chip(word)}  " if word else " "
    top += f"#[bold]{orch.tmux_text(name)}#[nobold]"
    if model:
        top += f"  #[fg={colour}]{orch.tmux_text(model)}#[fg=#{DIM}] orchestrates#[default]"
    if word == "working" and last:
        top += f"   {last if menu.tasks_bar(word, last) else orch.tmux_text(last)}"
    why = f"  {orch.tmux_text(last)}" if word != "working" and last else ""
    key, verb = (CLOSE_HINT if word == "done" else HINT).split("  ", 1)
    title = f"{name} · {word}" if word else name
    # tmux reads a title as a time too, unlike the bar's options: its `%` doubles as well
    return (top, why, f"{key}#[fg=#{DIM}]  {verb} #[default]",
            orch.tmux_text(title).replace("%", "%%"))


def live(runs, cfg, now):
    """Line two of a working seat: its live runs (`menu.seat_runs`), as one version for each of
    `WHYS`, the least folded first, each a list of (text, colour, bold), the text plain on one
    line (`terminal.plain`), the colour as `terminal.styled` takes one, or None.  The highlighted
    row of the menu draws the same (`menu.live_line`).

    A run reads `gh2 ■■□□ opus reviewing · round 2 of 3 · 11m`: its task id in bold, red on its
    last round; a cell for each step of a round, dim for those it passed, the current one in the
    colour of the model doing it, hollow for those to come; that model (`menu.DOING`) in its
    company's colour; what it is doing; its round once past the first; how long it has been on
    this step.  Runs go in the order a round does what they do.  More than two doing one thing
    are one count, `landing 8 · longest 2h`, and so are the runs queued for a slot, `waiting 2`.
    Each next version folds one more into its count, the last first, and the last drops the
    counts' times, so a line short of room folds whole runs into counts before anything is cut.
    """
    full, hollow = ("■", "□") if terminal.utf8() else ("#", "-")
    doings, steps, dim = list(menu.DOING), list(menu.FILLS), "dim"
    group = {doing: [run for run in runs if run["doing"] == doing]
             for doing in (*doings, "waiting")}

    def age(found):
        ages = [now - run["since"] for run in found if type(run["since"]) in (int, float)]
        return terminal.format_age(max(ages)) if ages else ""

    def one(run):
        at, model = steps.index(run["step"]), run["model"]
        colour = menu.model_colour(cfg, model) if model else None
        last = bool(run["rounds"]) and run["round"] >= run["rounds"]
        parts = [(run["task"], "FAIL" if last else None, True), (" ", None, False),
                 (full * at, dim, False), (full, colour, False),
                 (hollow * (len(steps) - 1 - at), dim, False), (" ", None, False)]
        if model:
            parts += [(model, colour, False), (" ", None, False)]
        said = ([f"round {run['round']}" + (f" of {run['rounds']}" if run["rounds"] else "")]
                if run["round"] > 1 else []) + [part for part in (age([run]),) if part]
        return [*parts, (run["doing"], None, False),
                *([(" · " + " · ".join(said), dim, False)] if said else [])]

    def count(doing, timed):
        found, longest = group[doing], age(group[doing])
        return [(f"{doing} {len(found)}", None, False),
                *([(f" · {'longest ' if len(found) > 1 else ''}{longest}", dim, False)]
                  if timed and longest and doing in menu.DOING else [])]

    versions = []
    for folded in range(len(WHYS)):
        shown, timed = [], folded <= len(doings)
        for at, doing in enumerate(doings):
            if len(group[doing]) > 2 or (group[doing] and at >= len(doings) - folded):
                shown.append(count(doing, timed))
            else:
                shown += [one(run) for run in group[doing]]
        if group["waiting"]:
            shown.append(count("waiting", timed))
        # a task's file and a model may be named anything: each text is drawn as text, on one line
        versions.append([(terminal.plain(text, spaced=True), colour, bold)
                         for n, said in enumerate(shown)
                         for text, colour, bold in ([("   ", None, False)] if n else []) + said])
    return versions


def seats():
    """(session id, name, word) of every seat on ak's own server, the word the one it last
    announced: what each bar's right end counts.  A session under a name no seat can have
    (`orch.session_name`) is no seat, so every name drawn is the plain ASCII a seat's is, whose
    cells `others` counts as tmux draws them."""
    from . import watch   # here, not at the top: the watch announces seats, which write this bar
    rc, out = orch.tmux_out("list-sessions", "-F", "#{session_id}\t#{session_name}",
                            socket=orch.socket_name())
    found = []
    for line in out.splitlines() if rc == 0 else ():
        sid, _, name = line.partition("\t")
        if sid.startswith("$") and name and orch.session_name(name) == name:
            found.append((sid, name, watch.seat_read(name).get("word")))
    return found


def others(found, name):
    """(by name, folded, needing, hit): the right end of `name`'s line one, from `seats()`.

    Each other seat that needs you is `! <name> needs you` in that word's colour; folded, they
    are `! 2 need you`, which is all `needing` says.  `● N working` and `✓ N done` follow, each
    only when it is not zero.  A seat never counts itself, and a session that has announced no
    word -- a seat being dressed, or no seat at all -- is not counted.  The right end is drawn
    flush against the client's right edge, so each name's cells from that edge are the same on
    every client, and `hit` is the format that turns where the pointer is into that name's
    session id.
    """
    words = [word for _, seat, word in found if seat != name]
    needs = [(sid, seat) for sid, seat, word in found if seat != name and word == "needs you"]
    mark = terminal.state_glyph("needs you")
    counts = [(None, word, f"{terminal.state_glyph(word)} {words.count(word)} {word}")
              for word in ("working", "done") if word in words]
    named = [(sid, "needs you", f"{mark} {seat} needs you") for sid, seat in needs] + counts
    needing = ([(None, "needs you", f"{mark} {len(needs)} "
                                    f"{'needs' if len(needs) == 1 else 'need'} you")]
               if needs else [])
    folded = needing + counts
    hit, start, edge = "", 0, sum(terminal.cells(said) + 3 for *_, said in named) - 2
    for sid, _, said in named:
        end = start + terminal.cells(said)
        if sid:
            hit += (f"#{{?#{{&&:#{{e|>:{AT},{edge - end}}},#{{e|<=:{AT},{edge - start}}}}},"
                    f"{sid},}}")
        start = end + 3
    return _drawn(named), _drawn(folded), _drawn(needing), hit


def _drawn(parts):
    """Each part in its word's colour, needs you's in bold as its chip is, and a name in the
    range its click is bound to; three spaces between them and one after."""
    return "   ".join(
        ("#[range=right]" if sid else "") + f"#[fg=#{terminal.STATE_STYLES[word][2]}"
        f"{',bold' if word == 'needs you' else ''}]{orch.tmux_text(said)}#[default]"
        + ("#[norange]" if sid else "") for sid, word, said in parts) + (" " if parts else "")


def retell(session):
    """That seat's word or name changed, or the seat went: every seat's bar counts it again now,
    not at the next tick, which rewrites each from what it finds anyway.  Never raises."""
    try:
        if orch.on_own_server(session):
            _tell()
    except Exception:  # noqa: BLE001 - another seat's bar never breaks this seat's announcing
        pass


def _tell(only=None, own=()):
    """Write line one's right end on that seat's bar, or on every seat's, then the caller's
    `own` options, each (target, option, text), and bind its click: one tmux call however many
    seats there are, where a call per seat made every start and every changed word wait on each
    open seat.

    One lock across every bar's reading and writing: the seat words are read under it and
    written before it is let go, so whoever writes last has read last, and an older reading
    never lands on a bar after a newer word.  The click is bound with every write, so a server
    that was up before the names came gets it with the first bar that draws one.

    A list longer than a tmux message is asked by itself where it stands, as it always was, and
    where tmux refuses it each of its options is told alone, a long one in pieces
    (`orch.tmux_option`): a bar never keeps what was said before because what is said now is
    long.
    """
    config.ensure_dirs()
    with (config.STATE / "statusbar.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        found, told = seats(), []
        for _, name, _ in found:
            if only in (None, name):
                named, folded, needing, hit = others(found, name)
                # One command list, which tmux runs whole before it reads another click: no
                # click lands between the names a bar draws and the lookup that finds them.
                # Told one by one, the lookup is emptied first, so a click finds no seat until
                # the names it is for are drawn.
                target = f"={name}:"   # that session alone, as `_write` says
                told.append((["set-option", "-t", target, SEATS, named, ";",
                              "set-option", "-t", target, FOLD, folded, ";",
                              "set-option", "-t", target, NEED, needing, ";",
                              "set-option", "-t", target, HIT, hit],
                             [(target, HIT, ""), (target, SEATS, named), (target, FOLD, folded),
                              (target, NEED, needing), (target, HIT, hit)]))
        told += [(["set-option", "-t", target, option, orch.tmux_literal(text)],
                  [(target, option, text)]) for target, option, text in own]
        socket, fitting = orch.socket_name(), []
        for words, options in told:
            if sum(len(word.encode()) + 1 for word in words) <= orch.TMUX_MESSAGE:
                fitting.append(words)
                continue
            orch.tmux_lists(fitting, socket=socket)
            fitting = []
            if orch.tmux_lists([words], socket=socket)[0] != 0:
                for option in options:   # to the first tmux refuses, as a list stops there
                    if orch.tmux_option(*option, socket=socket)[0] != 0:
                        break
        # a seat gone since it was listed fails its own list and no other's (`orch.tmux_lists`)
        orch.tmux_lists([*fitting, CLICK], socket=socket)


def dress(name, model):
    """A new seat's bar, before its first word: who is in it; and every other seat's bar counts
    it again, since a seat opened under a name that needed you needs you still.  Never raises."""
    try:
        _write(name, model, every=True)
    except Exception:  # noqa: BLE001 - dressing a bar never breaks the seat beneath it
        pass


def redress(session, answer, cfg=None, records=None):
    """Write that seat's bar and window title from its row's own values; never raises.

    The one writer: the watch tick, every menu draw and a seat's own hook come through here --
    all call `watch.announce_state` -- so the bar says what the row says: the state function's
    word and reason, and `menu.last_column` over `menu.seat_progress` and `menu.seat_runs`, from
    the caller's run `records` where it has them.  A legacy seat lives on the user's own server,
    where nothing is written.
    """
    try:
        if not orch.on_own_server(session):
            return
        name = session["name"]
        cfg = config.load() if cfg is None else cfg
        try:
            selection = config.load_session(cfg, name, required=False)
        except config.Error:
            selection = None
        word = answer.get("word")
        runs = menu.seat_runs(name, records) if word == "working" else []
        progress = menu.seat_progress(name)
        # each in its own cells and never more (`narrow`), so line one picks by the width it set
        lasts = [menu.last_column(word, answer.get("reason"), *progress, runs, cells,
                                  narrow=True, tmux=True) for cells in BARS]
        _write(name, selection["orchestrator"] if selection else None, word, lasts, cfg,
               live(runs, cfg, time.time()) if runs else ())
    except Exception:  # noqa: BLE001 - dressing a bar never breaks the draw or the tick beneath it
        pass


def _write(name, model, word=None, lasts=None, cfg=None, versions=(), every=False):
    """Set the bar on that seat's own session, never the server's or another seat's: a seat gone
    mid-draw, or a draw under test, fails its `set-option` quietly.  `={name}:` is that session
    alone: tmux reads a plain name as the start of any session's, so a gone `new-1` would write
    `new-10`'s bar, and it refuses `=name` without the colon as a target.  `lasts` are the
    seat's last column at each of `BARS`, and `versions` a working seat's line two (`live`),
    else every version of it is the reason.  `every` has each other seat's bar count this one
    again, in the same call."""
    cfg = config.load() if cfg is None else cfg
    lasts, colour = lasts or [""] * len(BARS), company(cfg, model)
    tops = [lines(name, model, colour, word, last)[0] for last in lasts]
    _, why, key, title = lines(name, model, colour, word, lasts[0])
    whys = ([why] * len(WHYS) if not versions else
            ["  " + "".join(f"#[fg={tone(colour)},{'bold' if bold else 'nobold'}]"
                            f"{orch.tmux_text(said)}" for said, colour, bold in version)
             + "#[default]"
             for version in versions])
    # With line one's right end, in one call, where a call per option made a seat's start wait
    # seconds on a busy host; another only where a long question's reason, drawn in every
    # width, would take it past what tmux takes in one.  The title last, so whoever sees it
    # has the whole bar to read.  Each value whole: a question may end in the `;` tmux would
    # take for the end of its command (`_tell`).
    _tell(None if every else name,
          [(f"={name}:", option, value)
           for option, value in (*LAYOUT, *zip(TOPS, tops), *zip(WHYS, whys), (KEY, key),
                                 ("set-titles-string", title))])
