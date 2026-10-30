"""The task's name for tests/test_key_queued_run_meets_new_rules.py, the answer key's test of a
run waiting for its slot judged again by the code installed while it waits, where the Go port's
black-box set finds it."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("test_key_queued_run_meets_new_rules.py")),
               run_name="__main__")
