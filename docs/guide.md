# How agentkit works

One interactive orchestrator plans with you and writes task files. Headless workers execute, a different model reviews,
and a script keeps going until the checks pass and the reviewer says PASS; then the run merges its own PR. Wired in:
Claude Code, Codex CLI, Muse Code, Grok Build, OpenCode and Antigravity CLI. Standard library Python 3.11 and bash only.

## The session

A session is a tmux session on agentkit's own server (`tmux -L agentkit`), so it outlives the connection that made it
and the orchestrator's process too. A bare `ak` is the menu on the server, on a client (over the ssh alias `install.sh
--client` recorded) and as the phone key's forced command `ak attach`. A tmux session there that agentkit did not start
and that runs no agent anywhere in its pane, such as a watcher loop, is not a session: no row, no card, no count.

`n` is one screen: an Orchestrator list (one choice) and a Workers list (several). Chosen already: `[defaults]
orchestrator` (shipped `opus`), or while it is spent the first model in config order that is not, and the `[defaults]
workers` (`opus astra`) not spent. From a pipe it asks `Orchestrator:` and `Workers:`, Enter taking each default, and
`--dry-run` starts no session. The seat opens in `~/code`; `ak orch <name>` keeps the shell's directory and reopens an
existing seat. Nobody picks its project: each run it launches refiles it under the project most of its runs belong to,
counting a run from its launch, still queued for a slot or not, for the checkout under `~/code` or `~/agentkit`
(agentkit's own) its task's `repo:` names, else for the one its task's `~/.agentkit/tasks/<project>/` is named for, never
one it merely inherits, and a worktree, sandbox or scratch workspace for nothing; a tie keeps its project. A seat with no
project is filed at the next menu draw or `ak watch` tick once one of its runs counts.

The orchestrator is launched with `orchestrator.md` as its rulebook, plus `~/.agentkit/rules.md` where you wrote one on
this host, handed over by its adapter for that launch only (Antigravity's as the body of an `--agent` definition in
`~/.agentkit/state/antigravity`) and never written into your own `~/.claude`, `~/.codex` or `~/.gemini`. A project's own
`AGENTS.md` or `CLAUDE.md` holds its conventions and is never the place for agentkit's rules.

At every turn's end `hooks/orchestrator-stop.sh` sends the turn back with *Continue: decide the next step and do it*
unless the last paragraph asks something, `ak notify needs` or `ak notify done` was recorded, a run of this seat's is
going, or its `ak wait <session>` names a session that is working; it blocks at most twice a turn. On Claude Code, background work the seat started counts as a run until it reports
back, a bare *shall I continue?* as the last sentence is no question, and a stop sent back reads `working`. A harness
with no blocking end-of-turn hook declares `[stop] enforce = "nudge"`, and the tick types `continue` instead.

Inside a seat `Ctrl-b m` opens the same menu as a popup: a number switches to that session, `n`
starts one, `r` renames this one, `x` stops it -- or, done, closes it at once -- and `q` closes the popup. The seat's status bar reads
`<name> · <orchestrator> → <workers> · <state> · <last column>`, the same values as its menu row, cut with one `…` at 120 columns or where it would reach the key on any client, a phone included, with `Ctrl-b m  menu` on the right (`Ctrl-b m  x close` once it is done), and the
window title is `<name> · <state>`. Agentkit's tmux config is `~/.agentkit/state/tmux.conf`; `~/.tmux.conf` is never read or written.

Every seat compacts alike, whatever its harness: forty minutes after the last turn, with no input since and the context
at or above 40,000 tokens, the harness's own compact command is typed once at a quiet prompt. Workers never compact, nor
does a harness with no compact command or no reported context size; `ak orch list --why` says why.

Any harness can hold the seat: `--model astra` opens Codex, `--model spark` opens Muse. A Claude seat owns its
conversation from launch by a uuid, a Codex seat proves its thread through a launch receipt, an OpenCode seat's plugin
writes its session into one, and Muse and Antigravity open a new conversation each time. A seat whose harness exited
keeps its window. A dead, detached seat nobody has opened for seven days is retired, and a record seven days gone from
tmux is swept, unless a run of the seat's is unfinished or a question in it is unread; then the name is free again.

Stopping a session (`x` on its highlighted row, after its one question under the row, `Keep` or `Stop`; `x` on a done session and `ak orch stop <name>` ask
nothing, so a finished session closes with one `x`) stops every run it launched, removes each run's worktree and local branch, deletes every
state file named for the seat or for a name it had before a rename, rulebook, idle-compact stamps and locks included, edits its open Discord card to `Answered`, and closes the tabs the seat or its
runs opened; the collector takes the stop mark a day later. The remote branch stays for the PR,
and the run directory for its result. `q` leaves a seat running and is not a stop.

## The run

`ak run task.md --bg` is one job: a task file, a worktree, an executor, the checks, a reviewer, fix rounds and a merge.
The orchestrator writes the task from `templates/task.md`: a title, `## Goal`, `## Constraints`, and a `bash` block
under `## Done when` whose every command must exit 0. Optional front matter: `repo` (the launching checkout; `none` is a
scratch workspace), `base` (the repo's default branch), `target` (the branch the PR merges into, default `base`), `from`
(a local branch to cut from), `merge` (`squash`, `merge` or `rebase`), `rounds` (3, the most), `after` (a job
dependency, repeatable). A check ending in `# once` runs only on the commit that ships; the reviewer sees it marked
deferred. The full suite a repository names as `tests:` in its `AGENTS.md` front matter is such a check in every run
there, from the target branch where the checkout predates it, and a done-when line with the same command runs once with it, so a task lists only the checks for its change.
A command that fails runs once more at once, within the same ceiling, and passes if the re-run does: the output keeps
the first failure's last lines under `flaky:`, and a dated line goes into `~/.agentkit/followups/<repo>.md`.
The repository facts the orchestrator keeps in `~/.agentkit/lessons/<repo>.md` ride every prompt, up to 4 KB; past
that, the run's hand-back names the file and asks the orchestrator to tighten it.

One behaviour per task. A launch is refused when the goal has more than three numbered points, the body more than 500
words outside the checks block, the checks more than six commands or `rounds` more than three, whatever `--anyway` says;
and when a run under way in the same repository names the same test or shares four title words, which `--anyway` starts
regardless. Runs have no count cap and wait FIFO while free memory is under the larger of 3 GB and 20% of RAM, load is
above the CPU count, or the nearest limited cgroup is past 75% of its `memory.high` outside reclaimable file cache; a
worker's own test runs share the parent's slot, and a third level is refused. A run that hits its own memory cap, the
smaller of 4 GB and 40% of the slice ceiling unless `run_memory_max_mb` sets it, ends `fail` with `killed: memory cap`.
A job started with `--bg` or relaunched by the tick gives each task, its resume and delivery retry included, its own run
scope and cap; one run from a terminal runs its tasks in its own process.

The worktree is `~/.agentkit/wt/<id>` on branch `ak/<slug>`, the first name free locally and on `origin`. The executor
writes and commits, its commands in the foreground. The loop runs the checks itself and hands the diff and their output
to the reviewer, a different model; it never re-runs them and answers `VERDICT: PASS` or `VERDICT: FAIL`, and one with
no verdict is asked once more, never failed. A round is FAIL only for a blocking finding: a correctness defect, a safety
or data-loss risk, a weakened check, or work outside the task. Everything else goes under `## Follow-ups`; the loop
writes those into the PR description and appends them to `~/.agentkit/followups/<repo>.md`, which the orchestrator reads
before the next task. An item at the `path:line` of an open one, or in its words, is not appended again; a file of the
same name in another case is merged in once; and past 24 KB the oldest items move to `<repo>.archive.md`, which keeps
them all. A FAIL starts a fix round with the findings. Three rounds is the budget: at the third FAIL the run ends
`fail`, hands back its open findings (their first 600 characters) with `three rounds spent: split or re-scope`; no `--rounds` above three starts or resumes, and a job gives it no more rounds and no rerun on another model.

On PASS the run brings the branch up to date with `origin/<target>` (a rebase, or a merge where `merge: merge` is asked
or the branch already carries merge commits), pushes, opens the PR, waits out the required checks and merges it, squash
by default. A clean integration keeps its review if the done-when passes again; an empty one ends PASS. A conflict or a
failing `# once` check gets up to three fixer rounds, never task rounds, then parks `waiting` on the target ref and SHA
until the tick sees it move (a check names its first failing line). A host lands one run per repository and target branch at a time, and that merge turn covers only a fetch, the push, the PR, its required checks and the merge: the
rebase, the done-when and final check re-runs, and every fixer and re-review they need run before it. A target still on
the verified commit lands; one moved only by commits touching none of the branch's files is rebased onto and lands on
the verified checks; any other move releases the turn to verify again, and a third such lap parks `waiting`. A run
queued for the turn shows `waiting for the merge turn of <repo> <branch>`, holding no slot and never read as silent; a
dead holder's turn passes on. A failed integration, conflict or final-check review gets a fixer with the whole review
(and a failing done-when's output) while rounds are left, and at the budget ends `fail` with its findings, or with why
the loop overrode a PASS. A base-branch merge race re-fetches, rechecks the PR head and target, verifies and pushes
changes and retries three times with growing waits before parking. Without push rights it forks, opens the PR upstream
and ends `PASS, not merged: waiting for the maintainer`, exiting 0; the tick follows the PR and hands the decision to the seat. `--no-merge` stops at the verdict. Other ended `merged: no` runs name their reason and exit 1.

A run ends `blocked` when the task is wrong: an executor or fixer ends its turn with `## Blocked` instead of `##
Summary`, or a fix round leaves the same checks failing the same way (or no harness can run it, see Resumption). No
checks, no reviewer, no further round. `result.md` opens `# BLOCKED — <title>`, and the orchestrator writes a new task.

Scheduled errors and merge waits send no ending. Every ending goes to the launching seat as one line typed at its next
quiet prompt: `run <id> finished <PASS merged|PASS not merged|FAIL|BLOCKED|ERROR>: <why>. Result: <path>. Decide the
next step.` A seat mid-turn gets it from the tick; its line is typed once, and one still sitting in the seat's composer
gets only its Enter. A seat that has died is reopened by the run and told `continue <task>`; only when that fails does a
`Needs you` card go to you. A run you launch by hand has no seat: its result is on the terminal and in `ak run status`.
Workers and checks run with `$AGENTKIT_UNATTENDED`, so a run one of them starts belongs to nobody.

Several task files run as one job: `ak run a.md b.md [--parallel N] [--bg]`, one card at the end, receipt in
`~/.agentkit/jobs/<id>/job.json`. An `after:` task starts once its dependencies merged, or at once when the one left has
passed review in its repository: cut from that reviewed tip, which it records, it waits as `waiting for <dep> to merge`, never read as silent, then lands, rebasing only
its own commits (`git rebase --onto <target> <tip>`), so a squash merge cannot conflict. A dependency parked `waiting`
keeps it waiting; one ending unmerged skips it (`skipped: <dep> did not merge`), its branch kept. `repo: none` delivers
files in `~/.agentkit/work/<id>`, which its hand-back names, not a PR. `ak run --review-pr URL` reviews somebody else's
PR with no executor and posts the verdict as a GitHub review. `ak run status` lists every run of the last seven days but
the smoke suite's own, with its round and age; naming one acknowledges it and prints its `result:`, `record:`,
`workspace:` and `continue:` lines. An ending handed back, acknowledged or superseded (by a later merged run of its
title, or a relaunch `from:` its branch) reads `done`, and a job's tasks read their runs as they are now. `ak run` exits 0 on PASS, 1 on FAIL, `exhausted`, `blocked` or an unfinished merge, 2 on error.

A run never waits forever. A check with no output for 20 minutes is killed with everything it spawned and fails the
round; the whole checks list has a six-hour ceiling. A model turn with no harness event for 20 minutes is killed and
retried on the same conversation. Every `git` and `gh` call runs under 120 seconds with prompts disabled; one that stops
ends the run `exhausted` with the remedy, or `pass` with `merge_failed` while the review still stands. Before the first
turn the run adds build junk (`__pycache__/`, `node_modules/`, …) to the repo's `.git/info/exclude`.
`~/.agentkit/env/<repo>.env` is exported into every worker and check for that repo.

### New features in live projects

A hobby project ships straight to live. When a new feature comes up in a repository whose `AGENTS.md` front matter has
no `users:` line, the orchestrator asks once, "Does <project> have real users?", and that feature's first task adds
`users: none` or `users: real`; no line reads as `none`. In a `users: real` repository a new feature merges round by
round behind the project's own switch, on only for you until you turn it on for everyone; only the reviewer is told, and
it fails a round whose new feature is outside the switch or on for anyone else by default. A feature on for everyone for
more than 14 days has its switch taken out by the orchestrator's next task in that project. A project names its switches with one command in the same front matter, `features: <command>`: `<command> list` prints them as JSON (`id`, `name`, `you`, `everyone`, `you_switchable`) and `<command> set <id> you|everyone on|off` flips one, printing the new row or one line on stderr. The menu lists such a project whether or not a session sits in it, as `ACME · 2 hidden features`, and Enter or a click on that heading opens `agentkit · ACME`, where the arrow keys pick a feature and `you` or `everyone` and Enter flips it through `set` at once, while `list` is asked in the background every minute (every ten seconds while that screen is open) and never holds up a draw; the project's own owner page flips the same switches.

## The states and the cards

A session is `● working`, `! needs you` or `✓ done`, and nothing else exists. One function, `watch.session_state`,
decides which, and every screen reads that answer: the menu row, the project heading, the top line, `ak orch list`, `ak
orch why`, the status bar and the window title. A seat's own hook event (a turn begun or ended, a question) decides it again at once, in the background, and an open menu draws again, as recorded, within two seconds of any seat's record changing. Its ladder, top first: a login this harness needs has expired (its own,
or the one a run it launched is parked on, or `gh` while a run owes a push) is `needs you`; the Claude worker token
dying within a fortnight is `needs you` on every seat; a question on its screen, or typed text nobody sent while no client is attached, with no turn in flight, is `needs you` (the question, or `unsent: <text>`) whatever its runs are doing, and with a client attached the typed text is his typing, which reads as the rungs below say; a run it launched that is unfinished is `working`, whether going
or waiting for a slot, window, target change or login the tick lifts by itself, or an error with a scheduled retry, or
parked `stalled`, or `exhausted` on a window or a dead reviewer the tick resumes by itself; a seat that ended its turn on `ak wait <session>` is `working` with `waiting on <session>` while that session itself reads `working` by its own runs or turn, never by a wait of its own, until the tick has told the seat that session stopped (below) or the seat's next `ak wait` or `ak notify`; an error with no automatic resume that
still needs attention (see below), or an `exhausted` run the tick cannot resume (rounds spent, a stopped `git`, no verdict), handed back or not, until `ak run resume <id>` or `ak run stop <id>`, is `needs you` (`run <id> parked: <reason>`); a harness turn in flight is `working`;
nobody in the seat any more is `needs you` with `session closed: press N to reopen`; the seat's own `ak notify done` is
`done` with the summary's first line until a newer notice, however often the session is opened, read or scrolled (a question on its screen, or typed text nobody sent, reads `needs you` over it; a job's `all N tasks finished` is no declaration of the seat's, though its card is still `Done`); otherwise it is at its prompt, which is `needs you`
with the question it asked or `waiting for you`. `ak orch why <seat>` says what decided it, on what evidence, since when.

A row is number, name, orchestrator, state, and one last column: the reason for `needs you` and `done`, and for
`working` the tasks bar (`tasks ██░░░ 2/5`, from `~/.agentkit/state/plan-<session>.md` under the seat's name or any name it was renamed from, the newest such plan winning, else from its unfinished jobs' tasks, and what history says the rest takes: `· ~45m left`, `· ~5h left`, `· ~36d left`) else empty, never `N running`. An
ended run is its orchestrator's business. `needs you` and `done` are messages, and opening the session is reading them.
Runs keep those row words in `ak run status`, with the parked state and its retry on the dim line; a wait that lifts
itself has an open circle (`○ waiting for claude login`), which is not a fourth session state.

Discord hears two things and nothing else. A `needs you` word held for 60 seconds with no client attached sends one
amber `Needs you · <session>` card. A `done` word sends one green `Done · <session>` card, red when the summary starts
with `FAIL`; an unfinished run delays it and a failed run drops the declaration with one log line. One card per episode
and declaration: opening the session edits open needs cards to `Answered`, a done edits them to `Done`, and edits never
ping; an edit Discord did not take stays on the card and is tried again at the next one. No card or retry goes out for
a seat you closed (`x`, `ak orch stop`, a pause script), whose row keeps its number, or an episode begun before this
install (`installed-at` or a fast-forward's newest module; a gone seat's when it went); `ak notify` counts from the
command. A card the webhook could not take is retried from the outbox after 1, 3, 10, 30 and then every 60 minutes.
Ghostty shows a desktop notice when another seat turns `needs you` while you are attached. Workers are refused, and the
test suites' `$AK_NOTIFY_SINK` outranks the webhook, so a test never reaches you. A card whose session is gone, neither a seat nor a saved record any more, or whose record is swept, has its open needs edited to `Answered` on the next tick, and the card goes once Discord has taken every edit.

## The picker

At launch a session's run saves its worker list in `run.json`, names it in status and log, and uses only that list for
every role and handover even if the session changes. Workers rank by budget: the fraction of allowance left plus a week
per reset held, divided by the fraction of window left, using the smallest provider non-session meter. The executor is
highest budget, with Fable preferred only if listed and its meter trails the shared Claude week; the reviewer is highest
budget on another provider, else a different model on the same provider unless its `reviews_own_provider = false`. A
meter at 100% used excludes a worker, and so does a harness not installed or not logged in (no adapter or program, or
its `auth` verb says no, asked at every pick), with one `skipped <model>: <harness> is not logged in` line in the run's
log per pick; `--exec` or `--review` naming one is refused, as is a resume whose saved executor no other model can take
over. An unknown budget ranks last, a pay-as-you-go provider joins only while every subscription that can run is ahead
of pace by more than `pace_margin`, and a run with no eligible pair parks `exhausted`, but a launch no refill can pair
(skipped harnesses, or workers with no allowed pair) is refused, by a `--bg` launch's parent too. The orchestrator choice ignores pace (see `n`; every model spent launches the default with a WARN); a run without a session uses the
default workers. Meters are cached for five minutes and each provider is probed at most once a minute host-wide, a refused worker or a spent reset included (Muse's billed probe once in ten, whatever its meters do); a spent-window
refusal parks the provider until it refills (spending a Codex reset first when held); `ak usage` shows the choices.

## The tick

`ak watch` runs every three minutes from cron on the server, under a lock so ticks never overlap, writing
`~/.agentkit/tmp/watch.log` and rolling it at 5 MB. Each tick: retries the notification outbox; reads every seat's
screen and asks each harness's `auth` verb where a login looks gone; types `continue` into a seat that has shown its
harness's own stall words for three quiet minutes, at most every three minutes, and after an hour of that asks you once;
resumes, relaunches and brings back what Resumption says; types hand-backs waiting on a busy seat; types `<session> is now <word>: <reason>. Decide the next step.` once into a seat whose `ak wait <session>` names a session that has stopped, at the seat's next quiet prompt, which ends that wait for good; closes idle browser
tabs; reviews others' PRs on repos this account owns and follows its own PRs on repos it does not; and once a day asks
the worker-token verb and schedules collection. A logged-out `gh` costs only the two GitHub passes. `ak watch --dry-run`
lists what a tick would do; `ak doctor` shows the slice, the tick's state and any effort a model does not take.

## Resumption

Nothing you launch is lost to a crash. A run whose loop process dies is resumed by the next tick where it stopped,
continuing the harness's own conversation (`claude -p --resume`, `codex exec resume`, Muse's `--session-id`); the first
death resumes at once, a second within ten minutes waits ten, a third within an hour parks the run and tells the seat
once. A job whose launcher dies is relaunched by the next tick in its launch directory, so its waiting tasks start in
order, while that directory is there, its seat's session exists and you did not close it, its launcher was alive (its heartbeat) under 24 hours ago, no unfinished task whose run stopped short of its ending was handed back, carded or
acknowledged, none was stopped, and this is not a third death within an hour; otherwise `ak run status` names `ak run
resume <job>` under it. A run with no output for 20 minutes has its step stopped and the loop carries on; a second
silence resumes the loop with both roles re-picked from its worker list and execution on another provider; a third parks
it `stalled` for `ak run resume <id>`. Quota `exhausted` resumes when its window refills, a reviewer-transport one as
below; other `exhausted` runs wait for `ak run resume <id>`; an expired login parks `waiting_login` until the harness's
`auth` verb answers `yes`. A transient fault (`API Error`, `Overloaded`, a 5xx, an empty answer) retries the same
session after 1, 5, 15, 30 and 60 minutes, then hourly; the tick's silence clock starts where each wait ends. An empty
answer whose stderr (the adapter's own included) says the harness never ran (not installed, an unknown flag or model, a
refused login, even quoted as `API Error`) and names no 5xx, overload or capacity error goes to another provider at
once, or ends the run, a PR review included, `blocked` on that line. A refusal that names the account re-picks both roles by budget from its worker list, same worktree and round.

`ak run resume <id> [--rounds N] [--bg]` resumes the worktree, the worker sessions and the options a run left; it
refuses `blocked` and `stopped`, and needs the worktree, which lives seven days. `ak run merge <id>` retries the
delivery of a PASS whose push or merge did not finish. `ak run stop <id> [--keep]` is the one deliberate end: `stopped`
is final, and `--keep` holds the branch for a task with `from: <branch>`. After a reboot the first tick or menu brings
back Claude and Codex seats with proven conversations, once per boot, but none you closed; the tick tells one that died
mid-turn to continue it, as a run is, over at most three ticks, so it reads `working`, unless you prompted or renamed it.

### When a run goes silent

On `ak run status`'s dim line (`error · retry 14:32`, `waiting · retry after the next merge to origin/main`) an admitted
ending says why: its launch session still exists, it ended under 24 hours ago, and it was not handed back, carded or
acknowledged. Only those endings may be parked from a conflict FAIL or resumed from `error` or `waiting`, an older
tick's waits included; by-hand runs and older endings wait for a person. The tick retries an admitted error on the
ladder above, an `exhausted` run after reviewer transport failures once a reviewer is eligible (at most hourly while it
keeps dying), and an admitted conflict `waiting` after main moves, task rounds spent or not. `ak run status <id>` on a
scheduled error keeps its retry and admission. When admission ends, an error loses its retry stamps, and it or a merge
wait reads `run <id> parked: <reason>` at once, before the tick clears an old stamp. An error with no automatic resume
reads `needs you` only while recent, unacknowledged, neither handed back nor awaiting it, and not superseded; an `exhausted` run the tick cannot resume reads the same, handed back, replaced or old, until `ak run resume <id>` or `ak run stop <id>`, and counts as `needs you` in the tally, never as `running`. A merge
wait that no longer qualifies is inactive history: its row reads `done` with the parked reason, it adds no owner alert or attention tally, neither the stop hook nor the tick counts it as work, and it can still be resumed by hand.

## Cleanup

A merged run's worktree and local branch go with the merge. A stop takes both at once, or with `--keep` the checkout
after seven days. A failed, blocked or errored checkout goes when its seat has been told or after seven days, unless a
resume can take it; its local branch stays until the 30-day removal, because a run that never pushed holds its only copy
there. A pass whose delivery ended without a merge loses its checkout after seven days, its branch kept, and a checkout
with no run record goes after a day. A run directory older than 30 days goes whole, with its checkout and branch, unless
the session that launched it still exists; a scratch run's workspace goes only with it. `~/.agentkit/tmp` entries older
than a day go, finished jobs after a week, and a state file named for a seat with no record, or an idle-compact stamp
whose wrapper is gone, a day after its last write. Trust and MCP entries in `~/.claude.json` and `~/.codex/config.toml`
that point into a gone `smoke-*` sandbox or `~/.agentkit/wt` checkout go in an atomic rewrite of just those entries, in
any layout; a file that does not parse is left alone. The collector writes `~/.agentkit/state/gc.log` and never touches a checkout under `~/code` or a live loop. A checkout goes with its uncommitted work; a tree holding what this user
cannot remove is reported once, on any path, and never retried. `ak run gc --dry-run` gives each item's reason; `ak run
gc` also sweeps every merged worktree, regardless of repository or git registration, and day-old `smoke-*` sandboxes,
reporting count and space freed. The tick takes a leftover merged tree only if clean and registered. A passing smoke suite removes its sandbox; a failed one keeps the newest failed sandbox and removes older ones whose suites ended.

## The config file

`~/.agentkit/config.toml` is copied from the checkout's `config.default.toml` by the first `install.sh` and never
overwritten. The menu's `c` screen changes it at once: `●` and `■` are the `[defaults]`, `‹ xhigh ›` a model's `effort`,
and a model's own screen sets its `model` from the harness's catalog (the effort following to one it lists), `effort`
and `reviews_own_provider`; `Remove` asks first, keeps the last model and the model's `[providers.*]` table even when it
was that company's last. The shipped `opus` model uses Opus 5.5 (`claude-opus-5-5`). The keys:

- `max_runs` (0, no count cap; `ak run status` names the cap in force), `min_free_mb`, `max_load` (0 disables that
  gate), `run_memory_max_mb` (one run's cap in MiB); `AK_MAX_RUNS`, `AK_MIN_FREE_MB` and `AK_MAX_LOAD` override them.
- `max_gates` (3; 0 no cap): done-when gates of one main checkout at once, host-wide, whichever worktree or seat; the rest wait, shown `waiting for a gate turn of <repo>`, the wait charged to neither silence window nor ceiling.
- `pace_margin` (10): the picker's pay-as-you-go margin above. `[defaults]`: `orchestrator` and `workers`; an older
  file's `[tiers]` reads as the first of `A` over `B` without it, and `c` writes `[defaults]` on its next save.
- `[models.<name>]`: `harness`, `model`, `effort` (one that model takes, per `adapters/<h>.sh models`, or `none`), `provider`,
  `reviews_own_provider` (true), `meter` (a meter of its provider that gates only this model).
- `[providers.<name>]`: `mode` (`subscription` or `payg`). MiMo's comes from the global OpenCode `opencode.json`: a
  plain `https://` token-plan URL is a subscription, and anything else -- another host or scheme, a backslash or user
  part, a substitution, `OPENCODE_CONFIG`, a file not plain JSON -- is payg. OpenCode runs with project config off, so
  no workspace changes it. For Muse `usage_model` and `usage_effort`: the one cached request its meters come from.

Secrets are in `~/.agentkit/secrets/`: `discord_webhook`, `discord_user_id` and `claude_oauth_token` (the worker token
`claude setup-token` mints, dated a year from its file). A repository's `AGENTS.md` front matter holds `tests:`, its
full suite, which a review of others' PRs runs as its check, and `users:` (above); task files go by convention in `~/.agentkit/tasks/<repo>/`.

## Adding a model or a harness

Press `c` and pick `+ add a model`: harness, then model, then effort, in the three lists the README describes; Enter
adds it, named from its label and offered as orchestrator and as worker at once. Or write the `[models.<name>]` block.
On `Providers`, `+ add` offers a provider `config.default.toml` has and the config has not, installs a missing harness, logs it in on the terminal, then adds its shipped `[providers.*]` table and first catalog model; `− remove` asks first, `Keep` picked, and a removed provider (`config.remove_provider`) leaves no model, default or usage row; the last stays.

### Adding a harness

A harness is `adapters/<h>.sh`, `adapters/<h>.toml`, and a `[models.<name>]` line naming it. No module outside
`agentkit/harness/` names a harness, so nothing in the core changes when one arrives; `tests/fixtures/adapters/echo.sh`
and `echo.toml` are a whole working harness in two pages. The script implements the verbs: `run <model> <effort>
<workspace> <prompt> <out> [<session>]` (headless; writes `final.md`, `session_id`, `stderr.log`, `events.jsonl`),
`usage` (one JSON object of meters, `error` set rather than a non-zero exit), `auth [seat]` (one line, exit 0 with a
token or 1 with why not; never a network call), `interactive <model> <effort> [<session> [new]]` (the TUI command line,
with the harness's own bypass flag), `hooks` (install its lifecycle hooks idempotently), `models` (an `id<TAB>label<TAB>efforts` line per model, efforts strongest last, `none` for a model that runs at no effort, empty
where the harness does not say: live where the harness lists them, else from its `[catalog]`, which also stands in for a
listing that fails, takes ten seconds or has no `timeout` to stop it), `install` and `login` for a fresh box, and
optionally `reset-status` and `reset` where the provider hands out usage-limit resets. Grok's `auth` passes on a refresh
token, since grok renews its six-hour key itself. Antigravity's `usage` reads the Gemini window of agy's own `/usage`
panel off that panel's endpoint. Refused, both `usage` verbs let their harness renew (`grok models`, `agy models`) and
ask again, and a renewed grok key still refused is `no login` until grok holds another or the endpoint answers it.

`interactive` is where the rulebook goes: `python3 tools/rulebook.py "$AGENTKIT_SESSION"` writes it and prints its path,
and the command line hands it to the harness, adding no instructions of its own, so an orchestrator behaves one way
whatever runs it. A variable the seat's launch sets goes under `[launch] seat_env`, and the core drops it from child
environments. What the harness runs as besides its `[update] version` program, such as Muse's `muse-bin-<build>`, is
named under `[launch] programs`: a tmux session made by hand is a seat only while one of those runs in it.

The manifest is everything else, as data: `[update]` (version, upgrade, revert commands), `[usage]` flags,
`[conversation]` (what a seat owns), `[hooks] installed`, `[stop] enforce`, `[authority]` and `[[hooks.event]]` (which
of hooks and screen decides each live fact), `[screen]` and `[[rule]]` (the composer and dialog patterns read off the
bottom of the pane), `[stall]` (its own words for a fault, a refusal and a spent quota), `[resume]`, `[quota]`, `[auth]`
(title, remedy, signatures), `[compact]` (the keys, the signal, where context is read), `[effort]` (its vocabulary),
`[catalog]` (models, efforts) and `[worker_token]` where it mints one. Then add `[providers.<name>]`.
`$AGENTKIT_ADAPTER_DIR` points at another adapter directory, which is how the offline suites run the loop with no model
behind it. Behaviour that needs Python goes in `agentkit/harness/<h>.py` behind one interface where every hook has a
default (`tokens` reads `events.jsonl`; Muse's are in its session store).

## The installer and updating

The README's one command works on a fresh macOS or Linux machine, safe to run again; `--server` and `--client [alias]`
set the role when the default is wrong, and `--phone-key KEY|FILE` appends the phone's key. It makes the directories
under `~/.agentkit` and `~/code` and puts `ak` on PATH. It installs what is missing: tmux, mosh, git, gh, jq, python3
3.11+, node, cron; on Linux also chromium, security-only unattended upgrades and Tailscale. With no harness installed it
asks once which to install and log in, or `all`, one provider being enough, and each adapter installs and logs its own
in, in a terminal; on a machine that has one it checks and logs in only those installed, wherever their binaries live,
adding none unasked. `gh auth login`, the Claude worker token, and the Discord webhook and user id are each asked for
once, only where missing and there is a terminal; the git credential helper and author are set from `gh` without asking.
On a server it also writes: the bypass defaults and update pins into `~/.claude/settings.json` (backed up beside itself
when it changes) and `~/.codex/config.toml`, each harness's lifecycle hooks through `adapters/<h>.sh hooks`, and the browser MCP registration. The server installs the tick's cron and, where a user systemd manager exists, writes
`~/.config/systemd/user/agentkit.slice.d/limits.conf` once: seats in `agentkit-seats.slice`, runs in the lower-weight
`agentkit-runs.slice`, both under `agentkit.slice`. Under a HOME not the account's own it touches nothing outside it.

`ak update` upgrades the harnesses this host has (any other is a `skipped` line), and none while a session works (it
names those sessions and exits 0); it verifies them with the gates that can run there and rolls back a harness the gates
fail, then fast-forwards `~/agentkit` itself and reruns `install.sh`, working sessions or not, as each `ak watch` tick
does after a merge to main. A checkout that is dirty, off main or cannot fast-forward is left as it is; that, or a
failed pull or `install.sh`, is said once per origin commit, in the tick's log and by `ak update`. It runs in the
foreground and says per harness whether it was upgraded, reverted, kept or left unchanged. The `c` screen's Update row
runs it too, and refuses while a session works; `--dry-run` prints the plan. Harnesses never update themselves.

`tests/smoke.sh` and `tests/e2e-fresh.sh` keep private `<login>/agentkit-smoke` and `<login>/agentkit-e2e`, created only when missing with the scopes `gh auth login` grants; each gate resets its repository under the host-wide lock: force-push `main` to its seed commit and delete leftover `ak/*` branches. The remote and provider logins are shared. The smoke suite holds the lock for every check; the e2e gate holds it from its GitHub run through exit. A suite that cannot take the lock stops before its checks. Cleanup is registered before HOME setup, so setup failures finish their retention receipt and keep the sandbox. The smoke suite reads shipped `config.default.toml` in its sandbox HOME and ignores the host's own agentkit config. It links individual credentials: `.claude/.credentials.json`, `.codex/auth.json`, `.config/muse/auth.json`, `.grok/auth.json`, `.local/share/opencode/auth.json`, Antigravity's `.gemini/antigravity-cli/antigravity-oauth-token`, GitHub's `.config/gh/hosts.yml`, `.agentkit/secrets/claude_oauth_token` and the desktop's `.local/share/browser-bridge/Xauthority`. Grok's `auth.json.lock` is shared too, so refreshers use the caller's lock. Harness login sources honor `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `GROK_HOME` and `GH_CONFIG_DIR` before those overrides are cleared for the sandbox. No caller directory is linked. It copies `.claude.json` for the account and MCP fields, `.gitconfig` and `.config/gh/config.yml` for GitHub access, `.config/opencode/opencode.json` for installations storing static API keys there (honoring `OPENCODE_CONFIG_DIR` or `OPENCODE_CONFIG`), and `.agentkit/secrets/discord_webhook` for check 5's GET; the notification sink blocks posts. Installer binaries stay on PATH without linking their directories, and Muse's raw cached readings are copied with their original age to avoid another paid probe. Claude's direct MCP call uses the worker token when available, as its workers do. A harness in the sandbox renews the caller's login as it would at home. If Claude or Grok renames over a credential link, `tests/merge_logins.py` returns only valid tokens with a later expiry than the caller's current login before either the suite or `--claude-stream` removes its sandbox, writing the whole file beside the caller's and renaming it over the path that file resolves to. Cleared, invalid, expired or older logins never overwrite the caller's; a write failure preserves the sandbox and fails the gate. Settings, hooks, project trust, caches and MCP registration stay in the sandbox: the suite writes nothing outside its sandbox but refreshed logins, and a run is the suite's by its task or repo under `~/.agentkit/tmp/smoke-<stamp>/`, never by a `smoke-` id or title, and counts in no seat's tallies or offers. Checks needing an uninstalled harness, a missing login, a Discord secret, a user systemd manager or the shared browser skip as not on this host and count as passed, like a throttled meter's; the suite fails only when check 3 makes no real call and no adapter's `auth` confirmed a login in one line within the 20 seconds `worker.auth_ok` allows (check 3 calls Claude, Codex and Muse; Grok Build, OpenCode or Antigravity count too; a settings file with no key in it, such as OpenCode's `opencode.json`, is no login). `tests/e2e-fresh.sh` links every harness's login the same way, from the same overrides, returns a renamed-over one the same way, finds each harness binary on the caller's PATH or in its installer's directory, asks each adapter's `auth` whether it can log in, bounded alike (Claude's worker token counts), and skips what the host lacks likewise; a lent login that is refused or unanswered fails. Its menu seat needs Claude's own pair and its GitHub run Claude and Codex. An exhausted model skips with the reason and leaves the gate incomplete; expired, malformed or unreadable saved logins fail. Exhaustion is checked per model. The GitHub run skips before resetting its remote when either required model is unavailable or exhausted; each MCP check applies the same rule. `bash tests/smoke.sh --claude-stream <out-dir>` captures events for the offline reader fixture; its sandbox HOME is a separate temporary directory removed on exit, leaving no credential links in the output.

## The Mac bridge and the shared browser

Drag a file into a session on the Mac: the agent runs `ak fetch <path>` on the server and reads the copy it prints, in
`~/.agentkit/macbridge/inbox/`. On macOS `install.sh` adds a LaunchAgent that connects out to the server over SSH and
sends only requested files, so Remote Login stays off; a reader under the terminal app supplies files macOS lets only
that app read, and a new terminal tab or `ak` starts both. It logs to the Mac's `~/.agentkit/macbridge/macbridge.log`.

The server runs one Chromium on a virtual display whose profile holds the real logins; it speaks CDP on `127.0.0.1:9222`
and five system units keep it up over reboots. Agents reach it through the `browser` and `desktop` MCP servers `ak
browser mcp-register` registers for Claude Code and Codex, and Muse through `browser/bridge.py`. `ak browser status`
shows the units, tabs and noVNC URL; `ak browser login` prints the URL and password for signing a site in by hand; `ak
browser install` stands it up where there is none. The tick closes a tab idle for an hour or past twelve open, and one a
run or seat opened closes when it ends or stops; Chromium is never restarted. noVNC binds to the Tailscale address.

## The history

Every run is recorded in `~/.agentkit/history.db`: repository, models and the launching seat's orchestrator, rounds,
verdict, timestamps, active seconds per step (checkpointed every 30 s; parks, slot, login, retry and merge-turn waits
are no step's), tokens where the harness reports them (else unknown), peak process-tree memory, session, and the task's
words, goal points, checks and files changed. Smoke and e2e runs are never recorded; an older agentkit's rows are read
as written, never rewritten, and a median keeps a few that counted waits from pulling an estimate far. Statistics skip
stopped runs and suite runs, by name or run record. History is best effort. The last twenty runs estimate a task's
memory and active time; `ak usage` shows each model's success rate and median active time, the picker reads that only
when budgets are within 0.15 of each other, and `ak run status --history` prints one line per repository (`last 20
tasks: median N rounds · over 400 words: median M rounds …`) for the orchestrator to size tasks by, then each model's as
orchestrator, executor and reviewer (`opus: orchestrator: 90% over 12 runs, ~45m`). A run's own directory is
`~/.agentkit/runs/<YYYYMMDD-HHMM>-<slug>/`: `task.md`, `run.json`, `log.txt` (the whole loop, with a `WARN` line per
retry), `result.md` (linking a scratch run's files) and `round-<r>/<role>/{prompt.md,final.md,stderr.log,events.jsonl}`.

## Troubleshooting

- A harness login expired: open the seat and log in there; for `gh login expired`, run `gh auth login` on the server. Parked runs resume by themselves. For `claude worker token expires in N days`, run `claude setup-token` and replace `~/.agentkit/secrets/claude_oauth_token`.
- A dropped Mac file the server cannot read: open a new Mac terminal tab or run `ak macbridge --reader` there, then fetch again.
- Test one headless turn: `ak worker opus prompt.md --workspace ~/code/foo`.
- A stale usage reading: open the menu; it reads each provider again within a minute.
- The slice ceiling: edit `~/.config/systemd/user/agentkit.slice.d/limits.conf`, or `systemctl --user set-property agentkit.slice TasksMax=4096`.
- A failed `ak update` that could not restore Muse: its snapshot is under `~/.agentkit/tmp/muse-snapshot-*`, named in the log.
