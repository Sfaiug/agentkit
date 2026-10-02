# agentkit architecture

Each module's knowledge, API, callers and leaks; `tests/test_boundaries.py` counts copies.

## What matters most

- `ak` shows seats as working, needs you or done; `ak run task.md` delivers a merged PR.
  Keep the inside behind those.
- A **seat** is a harness TUI in tmux with `session-<name>.json`.
  A **run** is a task: executor, done-when, review, merge and hand-back,
  in `~/.agentkit/runs/<id>/run.json`.
- State is files under `~/.agentkit`; the `ak watch` cron tick keeps seats and runs going.
  Tests never touch the real ones.
- A harness is a plugin: adapter pair, optional module, config entry. Its names and failure
  words leak into some twenty files.
- `run.py` (13.1k lines) holds most of the run side.

## Entry points

- `bin/ak`: verbs to each module's `main`; `ak` alone is the menu.
- `install.sh`: paths, packages, adapter `install`/`login`/`hooks`, defaults, cron, tmux,
  systemd slice. Leak: its own harness and binary lists.

## agentkit/

- `run.py`: staffing, turns, gates, review, landing, hand-back, provider failures, slots,
  admission and worktrees. Offers `main`, `going`, `pick_models`. For watch, job, gc, orch,
  menu, notify, usage, worker and a hook.
- `record.py`: run.json reads, stop-safe writes, recovery locks, defaults, folders and writer
  identity. Offers `read_state`, `save_state`, `record`, `stop_check`, `process_active`,
  `writing`. For run, job, menu, orch, watch, gc, retention, history and worker.
- `gc.py`: plans and schedules removal of seats, stamps, temps, worktrees, runs and jobs.
  Each harness's `tmp_rule` owns its temps and live sessions; retention deletes.
  `cmd_gc` for bin/ak, run, menu, watch and retention.
- `task.py`: the task file's front matter, done-when groups, size and round refusals; for
  run and job.
- `job.py`: several task files as one job. Hides the receipt (`job.json`), the scheduler,
  each task's ladder (waits, one merge, one rerun), hand-back and relaunch; calls the loop
  as `run.*`; for run (main, status, stop, resume), gc, watch and menu.
- `watch.py`: tick. Hides watch.json, seat errors (harness record, else manifest
  screen rules and words; `stalls`, `auth_expiry`), state (`session_state`, `waiting_on`),
  typing and reviving seats, resuming runs, PR scans, `doctor`. For run, job, orch, menu, notify,
  update, usage, worker and both hooks. Leaks: run.json writes (stall ladder, freeze marks,
  resume passes) and run states (`GOING`).
- `orch.py`: seats. Hides the tmux server, naming and rename, model and account choice,
  launch and resume, the picker, systemd slice and scopes. Offers `main`, `sessions`,
  `listing`, `ensure`, `resume`, `rename` to menu, watch, run, job, notify, usage, update.
  Leaks: rename rewrites watch.json and run.json; binds Claude panes by name.
- `menu.py`: the `ak` screen: redraw, keys, usage bars, `c`. Also owns run listing
  (`run_records`, `tally`) and the seat status bar (`redress`) that watch, run, orch and
  notify import. Leaks: provider colour and name tables; reads `usage.json` itself.
- `config.py`: every `~/.agentkit` path, config.toml, models, providers, accounts, adapter
  scripts and manifests, seat records, their rename chain and file names (`SEAT_FILES`), child
  env. Used by nearly everything.
- `worker.py`: headless turns, preambles, review gate, adapters, silence, auth and process
  cleanup. Offers `turn`, `call`, `kill_marked`, `auth_ok`.
  Used by run, watch, usage, menu, harness. Leak: Claude shell timeout.
- `plan.py`: `ak plan`: a seat's plan, each line an outcome with a check failing on main when
  written, or the owner's eye.
- `hand_in.py`: checks and renders `ak hand-in` findings, disputes and closings, with bounded
  evidence. Worker names the channel; run replays proofs, weighs findings and records
  dropped disputes.
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
- `update.py`: manifest `[update]` upgrades, rollback and agentkit's update (`go_live`).
  For menu, orch, run, watch. Leak: `MuseSnapshot` knows Muse's layout.
- `history.py`: SQLite `history.db` of runs and steps; active duration estimates. For
  run, menu, harness. Leak: parses harness event logs.
- `retention.py`: ownership-safe deletion: markers, `safe`/`busy` evidence, worktree
  cleanup, compression. For gc, run, orch, update, notify. Leaks: Claude and Codex
  config formats.
- `terminal.py`: width, wrapping, colour, keys, `choose`/`ask`/`frame`, state styles, for
  every listing screen (docs/cli-design.md). Used by menu, usage, orch, watch, run, motion.
- `motion.py`: one clock: time, easing, what moves; for menu, orch, terminal.
- `command_help.py`: help text per verb, for bin/ak and each `main`; imports nothing.
- `browser.py`: the shared Chromium stack: units, CDP, MCP, VNC, tab ownership. Used by run,
  watch. Leak: registers its MCP per harness by name.
- `macbridge.py`: `ak fetch` of Mac files: request, inbox, heartbeat, launchd agent. Used
  by bin/ak, menu, install.sh.
- `host.py`: memory, load, CPUs, process/cgroup counters, `alive`, `process_identity`;
  reads only, no agentkit imports. For config, orch, run, job, watch, gc and record.
- `proc_snapshot.py`: read-only /proc inventory; no agentkit imports, so it runs under sudo.
  For gc.
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
  `hooks/opencode-seat/`: OpenCode's plugin, feeding seat-state.sh. Leak: both rebuild
  config.py's seat file names and rename chain.
- `tools/`, called by adapters: `rulebook.py`, `idle-compact.py`, `codex-seat.py`,
  `trust.py`, `catalog.py`, `desktop-mcp.py`.
- `tests/`: one file per behaviour, run straight; `smoke.sh` is the gate, with real calls;
  `fixtures/` holds harness screens and an `echo` adapter. Moving code moves mocks.
- Also: `config.default.toml` (model to harness and provider), `orchestrator.md` (the seat
  rulebook), `templates/`, `browser/`, `docs/`.

## Direction

Planned, one task each.

Run side, out of `run.py`:
- `record`: transition table.
- `turn`: model calls and harness failures.
- `staffing`: executor and reviewer budgets.
- `gate`: commands, suite turns, admission.
- `prompts`: preambles and review contract.
- `rounds`: loop calling the rest.
- `land`: PR, checks, merge.
- `handback`: seat and user notices.

Session side:
- session store: immutable ids, rename as a field.
- a folder per harness: adapter, manifest, plugin, hooks in Python.
- `pane`: tmux capture, typing and sockets.
- `status`: hook facts, screen, notices to the three states.
- `care`: tick passes (resume, revive, nudge, recover).
