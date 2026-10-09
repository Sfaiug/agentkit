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
- `run.py` (11.0k lines) holds most of the run side.

## Entry points

- `bin/ak`: verbs to each module's `main`; `ak` alone is the menu.
- `install.sh`: paths, packages, adapter `install`/`login`/`hooks`, defaults, cron, tmux,
  systemd slice. Leak: its own harness and binary lists.

## agentkit/

- `run.py`: staffing, review, landing, hand-back, failures, worktrees and delivery locks.
  Passed writable workers and automatic review-PR merges park in the line and exit;
  foreground callers and jobs follow records. Forks keep `land`. API: `main`, `going`,
  `pick_models`; for watch, status, job, gc, orch, menu, notify, usage, worker and a hook.
- `gate.py`: run admission (the slot queue and host gates), check commands and host-wide
  heavy-suite turns. API: `slot_lock`, `claim_slot`, `wait_for_slot`, `slot_note`,
  `host_status_line`, `run_done_when`, turn/env helpers and wait notes. For run, land and
  tests. Leaks: run's `run_child_env`, `memory_cap_note`, `dirty_paths`, `OUT_CAP`,
  `redress_seat`, `run_depth`.
- `status.py`: `ak run status`: the run table, one run's details and their dim lines
  (parked, alive, stopped, step, final check). `cmd_status` for run, `parked_line` for
  watch. Reads run's state words (`going`, `unfinished`, `delivery`, `handback_reason`).
  Leak: run's private `_cached_providers`.
- `stop.py`: stop/clean a run; records its stop before ending processes and releasing
  its checkout. `stop_owned_runs` and `release_session` for orch, `cmd_stop` for menu,
  `marker_pids` for status. `recorded_ending` decides native and hookless turns;
  `ways_out` names parked-run choices. For watch and hooks. Leaks: run lifecycle helpers.
- `worktrees.py`: a run's worktree and local branch: whether they may go (final run, gone
  loop, never ~/code, held for a resume) and the one way they go, `stop_checkout`: the
  repo's `cleanup:` line, git, the directory, the branch. Stop, clean, endings and gc call
  it. `settle_run`, `drop_checkout`, `provably_final` for run and gc.
  Leaks: run's state predicates, `git`, `git_out`, `Stopped`.
- `leases.py`: the tick's collision scan: every pair of live runs of a repository merged in
  memory (`git merge-tree`) over the base they share; a pair that cannot merge is written on
  the younger run as waiting on the older, under `state/leases/`; a younger run still before
  its review is stopped there with its branch kept, waiting on the older (`park`, through
  `stop.end`): what the restart to come stands on. Reads run records (`record`), `run.going`
  and the loop's step; ak's commit step (`run.verify_work`) runs the scan itself.
- `land.py`: landing line and passed trees. Lander checks each stack in a scratch
  worktree, keyed by its tree, and wakes parked members to land; only a red member
  leaves to fix itself or hand the failure to its PR's seat. Record changes and the tick
  start fresh passes in the runs slice. Run consumes verdicts and rejoins after fixes or a changed target.
- `record.py`: run.json, stop-safe writes, recovery locks, defaults, folders, writer id,
  and the state words' groups (`ACTIVE`, `FAILED`, `ENDED`, `GOING`). `read_state`,
  `save_state`, `record`, `stop_check`, `process_active`, `writing`. For run, gate, job,
  menu, orch, watch, gc, retention, history and worker.
- `gc.py`: plans/schedules cleanup of seats, stamps, temps, worktrees, runs and jobs.
  Harness `tmp_rule` owns temps and live sessions; retention deletes.
  `cmd_gc` for bin/ak, run, menu, watch and retention.
- `task.py`: front matter, done-when groups, size counts and round refusals; for
  run and job.
- `job.py`: task files as jobs: `job.json` (capped `owner_words` since the seat's last
  launch), scheduling, task ladders (waits, merge, rerun), hand-back, relaunch.
  Calls `run.*`; for run, gc, watch, menu.
