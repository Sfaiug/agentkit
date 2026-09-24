# Title

<!-- One behaviour per task: at most 3 numbered goal points, 500 words outside the checks block, 6 checks. -->
## Goal
The outcome this task must achieve.
1. First checkable point.
2. Second checkable point.

## Constraints
- Boundaries the work must respect.
- Three rounds is the budget (`rounds` defaults to 3).

## Done when
Commands must exit 0. Mark the whole suite `# once` to run on the final commit.

```bash
python3 tests/test_foo.py
bash tests/smoke.sh  # once
```
