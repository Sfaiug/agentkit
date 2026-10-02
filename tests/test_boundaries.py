"""Boundaries: each piece of knowledge has one home, and the copies outside it only shrink.

A rule names the knowledge, a pattern `git grep` finds it by, the path prefixes that are its
home, and `max`: the count of matching lines outside that home on the day the rule was written.
A rule's `names` are ak's own that the pattern also finds: a line counts only if the pattern
still finds something once they are taken out of it.
A count above `max` fails with every path:line; a count below it passes and says which `max`
to lower.  Any task may lower a `max` in the area it touches, and no task raises one.
Offline: `git grep` over the tracked files of this checkout.
"""

import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Tests pin each piece of knowledge with fixtures, and the docs describe it to a reader: both
# follow the code wherever it lives, so the rules count where the product itself keeps a copy.
SCOPE = ("--", ".", ":!tests/", ":!*.md")

RULES = [
    # Process cleanup must use the worker's marker, so every ak home sweeps only its runs.
    {"name": "run marker",
     "flags": (),
     "pattern": r"AGENTKIT_RUN\b",
     "home": ("agentkit/worker.py",),
     "max": 0},
    # Host and cgroup readings have one reader: paths and counter names in code or
    # comments outside host.py count as another copy of how the host reports them.
    {"name": "host readings",
     "flags": (),
     "pattern": r"/proc/meminfo|/proc/loadavg|/sys/fs/cgroup|cgroup\.freeze|"
                r"\b(cpu|memory|pids)\.(pressure|stat|max|high|current|events)\b|CGROUP_ROOT",
     "home": ("agentkit/host.py",),
     "max": 0},
    # The heavy-suite turn owns its lock files, landing wait marker and child flag.
    {"name": "heavy suite turn",
     "flags": (),
     "pattern": r"\.heavy-|landing_since|AK_HEAVY_TURN",
     "home": ("agentkit/gate.py",),
     "max": 0},
    # A harness is its adapter pair and its plugin, and a model is bound to its harness and
    # provider by one config.default.toml entry: every other copy of a name is harness
    # knowledge that adding, renaming or dropping a harness has to find and change.
    {"name": "harness and provider names",
     "flags": ("-i", "-w"),
     "pattern": "claude|codex|muse|opencode|grok|grokbuild|antigravity|gemini|anthropic|openai"
                "|xai|mimo|[\"']meta[\"']|[\"']google[\"']",
     "home": ("adapters/", "agentkit/harness/", "config.default.toml"),
     "max": 288},
    # What a refusal from a provider looks like is the harness's to say (adapters/*.toml,
    # its plugin): a copy in the loop or the watcher is a second classifier to keep in step.
    # Every provider word counts, in code or comment, but none of ak's own names: the
    # `quota_dry` mark and its `QuotaDry` stop, the tests' `.run-quota-` dirs, the cgroup CPU
    # quota (`cpu_quota`, systemd's `CPUQuota`, the user unit's `unit_quota`), and the
    # usage-limit reset and its credits as the name of a feature.
    {"name": "provider failure words",
     "flags": ("-i",),
     "pattern": "rate[ _-]?limit|quota|capacity|overload|usage[ _-]?limit",
     "names": r"quota[_-]?dry|run-quota|(cpu|unit)[ _]?quota|usage[ -]limit (reset|credit)",
     "home": ("adapters/", "agentkit/harness/"),
     "max": 66},
    # run.json has one writer, so its keys and their transitions can be read in one file.
    # Called through the module (`record.save_state`); watch.py's own `save_state` writes the
    # watcher's state, not a run record.
    {"name": "run-record writes",
     "flags": (),
     "pattern": r"\.save_state\(",
     "home": ("agentkit/run.py",),
     "max": 0},
    # A run's writer owns the temporary files and recovery lock it leaves on disk.
    {"name": "run record write",
     "flags": (),
     "pattern": r"run\.tmp|delivery\.tmp|recovery\.lock",
     "home": ("agentkit/record.py",),
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
    # A task file's format is read in one module: a pattern for its front-matter fence
    # (`^---\n`) or its `## Done when` heading is a second reader to keep in step.  A task
    # written out (`## Done when\n```bash`) is no reader, and `FRONT` reads AGENTS.md's front
    # matter, the repository's declarations, not a task's.
    {"name": "task file format",
     "flags": (),
     "pattern": r"\^---\\n|Done when\\s",
     "names": r"FRONT = re\.compile\(r\"\^---\\n",
     "home": ("agentkit/task.py",),
     "max": 0},
    # A job's receipt has one home: every read, write, path or fingerprint of it -- gc's,
    # status's, resume's and the menu's included -- asks job.py, so a line anywhere else that
    # names its file, in code or in a comment, is a second idea of where a job keeps it.
    {"name": "job receipt",
     "flags": (),
     "pattern": r"job\.json",
     "home": ("agentkit/job.py",),
     "max": 0},
]


def outside(rule):
    """Each `path:line: text` matching the rule outside its home."""
    proc = subprocess.run(["git", "-C", str(REPO), "grep", "-n", "-I", "--no-color", "-E",
                           *rule["flags"], "-e", rule["pattern"], *SCOPE],
                          capture_output=True, text=True)
    if proc.returncode not in (0, 1):     # 1 is no match at all
        raise AssertionError(f"git grep failed: {proc.stderr}")
    found = [line for line in proc.stdout.splitlines() if not line.startswith(rule["home"])]
    if rule.get("names"):
        found = [line for line in found if re.search(
            rule["pattern"], re.sub(rule["names"], "", line.split(":", 2)[2], flags=re.I), re.I)]
    return found


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
