"""A seat's status bar: what each of its two lines says, and how tmux draws them.

Line one opens with the seat's state as a chip -- `● working`, `! needs you` or `✓ done`, in
dark bold text on that word's colour -- then the seat's name in bold, then `<model>
orchestrates` with the model in its company's colour, then a working seat's tasks bar, as its
menu row draws it.  Line two carries why a seat needs you or is done, the question or the
summary, with the one key at its right end: `Ctrl-b m  menu`, or `Ctrl-b m  x close` once done.

The bar draws on the terminal's own background and foreground and never tmux's green.  The
chips carry their own background, so they read on any terminal; the rest is the terminal's
foreground or ak's dim, which read on a dark one and a light one alike.  tmux cannot say which
a client is, and the tick that writes most bars has no terminal to ask, so a company colour
that a light terminal draws in its mirror tone (a white one) is the terminal's own foreground,
which is that tone wherever the bar is drawn.

The text is data: each write puts it in the session's own options (`@ak_top`, `@ak_why`,
`@ak_key`), and two fixed formats draw them, so nothing a reason says is ever read as a format
and each client cuts the lines to its own width.  Only ak's own tmux server is written to.
"""

from . import config, orch, terminal

HINT = "Ctrl-b m  menu"            # line two's right end: the one key
CLOSE_HINT = "Ctrl-b m  x close"   # ... and a done seat's, which that menu's `x` closes at once
TOP, WHY, KEY = "@ak_top", "@ak_why", "@ak_key"   # line one, line two, and line two's key
INK = "11111b"                     # the chip's dark text, Mocha's crust
DIM = terminal.STATE_STYLES["dim"][2]
# Each line as tmux draws it from those options, cut with one `…` where it would run off the
# client drawing it -- line two's a space short of the key, so the key stays whole on every
# client, a phone's included.  tmux cuts by cells and steps over the styles.  An option is
# drawn as it is and never expanded again, so its doubled `#` is one escape: a second pass
# would halve `##` again and draw `## heading` as `# heading`.
FORMATS = ("#[align=left]#{=/#{e|-:#{client_width},1}/…:" + TOP + "}",
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

    `last` is the seat's last column (`menu.last_column`): a working seat's tasks bar, which
    line one carries, or the reason a seat needs you or is done, which line two does.  Before
    its first word a seat's bar is its name and who orchestrates it, and its title the name.
    """
    top = f" {chip(word)}  " if word else " "
    top += f"#[bold]{orch.tmux_text(name)}#[nobold]"
    if model:
        top += f"  #[fg={colour}]{orch.tmux_text(model)}#[fg=#{DIM}] orchestrates#[default]"
    if word == "working" and last:
        top += f"   {orch.tmux_text(last)}"
    why = f"  {orch.tmux_text(last)}" if word != "working" and last else ""
    key, verb = (CLOSE_HINT if word == "done" else HINT).split("  ", 1)
    title = f"{name} · {word}" if word else name
    return top, why, f"{key}#[fg=#{DIM}]  {verb} #[default]", orch.tmux_text(title)


def dress(name, model):
    """A new seat's bar, before its first word: who is in it.  Never raises."""
    try:
        _write(name, model)
    except Exception:  # noqa: BLE001 - dressing a bar never breaks the seat beneath it
        pass


def redress(session, answer, cfg=None):
    """Write that seat's bar and window title from its row's own values; never raises.

    The one writer: the watch tick, every menu draw and a seat's own hook come through here --
    all call `watch.announce_state` -- so the bar says what the row says: the state function's
    word and reason, and `menu.last_column` over `menu.seat_progress`.  A legacy seat lives on
    the user's own server, where nothing is written.
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
        last = menu.last_column(word, answer.get("reason"), *menu.seat_progress(name))
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
    # the title last, so whoever sees it has the whole bar to read
    for option, value in (*LAYOUT, (TOP, top), (WHY, why), (KEY, key),
                          ("set-titles-string", title)):
        orch.tmux_out("set-option", "-t", f"={name}:", option, value, socket=orch.socket_name())
