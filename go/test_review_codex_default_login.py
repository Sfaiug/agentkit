"""The review's probe of a seat Go opens on the usual login under an inherited account home:
the answer key tests/test_key_codex_seat_on_the_usual_login.py, run on Go's ak as
tests/test_go_keys.py runs each claim of go/keys.txt, a skip failing it."""

from pathlib import Path
import subprocess
import sys

TESTS = Path(__file__).resolve().parents[1] / "tests"
sys.exit(subprocess.run([sys.executable, str(TESTS / "test_go_keys.py"),
                         "test_key_codex_seat_on_the_usual_login"]).returncode)
