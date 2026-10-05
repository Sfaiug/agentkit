"""A seat's status bar: what each of its two lines says, and how tmux draws them.

Line one opens with the seat's state as a chip -- `● working`, `! needs you` or `✓ done`, in
dark bold text on that word's colour -- then the seat's name in bold, then `<model>
orchestrates` with the model in its company's colour, then a working seat's tasks bar, as its
menu row draws it, in CELLS cells.  Its right end is the owner's other seats on ak's own
server: each that needs you by name, a click away, then how many others are working and done;
where they do not fit beside the left part, the names fold into a count first, and only then is
the left part cut.  Line two carries why a seat needs you or is done, the question or the
summary, with the one key at its right end: `Ctrl-b m  menu`, or `Ctrl-b m  x close` once done.

The bar draws on the terminal's own background and foreground and never tmux's green.  The
chips and the tasks bar carry their own background, so they read on any terminal; the rest is
the terminal's foreground or ak's dim, which read on a dark one and a light one alike.  tmux
cannot say which a client is, and the tick that writes most bars has no terminal to ask, so a
company colour that a light terminal draws in its mirror tone (a white one) is the terminal's
own foreground, which is that tone wherever the bar is drawn.

The text is data: each write puts it in the session's own options (`@ak_top`, `@ak_seats`,
`@ak_fold`, `@ak_why`, `@ak_key`), and two fixed formats draw them, so nothing a reason says
is ever read as a format and each client cuts the lines to its own width.  Only ak's own tmux
server is written to.

A name is drawn in a `range=right`, which nothing else on a bar draws and no key of tmux's own
is bound to, and the one key ak binds there is a click (CLICK): `@ak_hit` finds the seat whose
name is under the pointer and the click switches that client to it.  The wheel and every other
click over a name do what they do anywhere else on the bar, which is nothing.
"""

import fcntl

from . import config, orch, terminal

HINT = "Ctrl-b m  menu"            # line two's right end: the one key
CLOSE_HINT = "Ctrl-b m  x close"   # ... and a done seat's, which that menu's `x` closes at once
TOP, WHY, KEY = "@ak_top", "@ak_why", "@ak_key"   # line one, line two, and line two's key
SEATS, FOLD = "@ak_seats", "@ak_fold"   # line one's right end: the other seats, names folded
HIT = "@ak_hit"   # the session id of the name under the pointer, or nothing
# Where a name is: its cells counted from the client's right edge, the right end's own edge.
AT = "#{e|-:#{client_width},#{mouse_x}}"
CLICK = ("bind-key", "-n", "MouseDown1StatusRight", "if-shell", "-F", "#{E:" + HIT + "}",
         # a target is not a format, and the command run-shell -C runs is
         "run-shell -C \"switch-client -t '#{E:" + HIT + "}'\"")
INK = terminal.BAR_TONES["ink"][0]  # the chip's dark text, Mocha's crust
CELLS = 24                         # a working seat's tasks bar, its ticks there up to twelve tasks
DIM = terminal.STATE_STYLES["dim"][2]


def _beside(right):
    """Line one with `right` at its end, the left part cut a space short of it -- to one cell
    at the least, since tmux reads a limit of 0 as none and a negative one as the line's tail."""
    room = "#{e|-:#{client_width},#{e|+:#{w:" + right + "},2}}"
    return ("#[align=left]#{=/#{?#{e|>:" + room + ",0}," + room + ",1}/…:" + TOP + "} "
            "#[align=right]#{" + right + "}")


# Each line as tmux draws it from those options, cut with one `…` where it would run off the
# client drawing it -- line one's beside the other seats, by name where the whole left part
# still fits and folded where it does not; line two's a space short of the key, so the key
# stays whole on every client, a phone's included.  tmux cuts by cells and steps over the
# styles.  An option is drawn as it is and never expanded again, so its doubled `#` is one
# escape: a second pass would halve `##` again and draw `## heading` as `# heading`.
FORMATS = ("#{?#{e|<=:#{e|+:#{w:" + TOP + "},#{e|+:#{w:" + SEATS + "},2}},#{client_width}},"
           + _beside(SEATS) + "," + _beside(FOLD) + "}",
           "#[align=left]#{=/#{e|-:#{client_width},#{e|+:#{w:" + KEY + "},2}}/…:" + WHY + "} "
           "#[align=right]#{" + KEY + "}")
# What every write sets beside the text, so a seat dressed before this layout came has it too:
# its two lines among them.  tmux resizes a pane only when the height changes, so a seat's
# pane changes size once -- when it is dressed, or a seat dressed with one line at its first
# write since -- and never later.
LAYOUT = (("set-titles", "on"), ("status", "2"), ("status-style", "default"),
          ("status-format[0]", FORMATS[0]), ("status-format[1]", FORMATS[1]))


