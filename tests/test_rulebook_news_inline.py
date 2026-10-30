"""A rulebook change reaches a seat inside its prompt, with no extra calls: the answer key in
tests/test_key_rulebook_news.py, run here."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("test_key_rulebook_news.py")), run_name="__main__")
