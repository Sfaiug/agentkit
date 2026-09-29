---
users: none
tests: bash tests/smoke.sh
---
# agentkit, for an agent working on it

- Python 3.11 standard library and bash. No dependency is added, ever.
- One test file per behaviour: `python3 tests/test_<name>.py`, run straight, no runner.
- The acceptance gate is `bash tests/smoke.sh`; it has to pass before a change is done.
- Match the style of the file you are in. Read `ARCHITECTURE.md` first; a change that adds, removes, renames or moves a module updates the map. Any task may lower a `max` in `tests/test_boundaries.py` in the area it touches, and no task raises one.
- Docs ride the change: `README.md` and `docs/guide.md` say what the code now does.
- `orchestrator.md` is the rulebook an agentkit session is launched with, not a file for here.
- Tests driving `menu.loop` mock `menu.wait_key` beside `menu.read`: the real wait selects on stdin, and a stdin that never delivers EOF redraws forever instead of finishing. They leave `menu.Live`'s probe unstarted: its thread calls `usage.collect` after the test's mock is gone.