- `watch.py`: tick passes (`local_passes`), watch.json, seat state, errors, recovery,
  typing receipts, PR scans, after-merge checks and `health:` probes. `session_state`
  and `waiting_on` decide state; hookless stops use stop.recorded_ending.
  For run, job, orch, menu, notify, update, usage, worker and hooks.
  Leaks: run.json writes and run state groups.
- `retire.py`: the tick's pass that writes, once a day, a plan line for each feature switch
  on for everyone two weeks, to take out of the code, in the seat whose plan names it, else
  the newest, with the project's own switch list as the line's check. `retire.json` under
  STATE. For watch. Leak: menu's `features_run`, `switch_rows`, `switches_command`; plan's
  `open_lines`, `LINE`, `add`.
- `orch.py`: seats. Hides the tmux server, naming and rename, model and account choice,
  launch and resume, the picker, systemd slice and scopes. Offers `main`, `sessions`,
  `listing`, `ensure`, `resume`, `rename` to menu, watch, run, job, notify, usage, update.
  Leaks: rename rewrites watch.json and run.json; binds Claude panes by name.
- `menu.py`: the `ak` screen: redraw, keys, usage bars, `c`; run listing (`run_records`,
  `tally`) and a seat's last column and live runs (`seat_runs`), for watch, run, orch, notify,
  statusbar. Leaks: provider colour and name tables; reads `usage.json` itself.
- `statusbar.py`: a seat's two tmux status lines, line one ending in the owner's other seats
  and the click that switches to one; for orch, watch.
- `config.py`: `~/.agentkit` paths, config.toml, models, providers, accounts, adapters,
  manifests, seat records, rename chain, `SEAT_FILES`, child env. Used by nearly everything.
- `worker.py`: headless turns, preambles, review, adapters, silence, auth, cleanup.
  `turn`, `call`, `boxed` checks, `kill_marked`, `auth_ok`.
  Used by run, gate, watch, usage, menu, harness. Leak: Claude shell timeout.
- `plan.py`: `ak plan`, checked outcomes or the owner's eye; a merged run writes its review follow-ups here.
- `box.py`: credential masks, own temporary places and /run, PID teardown. `command`, `check`,
  `returncode`, `leftovers`; for worker and run.
- `guard.py`: what a seat may not do and its refusal -- tmux end or type into another seat
  (`refusal`), `gh pr merge` (`gh_refusal`), `git worktree add` into ~/code (`worktree_refusal`),
  scp/rsync/sftp a transfer to the live server (`transfer_refusal`); `tools/shim` hands `main`
  the argv, `REFUSALS` dispatches by tool, and `install_shim` links each `tools/<name>-shim` as
  `<HOME>/bin/<name>`.
- `hand_in.py`: checks and renders `ak hand-in` findings, disputes and closings with bounded
  evidence; worker names the channel; run replays proofs, weighs findings, drops disputes.
- `usage.py`: provider meters, budget, pace, exhaustion, probe cadence, resets,
  `usage.json`. Offers `collect`, `pick_order`, `mark_exhausted`, `render`. Used by run,
  orch, menu, watch, history. Leak: watch and Muse call its private helpers.
- `usage_probe.py`: one deadline for an adapter usage call and its children. For usage
  and `harness/muse_usage.py` (Muse meters from one billed request, cached; run by
  `adapters/muse-usage.sh`). Leak: Muse's names.
- `notify.py`: Discord webhook, test sink, outbox, a seat's needs/done card and last notice.
  Offers `shaped`, `record`, `transition`. Used by run, job, orch, watch, menu. Leak: calls
  up into menu, run, watch and orch.
- `update.py`: `[update]` upgrades, rollback (a versioned reinstall, or the harness's own
  `snapshot`); `go_live` once `tests/live.sh` passed. Used by menu, orch, run, watch.
- `history.py`: SQLite `history.db` of runs and steps; `ended_runs` for the scoreboard.
  For run, gate, harness. Leak: parses harness event logs.
- `scoreboard.py`: two weeks of work, ak's cost, committed size, words and wrapping.
  `compute`, `render` for run history.
