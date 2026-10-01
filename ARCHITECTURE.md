# agentkit architecture

Each module: what it hides, offers and who uses it. Leaks are named;
`tests/test_boundaries.py` counts them.

## What matters most

- `ak` shows seats as working, needs you or done; `ak run task.md` delivers a merged PR.
  Keep the inside behind those.
- A **seat** is an orchestrator session: a harness TUI in tmux with `session-<name>.json`.
  A **run** is one task: executor turn, done-when commands, review on another provider,
  merge, hand-back, recorded in `~/.agentkit/runs/<id>/run.json`.
- State is files under `~/.agentkit`; the `ak watch` cron tick keeps seats and runs going.
  Tests never touch the real ones.
- A harness is a plugin: adapter pair, optional module, config entry. Its names and failure
  words still leak into some twenty files.
- `run.py` (13.5k lines) holds most of the run side.

## Entry points

- `bin/ak`: maps a verb to a module's `main`; `ak` alone is the menu.
- `install.sh`: directories, packages, each adapter's `install`/`login`/`hooks`, harness
  defaults, cron, tmux, systemd slice. Leak: its own list of harnesses and binaries.

## agentkit/

- `run.py`: the run loop. Hides staffing, turns, the done-when gate, review rounds, landing,
  hand-back, run.json and its stop-safe write, provider failures, slots, host admission,
  worktrees. Offers `main`, `save_state`/`read_state`, `record` (locked read-change-write,
  preserving unreadable records), `going`, `pick_models`. Used by watch (~60 functions),
  job, gc, orch, menu, notify, usage, worker, retention and a hook.
- `gc.py`: what may go: seat files, compact stamps, temp entries, worktrees, runs and jobs;
  planner, sweep, schedule and `cmd_gc`. Asks each harness's `tmp_rule` for temp ownership
  and live sessions; retention deletes. Used by bin/ak, run, menu, watch and retention.
- `task.py`: the task file's front matter, done-when groups, size and round refusals; for
  run and job.
- `job.py`: several task files as one job. Hides the receipt (`job.json`), the scheduler,
  each task's ladder (waits, one merge, one rerun), hand-back and relaunch; calls the loop
  as `run.*`. Used by run (main, status, stop, resume), gc, watch and menu.
- `watch.py`: tick. Hides watch.json, seat errors (harness record, else manifest
  screen rules and words; `stalls`, `auth_expiry`), state (`session_state`, `waiting_on`),
  typing and reviving seats, resuming runs, PR scans, `doctor`. For run, job, orch, menu, notify,
  update, usage, worker and both hooks. Leaks: run.json writes (stall ladder,
  freeze marks, resume passes; all through `run.record`), run states (`GOING`).
- `orch.py`: seats. Hides the tmux server, naming and rename, model and account choice,
  launch and resume, the picker, systemd slice and scopes. Offers `main`, `sessions`,
  `listing`, `ensure`, `resume`, `rename`. Used by menu, watch, run, job, notify, usage,
  update. Leaks: rename rewrites watch.json and run.json; binds Claude panes by name.
- `menu.py`: the `ak` screen: redraw, keys, usage bars, `c`. Also owns run listing
  (`run_records`, `tally`) and the seat status bar (`redress`) that watch, run, orch and
  notify import. Leaks: provider colour and name tables; reads `usage.json` itself.
- `config.py`: every `~/.agentkit` path, config.toml, models, providers, accounts, adapter
  scripts and manifests, seat records, their rename chain and file names (`SEAT_FILES`), child
  env. Used by nearly everything.
- `worker.py`: headless turns: role preambles, review gate, adapter calls, silence watchdog,
  auth, process markers and cleanup. Offers `turn`, `call`, `kill_marked`, `auth_ok`.
  Used by run, watch, usage, menu, harness. Leak: Claude shell timeout.
- `usage.py`: provider meters, budget, pace, exhaustion, probe cadence, resets,
  `usage.json`. Offers `collect`, `pick_order`, `mark_exhausted`, `render`. Used by run,
  orch, menu, watch, history. Leak: watch and the Muse plugin call its private helpers.
- `usage_probe.py`: one deadline for an adapter usage call and its children. Used by usage
  and muse_usage. Leak: Muse's names.
- `muse_usage.py`: Muse meters from one billed request, cached; run by
  `adapters/muse-usage.sh`. Leak: a harness's code in the core package.
