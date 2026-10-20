# agentkit architecture

## What matters most

- `ak` shows seats as working, needs you, done or idle; `ak run task.md` delivers a merged PR.
  Keep the inside behind those.
- A **seat** is a harness TUI in tmux with `session-<name>.json`.
  A **run** is a task: executor, done-when, review, merge and hand-back,
  in `~/.agentkit/runs/<id>/run.json`.
- State is files under `~/.agentkit`; the `ak watch` cron tick keeps seats and runs going.
  Tests never touch the real ones.
- A harness is a plugin: adapter pair, optional module, config entry. Its names and failure
  words leak into some twenty files.
- `run.py` (3.0k lines) holds most of the run side; `gitcall.py`, `turns.py`, `prompts.py`, `transitions.py`, `staffing.py`, `handback.py`, `roundloop.py` and `deliver.py` are its leaves.

## Entry points

- `bin/ak`: verbs to each module's `main`; `ak` alone is the menu.
- `install.sh`: paths, packages, adapter `install`/`login`/`hooks`, defaults, cron, tmux,
  systemd slice. Leak: its own harness and binary lists.

## agentkit/

- `run.py`: a run's launch and resume, the drive of its loop, and a pull request's review.
  Passed writable workers and automatic review-PR merges park in the line and exit;
  foreground callers and jobs follow records. Forks keep `land`. API: `main`; for watch, job, gc, orch.
- `gitcall.py`: git, gh and tool calls with their stop handling (`Stopped`); Git's own patch and its files (`patch_args`, `patch_files`) for the size gate; the declared suite, rules and front matter read off a checkout; worktrees, leftovers, sandboxes, the reviewer's copy and probe checkouts; the run's child environment and logger. The base every leaf of `run.py` calls.
- `sentences.py`: the merge driver every ak git call that merges names for `*.md` (`gitcall.merge_config`): Markdown merged sentence by sentence, a clash inside one sentence left as git's line merge leaves it. Git runs it as a script; it imports nothing of ak's.
- `turns.py`: one model turn: the call, its retries, the handover when a window is spent, what a harness said instead of an answer, the endings it hands back (`Exhausted`, `Dead`, `Killed`, `Blocked`, `NotNeeded`, `RanDry`, `CannotRun`, `TransientHandover`), a round's turn directories and answer file, the memory cap a scope ran under, the stop of a run's process tree.
- `prompts.py`: what a reviewer is handed and how its hand-in is weighed: the diff and done-when output, the findings a fixer gets, the replay of earlier findings on a later commit and where a fix left them, the proofs ak runs for a finding, follow-up or dispute, what a fixer's summary becomes, a check's output read into its first failure's line. For run, roundloop, deliver, handback and land.
- `transitions.py`: a run's record between steps: the state words it carries (`going`, `unfinished`, `queued`, `delivery`), the history a run starts and finishes with its sizes, the pass a review saved and when it is void, the parks (exhausted, errored, on a conflict) and their retry ladders, which run supersedes another, the rounds a change spent across its runs and may still spend.
- `staffing.py`: who executes and who reviews a run: the models a session marks for each role, ordered by the usage they have left, the pair a round gets and the refusals when none fits, the hand to the next executor when one spends its window, and the words a run waiting on a reviewer or an exhausted provider shows. For run, job, menu, orch, status, usage and watch.
- `handback.py`: what a run hands back and to whom: the result it writes, the decision it records, a hand-back's words and verdict, the seat it speaks for and the notice it gets, the lock that tells one ending once, a merge's follow-ups, the recovery after a kill or memory cap. For run, roundloop, deliver, gate, gc, job, land, leases, menu, orch, plan, status, stop, watch, worktrees and a hook.
- `roundloop.py`: a task's rounds: the loop's state, the executor's turn and the landing fixer's, a worker's result and its disputes, the work's verification (checks, rules, base proof, a replay), the reviewer's turn and checkout, the same failure twice, the target's failure, the integration (base, patch id, conflicts, parks, aborts, a failed review's fix) and the final check. For run and land.
- `deliver.py`: a run's delivery: the push of its branch, the pull request on it (body, checks, fork rights), the gh calls behind them, the merge and what may merge (documents alone need no review), the landing line a run joins, releases and rejoins, the landing under the repository's lock, and its endings (blocked, on a dependency, a failed landing). For run, job, land and update.
- `gate.py`: run admission (the slot queue and host gates), check commands and host-wide
  heavy-suite turns. API: `slot_lock`, `claim_slot`, `wait_for_slot`, `slot_note`,
  `host_status_line`, `run_done_when`, turn/env helpers, wait notes. For run, land, tests. Leaks: gitcall's `run_child_env`, `dirty_paths`, `run_depth`; turns'
  `memory_cap_note`, `_scope_units`, `OUT_CAP`; handback's `redress_seat`.
- `status.py`: `ak run status`: the run table, one run's details and their dim lines
  (parked, alive, stopped, step, final check). `cmd_status` for run, `parked_line` for
  watch. Reads transitions' state words (`going`, `unfinished`, `delivery`) and handback's
  `handback_reason`.
  Leak: staffing's private `_cached_providers`.
- `stop.py`: stop/clean a run; records its stop before ending processes and releasing
  its checkout. `stop_owned_runs` and `release_session` for orch, `cmd_stop` for menu,
  `marker_pids` for status. `recorded_ending` decides native and hookless turns;
  `ways_out` names parked-run choices. For watch and hooks. Leaks: run lifecycle helpers.
- `worktrees.py`: a run's worktree and local branch: whether they may go (final run, gone
  loop, never ~/code, held for a resume) and the one way they go, `stop_checkout`: the
  repo's `cleanup:` line, git, the directory, the branch. Stop, clean, endings and gc call
  it. `settle_run`, `drop_checkout`, `provably_final` for run and gc.
  Leaks: run's state predicates, `git`, `git_out`, `Stopped`.
