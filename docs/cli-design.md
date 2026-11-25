# CLI design

Every screen speaks this page's one design language, so nobody needs a manual.
`menu.py` draws each with `terminal.py`'s helpers, never its own; what each does lives in its
code and tests.

## Frame

Every screen has the same frame, a notice's (`note`) too. The header is one line: `agentkit` and
the screen's name left, the clock right. Under it: one `border` rule,
the rows, one blank line, and the key line, always last. On the main screen and on `c`, the
usage sits under the header.
The rule is ak's one progress indicator. A job ak can count fills it, the header saying how
far (`config · applying 2 of 7`), and the rainbow glides along it while a screen loads.
Ctrl-b m's popup's border is rounded. Helpers:
`terminal.header_line`, `terminal.rule_line`, `terminal.key_line`, `terminal.layout_width`.

Example: `agentkit                                                              14:02`
then `────────────────────────────────────────────────────────────────────────`.

## Width and rhythm

The layout is at most 120 columns, seat content at most 100, and drawn for 40 columns,
"40 cells and wider" (owner, 18 Nov 2026): a line that wraps or misplaces a click below 40 is
no defect and gets no fix. A project's, harness's or company's name is bold, flush left over
its seats, models or subscriptions (`+ add a subscription`'s too), two spaces in; a blank
line parts projects.

Rows are tables of fixed columns, sized once per draw and split by two-space gutters,
never ` · `: number, name, model, state, and a last that takes the rest.

Nothing is cut inside a word, a glyph or a sentence. A column gives way first,
a long line wraps at words, and below 60 a row folds onto an indented second line. No
line keeps trailing space. Helpers: `terminal.cut`, `terminal.wrap`, `terminal.pad`,
`terminal.cells`, `terminal.plain`, `terminal.styled`.

## Words

Words are plain and explain themselves.

- **Glyphs:** each is followed by its word (`● working`).
- **Marks:** `●`/`○` pick one, `■`/`□` any; on in the accent, off dim (`terminal.toggle`).
- **Models:** named in full, version included: `Opus 5.5`, `gpt-6.1-sol`
  (`config.model_name`).
- **Subscriptions:** named by provider, with a roman numeral among
  several (`Claude II`), never by key or account (`config.account_label`).
- **Ages:** `<1m`, `5m`, `2h` or `3d`, never seconds (`terminal.format_age`).
- **Tasks, runs and estimates:** no screen names a task or a run, nor says when work
  will finish.
- **Progress:** every bar is a seat's progress line; every row ends in its tasks going:
  `━━━━╸──── 3 of 8 · 2 tasks` (owner, 11 Nov 2026; `terminal.plan_bar`,
  `terminal.share_line`).

Nothing explains itself on hover. A highlighted row opens its models alone (owner, 9, 17 Nov
2026).

## Characters

A screen draws only characters every terminal draws alike: Windows-1252, which every font
carries, `−≈≤≥`, `●○■□✓▸◂←↑→↓⏎␣`, and Box Drawing and Block Elements, which a terminal draws
itself (`tests/test_boundaries.py`).

## States

Five words are the whole vocabulary for a seat (`terminal.STATES`): `● working`,
`! needs you`, `✓ done`, `○ idle` and `○ out of usage`. `watch.session_state` decides which a seat is, for
every screen, its own bar included. A state never colours its row: the word
carries the colour (`terminal.state_text`, `terminal.state_colour`).

## Keys

Every screen reads the same keys, one at a time, with no Enter.

- **Arrows, Space and Enter:** arrows move the highlight, on selection: a row whole, a cell
  over its width, its row bold (`terminal.highlight`, `terminal.selected`). Space marks what it
  is on; Enter goes forward (`terminal.keys`). A card asking has the highlight.
- **Esc:** goes back; on the main screen it leaves.
- **A screen's own keys:** its key line names them after the shared ones.
- **Digits:** a digit opens that seat.
- **Pointer:** a click does what the key does. The pointer lights what a click acts on,
  never a second highlight. A meter opens its subscription.

A key that does nothing says nothing. Every key is answered within 100 ms.
From a pipe or file the menu reads a key, then Enter. Helpers:
`terminal.Keyboard`, `terminal.read_key`, `terminal.choose`, `terminal.field`,
`terminal.under`.

Example: `↑↓←→ move   ␣ mark   a add a company   esc back`.

## Colour

Screens ask for roles, never RGB, each drawn as its colour alone: `working` is accent,
`needs you` warning, `done` success, `FAIL` and `out of usage` error, `idle` and `waiting` dim; a
seat's bar transparent, its chip on-accent on its state's. Names and numbers are `text`, what tells of
its neighbour `muted`, what the eye skips `dim`, lines `border`, ak's own word `info`; a highlight
keeps them. A fade nears the background; lit, the text; moving, the rainbow (`themes.RAINBOW`).

The terminal's background picks the shades (`themes.ROLES`, Go: `terminal/themes.go`); `NO_COLOR`
colours nothing.

Colour says where a thing stands and never who.

## Motion

Something moves only while worked on, once when it changes, or under the pointer: work breathes,
news pulses, settles or nudges, the highlight glows in, fades out. Each takes
one time (`motion.py`):

- **Coming up:** a row's line, page, card, screens opening.
- **Filling:** a mark, an effort's cell.
- **A light passing:** a done line, an effort's top word.
- **A light going round,** a breath: a line with no plan, a waiting rule.

`motion.Clock` runs them where colour can move; a key ends each on its last frame.

## Other listings

`ak run status`, `ak orch list`, `ak usage` and `ak --help` print once, unframed: fixed columns,
the screens' names, states and colours.