- `retention.py`: ownership-safe deletion: markers, `safe`/`busy` evidence, worktree
  cleanup, compression; a harness config's stale trust and MCP entries, where its plugin
  says they are (`config_entries`). For gc, run, orch, update, notify.
- `pty_relay.py`: nonblocking terminal transport, bounded queues, ordered injected keys and
  exit draining. `Relay.poll`, `send`, `finish`, `close` for `tools/idle-compact.py`;
  owns the two directions without harness or model knowledge.
- `terminal.py`: width, wrapping, colour, keys, `choose`/`ask`/`frame`, state styles, for
  every listing screen. Used by menu, usage, orch, watch, run, motion.
- `motion.py`: one clock: time, easing, what moves; for menu, orch, terminal.
- `command_help.py`: help text per verb, for bin/ak and each `main`; imports nothing.
- `browser.py`: the shared Chromium stack: units, CDP, MCP, VNC, tab ownership; each
  harness's plugin writes the MCP entry (`register_mcp`). For run, watch.
- `macbridge.py`: `ak fetch` of Mac files: request, inbox, heartbeat, launchd agent. For
  bin/ak, menu, install.sh.
- `host.py`: memory, load, CPUs, pressure, process/cgroup counters, `alive`, `process_identity`,
  and a process's stat and statm (`proc_stat`, `resident_bytes`); reads only, no agentkit
  imports. For config, orch, run, gate, status, job, watch, gc, record, history and worker.
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
  resume, launch, titles, usage, tokens, `tmp_rule`, `snapshot`, `register_mcp`.
  `config_entries`: every plugin's trust and MCP tables. `user_messages`: timed owner input
  without notices or ak typing; `failure`: turn/seat failures in whole `[stall]` words;
  `interrupted`: when the owner ended a turn no hook reported (Claude's Esc); `unanswered`: a
  last prompt nothing answered yet. For orch, usage, update, run, gc, menu, watch, browser,
  retention.
  Codex's `remote_home` owns the private home's address for launch and removal;
  `pairing_home` resolves requested app access by seat name or explicit home path.
  `tools/codex-seat.py` uses those addresses and owns the live socket transport.
  Leak: orch imports `harness.claude`.

## hooks/, tools/, tests/

- `hooks/seat-state.sh`: every harness's lifecycle hook; writes a seat's `hook-`/`stop-`
  facts. `hooks/orchestrator-stop.sh`: the end-of-turn rule, via config, run, stop and
  watch. `hooks/opencode-seat/`: OpenCode's plugin, feeding seat-state.sh. Leaks: the first
  two rebuild config.py's seat file names, and seat-state.sh its rename chain.
- `tools/`: `shim`, the one sh body of every PATH shim -- the real binary is the first on PATH after
  the shim's own; a worker's or seatless call runs it at once (git is hot: no Python start), a
  seat's own asks `python3 -m agentkit.guard`, and only its refusal code stops the call -- with
  `tmux-shim` (refuses ending or typing into another seat), `gh-shim` (refuses a seat's `gh pr
  merge`), `git-shim` (refuses a `git worktree add` into ~/code) and `scp-shim`/`rsync-shim`/
  `sftp-shim` (refuse a transfer to the live server) links to it, each linked as
  `<HOME>/bin/<name>` first on a seat's PATH; and, called by adapters:
  `rulebook.py`, `idle-compact.py`, `codex-seat.py`, `catalog.py`, `desktop-mcp.py`.
- `tools/release.py`: the release kit a project copies to `deploy/release.py` and runs on its
  own host; standalone, imports nothing of agentkit.
- `tests/`: `landing.py` runs offline `smoke.sh` beside `every_file.py`, with grouped
  live output; live `live.sh`; `every_file.py`: imports/cases,
  live memory/CPU admission; `suite_shares.py` shards both. `fixtures/`: screens, `echo`,
  `landing.py` lands a crafted run through its line and lander verdict, `sandbox.py`'s
  `Sandbox` is the throwaway ak HOME that in-process tests run in.
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
