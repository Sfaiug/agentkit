"""The task's name for tests/test_key_round_runs_affected_suite.py, the answer key's test of a
round running the suite's tests its change can affect, where the Go port's black-box set finds it."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("test_key_round_runs_affected_suite.py")),
               run_name="__main__")
