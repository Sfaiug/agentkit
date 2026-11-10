---
users: none
tests: export AK_SHARD AGENTKIT_ACCEPTANCE_REQUIRED=1; offline() { unshare --user --map-current-user --net --keep-caps sh -c 'ip link set lo up && exec setpriv --inh-caps=-all --ambient-caps=-all "$@"' - "$@"; }; offline true 2>/dev/null || { echo "landing: cannot build the offline sandbox (unshare --user --net); the suite runs only inside it" >&2; exit 1; }; offline bash -c 'python3 tests/landing.py'
health: git -C ~/agentkit merge-base --is-ancestor "$AK_MERGE_SHA" HEAD && test ! -e ~/.agentkit/state/agentkit-install-pending && ~/agentkit/bin/ak doctor >/dev/null
content: go/internal/worker/rules/
---
# agentkit, for an agent working on it

## What ak is for

ak builds whatever you want, with AI models doing the work. You state an intent and get the finished result, live, for any project, on any machine, with any model. It always takes one path: intent → alignment → build → review → live, and what breaks live comes back in as a new intent. Alignment is the only part done with you: from 0 to 1 together, until the goal is clear and checkable; from 1 to 100 alone, asking only what only you can answer. One model builds, another reviews, round after round until the work passes, and nothing ever gets stuck: whatever fails recovers by itself.

Every change to ak is judged by what it does for what you build with it, and by these four rules:

1. **Less.** Use the fewest features, steps, options and concepts that reach the goal. The best part is no part, and the best process is no process. ak decides everything it can and never offers a choice it could make itself. It explains itself in plain words, so nobody needs a manual. If an addition is not a clear yes, it is a no.
2. **Quality, then speed, then cost.** Quality is the result doing what you asked and staying that way. The ideal is the best result, instantly, for nothing. When two of these pull apart, the one earlier in this list wins.
3. **Models are fuel; ak is the car.** ak stays the same while models and the programs that run them come and go. It runs whichever is best at the time and depends on none. Swapping one changes quality, speed and cost, never whether the intent gets delivered.
4. **ak enforces; words only explain.** Nothing depends on a model remembering an instruction or judging well on its own. A rule that can be a check, gate or hook is one, and it holds whatever model runs. A rule that lives only in text is unfinished.

This section changes only with the owner's yes. Every other line has one home, and ak's instruction files a word maximum that only goes down; ak's orchestrators improve the rest on their own.

## Working here

- Python 3.11 standard library and bash. Python takes no dependency, ever.
- One test file per behaviour: `python3 tests/test_<name>.py`, run straight, no runner.
- `tests/landing.py` refuses what Python 3.11 cannot parse, f-strings aside: `python3.11 -m py_compile` what you touch holding one like `f"{data["key"]}"`. `AGENTKIT_ACCEPTANCE_REQUIRED=1` makes skips fail.
- Match the file's style.
- `README.md` holds only what ak is, installation and starting.
- `orchestrator.md` instructs agentkit sessions, not work here.

## Lessons

Mistakes no check catches and no one area of the code holds; one that becomes a check or a comment at its code leaves.

- When wording changes, grep tests/ and fix assertions pinning it.
- Comments say why.
- Each run has a memory cap (exit 137). Commit before a test sweep; run three files at most at once.
- Tests use temporary HOME, fake process tables, units, tmux, seats, transcripts and state, and injected kill/systemctl (`_proc_table()`, `AK_HOST_READINGS`). In-process `run.review`, `run.execute` and sweeps set `tests/fixtures/seats.py`'s run variables, or refusal SIGTERMs your run.
- Commands call `bin/ak`, never bare `ak`. A changed signature: update every mock and fake of it in tests/; a fake takes `**_kw` for what it ignores.
- agentkit is public: tests, docs and commits use invented names (`acme`, `fix-api`), never a real checkout, product or seat.
- A final check stopped for silence names the hung process after `still running:`: fix the hang, or hand in blocked if origin/main hangs too; gate changes are their own task.
- Decide from exit codes and files, never another program's output text, except the stop hook's `?` at a turn's end.
- A test never asserts a plain word is absent from output that prints paths (worktree paths carry the run's title), nor a wall-clock duration (host load breaks it at landing). Inject the clock (`tests/fixtures/sandbox.py`, `tests/fixtures/clock.py`).
- When review keeps finding races or recovery paths, delete state or simplify the design.
- Refuse an input nobody uses (a linked AGENTS.md) plainly, never re-creating another system's semantics; a task or PR promises only what its code decides, in the code's own terms ("has read or write access", not "can open"): a reviewer measures every word.
- A Go milestone answers to the keys its task names: exit 3 fails it only where they reach, a difference from Python only on input real homes hold; its PR names the rest for the shadow run.

## Owner rules

- Models are plugins. Each run takes its executor and its reviewer from that role's marks that can run now, each on its own, the mark `quality.pick` names first, so a model may review its own build. Every run records who built and who reviewed at which effort, for the owner to compare; ak's runs give "Costs only" (5 Nov), and ak spends no turn testing models. The owner: "Data collection yes, no recommendation." (3 Nov); `quality.pick` first, not random (9 Nov). [18 Sep–9 Nov 2026]
- Every screen follows `docs/cli-design.md`, the one home of how a screen reads. [15, 16 Sep, 18 Oct]
- A notes intake, if built, is an optional add-on on the ak screen, using ak's providers. [1 Oct]
- ak ends a wait when that merges, closes or ends; a merge on a project with `health:`, once it is live or its window has passed. [4, 9 Oct 2026]
- Each line of `AGENTS.md` and `orchestrator.md` (word maxima: `tests/test_boundaries.py`) explains a check or a judgement no check can make.
- Every project meets one contract, enforced by checks and scaled by what is at stake: its suite runs every test file, and a live project proves it is live with a real `health:`, deploys only code ak tested, and puts the previous release back by itself when health breaks. How each project deploys stays its own; a ready-made deploy kit covers the common case. [5 Oct]
- ak becomes one Go program for Linux, Mac and Windows (WSL2 first, native menu over ssh); Go may vendor modules. Uncapped (`.gitattributes`) `go/` milestones land in shadow until takeover, after black-box `AK_BIN` keys pass today's ak. Python then takes fixes (bugs, throughput, resources), the 20 Oct menu, 30 Oct pipeline, 2 Nov night read and 5 Nov models screen, each with a key Go ports. Reason: one fast program anyone installs. [20, 23, 24, 30 Oct, 2, 5 Nov 2026]
