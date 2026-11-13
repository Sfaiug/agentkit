# CLI design

Every screen ak draws speaks this page's one design language, so nobody needs a manual.
`menu.py` draws each with `terminal.py`'s helpers, never its own; what each does lives in its
code and tests.

## Frame

Every screen has the same frame, a notice's (`note`) too. The header is one line: `agentkit`
and the screen's name at the left, the clock at the right. Under it comes one dim rule, the
rows, one blank line, and the key line, always last. On the main screen and on
`c`, the usage sits under the header.
What a key did is said under the rows, dim, after a blank line (`menu.note_lines`), and never
pushes them off: where its lines do not fit, the last says how many more there are. One thing
said of many seats is said once, led by their names, the first ones and how many more where
all do not fit the line.
The rule is ak's one progress indicator. It fills while ak updates itself, and a segment
glides along it while a screen waits on what it shows. Ctrl-b m's popup over a seat has a
rounded, dim border. Helpers: `terminal.header_line`,
`terminal.rule_line`, `terminal.key_line`, `terminal.layout_width`.

Example: `agentkit                                                              14:02`
then `────────────────────────────────────────────────────────────────────────`.

## Width and rhythm

The layout is at most 120 columns wide, and seat content at most 100. A project's name is
bold and flush left, with one blank line between projects and its seats two spaces under it.

Rows are tables. Their columns are fixed, sized once per draw and split by two-space gutters,
never ` · `: number, name, model, state, and a last column that takes the rest.

Nothing is ever cut in the middle of a word, a glyph or a sentence. A column gives way first,
a long line wraps at words, and below 60 columns a row folds onto an indented second line. No
line keeps trailing space. Helpers: `terminal.cut`, `terminal.wrap`, `terminal.pad`,
`terminal.cells`, `terminal.plain`, `terminal.styled`.

Example: `  1  atoll-fix  fable  ● working  ━━━━━╸─────── 2 of 5`.

## Words

Words are plain and explain themselves.

- **Glyphs:** every glyph is followed by its word (`● working`).
- **Marks:** `●`/`○` pick one, `■`/`□` any; on in the accent, off dim (`terminal.toggle`).
- **Models:** a model is named in full, its version included: `Opus 5.5`, `gpt-6.1-sol`
  (`config.model_name`).
- **Subscriptions:** a subscription is named by its provider, with a roman numeral when there
  are several (`Claude II`), never by its account.
- **Ages:** ages read `<1m`, `5m`, `2h` or `3d`, never seconds (`terminal.format_age`).
- **Tasks, runs and estimates:** no screen names a task or a run, and none says when work
  will finish.
- **Progress:** every bar is a seat's progress line; a row's count ends in its tasks going:
  `━━━━╸──── 3 of 8 · 2 tasks` (owner, 11 Nov 2026; `terminal.plan_bar`,
  `terminal.share_line`).

Nothing explains itself on hover. A highlighted row opens its models and squares, never what
its seat said (owner, 9 Nov 2026).

## Characters

A screen draws only characters every terminal draws alike: Windows-1252, which every font
carries, `−≈≤≥`, `●○■□✓▸◂←↑→↓⏎␣`, and Box Drawing and Block Elements, which a terminal draws
itself (`tests/test_boundaries.py`).

## States

Five words are the whole vocabulary for a seat (`terminal.STATES`): `● working`,
`! needs you`, `✓ done`, `○ idle` and `○ out of usage`. `watch.session_state` decides which a seat is, and
every screen reads that, its own bar included. A whole row is never coloured: the word
carries the colour (`terminal.state_text`, `terminal.state_colour`).

## Keys

Every screen reads the same keys, one key at a time, with no Enter.

- **Arrows, Space and Enter:** the arrows move the highlight, a bold row behind an accent `›`
  (`terminal.highlight`), Space marks what it is on, and Enter goes forward (`terminal.keys`).
- **Esc:** Esc goes back, and on the main screen it leaves.
- **A screen's own keys:** its key line (`terminal.keys`) names them after the shared ones.
- **Digits:** a digit opens that seat.
- **Pointer:** a click does what the key would do. The pointer lights what a click there
  would act on, never a second highlight or more words.

A key that does nothing says nothing. Every key is answered within 100 ms.
From a pipe or file the menu reads a line at a time: a key, then Enter. Helpers:
`terminal.Keyboard`, `terminal.read_key`, `terminal.choose`, `terminal.field`,
`terminal.under`.

Example: `↑↓←→ move   ␣ mark   a add a company   esc back`.

## Colour

Colour says where a thing stands. Screens ask for roles, never RGB: `working` is accent,
`needs you` warning, `done` success, `FAIL` and `out of usage` error, `dim`, `idle` and `waiting`
dim; the pointer lights on selection; a bar's chip is on-accent on its state's. A fade nears the
background; lit, the text.

`themes.ROLES` (Go: `terminal/themes.go`) holds both themes; `terminal.sense` picks white on a
light background, else black, and the colour depth, once per start. Under `NO_COLOR` nothing is
coloured.

A company's colour, its provider's `colour` in config.toml else `menu.COLOURS`, colours its
name on `c`; a harness's, from its manifest, its name over its models. Elsewhere it shows only
under the pointer, on its meter, lighting its meter and models.

## Motion

Something moves only while it is worked on, once when it changes, or under the pointer:

- **While work runs:** a working seat's `●` breathes, as do its progress line's tip, its
  tasks' squares and ak's spinner, `▖▘▝▗`.
- **When something changes:** a seat that turns `needs you` pulses, one that turns `done`
  settles, a mark fills or empties through a dim `■`, and a refused change nudges its mark.

Every animation runs on one clock, `motion.Clock`. A key ends an animation on its last frame.
Nothing moves off a terminal or under `NO_COLOR`.

## Other listings

`ak run status`, `ak orch list` and `ak --help` follow the same design: the frame, fixed
columns, and the same state words.
