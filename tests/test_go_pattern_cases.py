"""Go's pyre matches as Python's re: every pattern watch.screen compiles from each manifest, with
the flags it adds, searched over every screen fixture's whole text and over each of its rows.  This
builds Go's case file from them again and fails where the committed one differs; `--write`
rewrites it.
"""

from concurrent.futures import ProcessPoolExecutor
from functools import cache
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
CASES = REPO / "go/internal/pyre/testdata/cases.json"
os.environ["HOME"] = tempfile.mkdtemp(prefix="ak-pyre-")
os.environ.pop("AGENTKIT_ADAPTER_DIR", None)   # this checkout's manifests, never a fake's
sys.path.insert(0, str(REPO))
from agentkit import config, watch  # noqa: E402


def patterns(key, value):
    """Every compiled pattern in what watch.screen built, named by where it stands."""
    if isinstance(value, re.Pattern):
        yield key, value
    elif isinstance(value, dict):
        named = f"rule {value['id']}" if "id" in value else key
        for field, each in value.items():
            yield from patterns(f"{named} {field}".strip(), each)
    elif isinstance(value, (list, tuple)):
        for at, each in enumerate(value):
            yield from patterns(f"{key} {at}", each)


@cache
def fixture(name):
    return (REPO / "tests/fixtures" / name).read_bytes().decode()


def searched(pattern, flags, name):
    """Python's first match of the pattern in the fixture's whole text (row null) and in each row,
    split on newlines alone, as Go splits them."""
    compiled, text = re.compile(pattern, flags), fixture(name)
    return [{"fixture": name, "row": row, "span": list(match.span()), "groups": match.groupdict()}
            for row, part in [(None, text), *enumerate(text.split("\n"))]
            if (match := compiled.search(part))]


def cases():
    fixtures = sorted(path.name for path in (REPO / "tests/fixtures").glob("*-pane.txt"))
    compiled = [(harness, key, each) for harness, _ in config.manifests()
                for key, each in patterns("", watch.screen(harness))]
    # one process a core: antigravity's footer backtracks for minutes over a whole screen
    with ProcessPoolExecutor() as pool:
        found = pool.map(searched, *zip(*[(each.pattern, each.flags, name)
                                          for _, _, each in compiled for name in fixtures]))
        return {"fixtures": fixtures, "patterns": [
            {"harness": harness, "key": key, "pattern": each.pattern,
             "flags": "".join(letter for letter, flag in (("i", re.I), ("m", re.M))
                              if each.flags & flag),
             "matches": [match for _ in fixtures for match in next(found)]}
            for harness, key, each in compiled]}


def written(data):
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


class PatternCases(unittest.TestCase):
    def test_the_committed_cases_are_what_python_matches(self):
        self.assertTrue(CASES.exists(), f"{CASES} is missing: run this with --write")
        self.assertEqual(CASES.read_text(encoding="utf-8"), written(cases()),
                         f"{CASES.name} is not what Python matches: run this with --write")


if __name__ == "__main__":
    if "--write" in sys.argv:
        CASES.parent.mkdir(parents=True, exist_ok=True)
        CASES.write_text(written(cases()), encoding="utf-8")
    else:
        unittest.main(verbosity=2)
