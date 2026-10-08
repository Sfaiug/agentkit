---
users: none
tests: export AK_SHARD AGENTKIT_ACCEPTANCE_REQUIRED=1; offline() { unshare --user --map-current-user --net --keep-caps sh -c 'ip link set lo up && exec setpriv --inh-caps=-all --ambient-caps=-all "$@"' - "$@"; }; offline true 2>/dev/null || offline() { "$@"; }; offline bash -c 'python3 tests/landing.py'
---
# agentkit, for an agent working on it

## What ak is for

ak builds whatever you want. You state an intent and get the finished result, live. It always takes one path: intent → alignment → build → review → live, and what breaks live comes back in as a new intent. ak does the work, asks the user only what only they can answer, and keeps running review rounds until the work passes.

Every change to ak is judged by what it does for what you build with it, and by these four rules:

1. **Less.** Use the fewest features, steps, options and concepts that reach the goal. The best part is no part, and the best process is no process. ak decides everything it can and never offers a choice it could make itself. It explains itself in plain words, so nobody needs a manual. If an addition is not a clear yes, it is a no.
2. **Quality, then speed, then cost.** The ideal is the best result, instantly, for nothing. When two of these pull apart, the one earlier in this list wins.
3. **Models are plugins.** ak stays the same while models and harnesses come and go. It runs whichever is best at the time and depends on none. Swapping one changes quality, speed and cost, never whether the intent gets delivered.
4. **ak enforces; words only explain.** Nothing depends on a model remembering an instruction or judging well on its own. A rule that can be a check, gate or hook is one, and it holds whatever model runs. A rule that lives only in text is unfinished.

## Working here

- Python 3.11 standard library and bash. No dependency is added, ever.
- One test file per behaviour: `python3 tests/test_<name>.py`, run straight, no runner.
- The `tests:` gate (`tests/landing.py`) runs `bash tests/smoke.sh` beside `tests/every_file.py` (remaining `tests/test_*.py`; see its docstring). Either failure fails it. `AK_SHARD=k/N` selects both parts' k-th share (1-based); unset or `1/1` runs all. Dependent checks stay together; each piece has a tmux safety guard and sandbox. `AGENTKIT_ACCEPTANCE_REQUIRED=1` makes skips fail; supported network namespaces allow only loopback.
- Checks needing more than loopback (smoke.sh 1-5, 6, 6b, 6d, 6f, 6g, 31a, 31d, 31e: real models, GitHub, Discord, live meters, shared browser, user systemd) run in smoke.sh's live mode via `tests/live.sh`, before a host takes new code and when a harness upgrades.
- Match the style of the file you are in. Read `ARCHITECTURE.md` first; a change that adds, removes, renames or moves a module updates the map. Any task may lower a `max` in `tests/test_boundaries.py` in the area it touches, and no task raises one.
- Docs ride the change: `README.md` and `docs/guide.md` say what the code now does.
- `orchestrator.md` is the rulebook an agentkit session is launched with, not a file for here.
- Tests driving `menu.loop` mock `menu.wait_key` beside `menu.read`: the real wait selects on stdin, and a stdin that never delivers EOF redraws forever instead of finishing. They leave `menu.Live`'s probe unstarted: its thread calls `usage.collect` after the test's mock is gone.

## Lessons

Mistakes earlier work here made that no check catches yet. One that becomes a check leaves this list.

