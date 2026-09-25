# CLI design

One visual system for every screen agentkit draws. `menu.py` renders; every
helper it names lives in `terminal.py` and is never re-implemented per screen.
v5u, v5v and v5z apply this to every other screen.

## Frame

Every screen clears the terminal, then one header line: `agentkit` at the
left, the screen name after it when it is not the menu, the clock at the
right; under it one dim rule the width of the layout. It ends with one blank
line, the key line, and the prompt `> ` wherever a line is read; the main menu,
`c` and `i` on a terminal read keys, and end at their key line. The commit hash is not in
the header.

Helpers: `terminal.header_line`, `terminal.rule_line`, `terminal.key_line`,
`terminal.layout_width`.

Example: `agentkit                                                              14:02`
then `────────────────────────────────────────────────────────────────────────`.

## Width and rhythm

The layout is `min(terminal width, 120)` columns (`terminal.layout_width`);
seat content is capped at 100 (`terminal.content_width`). Section titles
(`Usage`, `Projects`) are plain words in the accent style, flush left, one
blank line above each; content sits two spaces under them; one blank line
between projects; seat rows two spaces under their project line. Nothing else
is indented.

Example:
`your projects · 1 needs you`
`atoll`
`  1  atoll-fix  fable  ● working  tasks ██░░░ 2/5`.

## The menu at rest

Projects and their seats, and nothing else. A project is a checkout under
`~/code`, or agentkit's own at `~/agentkit` -- so a run's worktree, a
temporary repository under `~/.agentkit/tmp` and a run id are none of them a
heading, and a checkout nobody sits in is not listed unless its `AGENTS.md`
names its feature switches (`features:`). A seat is filed under
the checkout most of its runs belong to, a run still queued for a slot among them, whether it
works in one checkout or across several from `~/code`; a tie keeps the one it has. Only a seat
none of whose runs belongs to a checkout sits under `no project`, and the next draw files it
once one does. There is no run row, ever: `ak run status` is where runs are looked up.

The question is answered once, on the top line -- `your projects · nothing
needs you`, `· 1 needs you`, `· 3 need you` -- and on no other line. A project
heading is the checkout's basename in the accent style and nothing more, but
for a project naming its switches: `ACME · 2 hidden features` (off for
everyone; no count when none), a row the highlight lands on, drawn `› ACME`.
Enter or a click on it opens `agentkit · ACME`, every feature once with a
`you` and an `everyone` column, `●` on and `○` (dim) off, `—` under `you` where
the project does not let you switch it, and one on for everyone on for you too.
It is read with the `c` matrix's keys (`menu.matrix_key`): ↑/↓ move, ←/→ choose
the column, Enter, space or a click flips through the project's `set` at once
and draws the row it answers; a failure is one dim line under the rows, the mark
unchanged. Its `list` runs in a thread with a 20 s timeout, asked every minute
and every ten seconds while the screen is open, so neither screen waits on it.
Needing projects sort first, which is what carries the eye down to one. Under
a heading seats sort needs you, then working, then done, then by name, and
numbers stay global by seat name. The seat row's last column is the reason for
`needs you` and `done` -- `session closed: press 2 to reopen`, the question
the seat asked, `waiting for you`, the done summary's first line -- and for
`working` the tasks bar (`tasks ██░░░ 2/5`) from the session's plan,
`~/.agentkit/state/plan-<session>.md` under its name or any name it was renamed
from (the newest wins), else from its unfinished jobs' tasks, else empty --
never `N running`. No row ever names a run: an ended run is its orchestrator's
business.

## Keys

Six keys and nothing else: the numbers, `n`, `x`, `c`, `i`, `q`.

