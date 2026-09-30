"""Boundaries: each piece of knowledge has one home, and the copies outside it only shrink.

A rule names the knowledge, a pattern `git grep` finds it by, the path prefixes that are its
home, and `max`: the count of matching lines outside that home on the day the rule was written.
A count above `max` fails with every path:line; a count below it passes and says which `max`
to lower.  Any task may lower a `max` in the area it touches, and no task raises one.
Offline: `git grep` over the tracked files of this checkout.
"""

import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Tests pin each piece of knowledge with fixtures, and the docs describe it to a reader: both
# follow the code wherever it lives, so the rules count where the product itself keeps a copy.
SCOPE = ("--", ".", ":!tests/", ":!*.md")

RULES = [
    # A harness is its adapter pair and its plugin, and a model is bound to its harness and
    # provider by one config.default.toml entry: every other copy of a name is harness
    # knowledge that adding, renaming or dropping a harness has to find and change.
    {"name": "harness and provider names",
     "flags": ("-i", "-w"),
     "pattern": "claude|codex|muse|opencode|grok|grokbuild|antigravity|gemini|anthropic|openai"
                "|xai|mimo|[\"']meta[\"']|[\"']google[\"']",
     "home": ("adapters/", "agentkit/harness/", "config.default.toml"),
     "max": 304},
    # What a refusal from a provider looks like is the harness's to say (adapters/*.toml,
    # its plugin): a copy in the loop or the watcher is a second classifier to keep in step.
    {"name": "provider failure words",
     "flags": ("-i",),
     "pattern": "rate[ _-]?limit|quota|capacity|overload|usage[ _-]?limit",
     "home": ("adapters/", "agentkit/harness/"),
     "max": 153},
    # run.json has one writer, so its keys and their transitions can be read in one file.
    # Called through the module (`run.save_state`); watch.py's own `save_state` writes the
    # watcher's state, not a run record.
    {"name": "run-record writes",
     "flags": (),
     "pattern": r"\.save_state\(",
     "home": ("agentkit/run.py",),
     "max": 0},
    # A live loop writes its record through `Loop.write`, which keeps what the watcher or a
    # rename put there since; a whole save of its memory would put the old record back.
    {"name": "a live loop's whole saves",
     "flags": (),
     "pattern": r"save_state\((self\.)?lp\.",
     "home": (),
     "max": 0},
    # A seat's files are named once, so a rename, a forget or a new store moves them all.
    {"name": "per-seat state file names",
     "flags": (),
     "pattern": r"(session|notify|card|seat|hook|compact|stop|plan|title|rulebook)-"
                r"(\{[^}]*\}|\$\{?[A-Za-z_]+\}?|\*)\.(json|md)"
                r"|len\([\"'](session|notify|card|seat|hook|compact|stop|plan)-[\"']\)",
     "home": ("agentkit/config.py",),
     "max": 11},
]


def outside(rule):
    """Each `path:line: text` matching the rule outside its home."""
    proc = subprocess.run(["git", "-C", str(REPO), "grep", "-n", "-I", "--no-color", "-E",
                           *rule["flags"], "-e", rule["pattern"], *SCOPE],
                          capture_output=True, text=True)
    if proc.returncode not in (0, 1):     # 1 is no match at all
        raise AssertionError(f"git grep failed: {proc.stderr}")
    return [line for line in proc.stdout.splitlines() if not line.startswith(rule["home"])]


class Boundaries(unittest.TestCase):
    def test_no_count_rises_above_its_max(self):
        for rule in RULES:
            with self.subTest(rule["name"]):
                found = outside(rule)
                self.assertLessEqual(
                    len(found), rule["max"],
                    f"{rule['name']}: {len(found)} lines outside {', '.join(rule['home'])}, "
                    f"max {rule['max']}; a max only goes down, so move the knowledge home:\n"
                    + "\n".join(found))
                if len(found) < rule["max"]:
                    print(f"{rule['name']}: {len(found)} lines, under max {rule['max']}: "
                          f"lower its max in tests/test_boundaries.py to {len(found)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
