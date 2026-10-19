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
Once the code has moved -- by this update, or by the tick under an open menu -- the
menu starts again with the same seat highlighted as soon as its main screen is up. An open sub-screen, including a typed draft, stays
until the owner comes back. A failed update says why as a notice. On a client,
the detached update starts before ssh connects; the next `ak` takes the new code.
Overlays and dry runs skip it. A screen whose content is still being fetched has a
segment glide along it (Motion). No other screen draws a bar for either.

Helpers: `terminal.header_line`, `terminal.rule_line`, `terminal.key_line`,
`terminal.layout_width`.

Example: `agentkit                                                              14:02`
then `────────────────────────────────────────────────────────────────────────`.

## Width and rhythm

The layout is `min(terminal width, 120)` columns (`terminal.layout_width`);
seat content is capped at 100 (`terminal.content_width`). A project's name is
bold, flush left; one blank line between projects; seat rows two spaces under
their project line. Nothing else is indented.

Example:
`atoll`
`  1  atoll-fix  fable  ● working  ━━━━━╸─────── 2 of 5`.

## The menu at rest

Projects and their seats, and nothing else. A project is a checkout under
`~/code`, or agentkit's own at `~/agentkit` -- so a run's worktree, a
temporary repository under `~/.agentkit/tmp` and a run id are none of them a
heading, and a checkout nobody sits in is not listed, whatever its `AGENTS.md`
says. As soon as its project is known, the orchestrator
files its seat with `ak orch project <checkout>` by checkout name or path. Names match in any
case; an exact match wins, otherwise a name matching several checkouts is refused and lists
the matches. Each launched run then files the seat under the checkout most of its runs belong
to, a run still queued for a slot among them, whether it works in one checkout or across
several from `~/code`; a tie keeps the one it has. A seat with no filing and no run belonging
to a checkout sits under `no project`, and the next draw files it once a run counts. There is
no run row, ever: `ak run status` is where runs are looked up, and the line a
seat's row opens, its tmux bar's second line, is where its tasks show, as squares.

