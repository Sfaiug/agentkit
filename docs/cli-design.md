# CLI design

Every screen ak draws speaks one design language, so nobody needs a manual to read it. This
page is that language. What each screen does exactly lives in the code and its tests:
`menu.py` draws every screen through the helpers `terminal.py` holds, and no screen makes its
own.

## Frame

Every screen has the same frame. The header is one line: `agentkit` at the left with the
screen's name after it, and the clock at the right. Under it comes one dim rule, then the
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

Rows are tables. Their columns are fixed, with two-space gutters, and sized once per draw:
number, name, model, state, and a last column that takes the rest. Columns are separated by
gutters, never by ` · `.

Nothing is ever cut in the middle of a word, a glyph or a sentence. A column gives way first,
a long line wraps at words, and below 60 columns a row folds onto an indented second line. No
line keeps trailing space. Helpers: `terminal.cut`, `terminal.wrap`, `terminal.pad`,
`terminal.cells`, `terminal.plain`, `terminal.styled`.

Example: `  1  atoll-fix  fable  ● working  ━━━━━╸─────── 2 of 5`.

## Words

Words are plain and explain themselves.

- **Glyphs:** every glyph is followed by its word (`● working`), except ⚒ for builds and ◎ for
  reviews.
- **Models:** a model is named in full, its version included: `Opus 5.5`, `gpt-6.1-sol`
  (`config.model_name`).
- **Subscriptions:** a subscription is named by its provider, with a roman numeral when there
  are several (`Claude II`), never by its account.
- **Ages:** ages read `<1m`, `5m`, `2h` or `3d`, never seconds (`terminal.format_age`).
- **Tasks, runs and estimates:** no screen names a task or a run, and none says when work
  will finish.
- **Progress:** a seat's progress is its line and its count (`terminal.plan_bar`):
  `━━━━╸──── 3 of 8`.

Nothing explains itself on hover. What a seat asks, or what it did, opens under its row while
that row is highlighted, and nowhere else.

## States

Five words are the whole vocabulary for a seat (`terminal.STATES`): `● working`,
`! needs you`, `✓ done`, `○ idle` and `◌ out of usage`. `watch.session_state` decides which one a seat is, and
every screen reads that, the seat's own bar included. A whole row is never coloured: the word
carries the colour (`terminal.state_text`, `terminal.state_colour`).

## Keys

Every screen reads the same keys, one key at a time, with no Enter.

- **Arrows and Enter:** the arrows move the highlight between rows, cells and pages, and
  Enter chooses what it is on.
- **Esc:** Esc goes back, and on the main screen it leaves.
- **A screen's own keys:** these are named on its key line, after the shared keys.
- **Digits:** a digit opens that seat.
- **Pointer:** a click does what the key would do. The pointer lights what a click there
  would act on, never a second highlight and never more words.

A key that does nothing is let go without a word. Every key is answered within 100 ms,
because a draw shows what the last read left: nothing is read between a key and its frame.
From a pipe or a file the menu reads a line at a time instead: a key, then Enter. Helpers:
`terminal.Keyboard`, `terminal.read_key`, `terminal.choose`, `terminal.field`,
`terminal.under`.

Example: `↑↓ move   ⏎ open   n new   x stop   c config   esc leave`.

## Colour

Colour says where a thing stands. A screen asks for a colour by its role, never by RGB:

- the accent and `working`, in blue;
- `needs you`, in amber;
- `done`, in green;
- `FAIL` and `out of usage`, in red;
- `dim`.

There is one palette for a dark background, `terminal.STATE_STYLES` (Catppuccin Mocha), and
one for a light background, `terminal.LIGHT` (Catppuccin Latte). `terminal.sense` picks the
palette and the colour depth once per start. Under `NO_COLOR` nothing is coloured.

A company's colour comes from `menu.COLOURS`, or from a provider's `colour` in config.toml,
and colours its name on `c`; a harness's, from its manifest, its name over its models. On the
main screen a company's shows only while the pointer is on its meter, filling it and lighting
each model on that subscription.

## Motion

Something moves only while a model works on it, once when it changes, or under the pointer:

- **While a model works:** a working seat's `●` breathes, and so do the tip of its progress
  line and its tasks' squares.
- **When something changes:** the change moves once. A seat that turns `needs you` pulses,
  one that turns `done` settles, a mark fills over two frames, and a refused change nudges
  its mark.

Every animation runs on one clock, `motion.Clock`. It draws at most twenty frames a second
and rewrites only the cells that changed. A key ends an animation on its last frame. Nothing
moves off a terminal or under `NO_COLOR`.

## Other listings

`ak run status`, `ak orch list` and `ak --help` follow the same design: the frame, fixed
columns, and the same state words.