- `leases.py`: the tick's collision scan: two live runs of a repository that cannot merge in
  memory over their shared base are recorded, the younger waiting on the older
  (`state/leases/`); a younger build before its review stops there, branch kept (`park`),
  and starts again once the older landed (`restart`), a landed `from:` dropped
  (`landed_with`).
  Reads run records and `transitions.going`.
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
  `cmd_gc` for bin/ak, run, menu, watch and retention; `stop_ended_logins`, the tick's pass
  that has logind stop a login ended a day ago that still runs something, on the server.
- `task.py`: front matter, done-when groups, size counts and round refusals; for
  run and job.
- `job.py`: task files as jobs: `job.json` (no owner's words; each gc pass removes saved
  ones), scheduling, task ladders (waits, merge, rerun), hand-back, relaunch.
  Calls `run.*`; for run, gc, watch, menu.
- `watch.py`: tick passes (`local_passes`), watch.json, seat state, errors, recovery,
  typing receipts, PR scans, after-merge checks, `health:` probes and the weekly audit
  (`tell_audit`). `session_state` and `waiting_on` decide state; hookless stops use
  stop.recorded_ending.
  For run, job, orch, menu, notify, update, usage, worker and hooks.
  Leaks: run.json writes and run state groups.
- `retire.py`: the tick's pass that writes, once a day, a plan line for each feature switch
  on for everyone two weeks, to take out of the code, in the seat whose plan names it, else
  the newest, with the project's own switch list as the line's check. `retire.json` under
  STATE. For watch. Leak: menu's `features_run`, `switch_rows`, `switches_command`; plan's
  `open_lines`, `LINE`, `add`.
- `audit.py`: the weekly audit's week, report and line: the first tick of an ISO week writes
  the board with its largest loss (`scoreboard.loss`) and the line the `audit` seat is told
  (`weekly`); `audit.json` and `audit/<week>.md` under STATE. For watch, whose `tell_audit`
  opens or resumes the seat and types the line.
