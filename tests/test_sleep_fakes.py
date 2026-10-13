"""Tests fake one module's sleep (`fixtures/clock.py`), never `time.sleep` itself, and the
sites that still do only shrink.

A fake of the global sleep spins every other wait in the process -- `subprocess` waits with
a timeout by sleeping in small steps, under every timed git, gh or adapter call -- and a
recording fake keeps every spin (#700: 3.7 GB in a landing check).  `MAX` is the count of
such sites on the day this check was written; any task may lower it as it moves a fake to
the fixture, and no task raises it: like a boundary maximum, it cannot exceed what origin/main
holds.  A site is the global sleep named as a target in code, comments and prose aside:
`time, "sleep"` side by side in a call or a table, or `"time.sleep"`, however it is quoted or
broken across lines.  Offline: the tracked tests of this checkout, this one too.
"""

import ast
import re
import subprocess
import unittest
from pathlib import Path

from test_boundaries import where_change_left_main

REPO = Path(__file__).resolve().parents[1]
MAX = 141


def sites():
    """Each `path:line: text` naming the global sleep as a target, by the line it starts on."""
    proc = subprocess.run(["git", "-C", str(REPO), "ls-files", "--", "tests/*.py",
                           "tests/fixtures/*.py"], capture_output=True, text=True, check=True)
    found = []
    for path in proc.stdout.splitlines():
        text = (REPO / path).read_text()
        lines = text.splitlines()
        for node in ast.walk(ast.parse(text, path)):
            items = ([*node.args, *(keyword.value for keyword in node.keywords)]
                     if isinstance(node, ast.Call) else getattr(node, "elts", []))
            named = [first for first, second in zip(items, items[1:])
                     if "time" in (getattr(first, "id", None), getattr(first, "attr", None))
                     and isinstance(second, ast.Constant) and second.value == "sleep"]
            if (isinstance(node, ast.Constant)
                    and str(node.value).split(".")[-2:] == ["time", "sleep"]):
                named.append(node)
            found += [f"{path}:{target.lineno}:{lines[target.lineno - 1]}" for target in named]
    return found


class SleepFakes(unittest.TestCase):
    def test_no_new_fake_of_the_global_sleep(self):
        found = sites()
        self.assertLessEqual(len(found), MAX, "a new fake of the global sleep; fake one module's "
                             "through fixtures/clock.py instead:\n" + "\n".join(found))
        if len(found) < MAX:
            print(f"{len(found)} sites patch the global sleep: lower MAX to {len(found)}")

    def test_the_max_only_goes_down(self):
        source = where_change_left_main(self, "tests/test_sleep_fakes.py")
        before = re.search(r"^MAX = (\d+)$", source, re.M)
        if before:
            self.assertLessEqual(MAX, int(before.group(1)), "MAX only goes down")


if __name__ == "__main__":
    unittest.main(verbosity=2)
