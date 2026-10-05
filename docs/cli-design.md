# CLI design

One visual system for every screen agentkit draws. `menu.py` renders; every
helper it names lives in `terminal.py` and is never re-implemented per screen.
v5u, v5v and v5z apply this to every other screen.

## Frame

Every screen clears the terminal, then one header line: `agentkit` at the
left, the screen name after it when it is not the menu, the clock at the
right; under it one dim rule the width of the layout. It ends with one blank
line, the key line, and the prompt `> ` wherever a line is read; the main menu,
`c` and `n` on a terminal read keys, and end at their key line. The commit hash is not in
the header.

The rule is ak's one progress indicator, and otherwise just a line. When `ak`
updates itself at start the main frame says `agentkit · updating` and the rule fills
from the left in the accent colour as each of fetch, pull and install begins, and
wholly once they are done; the filled part is drawn heavy (`━`), so it reads
where there is no colour. The check and update run in a detached process behind
the first frame; keys still answer within 100 ms, and leaving lets the update finish.
Once the code has moved, the menu starts again with the same seat highlighted as
soon as its main screen is up. An open sub-screen, including a typed draft, stays
until the owner comes back. A failed update says why as a notice. On a client,
the detached update starts before ssh connects; the next `ak` takes the new code.
Overlays and dry runs skip it. A screen whose content is still being fetched has a
segment glide along it (Motion). No other screen draws a bar for either.

Helpers: `terminal.header_line`, `terminal.rule_line`, `terminal.key_line`,
`terminal.key_height`, `terminal.layout_width`.

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
names its feature switches (`features:`). As soon as its project is known, the orchestrator
files its seat with `ak orch project <checkout>` by checkout name or path. Names match in any
case; an exact match wins, otherwise a name matching several checkouts is refused and lists
the matches. Each launched run then files the seat under the checkout most of its runs belong
to, a run still queued for a slot among them, whether it works in one checkout or across
several from `~/code`; a tie keeps the one it has. A seat with no filing and no run belonging
to a checkout sits under `no project`, and the next draw files it once a run counts. There is
no run row, ever: `ak run status` is where runs are looked up.

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
unchanged and shaking (Motion). Its `list` runs in a thread with a 20 s timeout, asked every minute
and every ten seconds while the screen is open, so neither screen waits on it.
Needing projects sort first, which is what carries the eye down to one. Under
a heading seats sort needs you, then working, then done, then by name, and
numbers stay global by seat name. The seat row's last column is the reason for
`needs you` and `done` -- `session closed: press 2 to reopen`, the question
the seat asked, `waiting for you`, the done summary's first line -- and for
`working` the tasks bar (`tasks ██░░░ 2/5`) from the session's plan,
`~/.agentkit/state/plan-<session>.md` under its name or any name it was renamed
from (the newest wins), else from its unfinished jobs' tasks, else empty --
except for a run recorded in the line to land: its seat shows `waiting · 3rd in line to land on main`.
Never `N running`, and never when the work will finish: the bar and its count
are a seat's progress. No row ever names a run: an ended run is its orchestrator's
business.

## Keys

Six keys: the numbers, `n`, `x`, `c`, `s`, Esc. Esc is the one way
back on every screen and at every question under the menu, and on the main
screen it leaves at once, whatever is still going behind it; `q` is no key
anywhere, and at a question it is a letter. The menu opens on the seats'
records as they stand: each seat's look and the maintenance run behind the
first frame, a look that lands draws the seats again, and what maintenance says
is a notice once it lands.

On a terminal the main menu has the keyboard and reads it a key at a time
(cbreak): a key acts the moment it is pressed, with no Enter, and no redraw
can wipe, merge or drop one. One seat row is highlighted -- it starts with `›`
in the accent colour and its text is bright -- and ↑/↓, `k`/`j` and the wheel
move it; Enter opens it. A click on any line of a seat opens that seat, and a
click on a key-line item does what its key does, read against the layout that
draw used (the pointer's every move, mode 1003, in SGR form, 1006, on only while
the menu has the terminal). A
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
on. Esc, or a click on `esc leave`, leaves. A key that does nothing here is let go without a
word. The key line is the example below -- `j/k move   enter open` leads it
without UTF-8 -- and never offers `j` or `k` for pages.

