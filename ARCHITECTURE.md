# agentkit architecture

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
- `run.py` (12.3k lines) holds most of the run side.

## Entry points

- `bin/ak`: verbs to each module's `main`; `ak` alone is the menu.
- `install.sh`: paths, packages, adapter `install`/`login`/`hooks`, defaults, cron, tmux,
  systemd slice. Leak: its own harness and binary lists.

## agentkit/

- `run.py`: staffing, review, landing, hand-back, failures, slots, worktrees and delivery locks.
  Passed writable workers and automatic review-PR merges park in the line and exit;
  foreground callers and jobs follow records. Forks keep `land`. API: `main`, `going`,
  `pick_models`; for watch, job, gc, orch, menu, notify, usage, worker and a hook.
- `gate.py`: check commands and host-wide heavy-suite turns; `run_done_when`, turn/env
  helpers and wait notes. For run and tests. Leaks: run's `run_child_env`, `memory_cap_note`,
  `dirty_paths`, `OUT_CAP`.
- `land.py`: landing line and passed trees. Lander checks each stack in a scratch
  worktree, keyed by its tree, and wakes parked members to land; only a red member
  leaves to fix itself or hand the failure to its PR's seat. Record changes and the tick
  start fresh passes in the runs slice. Run consumes verdicts and rejoins after fixes or a changed target.
- `record.py`: run.json, stop-safe writes, recovery locks, defaults, folders, writer id.
  `read_state`, `save_state`, `record`, `stop_check`, `process_active`,
  `writing`. For run, gate, job, menu, orch, watch, gc, retention, history and worker.
- `gc.py`: plans/schedules cleanup of seats, stamps, temps, worktrees, runs and jobs.
  Harness `tmp_rule` owns temps and live sessions; retention deletes.
  `cmd_gc` for bin/ak, run, menu, watch and retention.
- `task.py`: front matter, done-when groups, size counts and round refusals; for
  run and job.
- `job.py`: task files as jobs: `job.json` (capped `owner_words` since the seat's last
  launch), scheduling, task ladders (waits, merge, rerun), hand-back, relaunch.
  Calls `run.*`; for run, gc, watch, menu.
- `watch.py`: tick, watch.json, errors (harness/manifest; `stalls`, `auth_expiry`),
  state (`session_state`, `waiting_on`), typing receipts by source, revive, resume, PR scans,
  after-merge checks, `health:` probes, `doctor`. For run, job, orch, menu, notify,
  update, usage, worker, hooks.
  Leaks: run.json writes (stalls, freezes, resumes), states (`GOING`).
- `orch.py`: seats. Hides the tmux server, naming and rename, model and account choice,
  launch and resume, the picker, systemd slice and scopes. Offers `main`, `sessions`,
  `listing`, `ensure`, `resume`, `rename` to menu, watch, run, job, notify, usage, update.
  Leaks: rename rewrites watch.json and run.json; binds Claude panes by name.
- `menu.py`: the `ak` screen: redraw, keys, usage bars, `c`; run listing (`run_records`,
  `tally`) and a seat's last column, for watch, run, orch, notify, statusbar. Leaks:
  provider colour and name tables; reads `usage.json` itself.
- `statusbar.py`: a seat's two tmux status lines; for orch, watch.
- `config.py`: `~/.agentkit` paths, config.toml, models, providers, accounts, adapters,
  manifests, seat records, rename chain, `SEAT_FILES`, child env. Used by nearly everything.
- `worker.py`: headless turns, preambles, review, adapters, silence, auth, cleanup.
  `turn`, `call`, `boxed` checks, `kill_marked`, `auth_ok`.
  Used by run, gate, watch, usage, menu, harness. Leak: Claude shell timeout.
- `plan.py`: `ak plan`, checked outcomes or the owner's eye.
- `box.py`: credential masks, PID teardown. `command`, `check`, `returncode`, `leftovers`;
  for worker and run.
- `hand_in.py`: checks and renders `ak hand-in` findings, disputes and closings with bounded
  evidence; worker names the channel; run replays proofs, weighs findings, drops disputes.
- `usage.py`: provider meters, budget, pace, exhaustion, probe cadence, resets,
  `usage.json`. Offers `collect`, `pick_order`, `mark_exhausted`, `render`. Used by run,
  orch, menu, watch, history. Leak: watch and Muse call its private helpers.
- `usage_probe.py`: one deadline for an adapter usage call and its children. For usage
  and muse_usage. Leak: Muse's names.
