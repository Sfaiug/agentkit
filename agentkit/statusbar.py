"""A seat's status bar: what each of its two lines says, and how tmux draws them.

The bar is the seat's row on the `ak` screen with the line under it always open.  Line one is
its state as a chip -- its glyph and word on its colour in the text that reads on it, bold for
`! needs you` (`chip`) -- then the seat's name in bold, then its model
and orchestrator effort, dim, then its progress line, as its menu row draws it, as wide as `BARS`
lets it be.  Its right end, while another seat on ak's own server needs you, says so in its yellow,
`! 2 other seats need you`, a click away from the first of them; where it does not fit beside
the left part the line narrows, then it folds to `! 2 need you`, and only then is the left part
cut.  Line two shows what the seat needs you for where its chat cannot: an expired login, a
parked run, a failed move.  Its question is the chat's last message or card, so there line two
is who builds and who reviews, and each task in flight as its squares
(`whys`), with the one key at its right end, `Ctrl-b m  menu`, whatever the seat's word: the
bar is in the seat, where `x` is a letter typed.  It never moves: the seat is where the owner reads and types.

The bar draws on the terminal's own background and foreground and never tmux's green.  The
`needs you` chip carries its own background, so it reads on any terminal; the rest is
the terminal's foreground, ak's dim or a state's colour, which read on a dark one and a light
one alike: tmux cannot say which a client is, and the tick that writes most bars has no
terminal to ask.

The text is data: each write puts it in the session's own options (`@ak_top` at each bar
width, `@ak_need` and `@ak_fold`, `@ak_why` and its folded versions, `@ak_key`), and
two fixed formats draw them, so nothing a reason says is ever read as a format and each client
picks what fits its own width.  Only ak's own tmux server is written to.

What a bar shows is named on the bar: each write sets a digest of what it told (`TOLD`, and
`TOLD_END` for the right end, which `retell` tells apart), and one that would tell the same is
left out (`_tell`).

The right end is drawn in a `range=right`, which nothing else on a bar draws and no key of
tmux's own is bound to, and the one key ak binds there is a click (CLICK): `@ak_hit` is the
seat it leads to while the pointer is on it, and the click switches that client there.  The
wheel and every other click over it do what they do anywhere else on the bar, which is nothing.
"""

import fcntl
import hashlib
import os

from . import config, look, menu, orch, terminal, update

HINT = "Ctrl-b m  menu"            # line two's right end: the one key
TOP, WHY, KEY = "@ak_top", "@ak_why", "@ak_key"   # line one, line two, and line two's key
NEED, FOLD = "@ak_need", "@ak_fold"   # line one's right end: how many other seats need you,
                                      # and the same short, where it would cut this seat's name
HIT = "@ak_hit"   # the session id the right end leads to while the pointer is on it, or nothing
TOLD, TOLD_END = "@ak_told", "@ak_told_end"   # a digest of its own options, of its right end
# Where the pointer is: its cells counted from the client's right edge, the right end's own edge.
AT = "#{e|-:#{client_width},#{mouse_x}}"
CLICK = ("bind-key", "-n", "MouseDown1StatusRight", "if-shell", "-F", "#{E:" + HIT + "}",
         # a target is not a format, and the command run-shell -C runs is
         "run-shell -C \"switch-client -t '#{E:" + HIT + "}'\"")