The menu draws on the alternate screen with the cursor hidden, going home and
writing over the last draw line by line in one write, so it never flickers.
It gives the terminal back exactly -- the very termios attributes it found,
the main screen, the cursor, the pointer's reports off -- on Esc, on any exit or signal (a
kill, a hang-up, `^\`, and `^Z`, which takes it again on `fg`), and before
anything else takes it: a session, `ak update`, a harness's login. A note said
while the menu holds the screen (`pause`) has its own `agentkit · note` frame:
its lines wrap in the content column, with `esc back` beneath. Esc, Enter or a
click on `esc back` returns to the screen it came from, drawn whole; a resize
draws the note again at the new width. With the terminal given back, a note
prints where the cursor stands as before, its `esc back` still read a key at a
time, so Esc goes back at once. A question typed inside the menu -- the name `n`
and `r` ask, the Discord secrets -- is no line: it is typed on the menu's keys
(`terminal.field`), Enter answering, Backspace editing and Esc going back at
once with nothing saved; an answer Enter takes with nothing typed (`auto`,
the current name) is in the field, dim, until a key replaces it. A resize
draws again at once.

The popup `Ctrl-b m` opens inside a session floats over it: a rounded border in
the dim colour with ` agentkit ` set into its top edge, and a column and a row
of padding inside it -- on a phone it keeps the whole screen, border and all,
with no padding. While it is up the session behind it draws its own text dim
(text a harness colours itself keeps its colour), and has exactly its own
style back once the last popup over it is down, however each came down: its
menu ending, a crash, a kill, its client going. A tmux older than 3.3 draws the
plain popup and says nothing (`orch.tmux_conf`, `terminal.inset`).

`x` is the highlighted seat's, or in the popup the popup's own seat's. A done
seat it closes at once, with no question: `orch.cmd_stop` takes its runs,
checkouts, conversation, state files and tmux session. Any other it asks about
on the question card (Questions), under that seat's row, the rows below moving
down: `Stop <name> and everything it runs?`, then how many runs stop with it
and that ak cannot reopen the session, its record gone; the key line reads `esc
back` while it asks. The runs are counted off the draw, so the card is up at
once: `Its runs stop` until the number lands. The key line says `x close` while
a done seat is highlighted (in the popup, while its own seat is done) and
`x stop` otherwise, and a done
seat's tmux bar reads `Ctrl-b m  x close` at the right end of its second line.

A stdin that is no terminal -- a pipe, a file, the smoke suite -- keeps the
line menu: a key and Enter, and the key line
`n new   x stop   c config   esc leave`, with `j more   k previous`
joined on only while the list runs to more than one page; anything else typed
answers `not a key: '<key>'`, `q` included. An empty line or the end of input
leaves, as Esc does. There `x` asks `Stop [name]:` and `[y/N]`, and on every
sub-screen that reads a line `Esc` and an empty Enter go one level back.

Helpers: `terminal.Keyboard`, `terminal.read_key` and `terminal.Key` (named
keys: arrows, enter, esc, backspace, tab, space, a character, a click at a
column and row, the wheel), `terminal.highlight`, `terminal.key_spans`, and
`terminal.choose`, the list selector (one choice, or several marked with
space; a default preselected; Esc back; asked inside a screen it draws again
on a resize, where a click on a choice picks it). The main menu and the
new-session screen use them. A click belongs to the screen it began on: a button down on the menu and
up on the question or on `c`, or the other way round, is no click.

On a terminal, `s` toggles solo on the highlighted seat, or in the popup its own seat,
and appears as `s solo` on the key line while a seat is selected. The last column starts
with `solo` while on; the session's record keeps the switch across restarts and model changes.
Solo refuses task launches before a run is created and still allows its own PR reviews.

Example: `↑↓ move   ⏎ open   n new   x stop   c config   s solo   esc leave`.

Whatever the pointer is over lights up, on every screen, as it would in a window:
a row under it -- a seat, a model, a feature, a choice -- takes the keys' own
highlight, which moves there, and a key-line item or a cell of a row (a mark, an
effort, a model's label, `+ add`, an arrow on a model's own screen) a subtle
background, in place of the reverse the keys give a cell, or at eight colours the
reverse; the keys and the pointer never show two highlights. What lights is what a
click there acts on. Each loses it when the pointer leaves: off every row -- on a
key-line item, a header or blank space -- no row or cell is highlighted, a key-line
item alone lit, until the pointer is on a row again or a key brings the highlight
back on the row it was last on. The keys go on from there: an arrow moves it on, and
a key that acts on it -- Enter, space, their key-line items, the menu's `x` and `c`,
←/→ on a model's own screen -- only brings it back, so nothing unseen is acted on; a
digit names its own row and acts at once. `s` follows the same highlight rule. Any key puts out what the pointer lit, and a
screen opens, or comes back, with nothing lit: the pointer lights nothing until it
moves again. A question typed on a screen (`terminal.field`) lights its key line
too, and one asked over a screen's rows (`x`'s) takes those rows for nothing. A move
is drawn within a frame of the clock (Motion) of the pointer reaching another row,
cell or item, and only then: the moves a terminal sends while the pointer travels
are read through to where it ended first, for a frame at most, however soon a frame
of the clock's falls due, and a move within what is lit draws nothing. With no
colour the rows still follow it, and nothing else lights. Helpers: `terminal.under`,
the one reading of a position back to what a screen drew there, for a click and the
pointer alike, `terminal.lit`, `terminal.relight`, `terminal.away`, `terminal.unseen`.

Nobody needs a manual: the key line is the tooltip. While the pointer rests on
something that means more than its label -- a session row, a state word, a
project's heading, a usage row, a key-line item on any screen, on `c` a model,
a mark, an effort or a provider's name, on a model's own screen its id and its
effort, on `n` a model or a role's mark, and a provider or a subscription in the
lists `+ add` and `− remove` open -- the key line says what it is in one plain
sentence, in place of the keys: starting on the same row and wrapping at word
boundaries onto further lines, never cut. The rows above stay in place. The keys
and their explanations have room reserved through `terminal.key_height` before an
interactive list is drawn, so a full list never scrolls when the pointer rests on
a key or a row. `terminal.key_line` returns only the keys' own rows, with no blank
rows added for that room. A menu printed from a pipe reserves only its keys. The keys
come back when the pointer leaves it, and any key brings them back too. A state
word, a heading naming no switches, a usage row and a provider's name only
explain: nothing lights on them and a click there does nothing of its own (`terminal.Spot`); a key-line
item whose sentence stands in its place is not lit either. `esc back` means
just what it says, so it lights and explains nothing. The sentences live in
one table, `terminal.TIPS`, filled in with what each is about; a key-line item
is keyed by its own text, the same on every screen, and without UTF-8 by its
UTF-8 key (`enter` is `⏎`):

- `↑↓ move` (and `↑↓←→ move`): `the arrow keys, k and j, or the wheel move the highlight; so does the pointer`
- `⏎ open`: `Enter or a click opens what is highlighted: a session, a model's own screen, a list`
- `⏎ mark`: `Enter, space or a click flips the mark, saved to the session at once`
- `⏎ effort`: `Enter or space steps the effort up, round from its highest; a click on an arrow steps it`
- `⏎ remove`: `Enter asks Keep or Remove first, and the last model always stays`
- `←→ choose`: `← and → step the value through what its harness's catalog offers, saved at once`
- `⏎ choose`: `Enter or a click picks the highlighted one; Esc goes back with nothing done`
- `⏎ add`: `Enter or a click adds the highlighted one to the config; Esc goes back with nothing added`
- `⏎ flip`: `Enter or a click flips the switch through the project's own command, at once`
- `space choose`: `space or a click marks or unmarks the model for the role the highlight is on`
- `⏎ start`: `Enter starts the session on what is marked, wherever the highlight is`
- `n new`: `n starts a session: you name it and pick the models that orchestrate, execute and review`
- `x stop`: `x stops the highlighted session and everything it runs, asking first`
- `x close`: `x closes the highlighted session, which is done: its runs, checkouts and files go`
- `c config`: `c sets the highlighted session's models, every model's effort, the providers and Discord`
- `s solo`: `s toggles solo: no task launches while on; its own PR reviews still run`
- `esc leave`: `Esc leaves ak; the sessions go on working without it`
- in the popup, `n start a session`: `n starts a session and switches this terminal to it, closing the popup`
- `r rename this session`: `r renames this session: its record, its bar and its title follow`
- `x stop this session`: `x stops this session and everything it runs, asking first`
- `x close this session`: `x closes this session, which is done: its runs, checkouts and files go`
- a session row: `{name}: Enter or a click opens it, where you talk to its orchestrator`
- `needs you`: `needs you: it asked you something, or it cannot go on without you`
- `working`: `working: a run of its own is going, or a turn is, or a session it waits on works`
- `done`: `done: it said so, and the row carries its summary`
- a project's heading: `{name}: the project the sessions under it work in, those needing you first`
- one naming feature switches: `{name}: Enter or a click opens the switches of its hidden features`
- a usage row: its label, `NN% left`, `resets <when> (in 2 d 6 h)`, then `runs out early at this pace`, `lasts at this pace` or `on pace` (none once it is at 0%)
- a usage row with no week to draw: `{name}: no week to draw, {why}; the bar comes with the first reading of one`
- a model, on `c` and `n`: `{name}: {model} through {harness}, at {effort} effort`
- its id, on its own screen: `model id: what {harness} is asked to run, one its catalog lists`
- `orch`: `orch: the model the session's orchestrator runs on, one only`
- `exec`: `exec: a model that builds pieces beside the orchestrator; none, and it builds all`
- `review`: `review: a model that may review the session's runs; one at least`
- an effort: `effort: how hard {name} thinks, one of the efforts its harness takes for it`
- a provider, or in `− remove` a subscription: `{name}: your subscription; its seats, runs and usage row use its login`
- the provider a worker token is minted for: `{name}: its {note}`, the token's expiry
- in `+ add`, another subscription: `{name}: another subscription of it, logged in on this terminal, then listed`
- in `+ add`, a provider: `{name}: installed here if missing, logged in, and added with its first model`

