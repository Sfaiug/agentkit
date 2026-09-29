# agentkit architecture

What each module owns and hides, what it offers and who uses it, true today. Where knowledge
has leaked out of its home the map says so; `tests/test_boundaries.py` counts those leaks,
and its `max` counts only go down.

## What matters most

- The outside is deep: `ak` is one screen of seats in three states (working, needs you,
  done); `ak run task.md` carries a task to a merged PR. Keep the inside behind those.
- A **seat** is an orchestrator session: a harness TUI in tmux with `session-<name>.json`.
  A **run** is one task: executor turn, done-when commands, review on another provider,
  merge, hand-back, recorded in `~/.agentkit/runs/<id>/run.json`.
- State is files under `~/.agentkit`, and the `ak watch` cron tick keeps seats and runs
  going. Tests never touch the real ones.
- A harness is meant to be a plugin: an adapter pair, an optional plugin module and one
  config entry. Its names and failure words also live in some twenty other files today.
- `run.py` (14.7k lines) holds nearly the whole run side; `watch.py` also writes run.json.

## Entry points

- `bin/ak`: maps a verb to a module's `main`; `ak` alone is the menu.
- `install.sh`: directories, packages, each adapter's `install`/`login`/`hooks`, harness
  defaults, cron, tmux, the systemd slice. Leak: its own list of harnesses and binaries.

## agentkit/

- `run.py`: the run loop. Hides task parsing, staffing, turns, the done-when gate, review
  rounds, landing, hand-back, run.json and its stop-safe write, provider-failure
  classification, slots and host admission, worktrees, gc and jobs. Offers `main`,
  `save_state`/`read_state`, `record` (a live record's read-change-write under its lock;
  the loop's own saves merge through it), `going`, `pick_models`. Used by watch (about 60
  functions), orch, menu, notify, usage, worker, retention and a hook.
  Leaks: harness failure text in `TRANSIENT`/`OUTAGE`, Claude temp-file gc.
- `watch.py`: the tick. Hides watch.json, reading each manifest's screen rules and words
  (`quotas`, `stalls`, `auth_expiry`), seat state (`session_state`, `waiting_on`), typing
  into and reviving seats, resuming runs, PR scanning, `doctor`. Used by run, orch, menu,
  notify, update, usage, worker and both hooks. Leaks: run.json writes (the stall ladder and
  freeze marks through `run.record`, the resume passes whole), run states (`GOING`).
- `orch.py`: seats. Hides the tmux server, naming and rename, model and account choice,
  launch and resume, the picker, systemd slice and scopes. Offers `main`, `sessions`,
  `listing`, `ensure`, `resume`, `rename`. Used by menu, watch, run, notify, usage, update.
  Leaks: rename rewrites watch.json and run.json; binds Claude panes by name.
- `menu.py`: the `ak` screen: redraw, keys, usage bars, `c`/`m`/`i`. Also owns run listing
  (`run_records`, `tally`) and the seat status bar (`redress`) that watch, run, orch and
  notify import. Leaks: provider colour and name tables; reads `usage.json` itself.
- `config.py`: every `~/.agentkit` path, config.toml, models, providers, accounts, adapter
  scripts and manifests, seat records, their rename chain and file names (`SEAT_FILES`), child
  env. Used by nearly everything. Leaks: the shell hooks rebuild seat file names.
- `worker.py`: one headless turn: role preambles and the review gate text, the adapter `run`
  call, silence watchdog, process kills, auth check. Offers `call`, `kill_marked`,
  `auth_ok`. Used by run, watch, usage, harness. Leak: a Claude-only shell timeout.
- `usage.py`: provider meters, budget, pace, exhaustion, probe cadence, resets,
  `usage.json`. Offers `collect`, `pick_order`, `mark_exhausted`, `render`. Used by run,
  orch, menu, watch, history. Leak: watch and the Muse plugin call its private helpers.
- `usage_probe.py`: one deadline for an adapter usage call and its children. Used by usage
  and muse_usage. Leak: Muse's names.
- `muse_usage.py`: Muse meters from one billed request, cached; run by
  `adapters/muse-usage.sh`. Leak: a harness's code in the core package.
- `notify.py`: Discord webhook, test sink, outbox, the needs/done card and last notice per
  seat. Offers `shaped`, `record`, `transition`. Used by run, orch, watch, menu. Leak:
  calls up into menu, run, watch and orch.
