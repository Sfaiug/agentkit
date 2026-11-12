# CLI design

Every screen ak draws speaks the one design language on this page, so nobody needs a manual to
read it. What each screen does exactly lives in its code and tests: `menu.py` draws every screen
with `terminal.py`'s helpers, never its own.

## Frame

Every screen has the same frame, a notice's (`note`) too. The header is one line: `agentkit`
and the screen's name at the left, the clock at the right. Under it comes one dim rule, the
screen's rows, one blank line, and the key line, always last. On the main screen and on
`c`, the usage sits under the header.
The rule is ak's one progress indicator. It fills while ak updates itself, and a segment
glides along it while a screen waits on what it shows. The popup that Ctrl-b m opens over a
seat is drawn inside a rounded, dim border. Helpers: `terminal.header_line`,
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
- **Models:** a model is named in full, its version included: `Opus 5.5`, `gpt-6.1-sol`
  (`config.model_name`).
- **Subscriptions:** a subscription is named by its provider, with a roman numeral when there
  are several (`Claude II`), never by its account.
- **Ages:** ages read `<1m`, `5m`, `2h` or `3d`, never seconds (`terminal.format_age`).
- **Tasks, runs and estimates:** no screen names a task or a run, and none says when work
  will finish.
- **Bars:** every bar is a seat's progress line, `━━━━╸──── 3 of 8`
  (`terminal.plan_bar`, `terminal.share_line`).
- **Progress:** a row's count is its plan's, then how many tasks it has in flight, one column
  joined by ` · `: `3 of 8 · 2 tasks`, `no plan yet · 1 task` (owner, 11 Nov 2026). A task
  mostly builds a plan line, so the count never adds them. Short of room, the line gives way
  first, then the tasks. A seat's own bar leaves them to its squares.

Nothing explains itself on hover. A highlighted row opens its models and squares, never what
its seat said (owner, 9 Nov 2026).

## Characters

A screen draws only characters every terminal draws alike: Windows-1252, which every font
carries, `−≈≤≥`, `●○■□✓▸◂←↑→↓⏎␣`, and Box Drawing and Block Elements, which a terminal draws
itself. A terminal borrows any other from whatever font it finds, at another size in each
(`tests/test_boundaries.py`).

## States

Five words are the whole vocabulary for a seat (`terminal.STATES`): `● working`,
`! needs you`, `✓ done`, `○ idle` and `○ out of usage`. `watch.session_state` decides which one a seat is, and
every screen reads that, the seat's own bar included. A whole row is never coloured: the word
carries the colour (`terminal.state_text`, `terminal.state_colour`).

## Keys

Every screen reads the same keys, one key at a time, with no Enter.

- **Arrows, Space and Enter:** the arrows move the highlight, Space marks what it is on,
  and Enter goes forward (`terminal.keys`).
- **Esc:** Esc goes back, and on the main screen it leaves.
- **A screen's own keys:** its key line (`terminal.keys`) names them after the shared ones.
- **Digits:** a digit opens that seat.
- **Pointer:** a click does what the key would do. The pointer lights what a click there
  would act on, never a second highlight and never more words.

A key that does nothing is let go without a word. Every key is answered within 100 ms.
From a pipe or a file the menu reads a line at a time instead: a key, then Enter. Helpers:
`terminal.Keyboard`, `terminal.read_key`, `terminal.choose`, `terminal.field`,
`terminal.under`.

Example: `↑↓←→ move   ⏎ open   n new   c config   esc leave`.

## Colour

Colour says where a thing stands. A screen asks for a colour by its role, never by RGB:

- the accent and `working`, in blue;
- `needs you`, in yellow (orange on light);
- `done`, in green;
- `FAIL` and `out of usage`, in red;
- `dim`, `idle`, `waiting`, in grey.

Each is a colour of `palette.PALETTE` with the text that reads on it. `terminal.sense` picks
the background and colour depth once per start. Under `NO_COLOR` nothing is coloured.

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