A usage row under the pointer shows the one thing the row cannot: whether its
allowance lasts the week at this pace. One glint of light crosses its bar, left to
right in 400 ms (Motion), and a hairline tick stands in the bar at the share
that would be left had it been spent as fast as time passes, from the meter's
window and reset -- cut out of the fill's colour where the fill reaches past
it, and standing through a glide -- until the pointer leaves; the key line reads
`Claude II · 68% left · resets Thu 20:00 (in 2 d 6 h) · lasts at this pace`.
Helpers: `terminal.pointed`, `terminal.lit`, `menu.usage_tip`, `motion.glinting`.

## Questions

Every yes-or-no question on a screen read with the keys -- `x` on a seat that
is not done, in the menu and the popup, and `Remove` on a model, a provider or a
subscription on the `c` screens -- is one card, `terminal.confirm`, drawn where
its screen asks it: a blank line, the question in the normal colour, one dim
line saying what the answer means, the two choices, and a blank line. The safe
choice is first and highlighted, `✓ Keep`; the one that ends something follows,
`✗ Stop` or `✗ Remove`, in the warn colour (`amber`). ↑/↓, k/j and the wheel
move between them; Enter or a click answers, and Esc, or a click anywhere else,
keeps. On a phone the question and its meaning wrap and a choice never does; a
resize draws the card again where its screen now puts it. From a pipe a
question is still a line ending `[y/N]`.