CELLS = 36                         # a working seat's progress line and its count
BARS = (CELLS, 2 * CELLS // 3, CELLS // 3)   # ... and narrower, where line one is short of room
TOPS = (TOP, *(f"{TOP}{n}" for n in range(1, len(BARS))))   # line one's left part at each
DIM = terminal.tmux_colour("dim")
# Line two: who builds and reviews and every task's squares, then the squares cut to six, then
# the squares alone, then cut to six, then to one (`whys`).
WHYS = (WHY, *(f"{WHY}{n}" for n in range(1, 5)))


def _cut(option, room):
    """`option` cut with one `…` to `room` cells -- to one at the least, since tmux reads a limit
    of 0 as none and a negative one as the line's tail.  Only a text that does not fit goes
    through it: tmux marks one that fills its room to the cell cut too, as it drops the styles
    after its last cell."""
    return "#{=/#{?#{e|>:" + room + ",0}," + room + ",1}/…:" + option + "}"


def _line_one():
    """The widest progress line beside who else needs you that fits the client, drawn whole,
    then beside its short count; else the narrowest cut a space short of that."""
    room = "#{e|-:#{client_width},#{e|+:#{w:" + FOLD + "},2}}"
    found = "#[align=left]" + _cut(TOPS[-1], room) + " #[align=right]#{" + FOLD + "}"
    for left, right in reversed([(left, right) for right in (NEED, FOLD) for left in TOPS]):
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


def chip(word):
    """The state as its bar opens with it: its glyph and word on its colour in the theme's
    on-accent, bold where the word is -- `! needs you`, the one loud thing on the bar."""
    ink, rgb = terminal.tmux_colour("on-accent"), terminal.tmux_colour(word)
    bold = ",bold" * (terminal.STATE_STYLES[word][4] == "1")
    return f"#[fg=#{ink},bg=#{rgb}{bold}] {orch.tmux_text(terminal.state_text(word))} #[default]"


def lines(name, model, word=None, last="", why=""):
    """(line one, line two, its key, the window title): the seat's bar, as tmux text.

    Line one is its row on the `ak` screen: its word, its name, the model that orchestrates it,
    and `last`, its last column (`menu.last_column`), tmux text already.  Line two is `why`, the
    line its row opens under itself (`whys`).  Before its first word a seat's bar is its name and
    its model, and its title the name.
    """
    top = f" {chip(word)}   " if word else " "
    top += f"#[bold]{orch.tmux_text(name)}#[nobold]"
    if model:
        top += f"   #[fg=#{DIM}]{orch.tmux_text(model)}#[default]"
    if last:
        top += f"   {last}"
    key, verb = HINT.split("  ", 1)
    title = f"{name} · {word}" if word else name
    # tmux reads a title as a time too, unlike the bar's options: its `%` doubles as well
    return (top, f"  {why}" if why else "", f"{key}#[fg=#{DIM}]  {verb} #[default]",
            orch.tmux_text(title).replace("%", "%%"))


def whys(info):
    """Line two, one version for each of `WHYS`: a needs-you reason no chat shows, otherwise
    who builds and reviews (`menu.crew`) and every task's squares (`menu.squares`), then cut to
    six, then the squares alone, then cut to six, then to one and the count of the rest, so a
    narrow client still sees its tasks; as tmux text.  A question is not repeated: a stop shows
    `needs you` only once it is the agent's last message, or its card is up (owner, 23 Oct
    2026: "if we dont need it, lets remove it")."""
    if info.get("word") == "needs you" and not info.get("question"):
        return [orch.tmux_text(terminal.plain(info.get("sentence") or ""))] * len(WHYS)
    who, tasks = menu.crew(info, tmux=True), info.get("tasks") or []
    if not tasks:
        return [who] * len(WHYS)
    every, few, least = (menu.squares(tasks, tmux=True, most=most) for most in (None, 6, 1))
    return [f"{who}   {every}" if who else every, f"{who}   {few}" if who else few,
            every, few, least]


def sessions():
    """(session id, name, mark, `TOLD`, `TOLD_END`) of every session this HOME started on ak's
    own server; None where none of its is up: the socket is the user's, and a scratch HOME's `ak`
    wrote its empty records over real bars.  The fields are split at `:`, which tmux keeps out of
    every session's name, the HOME, which may hold one, last; read as a UTF-8 client it is the
    HOME itself, under any locale."""
    rc, out = orch.tmux_out("list-sessions", "-F", ":".join(f"#{{{field}}}" for field in (
        "session_id", "session_name", orch.MARK, TOLD, TOLD_END, "HOME")),
                            socket=orch.socket_name(), utf8=True)
    if rc != 0:
        return None
    rows = [line.split(":", 5) for line in out.splitlines()]
    home = os.path.realpath(os.path.expanduser("~"))
    ours = [row for row in rows if not row[5:] or not row[5] or os.path.realpath(row[5]) == home]
    if rows and not ours:
        return None
    return [row[:5] for row in ours if len(row) >= 5 and row[1] != orch.CONTROL]


def seats(listed=None):
    """(session id, name, word) of every seat among those `sessions`, listed now where not
    given, the word the one it last announced: what each bar's right end counts.  What
    `orch.seated` does not hold is no seat, whatever word a record under its name says: a
    watcher an orchestrator started, or a session whose agent has left.  A session under a name
    no seat can have (`orch.session_name`) is none either, so every name drawn is the plain
    ASCII a seat's is, whose cells `others` counts as tmux draws them.  A pass asks who is a seat
    once, as `orch.seated` may ask tmux for every pane, and never shares a word (`_tell`)."""
    from . import watch   # here, not at the top: the watch announces seats, which write this bar
    listed = (sessions() or []) if listed is None else listed
    held = look.once("seated, for the bars", lambda: orch.seated(
        orch.socket_name(), {name: (sid, mark) for sid, name, mark, *_ in listed}))
    return [(sid, name, watch.seat_read(name).get("word")) for sid, name, *_ in listed
            if sid.startswith("$") and name in held and orch.session_name(name) == name]


def others(found, name):
    """(needing, folded, hit): the right end of `name`'s line one, from `seats()`: how many other
    seats need you, `! 2 other seats need you` in that word's colour and bold, as its chip is,
    and the same short, `! 2 need you`, for a client too narrow for both it and this seat's
    name; or nothing; and `hit`, the format that turns the pointer on it into the first such
    seat's session id.  A seat never counts itself, and a session that has announced no word --
    a seat being dressed, or no seat at all -- is not counted.  It is drawn flush against the
    client's right edge, so its cells from that edge are the same on every client."""
    needs = [sid for sid, seat, word in found if seat != name and word == "needs you"]
    if not needs:
        return "", "", ""
    mark, many = terminal.state_glyph("needs you"), len(needs)
    said = f"{mark} {many} other {'seat needs' if many == 1 else 'seats need'} you"
    short = f"{mark} {many} {'needs' if many == 1 else 'need'} you"
    edge = terminal.cells(said) + 1     # the space after it, at the client's edge
    hit = f"#{{?#{{&&:#{{e|>:{AT},1}},#{{e|<=:{AT},{edge}}}}},{needs[0]},}}"
    return tuple(f"#[range=right]#[fg=#{terminal.tmux_colour('needs you')},bold]"
                 f"{orch.tmux_text(text)}#[default]#[norange] " for text in (said, short)) + (hit,)


def retell(session):
    """That seat's word or name changed, or the seat went: every seat's bar counts it again now,
    not at the next tick, and those whose right end moves are written.  Never raises."""
    try:
        if orch.on_own_server(session):
            _tell()
    except Exception:  # noqa: BLE001 - another seat's bar never breaks this seat's announcing
        pass


def _digest(told):
    """What names `told` on a bar: the same text, the same word, which `sessions` can split."""
    return hashlib.sha256(repr(told).encode()).hexdigest()[:16]


def _ends(listed, only):
    """The command lists that tell line one's right end, on that seat's bar or on every seat's,
    where the words as they stand now would say other than `listed` shows it told."""
    # a seat tmux did not list has no bar to write: no other session is asked what it is
    found = seats(listed) if only in (None, *(name for _, name, *_ in listed)) else []
    told = {name: end for _, name, _, _, end in listed}
    lists = []
    for _, name, _ in found:
        if only in (None, name):
            needing, folded, hit = others(found, name)
            digest = _digest((needing, folded, hit))
            if digest != told.get(name):
                # One command list, which tmux runs whole before it reads another click: no
                # click lands between what a bar draws and the lookup that finds its seat.
                # Where they are told one by one the lookup is emptied first, so a click finds
                # no seat until what it is for is drawn.  The digest around them, as `_own` says.
                target = f"={name}:"   # that session alone, as `_write` says
                lists.append(([(target, HIT, "")],
                              [(target, TOLD_END, ""), (target, NEED, needing),
                               (target, FOLD, folded), (target, HIT, hit),
                               (target, TOLD_END, digest)]))
    return lists


def _own(own, listed):
    """The command lists that tell each session its `own` options, where they would say other
    than `listed` shows it told.  On a session the listing shows gone -- no server is up, or it
    lists others -- nothing is told: tmux would refuse the call on every draw a stopped seat is
    in.  A listing that reads no session says nothing, since tmux ends a server with its last
    one, and there they are told as before.

    The digest is emptied first and set last, since tmux stops a list at the command that fails:
    one stopped part way leaves no digest that a later write could match."""
    told = {f"={name}:": mine for _, name, _, mine, _ in listed or ()}
    lists = []
    for target in dict.fromkeys(option[0] for option in own):
        options = [option for option in own if option[0] == target]
        digest = _digest(options)
        if listed == [] or told.get(target, digest) != digest:
            lists.append(((), [(target, TOLD, ""), *options, (target, TOLD, digest)]))
    return lists


def _tell(only=None, own=()):
    """Write line one's right end on that seat's bar, or on every seat's, then the caller's
    `own` options, each (target, option, text), and bind its click: one tmux call however many
    seats there are, where a call per seat made every start and every changed word wait on each
    open seat.

    What the listing shows already told is left out, before the lock: with nothing left there is
    no write.  A pass lists once (`look.once`) and anyone else for each write: a listing older
    than a write can only cost a write not needed, or leave a bar wrong until the next look.

    One lock across every bar's reading and writing: the seat words are read under it and
    written before it is let go, so whoever writes last has read last, and an older reading
    never lands on a bar after a newer word.  The click is bound with every write, so a server
    that was up before the names came gets it with the first bar that draws one.

    What tmux refuses for its length is told again in pieces (`orch.tmux_options`), so a bar
    does not keep what was said before because what is said now is longer than a message.  Code
    other than the live install's as it is now tells nothing (`update.publishes`).
    """
    listed = look.once("listed, for the bars", sessions)
    mine = _own(own, listed)
    if not mine and not _ends(listed or [], only):
        return
    config.ensure_dirs()
    with (config.STATE / "statusbar.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not update.publishes():   # asked under the lock: an install while it waited counts
            return
        # a seat gone since it was listed fails its own list and no other's (`orch.tmux_lists`)
        told = [*_ends(listed or [], only), *mine]
        if told:
            orch.tmux_options(told, [CLICK], socket=orch.socket_name())


def dress(name, model):
    """A new seat's bar, before its first word: who is in it; and every other seat's bar counts
    it again, since a seat opened under a name that needed you needs you still.  Never raises."""
    try:
        _write(name, model, every=True)
    except Exception:  # noqa: BLE001 - dressing a bar never breaks the seat beneath it
        pass


def redress(session, answer, cfg=None, records=None, mine=None):
    """Write that seat's bar and window title from its row's own values, where that moves them
    (`_tell`); never raises.

    The one writer: the watch tick, every menu draw and a seat's own hook come through here --
    all call `watch.announce_state` -- so the bar says what the row says: the state function's
    word, `menu.last_column` over `menu.seat_progress`, and the line its row opens, who builds
    and reviews and its tasks' squares (`menu.own_tasks`) from the caller's run `records`, or
    the seat's own among them, `mine`, where it has them.  A legacy seat lives on the
    user's own server, where nothing is written.
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
        progress = menu.seat_progress(name)
        # each in its own cells and never more (`narrow`), so line one picks by the width it set
        lasts = [menu.last_column(word, *progress, cells, narrow=True, tmux=True,
                                  unsent=answer.get("unsent"), back=answer.get("resumes_at"))
                 for cells in BARS]
        info = {"word": word, "sentence": answer.get("reason"), "question": answer.get("question"),
                "crew": menu.seat_crew(cfg, selection),
                "tasks": (menu.seat_tasks(name, records) if mine is None
                          else menu.own_tasks(mine))}
        _write(name, selection["orchestrator"] if selection else None, word, lasts, cfg,
               whys(info))
    except Exception:  # noqa: BLE001 - dressing a bar never breaks the draw or the tick beneath it
        pass


def _write(name, model, word=None, lasts=None, cfg=None, versions=(), every=False):
    """Set the bar on that seat's own session, never the server's or another seat's: a seat
    whose session is gone is not written (`_tell`), and one gone mid-draw fails its `set-option`
    quietly.  `={name}:` is that session alone: tmux reads a plain name as the start of any
    session's, so a gone `new-1` would write `new-10`'s bar, and it refuses `=name` without the
    colon as a target.  `lasts` are the seat's last column at each of `BARS`, and `versions`
    its line two at each of `WHYS` (`whys`), tmux text.  `every` has each other seat's bar
    count this one again, in the same call."""
    lasts = lasts or [""] * len(BARS)
    versions = list(versions) or [""] * len(WHYS)
    if model:
        cfg = config.load() if cfg is None else cfg
        model = config.model_at(cfg, config.load_session(cfg, name, required=False), model,
                                "orchestrator")
    tops = [lines(name, model, word, last)[0] for last in lasts]
    _, _, key, title = lines(name, model, word, lasts[0])
    whys_drawn = [lines(name, model, word, "", version)[1] for version in versions]
    # With line one's right end, in one call, where a call per option made a seat's start wait
    # seconds on a busy host.  The title last, so whoever sees it has the whole bar to read.
    # Each value whole: a name may end in the `;` tmux would take for the end of its command
    # (`orch.tmux_set`).
    _tell(None if every else name,
          [(f"={name}:", option, value)
           for option, value in (*LAYOUT, *zip(TOPS, tops), *zip(WHYS, whys_drawn), (KEY, key),
                                 ("set-titles-string", title))])