- `stuck.py`: work nothing moves while it waits, told to the `audit` seat once per stall
  (`scan`, after the week's line): a landing line's check pass three times its line's median
  (`land.passes`), or the run first in line for a slot three times the median wait there of the
  last firsts let in (`gate.first_in_line`), each half an hour at least; `stuck.json` under
  STATE. For watch's `tell_audit`.
- `orch.py`: seats: tmux server, names, models/accounts, launch/resume, picker and systemd placement.
  `main`, `sessions`, `listing`, `ensure`, `resume`, `rename` for menu, watch, run, job,
  notify, usage, update. Sweep saves tagged auxiliary sessions' screens and closes them
  after a day with every pane dead. Leaks: rename rewrites watch.json/run.json; binds Claude panes by name.
- `menu.py`: the `ak` screen: redraw, keys, usage bars, `c` and its models screen; run listing
  (`run_records`, which
  loads `state/run-records.db` once per process and reads and writes only changed runs, and
  `tally`) and a seat's last column, crew and task squares (`seat_tasks`), for watch, run,
  orch, notify, statusbar. Leaks: provider colour and name tables; reads `usage.json` itself.
- `statusbar.py`: a seat's two tmux status lines, line one ending in how many other seats
  need the owner and the click that switches to the first; for orch, watch.
- `config.py`: `~/.agentkit` paths, config.toml, models, providers, accounts, adapters,
  manifests, seat records, rename chain, `SEAT_FILES`, child env, the weekly audit's setting
  (`audit`). Used by nearly everything.
- `worker.py`: headless turns, preambles, review, adapters, silence, auth, cleanup.
  `turn`, `call`, `boxed` checks, `kill_marked`, `auth_ok`.
  Used by run, gate, watch, usage, menu, harness. Leak: Claude shell timeout.
- `plan.py`: `ak plan`, checked outcomes; a merged run writes its review follow-ups here.
- `box.py`: credential masks, own temporary places and /run, PID teardown. `command`, `check`,
  `returncode`, `leftovers`, `cpu_seconds`; for worker and run.
- `guard.py`: what a seat may not do and its refusal -- tmux end or type into another seat
  (`refusal`), `gh pr merge` (`gh_refusal`), `git worktree add` into ~/code (`worktree_refusal`),
  scp/rsync/sftp a transfer to the live server (`transfer_refusal`); `tools/shim` hands `main`
  the argv, `REFUSALS` dispatches by tool, and `install_shim` links each `tools/<name>-shim` as
  `<HOME>/bin/<name>`.
- `hand_in.py`: checks and renders `ak hand-in` findings, disputes and closings with bounded
  evidence; worker names the channel; run replays proofs, weighs findings, drops disputes.
- `usage.py`: provider meters, budget, pace, exhaustion, probe cadence, resets,
  `usage.json`, and what a week holds in tokens (`capacity.json`). Offers `collect`,
  `pick_order`, `mark_exhausted`, `record_pairs`, `render`. Used by run,
  orch, menu, watch, history. Leak: watch and Muse call its private helpers.
- `logins.py`: when each subscription's login ends and whose it is, asked of the adapters'
  `login-end` hourly by the tick (one ending within 7 days every tick), kept in
  `logins.json`; one ending within 3 days pages the owner once a local day. `refresh`,
  `read`, `remind`, `ending`, `harness`.
- `usage_probe.py`: one deadline for an adapter usage call and its children. For usage
  and `harness/muse_usage.py` (Muse meters from one billed request, cached; run by
  `adapters/muse-usage.sh`). Leak: Muse's names.
- `boards.py`: the public boards' rows (Artificial Analysis, Arena, LiveBench), each asked at
  most once a day into `state/boards.json`. Offers `collect`, `split_effort`, `lines`. Used by
  matrix.
- `matrix.py`: the matrix: a row per model and effort the installed harnesses offer, with the
  boards' numbers, scored per role (`ROLES`), the cheapest as good as the best (`within`)
  recommended, ak's own numbers (`live`); `ak models`. Offers `rows`, `scored`, `recommended`,
  `rank`, `live`. For bin/ak.
- `notify.py`: Discord webhook, test sink, outbox, a seat's needs/done card and last notice.
  Offers `shaped`, `record`, `transition`, `page` (about no seat). Used by run, job, orch,
  watch, menu, logins. Leak: calls
  up into menu, run, watch and orch.
- `update.py`: `[update]` upgrades, rollback (a versioned reinstall, or the harness's own
  `snapshot`); `go_live` once `tests/live.sh` passed. Used by menu, orch, run, watch.
- `history.py`: SQLite `history.db`: runs, their steps and waits (`phase`, `phases`), reviews with round, verdict and effort, the owner's seatless moments (`owner_time`) and dones by conversation (`done`) from notify; `ended_runs`, `merged`, `parks` (`parked_at`), `owner`, `dones` for the scoreboard, `reviewed_runs` for the matrix.
  For run, gate, harness. Leak: parses harness event logs.
- `scoreboard.py`: two weeks of work, ak's cost, committed size, the merged changes that broke after review (`broke`), who built them (`built`), what the park held (`parks`), the tokens that bought no merge (`sunk`), the owner's time (`owner`) and wait to done (`intent`), the week's largest loss in the vision's order (`loss`), words and wrapping.
  `compute`, `render` for run history.
- `retention.py`: ownership-safe deletion: markers, `safe`/`busy` evidence, worktree
  cleanup, compression; a harness config's stale trust and MCP entries, where its plugin
  says they are (`config_entries`). For gc, run, orch, update, notify.
- `aside_editor.py`: the editor every seat's harness opens its composer in (`$VISUAL`, set
  at launch): asked through a pane option, it keeps the owner's unsent text in a tmux buffer
  for a line of ak's and hands it back; asked nothing, it opens the owner's own. For orch's
  launch and watch; `tools/aside-editor` runs it.
- `pty_relay.py`: nonblocking terminal transport, bounded queues and exit draining.
  `Relay.poll`, `finish`, `close` for `tools/idle-compact.py`; owns the two directions without
  harness or model knowledge.
