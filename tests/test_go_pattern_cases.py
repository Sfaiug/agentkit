"""Go's pyre matches as Python's re: every pattern watch.screen compiles from each manifest, with
the flags it adds, searched over each row of every screen fixture, and over its whole text where
re.M reads several rows together; and every letter ignoring case takes for more than its own upper
and lower case, outside a class and inside one.  This builds Go's case file from them again and
fails where the committed one differs; `--write` rewrites it.
"""

from collections import defaultdict
from functools import cache
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
import _sre

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
    """Python's first match of the pattern in each row of the fixture, split on newlines alone, as
    Go splits them, and in its whole text (row null) where re.M reads rows together: Python's
    watch searches no other pattern over a whole screen."""
    compiled, text = re.compile(pattern, flags), fixture(name)
    parts = [*([(None, text)] if flags & re.M else []), *enumerate(text.split("\n"))]
    return [{"fixture": name, "row": row, "span": list(match.span()), "groups": match.groupdict()}
            for row, part in parts if (match := compiled.search(part))]


def letters():
    """Every letter of a kind ignoring case takes for more than one upper and one lower case: one
    Python's re pairs with another (`s` with `ſ`), or that holds more than two (`k` with the Kelvin
    sign).  A kind is the letters whose lower case falls among one lower case's pairs."""
    kinds = defaultdict(str)
    for code in range(sys.maxunicode + 1):
        lower = _sre.unicode_tolower(code)
        kinds[min((lower, *re._compiler._EXTRA_CASES.get(lower, ())))] += chr(code)
    return "".join(kind for kind in kinds.values()
                   if len(kind) > 2 or any(ord(each) in re._compiler._EXTRA_CASES for each in kind))


def cases():
    fixtures = sorted(path.name for path in (REPO / "tests/fixtures").glob("*-pane.txt"))
    compiled = [(harness, key, each) for harness, _ in config.manifests()
                for key, each in patterns("", watch.screen(harness))]
    cased = letters()
    folded = [(pattern, flags) for letter in cased
              for pattern, flags in ((letter, re.I), (f"(?i)[{letter}]", 0))]
    return {"fixtures": fixtures, "patterns": [
        {"harness": harness, "key": key, "pattern": each.pattern, "flags": said(flags),
         "matches": [match for name in fixtures for match in searched(each.pattern, flags, name)]}
        for harness, key, each in compiled
        # the flags watch gave, never those the pattern sets itself, which Go reads as Python does
        for flags in [each.flags & ~re.compile(each.pattern).flags]],
        "cased": {"letters": cased, "patterns": [
            {"pattern": pattern, "flags": said(flags),
             "found": "".join(each for each in cased if re.search(pattern, each, flags))}
            for pattern, flags in [*folded, ("[a-z]", re.I), ("(?i)[^α-ω]", 0)]]}}


def said(flags):
    return "".join(letter for letter, flag in (("i", re.I), ("m", re.M)) if flags & flag)


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
