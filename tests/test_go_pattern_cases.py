"""Go's pyre matches as Python's re: every pattern watch.screen compiles from each manifest, with
the flags it adds, searched over each row of every screen fixture, and over its whole text where
the pattern reads several rows (re.M).  This builds Go's case file from them again and fails where
the committed one differs; `--write` rewrites it.
"""

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


def cases():
    fixtures = sorted(path.name for path in (REPO / "tests/fixtures").glob("*-pane.txt"))
    texts = {name: (REPO / "tests/fixtures" / name).read_bytes().decode() for name in fixtures}
    found = []
    for harness, _ in config.manifests():
        for key, compiled in patterns("", watch.screen(harness)):
            matches = []
            for name in fixtures:
                # the whole text is row null; rows are split on newlines alone, as Go splits them.
                # A pattern of one row never reads a whole screen, and antigravity's footer,
                # searched over one, backtracks for minutes.
                whole = [(None, texts[name])] if compiled.flags & re.M else []
                for row, text in [*whole, *enumerate(texts[name].split("\n"))]:
                    if match := compiled.search(text):
                        matches.append({"fixture": name, "row": row, "span": list(match.span()),
                                        "groups": match.groupdict()})
            flags = "".join(letter for letter, flag in (("i", re.I), ("m", re.M))
                            if compiled.flags & flag)
            found.append({"harness": harness, "key": key, "pattern": compiled.pattern,
                          "flags": flags, "matches": matches})
    return {"fixtures": fixtures, "patterns": found}


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