- `update.py`: harness upgrades from each manifest's `[update]`, rollback, agentkit's own
  update (`go_live`). Used by menu, orch, watch. Leak: `MuseSnapshot` knows Muse's layout.
- `history.py`: SQLite `history.db` of runs and steps; duration and memory estimates. Used
  by run, menu, harness. Leaks: reads run.json directly; parses harness event logs.
- `retention.py`: ownership-safe deletion: markers, `safe`/`busy` evidence, worktree
  cleanup, compression. Used by run's gc, orch, update, notify. Leaks: Claude and Codex
  config formats; imports run back.
- `terminal.py`: width, wrapping, colour, keys, `choose`/`ask`/`frame`, state styles, for
  every listing screen (docs/cli-design.md). Used by menu, usage, orch, watch, run.
- `command_help.py`: help text per verb, for bin/ak and each `main`; imports nothing.
- `browser.py`: the shared Chromium stack: units, CDP, MCP, VNC, tab ownership. Used by run,
  watch. Leak: registers its MCP per harness by name.
- `macbridge.py`: `ak fetch` of Mac files: request, inbox, heartbeat, launchd agent. Used
  by bin/ak, menu, install.sh.
- `proc_snapshot.py`: read-only /proc inventory, importing nothing of agentkit so it can run
  under sudo. Used by run.
- `__init__.py`: empty.

## Harnesses

- `adapters/<h>.sh`, for `claude`, `codex`, `muse`, `grokbuild`, `opencode`, `antigravity`,
  answers `run`, `interactive`, `usage`, `install`, `login`, `auth`, `hooks`, `models`
  (codex adds `reset`); `$AGENTKIT_ACCOUNT` picks the login.
- `adapters/<h>.toml` is the manifest: update, usage, conversation, titles, launch, hooks,
  screen rules, stall/quota/auth/resume words, compact, effort, catalog.
- `agentkit/harness/`: `load(name)` merges the manifest and an optional plugin module
  (`claude.py`, `codex.py`, `muse.py`, `opencode.py`, `grokbuild.py`) with a default for
  every hook: conversation, resume, launch, titles, usage, tokens. Used by orch, usage,
  update, run, menu. Leak: orch and run import `harness.claude`.

## hooks/, tools/, tests/

- `hooks/seat-state.sh`: every harness's lifecycle hook; writes a seat's `hook-`/`stop-`
  facts. `hooks/orchestrator-stop.sh`: the end-of-turn rule, via run and watch.
  `hooks/opencode-seat/`: OpenCode's plugin, feeding seat-state.sh. Leak: both shell hooks
  rebuild the seat file names and rename chain config.py owns.
- `tools/`, called by adapters: `rulebook.py` (a seat's rulebook), `idle-compact.py`
  (compacts idle seats), `codex-seat.py`, `trust.py`, `catalog.py`, `desktop-mcp.py`.
- `tests/`: one file per behaviour, run straight; `smoke.sh` is the gate, with real model
  calls; `fixtures/` holds harness screens and an `echo` adapter. Tests patch run internals
  by name, so moving code moves mocks.
- Also: `config.default.toml` (model to harness and provider), `orchestrator.md` (the seat
  rulebook), `templates/`, `browser/`, `docs/`.

## Direction

Planned work, each its own task; none of it is true today.

Run side, out of `run.py`:
- `task`: the task file, front matter, done-when groups, size refusal.
- `record`: sole owner of run.json: keys, the stop-safe write, a transition table.
- `turn`: one model turn; a harness `classify` hook says transient, outage, quota or login.
- `staffing`: who executes and who reviews, from budgets.
- `gate`: done-when commands, heavy-suite turns, host admission.
- `prompts`: role preambles and the review contract.
- `rounds`: the loop, ~150 lines calling the rest.
- `land`: PR, checks, merge.
- `handback`: telling the seat and the user, once.

Session side:
- a session store keyed by an immutable id: a rename is one field.
- one folder per harness: adapter, manifest, plugin and hooks, with hooks parsed in Python.
- `pane`: tmux capture, typing and sockets.
- `status`: a pure function from hook facts, screen and notices to the three states.
- `care`: the tick's passes (resume, revive, nudge, recover) as a list.