On a terminal the main menu has the keyboard and reads it a key at a time
(cbreak): a key acts the moment it is pressed, with no Enter, and no redraw
can wipe, merge or drop one. One seat row is highlighted -- it starts with `›`
in the accent colour and its text is bright -- and ↑/↓, `k`/`j` and the wheel
move it; Enter opens it. A click on any line of a seat opens that seat, and a
click on a key-line item does what its key does, read against the layout that
draw used (SGR mouse mode 1006, on only while the menu has the terminal). A
click acts when the button comes up, so nothing it opens is handed the rest
of it. A key pressed while the button is down acts at once and the menu reads
nothing past it, so all he typed after it goes to whatever takes the
terminal; the rest of that click is no click -- a question drops it from the
line it reaches (`terminal.readline`), a session's tmux takes it for the
mouse event it is, and the menu, back at the keyboard, reads it as nothing,
however late it comes. The highlight is the seat's name, so it stays on its
seat whatever comes or goes above it, the page up is the one it is on, and a
seat opened by its number or a click is the one highlighted on the way back.
A digit opens that seat; a second digit within half a second makes two digits
(`1` `2` is seat 12), and a digit no two-digit seat starts with opens at
once. A resize in that half second does not cut it short, and any other key
read in it is kept for after the seat -- a click with the screen it was made
on. Esc leaves, like `q`. A key that does nothing here is let go without a
word. The key line is the example below -- `j/k move   enter open` leads it
without UTF-8 -- and never offers `m` or `k` for pages.