No line counts who needs the owner: each needing row says it, and those projects come
first. A project heading is the checkout's basename in bold and nothing more,
but for a project naming its switches: how many are hidden, dim at the right,
`23 hidden features` (off for everyone; omitted when none or too narrow to fit beside the name),
a row the highlight lands on, drawn `› ACME`.
Enter or a click on it opens `agentkit · ACME`, every feature once with a
`you` and an `everyone` column, `●` on (blue under `you`, green under `everyone`)
and `○` (dim) off, `—` under `you` where
the project does not let you switch it, and one on for everyone on for you too.
It is read with the `c` matrix's keys (`menu.matrix_key`): ↑/↓ move, ←/→ choose
the column, Enter, space or a click flips through the project's `set` at once
and draws the row it answers; a failure is one dim line under the rows, the mark
unchanged and shaking (Motion). Its `list` runs in a thread with a 20 s timeout, asked every minute
and every ten seconds while the screen is open, so neither screen waits on it.
Projects come by name, and under a heading seats in the order they were made,
whatever their word: a seat's number is its place on the screen, 1 at the top,
and a seat made, stopped or removed moves only the ones after it
(`orch.numbered`). A seat's row is one line, and its last column
is its progress line (see Rows are tables) from the session's plan,
`~/.agentkit/state/plan-<session>.md` under its name or any name it was renamed
from (the newest wins), else from its unfinished jobs' tasks, in its word's
colour while it is not at rest, its work waiting in the line to land too
(`working` includes landing: its squares say so), else empty. What the
reason says -- the question the seat asked, `stopped with work open: <line>`,
the done summary, an idle seat's way back in, `session closed: press 2 to
reopen` -- opens under the row (Rows are tables), never beside it. Never `N
running`, and never when the work will finish: the line and its count are a
seat's progress. No screen names a run or a task, and an ended run is its
orchestrator's business.

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
without UTF-8 -- and never offers `j` or `k` for pages: while the seats run to
more than one page it starts with where the owner is, `←  1 / 2  →`, and ← and →,
or a click on either arrow, turn the page, the highlight going to the first
thing it can rest on of the nearest page that way holding one. The place
between the arrows opens nothing.

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
checkouts and tmux session and keeps the seat, its number reopening it. Any
other it asks about
on the question card (Questions), under that seat's row, the rows below moving
down: `Stop <name> and everything it runs?`, then how many runs stop with it
and that the session moves to past sessions, where it reopens where it
stopped; the key line reads `esc back` while it asks. The runs are counted off the draw, so the card is up at
once: `Its runs stop` until the number lands. The key line says `x close` while
a done seat is highlighted (in the popup, while its own seat is done) and `x
stop` otherwise, and a done
seat's tmux bar reads `Ctrl-b m  x close` at the right end of its second line.

A stopped seat has no row under its project: it keeps its number on the past
screen, `p`, which the key line offers as `p past` while there is one. The
screen is `past sessions` over the main screen's rows, one a stopped seat under
its project's heading, numbered on after the live ones in the same order --
number, name, orchestrator, `stopped 2h ago` in the state's column, and its
harness's word where it cannot resume the conversation -- with the keys `↑↓ move   ⏎ reopen   x remove   esc back`: Enter or a
click reopens the highlighted seat where it stopped, as its number does from
the main screen, and the menu is back; `x` removes it at once, the rest
staying up; Esc goes back. From a pipe a number reopens, `x` asks which to
remove by the same numbers, and an empty line goes back. The sweep removes a stopped seat on its
own a week after the stop.

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

Example: `↑↓ move   ⏎ open   n new   x stop   c config   esc leave`.

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

Nobody needs a manual, and nothing explains itself: the pointer lights what it
rests on and the key line stays the keys, on every screen (the owner, 14 Oct
2026: "I dont think hovering should show extra info anywhere"). What a seat asks
or did opens under its row (Rows are tables), and what a subscription's cell has
no room for opens under the grid (Subscriptions); nothing else says more. A state
word, a heading naming no switches, a subscription and a provider's name only
explain: nothing lights on them and a click there does nothing of its own
(`terminal.Spot`). `esc back` means just what it says, so it lights nothing.

## Questions

Every yes-or-no question on a screen read with the keys -- `x` on a seat that
is not done, in the menu and the popup, `Remove` on a model, a provider or a
subscription on the `c` screens, and `Move` on another model's orchestrator mark of a
seat there -- is one card, `terminal.confirm`, drawn where
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
`  2 runs stop with it; the session moves to past sessions, p, where it reopens where it stopped.`
`› ✓ Keep`
`  ✗ Stop`.

## The config screen

`c` is a sub-screen in the same frame, headed `agentkit · config`. Over its page,
on every page, each subscription's meter as the main screen draws it; where over
it they would leave the page fewer than three rows, they lead the page instead
and scroll with it, so the highlighted model's line still has its room. It is a
matrix read with the keys, so the file is never
opened: every offered model once, under its provider's display name in the
accent, a row of label, then `orch` (`●` on the highlighted
session's, `○` dim elsewhere), `builds` and `reviews` (`■`/`□`) and `effort`: a
cell for each level that model offers, full up to its effort and the rest open
and dim, then its word (`▰▰▰▰▱  xhigh`; without UTF-8 `####-`), the words in one
column after the most cells any model has (the owner's pick of 18 Oct 2026). A
model with one effort shows its word alone. A click on a cell takes that level,
and one on the word steps it as Enter does. The columns stay visible; the
cells give way, then the label. A spent model's row is dim.
↑/↓, k/j and the wheel move between rows,
←/→ between all four columns; Enter or space on an effort steps it up through
that model's own efforts (`config.efforts`), from the highest round to the
lowest. The highlighted row
is `highlight`'s and its cell is drawn reversed. Enter, space or a click flips a
mark and a click on an effort's arrow steps it; each change is saved at once and
drawn at once, the orchestrator only moves, and the last reviewer stays, saying
so under the rows, its mark shaking (Motion). Under the rows, above the keys, the highlighted
model's own line says what it runs on (`fable runs on Claude I, II`, dim), why it is spent
(`· spent · resets Mon 02:00`, amber) and, on a seat's, the roles `ak models` recommends it for
(`· recommended to build and review`, dim), each on lines of its own where they do not fit,
as many whole as a short screen holds once the note under it and a row have theirs, the blank
line over it giving way first,
coming up as the highlight comes to it: one place for every model, outside the rows a short screen pages so
none leaves it off, as many lines as the tallest, empty while the highlight is off the models,
so no row moves from under the pointer or the keys. `r recommended` opens the models screen
(The models screen).
Under the models `+ add a model`, `+ add a provider` (a list opening in the
frame), `Discord` (connected or not) and `Version` (the commit and its date; read,
with no action). Each meter over the page is a row the keys reach, ↑ past the
first model, and the pointer too: lit as on the main screen, its line under the
meters, and Enter or a click lists what it offers, `↻ spend a reset` while it
holds one, `sign in again` while its login ends and `− remove`, the highlight
never starting on the spend; offering only `− remove`, it asks at once. A reset
spent, the line under the rows says that subscription's week as its usage row reads it:
`Claude II · 68% left · resets Thu 20:00 (in 2 d 6 h) · lasts at this pace`. Enter
or a click on `+ add a model` opens `config · add a model`: `harness`, then
`model`, then `effort`, each a list opening under the one chosen above it, a
chosen one kept as one line; Enter on the effort adds the model and highlights
its row, glowing (Motion), Esc steps back one list. A list longer than the screen adds
`/ find` to the key line: what is typed after `/` keeps the choices holding it, shown as
`/text` beside the list's name, and Esc lets the whole list back. On `Discord` Enter or a click asks its two
secrets on the same keys. The key
line names what the keys do on the cell at hand (`⏎ mark`, `⏎ effort`,
`⏎ open`) and ends `esc back`; Esc or a click on it returns. A
screen too short shows the part the highlight is on, a row taller than the page a page at a
time: ↑/↓ turn its pages before they leave it. From a pipe, and in a dry
run, it is drawn once. ← from the marks reaches the label, and Enter or a click
there opens `config · <label>`: `model id`, `effort`, `executes at` and `reviews at`
between the arrows ←→ step (the id and each effort only through what the harness's
catalog lists, each effort following the id; the last two read `same`, dim, while
they follow its effort), then `Remove`, whose Enter asks on the question
card under it, `Keep` picked; each value goes under its
label on a phone. Esc returns to the matrix on that model's row. Once the worker
token's expiry is 14 days away or less, or past, it stands under the rows
(`claude worker token expires 2026-10-21 (in 7 days)`). There is no `i` page.

Helpers: `terminal.frame` (written over in place while a keyboard has the
screen), `terminal.state_text`.

## The models screen

`r recommended` on `c` -- the key stands while a matrix is computed and the seat has a
record -- opens `agentkit · models · <seat>`: every model the installed harnesses offer
against the public boards, as `ak models` scores them, with nothing typed. Its first row is
the one knob, `as good as the best: within ‹ 5 ›`: ←/→ step `within` a point, never
under 0, saved to config.toml at once, and the lines under it follow. Then the formula,
each row said with its quality and cost (`opus @ max 100 $8708`): `best`, dim, the row of the
highest quality per role; `as good`, dim, the rows within the knob of it, cheapest first; and
`recommended`, the cheapest as good, said so (`recommended  the cheapest as good: orch opus @
xhigh 97 $4057 · builds opus @ xhigh 96 $4057 · reviews gpt-sol @ max 95 $1082`), then, dim,
what quality and cost are. Under them one model a row, the scored ones first by their best
quality: its config
name, or its id where the config does not run it (dim where no board scores it), its
harness (dim), its effort between the arrows that step it (`‹ xhigh ›`; the word alone with
one effort), its quality per role at that effort out of 100 -- the recommended row's in
`done`'s colour, one as good in the accent, `-` without a score -- and what Artificial
Analysis's index run cost it, in dollars. On a screen too narrow for the table the harness
column gives way, then the cost, then the label is cut: a 40-cell phone shows the model, its
effort and its three numbers. ↑/↓, k/j and the wheel move between the knob, the three lines
that say why (each a row read with no action, so a short screen, where they wrap to more
lines than its page holds, shows each in turn, a page at a time where one is taller than the
page) and the models; ←/→ on a model step the effort its row shows through its own efforts (the
catalog's, and any the boards or the config have it at), the numbers and the cost following,
nothing saved: the effort a model runs at is set on `c`. `r`, or a click on `r take
recommended`, takes the recommendation: the seat's executors and reviewers become the
recommended rows' models at their efforts, the orchestrator only said, and what it could not
do stands under the rows until the next key. The pointer lights the knob's and an effort's
arrows, and a click on one steps it. A screen too short shows the part the highlight is on.
Esc returns to `c`, whose marks show the change. The key line reads `↑↓ move   ←→ effort
r take recommended   esc back`, `←→ as good` on the knob and no arrows on a model with one
effort.

Helpers: `menu.models_body`, `menu.models_screen`, `menu.matrix_key`, `terminal.frame`.

Example: `› opus      claude   ‹ xhigh ›   97   97   97   4000`.

## The new-session screen

`n` opens the new seat's row in its place on the main screen, on the next frame, wherever the
highlight is: last under `no project`, with that heading where none is shown, numbered as the
seat will be once made, every row after it numbered on, its state `new`. Its name cell holds a caret and, dim until a key, the name Enter alone gives it: letters, digits,
`-` and `_` type into it, lower case and at most `orch.NAME_CAP` of them, a space as `-`, and
Backspace takes the last back. The line under it stays open while it is typed, the crew it
starts with as a seat's crew reads (`menu.crew`): the last creation's `[defaults]`, each
with something left to spend (`orch.default_crew`). A taken name, or a crew
no run could start from (`orch.role_refusal`), says why in amber alone on that line, wrapped
whole on a phone, and Enter makes nothing until it changes. The keys read
`⏎ start   tab models   esc back`, each clickable. Enter makes the seat and opens it, filed
under a project once its orchestrator or its runs say which; Esc takes the row back; Tab opens the model picker, which starts from
the row's crew: Enter there starts the seat, Esc goes back to the row. Notices and updates wait
while the row is open. The popup's `n` makes the same row, and its client switches to the new
seat.

The picker is `agentkit · new session`: every model appears once, with the same configured name
and provider heading as on `c`: `Claude`, `ChatGPT`, and each other provider's display name in
the accent style. Each row has `orch` (`●`/`○`) for the one orchestrator, `builds` and `reviews`
(`■`/`□`) for its two role groups, with its harness and effort dim beside it. Names are no wider
than a third of the screen, a longer one cut. The defaults are chosen when it opens; a spent
model reads dim with `spent · resets <day HH:MM>`, on a line of its own under the name where the
row does not fit, and is never chosen for the owner. ↑/↓, k/j and the wheel move between models
and scroll them on a short screen, the role headings kept visible; ←/→ choose the role. Space or
a click chooses, Enter starts from anywhere -- or, with every model spent and a role still
empty, takes the highlight to it -- Esc goes back, and reviewers keep their last model, its mark
shaking (Motion). Executors may be left empty: the orchestrator builds everything, its own
`builds` mark filled and dim on both `n` and `c`. Enter on an empty name leaves a free one-word
name of a Star Wars: The Clone Wars character (`orch.character_name`: `ahsoka`, `rex`), unnamed until its orchestrator knows the job and gives it the shortest name, at most
three words, with `ak orch rename --auto <name>`. Once named, `--auto` changes nothing, prints
the current name and exits 0; plain `ak orch rename` still renames. A seat can take back its own
former name; another seat's former name stays reserved, with a variant chosen for a rename from
Claude. From a pipe `n` asks `Name (Enter: auto):`, `Orchestrator [opus]:` and
`Workers [opus astra]:` a line at a time, Enter or EOF taking each default; a taken name asks
again.

Helpers: `menu.born`, `menu.born_groups`, `menu.born_key`, `terminal.Keyboard`,
`terminal.field`, `terminal.read_key`, `terminal.highlight`, `terminal.key_spans`,
`menu.model_label`, `menu.model_heading`,
`terminal.toggle` (every mark, here, on `c` and on a project's switches).

Example under `Claude`: `› opus    ●     ■      ■     claude · xhigh`.

## Rows are tables

Fixed columns with two-space gutters, sized once per draw from the rows on
screen: number, name, orchestrator, state (glyph and word in the state's
colour), and one last column. Those before the last always fit the screen: the
name and the orchestrator share what the number and the state leave, the longer
giving way first. Each keeps at least eight cells beside the state, or its full
width if shorter; otherwise the state moves below and the labels take the freed
space. The last column, the progress line, takes all
the remaining width; a row with fewer than ten cells left puts it on the indented
line under the row, so no line runs past the screen.
Columns use gutters, never ` · `. Never cut inside a
glyph or a colour sequence. No rendered line keeps trailing space: cell pads
land outside the colour escapes and every row is rstripped, so the snapshots
never pin invisible whitespace.

A working seat's progress takes all the room its last column has, never under
8 cells of line, and is never wrapped or cut: one too long for the column, or a row with
fewer than ten cells left, puts it whole on the indented line under its row. It is a
smooth line of how much of the seat's plan is done, then `done of total`: the done
share is `━` in the state's colour, fading in from half way to the background at the
line's start to the colour at its tip, with a half cell `╸` where the share ends inside
one, and the rest a dim `─` (`terminal.plan_bar`). It says nothing of the tasks in
flight. Without colour the shapes carry it, `━━━━╸──── 3 of 8`, and without UTF-8 it is
`====----- 3 of 8`. A seat's tmux bar draws the same line, its fade included, in 36
cells, narrowing to 24 and then 12 where line one is short of room, before anything is
cut. No screen says when a seat's work will finish:
its progress is its line and its count.

The row the owner points at, with the pointer or ↑/↓, opens its lines under
itself, and only while they point at it: no row has its lines open when the
screen comes up or comes back, nor once the pointer is on no row. They are
indented under the name and lit as the row is (`menu.detail`): the
question for `needs you`, what got done for `done` and an idle seat's way back
in, wrapped whole at words, so a question is read whole on ak's own screen before
its seat is opened, whatever harness it runs; for any other, each model that builds or
reviews named once, dim as the orchestrator column, with ⚒ after it where it builds and ◎ where
it reviews (glyphs without their word, the owner's pick of 18 Oct 2026), and each task in
flight as three squares -- build, review, land -- the stages it reached filled, in
working's colour while a model or ak works on it, dim while it waits, the rest
empty, and a run that ended gone from it, whatever it delivered:
`astra ⚒   opus ⚒◎   ■□□  ■■□  ■■■` (`menu.crew`, `menu.squares`,
`menu.seat_tasks`). No screen names a task. No other row grows: every page
keeps as many lines as the most any seat on screen opens, up to half the screen
and what the headings, a row and the keys leave, a longer question cut to them with `…`, so no page overflows or turns as the
highlight moves. From a pipe there is no highlight, so every row saying
something opens its lines. The orchestrator column is the model, dim: it takes its
company's colour only while the pointer is on the subscription it runs on.

Helpers: `terminal.cut`, `terminal.wrap`, `terminal.pad`, `terminal.cells`,
`terminal.plain`, `terminal.styled`, `terminal.state_text`,
`terminal.state_colour`, `terminal.plan_bar`, `menu.detail`,
`menu.seat_tasks`, `menu.squares`, `menu.crew`.

Example: `  1  atoll-fix  fable  ● working  ━━━━━╸─────── 2 of 5`.

## Narrow screens

Under 60 columns a seat row is two lines or more (number, name, orchestrator
and state, then the last column indented under it). The progress line takes that
line's room and never more; a line too short for a cell of it beside its count
shows the count alone.

Example at 40 columns:
`  1  atoll-fix  fable  ● working`
`    ━━━━━━━━━━━━━━━━──────────────── 2 of 4`.

## Height

Height is budgeted the way width is, leaving one line for the prompt and one
to spare. The usage is always under the header and the key line always last:
with the keyboard it is at the screen's bottom, above the two lines every draw
keeps, wherever the rows end. Seats that do not fit between them turn pages,
whole seat blocks packed under repeated headers, so a seat's lines never split
across pages: one taller than a page is cut to it, its last line ending in `…`.
Rows keep their global numbers. A screen too short for the usage block
and a few rows under it, or too narrow for a name beside each cell's words, folds it to each subscription's reading, whole, in as
many lines as the width takes (`Claude I 17% · ChatGPT 74% · Grok —`); one too
short for that drops the frame and the blank lines too (compact), and only one
with no room for a seat under its heading even then gives up the lines the
highlighted row opens, then cuts the readings, ending in `· …`. On a terminal the
page up is the one the highlight is on and the key line says which (`←  1 / 2  →`),
an arrow amber where a seat that needs the owner is that way; in a pipe it says
`2 / 3`, the page never the part that is cut, and `j` and `k` turn the pages.

## Subscriptions

Right under the rule, a grid of every subscription, three to a line from 105
columns; a provider with `mode = "free"`, as OpenCode's own free models, is no
subscription and is not on it. Each has its name, a ten-cell meter of its **shared** weekly meter -- the one every model of
it draws on, never a cap one model has to itself -- `▰` left and a dim `▱` spent,
and `NN% left`; a spent week says `empty until <when>`, dim, or the credits it
still runs on, which count as usage left. A row
with no shared week at all -- no reading, or nothing but one model's private cap --
is `—` and the words that say why, never `—` alone. No cell's words are cut: the names
give way to the longest. At rest nothing on it has a
company's colour; a subscription whose login ends within 7 days, or has ended, has its
meter (or its words, with none) amber. The rows run red through violet by the hue of that
colour, the near-greys last and lightest first: Claude, MiMo, Muse, Gemini, Grok, ChatGPT.
The pointer on one washes its name and meter in its company's own colour, and
the model of every seat that runs on it with them (Motion) --
Claude `#D97757`, ChatGPT `#FFFFFF`, Muse `#3E9EFB`,
Grok `#736CD3`, Gemini `#203B9B`, MiMo `#FB8046`, or the provider's
`colour = "#RRGGBB"` in config.toml, else the accent; on a light
background a light grey is drawn as its mirror tone, so ChatGPT's white reads
black -- and the blank line under the grid says the rest, joined with ` · ` and
each only when it applies: that login, in amber, `login owner@acme.test ends Mon 26 Oct
04:47 (in 2 days)` or `ended <when>` (`menu.login_notes`), which a short line keeps before
the name, and `click to log in again`: a click there hands the terminal to its harness's
`login again`, and the screen is back as soon as that ends, or once what a failed one said
has been read (`menu.sign_in`); the tick asks an amber login again every time it runs, so
its meter turns grey at the next tick once a new login stands; `resets <weekday> <HH:MM>` in local
time from that meter (`resets 23 Oct` more than six days out in a window longer
than a week, such as MiMo's 30-day plan; `resets in 3d` when only a duration is
known); the credits; `1 reset in hand` (`2 resets in hand`) while the subscription holds
usage-limit resets, which the owner spends on `c`; one `<Model> NN%` note per
scoped cap whose figure differs from the shared one; the 5-hour window; `? <reason>` in the
adapter's own words when the last probe errored though the meter it read still
stands; how old an old reading is (`menu.usage_detail`). Everything else a provider knows -- `week
elapsed`, `session`, `headroom`, `budget`, `outlook` --
belongs to `ak usage`, whose table gains a `resets` column reading the same
shared week off the same meter, so the two views can never disagree. With the
pointer on none of them, the line under the usage, the grid or its folded
readings, in a pipe as with the keyboard, says a worker token that ends within
14 days, dim (`claude worker token expires 2026-10-21 (in 7 days)`), or one that
has, in amber, which every seat then reads as `needs you` (`watch.token_standing`).

Example: `  Claude I    ▰▰▰▰▰▱▱▱▱▱  52% left  ChatGPT     empty until Thu 20:00`.

## Colour

Screens ask for a colour by its role, never by RGB: the accent (section titles,
project headings, the highlight's `›`), `working`, `needs you` (`attention`,
`amber`), `done` (`good`), `FAIL` (red) and `dim` (`waiting`). The one RGB a
screen names is a company's own, on a lit meter and a seat's
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

A seat's tmux bar (`statusbar.py`) is its row on the `ak` screen with the line
under it always open, two lines on the terminal's own background, never tmux's
green, and it never moves. Line one opens with its word: `! needs you` alone a
chip, dark bold text on its amber, the one loud thing on the bar, which reads on
either background; any other word its glyph and word in its colour. Then the
seat's name in bold, the model that orchestrates it in `dim`, never a company's
colour, and its progress line. Line one's right end, while another seat on ak's
server needs you, is how many in needs-you's bold colour, `! 2 other seats need
you`, a click on it switching to the first of them; nothing about working or done
seats. Where it does not fit beside the left part, its progress line narrows
first, then it folds to `! 2 need you`, and only then is the left part cut.

Line two is what the row opens for any seat that is not asking or done: who
builds and who reviews, and each task in flight as its squares (`statusbar.whys`),
for every word, since inside a seat its question or its summary is on its own
screen. Each client draws the first of its versions that fits: all the squares,
then six of them and a count, then the squares alone, then six and a count alone,
then one and a count alone.

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

At rest only what a model works on moves: each working session's `●`, on the main
list and in the popup, the tip of its progress line, and on the line its
highlighted row opens each moving task's square of the stage it is at
(`menu.tips`) ease from `working`'s colour to a tone of it half way to the
background and back every two seconds, all in the same phase; its word and
everything else stand still, but the rule while the usage is asked (below). Every animation, this one and those after it, runs on one
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
400 ms, and one light crosses its progress line, left to right over 400 ms
(`motion.sweeping`). Either way its whole row glows in its word's colour and fades
into the background over a second (`motion.glowing`). The line a row opens as
the highlight comes to it comes up out of the background over 120 ms, and the
rows of a page turned to over 150 ms (`motion.fading`); a question the screen
shows for the first time since it opened writes itself out there instead, a cell
at a time over a third of a second (`motion.writing`). As the menu opens, each
seat's progress line grows from empty to its length over 450 ms, each row 40 ms
after the one above it (`motion.growing`); one whose plan moves glides to its new
length over 700 ms, a light at its head, unless its seat turns done as it moves: then the
done light crosses it, and it is full. Its count moves with it, saying at every frame what
the line shows: from 0 as it grows, and on to a task ticked as it glides (`motion.counting`);
a count whose total changed, or with fewer done, is written at once. On the line the
highlighted row opens, a
task that reaches its next stage fills that square through its half (`□ ▣ ■`) over
150 ms (`motion.halving`); a task first seen stands still. Only a change seen while the
menu is up moves: the first draw after opening, one after a resize and one back
from another screen or a notice draw every value as it is (`motion.Clock.look`,
`forget`).

The pointer coming onto a subscription is news the same way: its name, its meter's
filled cells and the model of every seat that runs on it wash from their grey into
its company's colour, left to right over 300 ms with a light riding the edge, and
drain back right to left over 200 ms once it leaves (`motion.colouring`).

A step on an effort on `c` is news too: each cell it fills lights and settles
over 150 ms, and each it empties stays full but dim for half of that before it
opens, one after another 40 ms apart from the level it left, the rest standing
still; a step onto the model's highest level then sends one light through the
word, a letter at a time left to right, over 600 ms -- once for each step onto
it (`motion.filling`, `motion.shimmering`, `terminal.effort_cells`).

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
colours over 120 ms, on the same clock. Whatever is drawn or moves in that time
-- a key's draw, at once, news, a line growing in -- comes up with it, and the
popup closes at once, nothing fading out (`motion.Clock.rise`). A page comes up the
same way as it opens -- `c`, `p`, a project's features, the models and the
new-session picker -- all but its header and rule: `agentkit` stays and the
page's name writes itself out after it over those 120 ms (`motion.titled`). A
screen gone back to is drawn as it is.

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
go (`motion.fetching`, `menu.matrix_key`, `menu.waited`). Such a screen also says,
where it has room, under what it shows what ak waits on -- `reading the models
opencode offers`, `reading what each subscription has left`, a provider's list, a
reset spent -- a spinner in the accent turning beside it, a glyph every 100 ms
(`⠋⠙⠹…`, `|/-\` without UTF-8); only ak's own waits get one, and a model at work
breathes instead (`motion.spinning`).

Helpers: `motion.Clock`, `motion.breathing`, `motion.pulsing`, `motion.settling`,
`motion.filling`, `motion.shimmering`, `motion.fetching`, `motion.spinning`,
`menu.moving`, `menu.waited`, `terminal.faded`, `terminal.fade`, `terminal.effort_cells`.

## Ages

Ages read `<1m`, `5m`, `2h`, `3d`, never seconds. One helper, used by every
screen.

Helpers: `terminal.format_age`.

Example: `turn running 4h`, `2 running · silent 2h · <task>` — the `ak orch why` telling, not the row.

## States

One state table, `terminal.STATES`, and it is the whole vocabulary: a session
is `● working` (blue), `! needs you` (bold yellow), `✓ done` (green) or `○ idle`
(dim: nothing running, asked or owed), and nothing else exists; a run and a
project read one of the first three. An idle seat sorts last in its project, and
neither a bar's tally nor the top line counts it. `watch.session_state`
decides which, once, and every screen reads that: the menu row, the project
heading, the top line, `ak orch list`, `ak orch why`, `ak run
status`, the seat's own status bar and its window title. A whole row is never
coloured, and the reason for the word lives in the row's last column.

Example: `● working`, `! needs you`, `✓ done`, `○ idle`.

A run, and only a run, can also be parked on something outside itself that lifts
by itself -- a slot, a provider window, a target change, an expired login. Those rows say what
the run waits for instead of a word, dim and under `terminal.STATE_STYLES`'
open circle (`○ waiting for claude login`, `○ waiting`), which is what says
nobody has to act on it, as an idle seat's does. It is no state and no session ever wears it:
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
