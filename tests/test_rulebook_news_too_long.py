"""A rulebook change too long for a seat's prompt reaches it as a file it acknowledges: the
answer key in tests/test_key_rulebook_news_too_long.py, run here."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("test_key_rulebook_news_too_long.py")), run_name="__main__")