- `muse_usage.py`: Muse meters from one billed request, cached; run by
  `adapters/muse-usage.sh`. Leak: harness code in the core.
- `notify.py`: Discord webhook, test sink, outbox, a seat's needs/done card and last notice.
  Offers `shaped`, `record`, `transition`. Used by run, job, orch, watch, menu. Leak: calls
  up into menu, run, watch and orch.
- `update.py`: `[update]` upgrades, rollback; `go_live` once `tests/live.sh` passed.
  Used by menu, orch, run, watch. Leak: `MuseSnapshot` knows Muse's layout.
- `history.py`: SQLite `history.db` of runs/steps.
  `ended_runs` for scoreboard. For run, gate, menu, harness. Leak: harness event logs.
- `scoreboard.py`: two weeks of work, ak's cost, committed size, words and wrapping.
  `compute`, `render` for run history.
- `retention.py`: ownership-safe deletion: markers, `safe`/`busy` evidence, worktree
  cleanup, compression. For gc, run, orch, update, notify. Leaks: Claude and Codex
  config formats.
- `terminal.py`: width, wrapping, colour, keys, `choose`/`ask`/`frame`, state styles, for
  every listing screen. Used by menu, usage, orch, watch, run, motion.
- `motion.py`: one clock: time, easing, what moves; for menu, orch, terminal.
- `command_help.py`: help text per verb, for bin/ak and each `main`; imports nothing.
- `browser.py`: the shared Chromium stack: units, CDP, MCP, VNC, tab ownership. For run,
  watch. Leak: registers its MCP per harness by name.
- `macbridge.py`: `ak fetch` of Mac files: request, inbox, heartbeat, launchd agent. For
  bin/ak, menu, install.sh.
- `host.py`: memory, load, CPUs, pressure, process/cgroup counters, `alive`, `process_identity`;
  reads only, no agentkit imports. For config, orch, run, gate, job, watch, gc and record.
- `proc_snapshot.py`: read-only /proc inventory; no agentkit imports, so it runs under sudo.
  For gc.
- `__init__.py`: empty.

## Harnesses

- `adapters/<h>.sh`, for `claude`, `codex`, `muse`, `grokbuild`, `opencode`, `antigravity`,
  answers `run`, `interactive`, `usage`, `install`, `login`, `auth`, `hooks`, `models`
  (codex adds `reset`); `$AGENTKIT_ACCOUNT` picks the login.
- `adapters/<h>.toml` is the manifest: update, usage, conversation, titles, launch, hooks,
  screen rules, stall/quota/auth/resume words, compact, effort, catalog, contract-check model/effort.
- `agentkit/harness/`: `load(name)`: manifest + optional `<h>.py`; defaults: conversation,
  resume, launch, titles, usage, tokens, `tmp_rule`. `user_messages`: timed owner input
  without notices or ak typing; `failure`: turn/seat failures in whole `[stall]` words.
  For orch, usage, update, run, gc, menu, watch. Leak: orch imports `harness.claude`.

## hooks/, tools/, tests/

- `hooks/seat-state.sh`: every harness's lifecycle hook; writes a seat's `hook-`/`stop-`
  facts. `hooks/orchestrator-stop.sh`: the end-of-turn rule, via run and watch.
  `hooks/opencode-seat/`: OpenCode's plugin, feeding seat-state.sh. Leak: both rebuild
  config.py's seat file names and rename chain.
- `tools/`, called by adapters: `rulebook.py`, `idle-compact.py`, `codex-seat.py`,
  `trust.py`, `catalog.py`, `desktop-mcp.py`.
- `tests/`: `landing.py` runs offline `smoke.sh` beside `every_file.py`, with grouped
  live output; live `live.sh`; `every_file.py`: imports/cases,
  live memory/CPU admission; `suite_shares.py` shards both. `fixtures/`: screens, `echo`,
  `landing.py` lands a crafted run through its line and lander verdict.
  `check_harness_contract.py`: standalone live contract check, also smoke's check 3;
  discovers adapter manifests and shares login/quota checks with smoke's later live calls.
- Also: `config.default.toml` (model to harness and provider), `orchestrator.md` (the seat
  rulebook), `templates/`, `browser/`, `docs/`.

## Direction

Planned, one task each.

Run side, out of `run.py`:
- `record`: transition table.
- `turn`: model calls and harness failures.
- `staffing`: executor and reviewer budgets.
- `gate`: admission.
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