The menu draws on the alternate screen with the cursor hidden, going home and
writing over the last draw line by line in one write, so it never flickers.
It gives the terminal back exactly -- the very termios attributes it found,
the main screen, the cursor, clicks off -- on `q`, on any exit or signal (a
kill, a hang-up, `^\`, and `^Z`, which takes it again on `fg`), and before
anything else takes it: a session, `ak update`, and every sub-screen that
reads a line, as they always have. A resize draws again at once.

`x` is the highlighted seat's, or in the popup the popup's own seat's. A done
seat it closes at once, with no question: `orch.cmd_stop` takes its runs,
checkouts, conversation, state files and tmux session. Any other it asks about
inline, under that seat's row, as a two-item selector -- `Stop <name> and
everything it runs?`, `Keep` preselected, then `Stop` -- where Enter or a click
answers and Esc, or a click anywhere else, keeps; the key line reads `esc keep`
while it asks. The key line says `x close` while a done seat is highlighted (in
the popup, while its own seat is done) and `x stop` otherwise, and a done
seat's tmux bar reads `Ctrl-b m  x close` on its right half.

A stdin that is no terminal -- a pipe, a file, the smoke suite -- keeps the
line menu: a key and Enter, and the key line
`n new   x stop   c config   i info   q leave`, with `m more   k previous`
joined on only while the list runs to more than one page; anything else typed
answers `not a key: '<key>'`. There `x` asks `Stop [name]:` and `[y/N]`, and
on every sub-screen that reads a line `q`, `Esc` and an empty Enter all go one
level back.

Helpers: `terminal.Keyboard`, `terminal.read_key` and `terminal.Key` (named
keys: arrows, enter, esc, backspace, tab, space, a character, a click at a
column and row, the wheel), `terminal.highlight`, `terminal.key_spans`, and
`terminal.choose`, the list selector (one choice, or several marked with
space; a default preselected; Esc back; asked inside a screen it draws again
on a resize, where a click on a choice picks it). The main menu and the
new-session screen use them. A click belongs to the screen it began on: a button down on the menu and
up on the question or on `i`, or the other way round, is no click.

Example: `↑↓ move   ⏎ open   n new   x stop   c config   i info   q leave`.

## The config and info screens

`c` and `i` are sub-screens in the same frame, headed `agentkit · config` and
`agentkit · info`. `c` is a matrix read with the keys, so the file is never
opened: every offered model once, under its provider's display name in the
accent, a row of label, harness (dim), then `orchestrator` (`●` on the one
default, `○` dim elsewhere), `worker` (`■`/`□`) and `effort` (`‹ xhigh ›`);
the columns are `orch` and `work` where the full words do not fit, then the
harness gives way, then the label. ↑/↓, k/j and the wheel move between rows,
←/→ between all three columns; Enter or space on an effort steps it up through
that model's own efforts (`config.efforts`), from the highest round to the
lowest. The highlighted row
is `highlight`'s and its cell is drawn reversed. Enter, space or a click flips a
mark and a click on an effort's arrow steps it; each change is saved at once and
drawn at once, the orchestrator only moves, and the last worker stays, saying
so under the rows. Under the models `+ add a model`, `Providers` (the config's
providers in their colours, then `+ add` and `− remove`, ←/→ choosing between
the two, each a list opening in the frame), `Discord` (connected or not)
and `Update` (the build, `up to date` or the newer commit, the harnesses). Enter
or a click on `+ add a model` opens `config · add a model`: `harness`, then
`model`, then `effort`, each a list opening under the one chosen above it, a
chosen one kept as one line; Enter on the effort adds the model and highlights
its row, Esc steps back one list. On the other two Enter or a click gives the
terminal back for that row's step and its lines. The key
line names what the keys do on the cell at hand (`⏎ mark`, `⏎ effort`,
`⏎ open`) and ends `esc back`; Esc, `q` or a click on it returns. A
screen too short shows the part the highlight is on. From a pipe, and in a dry
run, it is drawn once. ← from the marks reaches the label, and Enter or a click
there opens `config · <label>`: `model id`, `effort` and `Reviews its own
company's work` between the arrows ←→ step (the id and the effort only through
what the harness's catalog lists, the effort following the id), then `Remove`, whose Enter asks `Keep` or
`Remove` under it the way `x` asks, `Keep` picked; each value goes under its
label on a phone. Esc returns to the matrix on that model's row.
`i` is one calm screen and reads no line: one line on what agentkit is, then
`States` and `Keys` in the README's own lines, then `Installed`, the worker
token's date and the build, and nothing else. Two-column lines wrap under their
text on a phone, and a resize wraps them anew. It is written over the menu's screen and read with the keys:
when it does not fit, ↑/↓, k/j and the wheel scroll it and the key line leads
with `↑↓ scroll`; Esc, `q` or a click on `esc back` returns. From a pipe it is
drawn once and the menu goes on.

Helpers: `terminal.frame` (written over in place while a keyboard has the
screen), `terminal.scroll`, `terminal.hang`, `terminal.state_text`.

## The new-session screen

`n` is `agentkit · new session`, read with the keys: `Orchestrator`, then `Workers`, titles in
the accent style, every model once under each -- `●`/`○` for the one orchestrator, `■`/`□` for
the workers -- with its harness and effort dim beside it, the names no wider than a third of the
screen, a longer one cut. The defaults are chosen when it opens;
a spent model reads dim with `spent · resets <day HH:MM>`, on a line of its own under the name
where the row does not fit, and is never chosen for him. ↑/↓, k/j and the wheel move one
highlight through both lists and scroll them on a short screen; space or a click chooses, Enter
starts from anywhere -- or, with every model spent and a list still empty, takes the highlight to
it -- Esc or `q` goes back, and the last worker stays chosen. No name is asked:
the seat is its orchestrator's (`opus`, then `opus-2`). From a pipe `n` asks `Orchestrator
[opus]:` and `Workers [opus astra]:` a line at a time instead, Enter taking each default.

Helpers: `terminal.Keyboard`, `terminal.read_key`, `terminal.highlight`, `terminal.key_spans`.

Example: `› ● Opus 5.5     claude · xhigh`.

## Rows are tables

Fixed columns with two-space gutters, sized once per draw from the rows on
screen: number, name, orchestrator, state (glyph and word in the state's
colour), and one last column. The last column takes all the remaining width;
it wraps once at a word onto an indented continuation and is cut with ` …`
only past that. Columns use gutters, never ` · `. Never cut inside a
glyph or a colour sequence. No rendered line keeps trailing space: cell pads
land outside the colour escapes and every row is rstripped, so the snapshots
never pin invisible whitespace. The usage bars are one column, sized once per
draw from the row that has the least room.

Helpers: `terminal.cut`, `terminal.wrap`, `terminal.pad`, `terminal.cells`,
`terminal.plain`, `terminal.styled`, `terminal.state_text`,
`terminal.state_colour`, `terminal.progress_bar`.

Example: `  1  atoll-fix  fable  ● working  tasks ██░░░ 2/5`.

## Narrow screens

Under 60 columns a seat row is two lines (number, name, orchestrator and
state, then the last column indented under it). The plan bar shortens to 4
cells. No column ever lands alone on a line.

Example at 40 columns:
`  1  atoll-fix  fable  ● working`
`    tasks ██░░ 2/4`.

## Height

Height is budgeted the way width is, leaving one line for the prompt and one
to spare. The usage block gives way first, then compact
mode drops the frame and the blank lines so every number stays reachable.
Pages start with a collapsed overview (every project header, no numbers),
then whole seat blocks packed under repeated headers, so a seat's lines never
split across pages; rows keep their global numbers. The heading says which
page is up (`your projects 2/3`), and in compact mode the page is never the
part that is cut. On a terminal the page up is the one the highlight is on,
and there is no overview page, since the highlight is never on it; in a pipe
`m` and `k` turn the pages.

## Usage rows

One row per provider under `usage left`, one column of bars: the provider's
display name, the bar and `NN% left` of its **shared** weekly meter -- the one
every model of it draws on, never a cap one model has to itself -- then, joined
with ` · ` and each only when it applies: `resets <weekday> <HH:MM>` in local
time from that meter (`resets 23 Oct` more than six days out in a window longer
than a week, such as MiMo's 30-day plan; `resets in 3d` when only a duration is
known); one `<Model> NN%` note per scoped cap whose figure differs from the
shared one; `? <reason>` in the
adapter's own words when the last probe errored though the meter it read still
stands, or `rate limited` / `unavailable` when the endpoint refused it and the
last reading stood in. No row, heading or note -- here or in `ak usage` -- says
how old a reading is: an open menu probes each provider at most once a minute,
host-wide, the tick does when no menu is open, and Muse's billed probe spends at
most one model call in ten minutes. A row with no
shared week at all -- no reading, or nothing but one model's private cap --
is `—` and the words that say why, never `—` alone. The bar's filled cells are
the company's own colour -- Claude `#D97757`, ChatGPT `#FFFFFF`, Muse
`#3E9EFB`, Grok `#FCFCFC`, Gemini `#203B9B`, MiMo `#FB8046`, or the provider's
`colour = "#RRGGBB"` in config.toml, else the accent -- and its empty cells are
dim; a terminal without truecolor gets the nearest of its 256 or 8 colours. The
rows run red through violet by that colour's hue, the near-greys last and
lightest first: Claude, MiMo, Muse, Gemini, ChatGPT, Grok. The bar gives way to the
notes first, down to four cells; only then does each note that still will not
fit give way on its own, so a phone keeps every short note it has room for
rather than losing them all with one long one. Everything else a provider knows -- `week
elapsed`, `session`, the resets in hand, `headroom`, `budget`, `outlook` --
belongs to `ak usage`, whose table gains a `resets` column reading the same
shared week off the same meter, so the two views can never disagree; the
usage-limit credits that used to hold that heading are `resets held`.

Example: `  Claude    ██████░░░░░░  52% left · resets Fri 14:00 · Fable 41%`.

## Live

The main screen is live, and so is a project's feature switches screen. The main one draws from the cache at once, probes
every provider off the drawing thread and draws again when that lands, and
redraws whenever the key read times out after ten seconds, so the clock, the
seat rows, the top line's counts and the usage stay true. The read is `select`
on stdin and on a pipe the finished probe writes to, and the ten seconds hold
whatever stdin is: a terminal is read a key at a time, and a pipe that writes
half a line is gathered a byte at a time so the clock still comes round. A key
pressed during a draw waits in the terminal until the next wait reads it, and
half a line on a pipe waits in `terminal._HALF_TYPED`.
`terminal.readline` is the one place a line comes off stdin -- for the bounded
wait, for every sub-screen's question and for the ones `orch` asks under them --
and it reads a terminal a byte at a time as it does a pipe, so no question can
buffer the key behind it out of the screen's reach, not even the keys a terminal
hands over all at once when the menu gives it back.
Other sub-screens are not live; the feature switches screen is read a second
at a time and draws again once its `list` lands. A menu with no
keyboard in front of it does not wait and does not probe.

Helpers: `menu.wait_key`, `terminal.read_key`, `terminal.readline`,
`terminal.wait_line`, `menu.Live`, `menu.TICK`.

## Ages

Ages read `<1m`, `5m`, `2h`, `3d`, never seconds. One helper, used by every
screen.

Helpers: `terminal.format_age`.

Example: `turn running 4h`, `2 running · silent 2h · <task>` — the `ak orch why` telling, not the row.

## States

One state table, `terminal.STATES`, and it is the whole vocabulary: a session
-- and a run, and a project -- is `● working` (blue), `! needs you` (bold
yellow) or `✓ done` (green), and nothing else exists. `watch.session_state`
decides which, once, and every screen reads that: the menu row, the project
heading, the top line, `ak orch list`, `ak orch why`, `ak run
status`, the seat's own status bar and its window title. A whole row is never
coloured, and the reason for the word lives in the row's last column.

Example: `● working`, `! needs you`, `✓ done`.

A run, and only a run, can also be parked on something outside itself that lifts
by itself -- a slot, a provider window, a target change, an expired login. Those rows say what
the run waits for instead of a word, dim and under `terminal.STATE_STYLES`'
open circle (`○ waiting for claude login`, `○ waiting`), which is what says
nobody has to act on it. It is not a fourth state and no session ever wears it:
a phrase takes the style its first word names, so every listing still draws its
state column through the same helpers.

## Other listings

`ak run status`, `ak orch list` and `ak --help` wear the
same design: fixed columns with two-space gutters under the frame, the title
taking all the remaining width.

`ak run status` reads the run's word from the same table: still going, parked on a slot, provider window or
target change the tick lifts by itself, or parked `stalled` for the orchestrator to resume, is `working`;
an interruption, a FAIL, an error and a `blocked` are `needs you`; a run that passed is `done`, and so is an
ending its orchestrator already has: handed back, acknowledged, or superseded by a later merged run of its
title or a relaunch `from:` its branch. A run parked on an expired login says so in the column itself
(`○ waiting for claude login`), because until somebody logs in neither the loop
nor the tick can move it. A `blocked` run is final and has no resume to offer, so it
keeps one dim line under its row saying why, with the row's glyph (`! blocked · <reason>`).

`ak run status` is the table id (its date and time, then the slug cut
at a word), title, state, worker, round, age; the id yields to a twenty-column
title floor, so one long id never starves every title. The run's `result:`,
`record:`, `workspace:`, `limits:` and `continue:` lines sit indented under its own row
only for one id or `--why`. `limits:` shows the recorded `silence_minutes` and
`ceiling_hours`; the stall ladder uses the same silence window for every step,
with a short margin for the loop to finish cleanup and record its own stop.
`--plain` keeps the older lines for scripts.

`ak orch list` is the table name, project, state, tally, orchestrator,
workers, age; the whole worker list wraps onto a continuation under the
workers column and is never cut, each continued piece keeping its comma.
On a narrow screen the header
names the seat and its project and the
state, tally, orchestrator, age and workers ride their own lines under it.
The checkout path shows only with `--why`, which keeps its explanations.

`ak --help` is one screen: `ak`, the menu, then the commands an orchestrator
uses (`run`, `notify`, `usage`, `browser`, `fetch`), one line each
with its purpose, then one dim `internal:` line naming the rest. A command's
own help opens with its purpose once, then its usage.

Helpers: `terminal.title_lines`, `terminal.table_row`, `terminal.state_cell`.