- `terminal.py`: width, wrapping, colour, keys, `choose`/`ask`/`frame`, state styles, for
  every listing screen. Used by menu, usage, orch, watch, run, motion.
- `motion.py`: one clock: time, easing, what moves; for menu, orch, terminal.
- `command_help.py`: help text per verb, for bin/ak and each `main`; imports nothing.
- `browser.py`: the shared Chromium stack: units, CDP, MCP, VNC, tab ownership; each
  harness's plugin writes the MCP entry (`register_mcp`). For run, watch.
- `macbridge.py`: `ak fetch` of Mac files: request, inbox, heartbeat, launchd agent. For
  bin/ak, menu, install.sh.
- `helper.py`: a Mac (`suite_helper`) runs a sharded suite's pieces in sealed `container` VMs
  while on power: `room`, `start` sends the tree, `piece` (exit `LOST`: lost), `finish`. For gate.
- `host.py`: memory, load, CPUs, pressure, process/cgroup counters, `alive`, `process_identity`,
  and a process's stat and statm (`proc_stat`, `resident_bytes`); reads only, no agentkit
  imports. For config, orch, run, gate, status, job, watch, gc, record, history and worker.
- `proc_snapshot.py`: read-only /proc inventory; no agentkit imports, so it runs under sudo.
  For gc.
- `__init__.py`: empty.

## Harnesses

- `adapters/<h>.sh`, for `claude`, `codex`, `muse`, `grokbuild`, `opencode`, `antigravity`,
  answers `run`, `interactive`, `usage`, `install`, `login`, `login-end`, `auth`, `hooks`,
  `models` (codex adds `reset`); `$AGENTKIT_ACCOUNT` picks the login.
- `adapters/<h>.toml` is the manifest: update, usage, conversation, titles, launch, hooks,
  screen rules, stall/quota/auth/resume words, effort, catalog, contract-check model/effort.
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
  Codex's `ask` is a seat's PreToolUse hook: its question tool asks through `notify`.
  Leak: orch imports `harness.claude`.

## hooks/, tools/, tests/

- `hooks/seat-state.sh`: every harness's lifecycle hook; writes a seat's `hook-`/`stop-`
  facts. `hooks/orchestrator-stop.sh`: the end-of-turn rule, and a done seat's question refused
  before it goes up, via config, handback, stop and watch. `hooks/sub-agent.jq`: what tells both a sub-agent's own prompt or Stop, which they
  leave alone. `hooks/opencode-seat/`: OpenCode's plugin, feeding seat-state.sh. Leaks: the first
  two rebuild config.py's seat file names, and seat-state.sh its rename chain.
- `tools/`: `shim`, the one sh body of every PATH shim -- the real binary is the first on PATH after
  the shim's own; a worker's or seatless call runs it at once (git is hot: no Python start), a
  seat's own asks `agentkit.guard`, which refuses or execs it (tagging tmux new-session) -- with
  `tmux-shim` (refuses ending or typing into another seat; gives what a seat starts its name),
  `gh-shim` (refuses a seat's `gh pr merge`), `git-shim` (refuses a `git worktree add` into
  ~/code) and `scp-shim`/`rsync-shim`/`sftp-shim` (refuse a transfer to the live server) links
  to it, each linked as
  `<HOME>/bin/<name>` first on a seat's PATH; and, called by adapters:
  `rulebook.py`, `idle-compact.py` (every seat's harness runs under it: it looks at the seat
  again when its screen comes to rest, starts moving or its harness exits; it types nothing),
  `codex-seat.py`, `catalog.py`, `desktop-mcp.py`; `aside-editor`, every seat's `$VISUAL`
  (`agentkit/aside_editor.py`).
- `tools/helper/`: helper.py's Mac side: `mac.sh` (probe, known, prepare, run, finish; it
  keeps each repository's history), `piece.sh` (one piece in the VM, offline) and agentkit's own
  suite image `Containerfile`.
- `tools/release.py`: the release kit a project copies to `deploy/release.py` and runs on its
  own host; standalone, imports nothing of agentkit.
- `tests/`: `landing.py` runs the static checks, then offline `smoke.sh` beside
  `every_file.py`, with grouped live output; live `live.sh`; `every_file.py`: imports/cases,
  live memory/CPU admission; `suite_shares.py` picks each mode's checks and shards both.
  `fixtures/`: screens, `echo`,
  `landing.py` lands a crafted run through its line and lander verdict, `sandbox.py`'s
  `Sandbox` is the throwaway ak HOME that in-process tests run in, `tick.py`'s `only_passes` a
  test's tick that runs only the passes it names, and `tick.py` itself smoke's `ak watch`.
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
