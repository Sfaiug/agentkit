---
users: none
tests: bash tests/smoke.sh; smoke=$?; python3 tests/every_file.py && exit $smoke
---
# agentkit, for an agent working on it

## What ak is for

ak builds whatever you want. You state an intent and get the finished result, live. It always takes one path: intent → alignment → build → review → live, and what breaks live comes back in as a new intent. ak delegates, asks the user only what only they can answer, and keeps running review rounds until the work passes.

Every change to ak is judged by what it does for what you build with it, and by these four rules:

1. **Less.** Use the fewest features, steps, options and concepts that reach the goal. The best part is no part, and the best process is no process. ak decides everything it can and never offers a choice it could make itself. It explains itself in plain words, so nobody needs a manual. If an addition is not a clear yes, it is a no.
2. **Quality, then speed, then cost.** The ideal is the best result, instantly, for nothing. When two of these pull apart, the one earlier in this list wins.
3. **Models are plugins.** ak stays the same while models and harnesses come and go. It runs whichever is best at the time and depends on none. Swapping one changes quality, speed and cost, never whether the intent gets delivered.
4. **ak enforces; words only explain.** Nothing depends on a model remembering an instruction or judging well on its own. A rule that can be a check, gate or hook is one, and it holds whatever model runs. A rule that lives only in text is unfinished.

## Working here

- Python 3.11 standard library and bash. No dependency is added, ever.
- One test file per behaviour: `python3 tests/test_<name>.py`, run straight, no runner.
- The acceptance gate is the `tests:` line: `bash tests/smoke.sh`, then `tests/every_file.py`, which runs every `tests/test_*.py` smoke.sh does not, each once, in parallel and without the caller's `AGENTKIT_*`/`AK_*` variables; either failing fails the gate. A round runs the task's done-when commands and review; the loop runs the full suite once at landing on the commit to be merged.
- Match the style of the file you are in. Read `ARCHITECTURE.md` first; a change that adds, removes, renames or moves a module updates the map. Any task may lower a `max` in `tests/test_boundaries.py` in the area it touches, and no task raises one.
- Docs ride the change: `README.md` and `docs/guide.md` say what the code now does.
- `orchestrator.md` is the rulebook an agentkit session is launched with, not a file for here.
- Tests driving `menu.loop` mock `menu.wait_key` beside `menu.read`: the real wait selects on stdin, and a stdin that never delivers EOF redraws forever instead of finishing. They leave `menu.Live`'s probe unstarted: its thread calls `usage.collect` after the test's mock is gone.

## Owner rules

- Adding a model or harness is an adapter, its toml and a `models.toml` entry, never a name hard-coded in code; `n` keeps the orchestrator question so the owner can switch freely. [18 Sep]
- ak picks models only on live facts (quota, host, errors); past-run numbers may be shown but never pick, and ak never labels a model good or bad at a role: the owner marks who executes and who reviews. [28 Sep, 29 Sep]
- No fixed capacity numbers: every limit (runs at once, gate turns, memory) is derived from the machine ak runs on, for any user; correctness locks (one merge per repository) are not capacity and stay. [23 Sep, 28 Sep]
- Everything is umbrella: it works for any ak user, machine, provider and project type, never only for this owner's setup. [23 Sep]
- Nothing may ever get stuck: every state recovers by itself, a dead seat or run resumes where it stopped, and the owner hears only when recovery failed. [16 Sep, 19 Sep]
- The owner sees only what needs them (a seat's question, their own unsent draft, a final failure nobody handles) or a finished job. Of every line on a screen ask "what would the owner do with it?"; if nothing, it goes. The system cleans up after itself. [15 Sep, 18 Sep]
- Every screen follows `docs/cli-design.md`: plain words that explain themselves, every glyph followed by its word, nothing cut mid-sentence, the same back, forward and exit keys everywhere. [15 Sep, 16 Sep]
- No test-selection engine and no automatic affected-test selection: a repository declares its own suite, and ak runs it once, at landing, for the passed changes landing together; a round runs only the task's own checks. [16 Sep, 25 Sep, 1 Oct]
- `ak run --first` puts a loop repair first to start and first to merge, never ahead of a waiting test suite: suite turns go to landing runs first, then to whoever waited longest. [25 Sep, 2 Oct]
- Who builds follows one table that ak checks: the orchestrator builds what needs the owner or the conversation and what is quicker to do than to describe; executors build what a check can judge and a task fully describes; ak refuses a task without a check that fails on main; the owner can switch any session to solo. The orchestrator's own PRs get review rounds, with the findings sent back into its session. [1 Oct]
- The normal way in is a session: open it, pick who orchestrates, executes and reviews, type the prompt. A notes intake, if built, is an optional add-on on top of ak, on the ak screen, using the providers ak already has. [1 Oct]
- No `ak trial`, leaderboard or in-house skill test of models: public benchmarks judge general strength. [28 Sep, 29 Sep]
- Every provider takes more than one subscription. A subscription is always shown by its provider's name, with a roman numeral as its number when there are several (Claude I, Claude II), never by its account name. [29 Sep]
- The features screen has only `you` and `everyone`; grants for specific users live on the project's own owner page, never in ak. [23 Sep]
- The orchestrator rulebook has no length cap: each line explains something ak checks or a judgement no check can make, and a rule ak comes to enforce shrinks to a mention. [1 Oct]