- `notify.py`: Discord webhook, test sink, outbox, a seat's needs/done card and last notice.
  Offers `shaped`, `record`, `transition`. Used by run, job, orch, watch, menu. Leak: calls
  up into menu, run, watch and orch.
- `update.py`: harness upgrades per manifest `[update]`, rollback, agentkit's own
  update (`go_live`). Used by menu, orch, run, watch. Leak: `MuseSnapshot` knows Muse's layout.
- `history.py`: SQLite `history.db` of runs and steps; duration and memory estimates. Used
  by run, menu, harness. Leaks: reads run.json directly; parses harness event logs.
- `retention.py`: ownership-safe deletion: markers, `safe`/`busy` evidence, worktree
  cleanup, compression. Used by gc, run, orch, update, notify. Leaks: Claude and Codex
  config formats; imports run back.
- `terminal.py`: width, wrapping, colour, keys, `choose`/`ask`/`frame`, state styles, for
  every listing screen (docs/cli-design.md). Used by menu, usage, orch, watch, run, motion.
- `motion.py`: one clock: time, easing, what moves; for menu, orch, terminal.
- `command_help.py`: help text per verb, for bin/ak and each `main`; imports nothing.
- `browser.py`: the shared Chromium stack: units, CDP, MCP, VNC, tab ownership. Used by run,
  watch. Leak: registers its MCP per harness by name.
- `macbridge.py`: `ak fetch` of Mac files: request, inbox, heartbeat, launchd agent. Used
  by bin/ak, menu, install.sh.
- `proc_snapshot.py`: read-only /proc inventory; no agentkit imports, so it runs under sudo.
  Used by gc.
- `__init__.py`: empty.

## Harnesses

- `adapters/<h>.sh`, for `claude`, `codex`, `muse`, `grokbuild`, `opencode`, `antigravity`,
  answers `run`, `interactive`, `usage`, `install`, `login`, `auth`, `hooks`, `models`
  (codex adds `reset`); `$AGENTKIT_ACCOUNT` picks the login.
- `adapters/<h>.toml` is the manifest: update, usage, conversation, titles, launch, hooks,
  screen rules, stall/quota/auth/resume words, compact, effort, catalog.
- `agentkit/harness/`: `load(name)` combines manifest and optional plugin `<h>.py`, with
  defaults for conversation, resume, launch, titles, usage, tokens and `tmp_rule`;
  `failure` reads a failed turn or seat in whole `[stall]` words. Used by orch, usage,
  update, run, gc, menu, watch. Leak: orch imports `harness.claude`.

## hooks/, tools/, tests/

- `hooks/seat-state.sh`: every harness's lifecycle hook; writes a seat's `hook-`/`stop-`
  facts. `hooks/orchestrator-stop.sh`: the end-of-turn rule, via run and watch.
  `hooks/opencode-seat/`: OpenCode's plugin, feeding seat-state.sh. Leak: both shell hooks
  rebuild config.py's seat file names and rename chain.
- `tools/`, called by adapters: `rulebook.py`, `idle-compact.py`, `codex-seat.py`,
  `trust.py`, `catalog.py`, `desktop-mcp.py`.
- `tests/`: one file per behaviour, run straight; `smoke.sh` is the gate, with real calls;
  `fixtures/` holds harness screens and an `echo` adapter. Moving code moves mocks.
- Also: `config.default.toml` (model to harness and provider), `orchestrator.md` (the seat
  rulebook), `templates/`, `browser/`, `docs/`.

## Direction

Planned, one task each; none of it is true today.

Run side, out of `run.py`:
- `record`: sole owner of run.json: keys, stop-safe write, transition table.
- `turn`: one model turn, branching on the harness's `failure` and login words.
- `staffing`: who executes and reviews, from budgets.
- `gate`: done-when commands, heavy-suite turns, host admission.
- `prompts`: role preambles and the review contract.
- `rounds`: the loop, ~150 lines calling the rest.
- `land`: PR, checks, merge.
- `handback`: telling the seat and the user, once.

Session side:
- a session store keyed by an immutable id: a rename is one field.
- one folder per harness (adapter, manifest, plugin, hooks), hooks parsed in Python.
- `pane`: tmux capture, typing and sockets.
- `status`: a pure function of hook facts, screen and notices to the three states.
- `care`: the tick's passes (resume, revive, nudge, recover) as a list.