def company(cfg, model):
    """The colour `model`'s company is drawn in, as on its usage bar (`menu.colour`), for tmux.

    A light grey is `default`, the terminal's own foreground: the colour itself on a dark
    terminal, and on a light one its mirror tone, as the usage rows draw it there.
    """
    from . import menu   # here, not at the top: the menu draws seats, which write this bar
    entry = cfg["models"].get(model) if model else None
    own = menu.colour(cfg, entry.get("provider") if isinstance(entry, dict) else None)
    rgb = own[1:] if own.startswith("#") else terminal.STATE_STYLES[terminal.KINDS[own]][2]
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
    from . import menu   # here, not at the top: the menu draws seats, which write this bar
    if word == "working" and last:
        top += f"   {last if menu.tasks_bar(word, last) else orch.tmux_text(last)}"
    why = f"  {orch.tmux_text(last)}" if word != "working" and last else ""
    key, verb = (CLOSE_HINT if word == "done" else HINT).split("  ", 1)
    title = f"{name} · {word}" if word else name
    # tmux reads a title as a time too, unlike the bar's options: its `%` doubles as well
    return (top, why, f"{key}#[fg=#{DIM}]  {verb} #[default]",
            orch.tmux_text(title).replace("%", "%%"))


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
    """(by name, folded, hit): the right end of `name`'s line one, from `seats()`.

    Each other seat that needs you is `! <name> needs you` in that word's colour; folded, they
    are `! 2 need you`.  `● N working` and `✓ N done` follow, each only when it is not zero.  A
    seat never counts itself, and a session that has announced no word -- a seat being
    dressed, or no seat at all -- is not counted.  The right end is drawn flush against the
    client's right edge, so each name's cells from that edge are the same on every client, and
    `hit` is the format that turns where the pointer is into that name's session id.
    """
    words = [word for _, seat, word in found if seat != name]
    needs = [(sid, seat) for sid, seat, word in found if seat != name and word == "needs you"]
    mark = terminal.state_glyph("needs you")
    counts = [(None, word, f"{terminal.state_glyph(word)} {words.count(word)} {word}")
              for word in ("working", "done") if word in words]
    named = [(sid, "needs you", f"{mark} {seat} needs you") for sid, seat in needs] + counts
    folded = ([(None, "needs you", f"{mark} {len(needs)} "
                                   f"{'needs' if len(needs) == 1 else 'need'} you")]
              if needs else []) + counts
    hit, start, edge = "", 0, sum(terminal.cells(said) + 3 for *_, said in named) - 2
    for sid, _, said in named:
        end = start + terminal.cells(said)
        if sid:
            hit += (f"#{{?#{{&&:#{{e|>:{AT},{edge - end}}},#{{e|<=:{AT},{edge - start}}}}},"
                    f"{sid},}}")
        start = end + 3
    return _drawn(named), _drawn(folded), hit


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


def _tell(only=None):
    """Write line one's right end on that seat's bar, or on every seat's, and bind its click.

    One lock across every bar's reading and writing: the seat words are read under it and
    written before it is let go, so whoever writes last has read last, and an older reading
    never lands on a bar after a newer word.  The click is bound with every write, so a server
    that was up before the names came gets it with the first bar that draws one.
    """
    config.ensure_dirs()
    with (config.STATE / "statusbar.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        found = seats()
        for _, name, _ in found:
            if only in (None, name):
                named, folded, hit = others(found, name)
                # One command list, which tmux runs whole before it reads another click: no
                # click lands between the names a bar draws and the lookup that finds them.
                target = f"={name}:"   # that session alone, as `_write` says
                orch.tmux_out("set-option", "-t", target, SEATS, named, ";",
                              "set-option", "-t", target, FOLD, folded, ";",
                              "set-option", "-t", target, HIT, hit, socket=orch.socket_name())
    orch.tmux_out(*CLICK, socket=orch.socket_name())


def dress(name, model):
    """A new seat's bar, before its first word: who is in it; and every other seat's bar counts
    it again, since a seat opened under a name that needed you needs you still.  Never raises."""
    try:
        _write(name, model)
        _tell()
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
        from . import menu   # here, not at the top: the menu draws seats, which write this bar
        name = session["name"]
        cfg = config.load() if cfg is None else cfg
        try:
            selection = config.load_session(cfg, name, required=False)
        except config.Error:
            selection = None
        word = answer.get("word")
        last = menu.last_column(word, answer.get("reason"), *menu.seat_progress(name),
                                menu.seat_runs(name, records) if word == "working" else (),
                                CELLS, tmux=True)
        _write(name, selection["orchestrator"] if selection else None, word, last, cfg)
    except Exception:  # noqa: BLE001 - dressing a bar never breaks the draw or the tick beneath it
        pass


def _write(name, model, word=None, last="", cfg=None):
    """Set the bar on that seat's own session, never the server's or another seat's: a seat gone
    mid-draw, or a draw under test, fails its `set-option` quietly.  `={name}:` is that session
    alone: tmux reads a plain name as the start of any session's, so a gone `new-1` would write
    `new-10`'s bar, and it refuses `=name` without the colon as a target."""
    cfg = config.load() if cfg is None else cfg
    top, why, key, title = lines(name, model, company(cfg, model), word, last)
    _tell(name)
    # the title last, so whoever sees it has the whole bar to read
    for option, value in (*LAYOUT, (TOP, top), (WHY, why), (KEY, key),
                          ("set-titles-string", title)):
        orch.tmux_out("set-option", "-t", f"={name}:", option, value, socket=orch.socket_name())