Helpers: `terminal.confirm`, `terminal.choose`.

Example:
`  Stop fix-api and everything it runs?`
`  2 runs stop with it; ak cannot reopen the session: Stop removes its record.`
`› ✓ Keep`
`  ✗ Stop`.

## The config screen

`c` is a sub-screen in the same frame, headed `agentkit · config`. It is a
matrix read with the keys, so the file is never
opened: every offered model once, under its provider's display name in the
accent, a row of label, harness (dim), then `orch` (`●` on the highlighted
session's, `○` dim elsewhere), `exec` and `review` (`■`/`□`) and `effort` (`‹ xhigh ›`),
then its strength: a bar for each level that model offers, rising in height
(`▂▃▅▆█` for five), filled up to its effort and the rest dim -- blank where
nothing can dim them, and without UTF-8 a `|` for each filled one alone. A model
with one effort shows its word alone, with no bars and no arrows. The columns
stay visible; the harness gives way, then the bars, then the label.
↑/↓, k/j and the wheel move between rows,
←/→ between all four columns; Enter or space on an effort steps it up through
that model's own efforts (`config.efforts`), from the highest round to the
lowest. The highlighted row
is `highlight`'s and its cell is drawn reversed. Enter, space or a click flips a
mark and a click on an effort's arrow steps it; each change is saved at once and
drawn at once, the orchestrator only moves, and the last reviewer stays, saying
so under the rows, its mark shaking (Motion). Under the models `+ add a model`, `Providers` (the config's
providers in their colours, then `+ add` and `− remove`, and `↻ spend a reset`
while a subscription holds one, ←/→ choosing between them, ↓ landing on none
past `− remove`, each a list opening in the frame where it has a choice),
`Discord` (connected or not)
and `Version` (the commit and its date; read, with no action). Enter
or a click on `+ add a model` opens `config · add a model`: `harness`, then
`model`, then `effort`, each a list opening under the one chosen above it, a
chosen one kept as one line; Enter on the effort adds the model and highlights
its row, glowing (Motion), Esc steps back one list. On `Discord` Enter or a click asks its two
secrets on the same keys. The key
line names what the keys do on the cell at hand (`⏎ mark`, `⏎ effort`,
`⏎ open`) and ends `esc back`; Esc or a click on it returns. A
screen too short shows the part the highlight is on. From a pipe, and in a dry
run, it is drawn once. ← from the marks reaches the label, and Enter or a click
there opens `config · <label>`: `model id` and `effort` between the arrows ←→ step
(the id and the effort only through what the harness's catalog lists, the effort
following the id), then `Remove`, whose Enter asks on the question
card under it, `Keep` picked; each value goes under its
label on a phone. Esc returns to the matrix on that model's row. The worker
token's expiry is the tooltip of the provider it is minted for on `Providers`
(`claude worker token expires 2027-09-22 (in 142 days)`), and once it is 14
days away or less, or past, that line stands under the rows whatever the
pointer is on. There is no `i` page: what it said is the key line's now.

Helpers: `terminal.frame` (written over in place while a keyboard has the
screen), `terminal.state_text`, `menu.config_tips`.

## The new-session screen

`n` is `agentkit · new session`. First it asks `Name:`, two spaces into the content column,
`auto` dim in the field, with a blank line and `esc back` below it. Then every model appears
once, with the same configured name and provider heading as on `c`: `Claude`, `ChatGPT`,
and each other provider's display name in the accent style. Each row has `orch` (`●`/`○`)
for the one orchestrator, `exec` and `review` (`■`/`□`) for its two role groups, with its
harness and effort dim beside it. Names are no wider than a third of the screen, a longer
one cut. The defaults are chosen when it opens;
a spent model reads dim with `spent · resets <day HH:MM>`, on a line of its own under the name
where the row does not fit, and is never chosen for him. ↑/↓, k/j and the wheel move between
models and scroll them on a short screen, the role headings kept visible; ←/→ choose the role.
Space or a click chooses, Enter starts from anywhere -- or, with every model spent and a role
still empty, takes the highlight to it -- Esc goes back, and reviewers keep their last
model, its mark shaking (Motion). Executors may be left empty: the orchestrator builds
everything, its own `exec` mark filled and dim on both `n` and `c`. At the Name question, a taken
name asks again and Esc goes back. Enter leaves `new`, then `new-2`, unnamed until its
orchestrator knows the job and gives it the shortest name, at most three words, with
`ak orch rename --auto <name>`. Once named, `--auto` changes nothing, prints the current name and exits 0;
plain `ak orch rename` still renames. A seat can take back its own former name; another seat's
former name stays reserved, with a variant chosen for a rename from Claude. From a pipe `n`
asks `Name (Enter: auto):`, `Orchestrator [opus]:` and `Workers [opus astra]:` a line at a time,
Enter or EOF taking each default.

Helpers: `terminal.Keyboard`, `terminal.field`, `terminal.read_key`, `terminal.highlight`, `terminal.key_spans`,
`menu.model_label`, `menu.model_heading`,
`terminal.toggle` (every mark, here, on `c` and on a project's switches).

Example under `Claude`: `› opus    ●     ■      ■     claude · xhigh`.

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
`j` and `k` turn the pages.

## Usage rows

One row per provider under `usage left`, one column of bars: the provider's
display name, the bar and `NN% left` of its **shared** weekly meter -- the one
every model of it draws on, never a cap one model has to itself -- then, joined
with ` · ` and each only when it applies: `resets <weekday> <HH:MM>` in local
time from that meter (`resets 23 Oct` more than six days out in a window longer
than a week, such as MiMo's 30-day plan; `resets in 3d` when only a duration is
known); `1 reset in hand` (`2 resets in hand`) while the subscription holds
usage-limit resets, which the owner spends on `c`; one `<Model> NN%` note per
scoped cap whose figure differs from the shared one; `? <reason>` in the
adapter's own words when the last probe errored though the meter it read still
stands, or `rate limited` / `unavailable` when the endpoint refused it and the
last reading stood in. No row, heading or note -- here or in `ak usage` -- says
how old a reading is: an open menu probes each provider at most once a minute,
host-wide, the tick does when no menu is open, and Muse's billed probe spends at
most one model call in ten minutes. A row with no
shared week at all -- no reading, or nothing but one model's private cap --
is `—` and the words that say why, never `—` alone. The bar's filled cells are
the company's own colour -- Claude `#D97757`, ChatGPT `#FFFFFF`, Muse `#3E9EFB`,
Grok `#736CD3`, Gemini `#203B9B`, MiMo `#FB8046`, or the provider's
`colour = "#RRGGBB"` in config.toml, else the accent -- until little is left,
whoever's week it is (`menu.fill`, on the whole percent the row prints): amber
from 20% down, red from 5% down; a week with anything left keeps at least one
filled cell, so its red is seen, and the empty cells are dim. On a light
background a light grey is drawn as its mirror tone, so ChatGPT's white reads
black. The rows run red through violet by the hue of that colour, the
near-greys last and lightest first: Claude, MiMo, Muse, Gemini, Grok, ChatGPT. The bar gives way to the
notes first, down to four cells; only then does each note that still will not
fit give way on its own, so a phone keeps every short note it has room for
rather than losing them all with one long one. Everything else a provider knows -- `week
elapsed`, `session`, `headroom`, `budget`, `outlook` --
belongs to `ak usage`, whose table gains a `resets` column reading the same
shared week off the same meter, so the two views can never disagree; the
usage-limit credits that used to hold that heading are `resets held`.

Example: `  Claude    ██████░░░░░░  52% left · resets Fri 14:00 · Fable 41%`.

## Colour

Screens ask for a colour by its role, never by RGB: the accent (section titles,
project headings, the highlight's `›`), `working`, `needs you` (`attention`,
`amber`), `done` (`good`), `FAIL` (red) and `dim` (`waiting`). The one RGB a
screen names is a company's own, on the `c` screen's Providers row and a seat's
bar. There is one palette per background, and `terminal.styled` draws from it:

- dark, `terminal.STATE_STYLES` (Catppuccin Mocha): accent and `working`
  `#89b4fa`, `needs you` `#f9e2af` bold, `done` `#a6e3a1`, `FAIL` `#f38ba8`,
  `dim` `#6c7086` faint.
- light, `terminal.LIGHT` (Catppuccin Latte, its yellow and green darkened so
  every colour reads at 4.9:1 or better on white): accent and `working`
  `#1e66f5`, `needs you` `#9c6314` bold, `done` `#338022`, `FAIL` `#d20f39`,
  `dim` `#6c6f85` faint.

Once per menu start, on a terminal the menu has taken, `terminal.sense` asks what
the terminal is. True colour is drawn when `COLORTERM` says `truecolor` or
`24bit`, or inside tmux -- which drops `COLORTERM`, as ssh does -- when
`tmux display -p '#{client_termfeatures}'` lists `RGB` or `Tc`; otherwise the
nearest of 256 colours, else the eight basic tones, and none under `NO_COLOR`,
`TERM=dumb` or off a terminal. The background is the terminal's answer to OSC 11
within 100 ms: lighter than half way draws the light palette, anything else or
no answer in time the dark one. The answer is read by `sense` and never as a
key: keys typed while it waits are kept for `terminal.read_key`, and an answer
that comes later is swallowed there whole. Every other command draws the dark
palette, in true colour by `COLORTERM` alone.

A seat's tmux bar (`statusbar.py`) is two lines on the terminal's own
background, never tmux's green. Its state chip is dark bold text on that
state's dark colour, which reads on either background; the rest is the
terminal's own text or `dim`, and the orchestrator its company's colour. tmux
cannot say which background a client has, so a light grey company (ChatGPT's
white) is the terminal's own foreground: its mirror tone on a light terminal.

Helpers: `terminal.sense`, `terminal.styled`, `terminal.colour_depth`.

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

## Motion

At rest one thing moves: each working session's `●`, on the main list and in the
popup, eases from `working`'s colour to a tone of it half way to the background
and back every two seconds, every dot in the same phase; its word and everything
else stand still, but the rule while the usage is asked (below). Every animation, this one and those after it, runs on one
clock, `motion.Clock`, and no screen keeps a timer: a screen hands the clock the
cells that move when it draws, and each of the menu's waits -- for a key, for a
second digit, for the stop question's answer -- draws a frame only while
something animates and no key is waiting, at most twenty a second, rewriting only
the cells that changed, so a key is still answered within 100 ms. The pointer
moving onto another row, cell or key-line item is answered at most once a frame
on the same clock, so a flood of its moves is one draw (Keys). A resize
draws the whole screen again before another frame. Nothing moves off a
terminal, under `NO_COLOR` or at eight colours: there the dot stands still.

News moves once and is then still, on the same clock. A row that turns
`needs you` gives its `!` two soft pulses toward the light, 600 ms in all; one
that turns `done` has its `✓` appear bright and settle to `done`'s colour over
400 ms. A usage or tasks bar whose value changes glides to it over 300 ms, an
eighth of a cell at a time, each cell on its own, and its last frame is the bar
as drawn; a task bar's newly filled block lights briefly, and a bar whose value
reaches full -- even one its rounding drew full already -- then sends one light
across it, left to right, the only light on it. Only a change seen while the
menu is up moves: the first draw after opening, one after a resize and one back
from another screen or a notice draw every value as it is (`motion.Clock.look`,
`forget`). The pointer coming onto a usage row is news the same way: one light
crosses its bar, left to right over 400 ms, then it is still, its tick standing
(Keys); resting there sends it again only once the pointer has left and come
back.

A step on an effort on `c` is news too: the bar it fills rises into place over
150 ms, and the one it empties lowers, the rest standing still; a step onto the
model's highest level then sends one light through the word, a letter at a time
left to right, over 600 ms -- once for each step onto it (`motion.rising`,
`motion.shimmering`, `terminal.signal`).

Every mark -- on `c`, on `n` and on a project's switches -- fills when set and
empties when cleared over two frames, 80 ms in all: `□ ▣ ■`, `○ ◉ ●` and back,
the new state saved at the key; without UTF-8 it lands at once. A change ak
refuses -- the last reviewer, a pair that is not allowed, a switch
the project refused -- nudges its mark a cell left, right, left and back over
240 ms, the reason under the rows. A model, provider or subscription just added
on `c` returns highlighted on a soft glow of the accent that fades into the
highlight over a second. Each moves on while the rule glides, and the cell under
the pointer stays lit through it (`terminal.pointed`). A key during any of these
ends it on its last frame and is answered within 100 ms (`terminal.toggle`,
`motion.toggled`, `motion.glowing`, `motion.Clock.touch`, `settle`).

The popup's content fades in once, as it opens: from the background to its
colours over 120 ms, on the same clock. Whatever is drawn in that time -- a
key's draw, at once, or news -- comes up with it, and the popup closes at once,
nothing fading out (`motion.Clock.rise`).

A screen whose content is still being fetched after 150 ms -- a project's feature
switches while their `list` or a `set` is asked, a harness's model catalog on the
`c` screens, the usage `c` on a session and `n` ask before their screens and the main screen
asks every minute -- has a bright segment eight cells long glide along its rule, in
from the left and out at the right every 1.2 s, until it lands; the screen then
draws what came within a frame, its rule still. A fetch shorter than that shows
nothing. Keys are read as ever while it glides, and a `set` is asked off the
screen: a flip before it answers is let go, and one Esc left behind never draws
over a later one. Where the screen waits on the fetch itself -- a catalog, the
usage -- it is drawn again on a resize, Esc or a click on `esc back` goes
back from the wait, the fetch left to finish on its own, and any other key is let
go (`motion.fetching`, `menu.matrix_key`, `menu.waited`).

Helpers: `motion.Clock`, `motion.breathing`, `motion.pulsing`, `motion.settling`,
`motion.gliding`, `motion.glinting`, `motion.rising`, `motion.shimmering`, `motion.fetching`,
`menu.moving`, `menu.waited`, `terminal.faded`, `terminal.fade`, `terminal.signal`.

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
