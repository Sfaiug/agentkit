# Title

<!-- One behaviour per task: $executor_size. -->
## Goal
The outcome.
1. First checkable point.
2. Second checkable point.

## Constraints
- Boundaries the work must respect.
- $task_budget

<!-- Optional. -->
## Decided
Not wanted: add an archive browser.
Accepted: the export skips archived rows.

## Done when
Commands must exit 0. If AGENTS.md declares `tests:`, list focused checks; ak runs that suite at landing.
Otherwise mark the suite `# once`.

```bash
python3 tests/test_foo.py
bash tests/smoke.sh  # once
```