- `python3.11 -m py_compile` what you touch: ak supports 3.11, and a newer `python3` accepts syntax 3.11 rejects.
- Never start the landing suite (`tests/landing.py`, its `tests/smoke.sh` or `tests/every_file.py`): it runs every test at landing, so when you change a sentence, rule, order or name, grep tests/ and fix each test pinning it.
- Comments say why. Listing screens go through `agentkit/terminal.py` (`docs/cli-design.md`).
- Each run has a memory cap (exit 137). Commit before a test sweep; run only the files your change touches, three at most at once; background one only under `timeout -k 30 20m`, read before your turn ends.
- `ak hand-in blocked` only when the task can't be done as written, never for a provider failure or the `# once` suite.
- Tests never touch real processes, units, seats, transcripts or state: fake process tables and tmux, injected kill/systemctl (`_proc_table()`, `AK_HOST_READINGS`), a temporary HOME. A test calling `run.review`, `run.execute` or a sweep in-process clears `AGENTKIT_RUN`, `AK_PARENT_RUN`, `AK_RUN_LOG` and sets `AK_RUN_DEPTH=0`, `AK_MAX_RUNS=0`, or a refusal SIGTERMs your own run.
- A sandbox HOME links (never copies) the caller's credential files and `*-probe.lock`/`*-probe.retry`, never a directory harnesses or install.sh write into (.claude, .codex, .grok, .config, .opencode, .local).
- Automatic resumes take only what a seat still waits on: not handed back, live session, under a day old, never by-hand.
- Commands call `bin/ak`, never bare `ak`. A changed signature: update every mock and fake of it in tests/; a fake takes `**_kw` for what it ignores.
- agentkit is public: tests, docs and commits use invented names (`acme`, `fix-api`), never a real checkout, product or seat.
- Never depend on when a seat's turn began; decide from recorded notices, runs and the screen. A new fact gets its own field (`stopped_at` means closed).
- tmux targets are `={name}:`; a fake tmux answers only what real tmux 3.5a does; every tmux client call on a run's path has a timeout.
- Usage display work never changes which meters `collect` keeps (`_without_past` drops past-reset ones on purpose).
- A model entry names its model id, never `model = "default"`.
- In-checkout test sandboxes use the `.ak-test-` prefix, the only one the loop never commits.
- A removed `.gitignore` pattern leaves its matches untracked on the live checkout and stops `go_live` pulling: keep it or delete them too.
- A final check stopped for silence names the hung process after `still running:`: fix the hang on your branch, or hand in blocked if origin/main hangs too; gate changes are their own task.
- A repairing tick re-derives placement or state from what it finds; findings remembered between ticks lose races.
- A run's CPU and memory come from its cgroup (`cpu.stat`, `memory.current`), which counts killed and orphaned processes; process-tree sampling misses them. Put a process in its cgroup at start (its own scope, as `in_slice` does); moving it later races.
- To end a detached script's work, hold its process group (a holder leader, reaped last) and signal the group; `ps` never proves a group empty. Some macOS Pythons lack `os.waitid`. A group ends only what stays in it: to end everything a command started, even what made its own group or session, start it in a cgroup scope (`orch.start_in_slice`'s claim and witness, `orch.seat_scope_run`'s argv) and stop the scope. Process groups, tree walks and subreapers each lost a race in review, and a session of its own hides the line from the caller's Ctrl+C (#537, closed after 12 rounds).
- One process never takes over another run's record (its pid, its stop, its ending): leave a verdict in its record and wake it to act.
- Work outliving a run goes to the tmux server (`run-shell -b`): a run's threads and children die with its scope.
- Decide from exit codes and files, never another program's output text, which catches proofs and verdicts it shouldn't.
- Never re-create another system's semantics for an input nobody uses (Linux's path walk inside Git trees, for a linked AGENTS.md): every review round found one more difference (#520, six rounds). Refuse the input plainly instead.
- A test never asserts a plain word is absent from output that prints paths: worktree paths carry the run's title.
- A test never asserts a wall-clock duration (under 100 ms, say): host load breaks it at landing. Inject the clock and assert what it read.
- `tests/fixtures/sandbox.py`'s `Sandbox` stops this process's clock (`time.time()` reads 10000) and keeps ak's state in `<root>/state`, while a hook run as a subprocess stamps the real clock into `$HOME/.agentkit/state`: copy its record across and compare against its own stamps.
- A rule on what may merge belongs in both merge paths: `do_merge` (task runs) and `merge_own_pr` (a seat's own PR, now the main path); a guard on one alone is a bypass.
- Typing into a seat has one typer per kind of line: the tick, under its lock. A second typer (a sender trying first) needs claims and delivery reports that each review round finds a new race in (#439, 3 rounds).
- A fix that reads the screen adds no fallback for shapes it did not set out to read: every such fallback (an at_prompt backstop, an "empty composer" pattern) misread another real screen and cost a review round (#501, 3 rounds).
- A line typed into a seat is delivered at least once: no mark, receipt or transcript read closes every crash window between its Enter and the queue rewrite (#439, #502: six rounds). Say so in the task and the PR; never promise exactly once.
- A test that asserts a UTF-8 glyph the menu draws (│ ▶ ✓ …) pins `patch.dict(os.environ, {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})`: under LANG=C the menu draws ASCII and the landing suite runs in the caller's locale.
- Whatever a bar or the menu shows of a run is in run.json when its step publishes (round directories come later), and an open menu sees only the files it watches: a display fact derived from anything else lags (#504, 3 rounds).
- A screen-reading change reads only the rows the code it replaces read: every reach further up (a whole-pane read, a tail extended to a box) met an older composer, echo or box a reviewer could place there (#507, nine rounds).
- When each review round finds one more state, race or recovery path, stop patching paths: delete the state or change the design so fewer paths must be right (switch retirement, #547 to #586).
- A screen-reading fix is proven on a pane captured from a real, renamed seat, not only a hand-drawn fixture: Claude draws the seat's name into the rule under a question's footer, which #591's fixture lacked (#609).
- Try a seat end to end only with HOME and AGENTKIT_TMUX_SOCKET both sandboxed: a seat record in the real ~/.agentkit is revived by the tick onto ak's own server and reads needs you to the owner.
- A replay that compares two revisions runs each in a clone made from git alone, and compares only the checks the second one reproduces: a shared checkout passed one replay's files to the next, a staged overlay or a commit message set one side apart, and copying the checkout's untracked files brought sockets, links back into it and a copy of the copy (#506, over twenty rounds).
- A task or PR promises only what its code decides, in the code's own terms ("has read or write access", not "can open"; "the internet answers", not "as the host does"): a reviewer measures every word, and wider ones cost five findings and a relay nobody asked for (#697, #699).
- A PID namespace's number names another namespace the moment it ends: never find a process by it. Hold a pidfd, or go through a process you hold: its group, its children (#699: each box that ended could kill another box's first process on the same host).
- A box change is tried twice before it is pushed: inside one of ak's own boxes, as the lander runs every test, and on a host with a route out, where the offline suite never goes. Either run shows at once what three review rounds found (#699).
- A test fakes one module's sleep (`tests/fixtures/clock.py`), never `time.sleep` itself: every other wait in the process then spins, and a recording fake keeps every spin (#700: 3.7 GB in a landing check).

## Owner rules

- Codex pairing is optional and requested when the owner wants app access; opening or resuming a seat sends no setup alert. Optional access does not need the owner or block terminal work. [7 Oct 2026]
- Adding a model or harness is an adapter, its toml and a `models.toml` entry, never a name hard-coded in code; `n` keeps the orchestrator question so the owner can switch freely. [18 Sep]
- ak picks models only on live facts (quota, host, errors); past-run numbers may be shown but never pick, and ak never labels a model good or bad at a role: the owner marks who executes and who reviews. [28 Sep, 29 Sep]
- ak is measured by what it delivers in every project: `ak run status --history` shows quality, speed, cost and size week by week, work on ak itself counts as cost, and these numbers never pick a model. [2 Oct]
- No fixed capacity numbers: every limit (runs at once, gate turns, memory) is derived from the machine ak runs on, for any user; correctness locks (one merge per repository) are not capacity and stay. [23 Sep, 28 Sep]
- Everything is umbrella: it works for any ak user, machine, provider and project type, never only for this owner's setup. [23 Sep]
- Only a person opens a seat, and a seat keeps its conversation: `ak orch` with no terminal opens none; Claude seats run with `/background`'s daemon off. Stray seats paged the owner; the daemon mixed them up. [4 Oct]
- Nothing may ever get stuck: every state recovers by itself, a dead seat or run resumes where it stopped, and the owner hears only when recovery failed. [16 Sep, 19 Sep]
- Done means live: a project's `health:` line says how to tell its live product works, and a merged change counts as done once that passes with the change deployed; what breaks live comes back in by itself. [2 Oct]
- The owner sees only what needs them (a seat's question, their own unsent draft, a final failure nobody handles) or a finished job. Of every line on a screen ask "what would the owner do with it?"; if nothing, it goes. The system cleans up after itself. [15 Sep, 18 Sep]
- Every screen follows `docs/cli-design.md`: plain words that explain themselves, every glyph followed by its word, nothing cut mid-sentence, the same back, forward and exit keys everywhere. [15 Sep, 16 Sep]
- No test-selection engine and no automatic affected-test selection: a repository declares its own suite, and ak runs it once, at landing, for the passed changes landing together; a round runs only the task's own checks. [16 Sep, 25 Sep, 1 Oct]
- The landing suite tests only the project's own code: no real model, no real GitHub, no network beyond loopback. Checks that need the outside world run before the host switches to new code and when a harness upgrades (agentkit: `tests/live.sh`), never on every landing. [2 Oct]
- Landing takes about one suite time in every project: ak splits the suite into as many side-by-side pieces as the machine fits, tests the passed changes waiting to land together, each on top of those ahead, and merges each that passes; a failing one holds up no other, and waiting holds no process. [3 Oct]
- The landing line may test several waiting runs together and land them all when that one test passes; only main's tip after the batch must be tested. [5 Oct]
- `ak run --first` puts a loop repair first to start; suite turns go to landing runs first, then to whoever waited longest. A landing suite gets its pieces before any new build or round check is admitted: finished work waiting to land goes first. [25 Sep, 2 Oct, 3 Oct, 5 Oct]
- The orchestrator builds, whatever the size; marked executors take only independent pieces sharing no file with its work, and ak moves no work for quota. A behaviour change needs a test that fails on the old code; ak proves it wherever it can and records why when it cannot, never failing a round for a missing proof, as no path tells every project's tests from its code [7 Oct]. The orchestrator's own PRs get review rounds, findings back to its session, and land through the same line as every change; review follow-ups become checked lines in its plan. [1 Oct, 2 Oct, 3 Oct, 4 Oct]
- Size never refuses work (no cap on PR lines or task points, words or checks, nor on the docs' words or `AGENTS.md`'s size: changes that fit alone went red together in the landing line); it is recorded and shown. Nothing ak hands a model is cut; `AGENTS.md`'s only ceiling is the most a harness reads of it on its own, which its adapter declares. Review rounds stay three. [3 Oct, 4 Oct]
- The owner's own words are what a job is measured against: ak keeps them with the job from the seat's own record, never from a summary. [2 Oct]
- The normal way in is a session: open it, pick who orchestrates, executes and reviews, type the prompt. A notes intake, if built, is an optional add-on on top of ak, on the ak screen, using the providers ak already has. [1 Oct]
- No `ak trial`, leaderboard or in-house skill test of models: public benchmarks judge general strength. [28 Sep, 29 Sep]
- Every provider takes more than one subscription. A subscription is always shown by its provider's name, with a roman numeral as its number when there are several (Claude I, Claude II), never by its account name. [29 Sep]
- The features screen has only `you` and `everyone`; grants for specific users live on the project's own owner page, never in ak. [23 Sep]
- Instructions have four homes: `orchestrator.md` and the worker rules (ak's), the host's `~/.agentkit/rules.md` (the owner's), and a project's `AGENTS.md` (its knowledge and the owner's product rules), each handed whole to every session and worker it concerns; nothing else instructs a model ak runs, no harness memory and no lessons file. None has a length cap beyond the harness ceiling above; in each, a line explains something ak checks or a judgement no check can make, and a rule ak comes to enforce shrinks to a mention. [1 Oct, 4 Oct]
- Credits a provider account still holds (ChatGPT credits first, any provider that reports a balance) count as usage left. [2 Oct]
- ak never spends a usage-limit reset on its own; the owner spends one by hand, from the Providers row of `c`. [2 Oct]
- No screen estimates when work will finish; a seat's progress is its tasks bar and its count, never a percentage. [2 Oct]
- Every project meets one contract, enforced by checks and scaled by what is at stake: its suite runs every test file, its front matter holds only lines ak reads, and a live project proves it is live with a real `health:`, deploys only code ak tested, and puts the previous release back by itself when health breaks. How each project deploys stays its own; a ready-made deploy kit covers the common case. [5 Oct]
- A seat's live runs are named on one line only, its live line (the seat bar's second line, and under the highlighted dashboard row): task id, what it is doing, the model doing it. No other row names a run. [18 Sep, 2 Oct]
- Seats message each other only through `ak tell`, the same way for every harness and account; it is never taken for the owner's words. [4 Oct]
- `~/code` holds only the owner's checkouts: a seat builds in a checkout under `~/.agentkit/wt/`, and ak removes it a day after it last changed, merged or not, unless it holds a change not yet committed or is a clone; its branch and commits stay in the project's repository. Seats' worktrees in `~/code` showed as projects and were never cleaned; waiting for GitHub's merge only added races. [5 Oct, 6 Oct]
- The vision at the top of this file, the landing gate and what the scoreboard measures change only with the owner's yes; the rest of ak the orchestrators improve on their own. [2 Oct]
