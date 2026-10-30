"""Boundaries: each piece of knowledge has one home, and the copies outside it only shrink.

A rule names the knowledge, a pattern `git grep` finds it by, the path prefixes that are its
home, and `max`: the count of matching lines outside that home on the day the rule was written.
A rule's `names` are ak's own that the pattern also finds: a line counts only if the pattern
still finds something once they are taken out of it.
A count above `max` fails with every path:line; a count below it passes and says which `max`
to lower.  Any task may lower a `max` in the area it touches, and no task raises one.
Existing maxima cannot exceed origin/main's; an unreadable target skips that comparison.
The files every model ak runs is handed whole have a word `max` that only goes down the same way.
Offline: `git grep` over the tracked files of this checkout.
"""

import ast
import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Python and Go tests pin knowledge with fixtures, and docs describe it to a reader: both
# follow the code wherever it lives, so the rules count where the product itself keeps a copy.
SCOPE = ("--", ".", ":!tests/", ":!*_test.go", ":!*.md")

RULES = [
    # Lifecycle reads belong to the lightweight reader, so a completed tool never needs
    # the screen watcher. The two reads formerly in watch.py have moved here together.
    {"name": "lifecycle fact interpretation",
     "flags": (),
     "pattern": r'fact\.get\("event"\)|hook_facts_path\([^)]*\)\.read_text',
     "home": ("agentkit/lifecycle.py",),
     "max": 0},
    # The old wrapper owned four blocking transfer/drain sites. One relay now
    # owns both directions, so another injector cannot reintroduce their cycle.
    {"name": "terminal relay",
     "flags": (),
     "pattern": r"\b(to_child|to_owner)\b|write_all\((master_fd|stdout_fd)|"
                r"select\.select\(\[master_fd",
     "home": ("agentkit/pty_relay.py",),
     "max": 0},
    # Scoreboard formulas and display words stay together so a change has one home.
    {"name": "scoreboard",
     "flags": (),
     "pattern": r"\b(first_round|token_share|code_lines|readme_words|agents_words)\b|"
                r"Scoreboard \(reported tokens|no runs ended|median tokens per merged run",
     "home": ("agentkit/scoreboard.py", "go/internal/cli/scoreboard.go"),
     "max": 0},
    # Process cleanup must use the worker's marker, so every ak home sweeps only its runs.
    {"name": "run marker",
     "flags": (),
     "pattern": r"AGENTKIT_RUN\b",
     "home": ("agentkit/worker.py", "go/internal/host/process.go"),
     "max": 0},
    # Host and cgroup readings have one reader: paths and counter names in code or
    # comments outside host.py count as another copy of how the host reports them.  A machine
    # reached over ssh has no host.py to import: tools/machine.sh reads it there.
    {"name": "host readings",
     "flags": (),
     "pattern": r"/proc/meminfo|/proc/loadavg|/sys/fs/cgroup|cgroup\.freeze|"
                r"\b(cpu|memory|pids)\.(pressure|stat|max|high|current|events)\b|CGROUP_ROOT",
     "home": ("agentkit/host.py", "go/internal/host/readings.go", "tools/machine.sh"),
     "max": 0},
    # A process's stat and statm fields have one reader: host.proc_stat names them, and
    # host.resident_bytes counts pages. box.py runs as its own script inside the worker's
    # walls, and proc_snapshot.py under sudo with no agentkit imports: each keeps a copy.
    {"name": "process stat",
     "flags": (),
     "pattern": r'"stat"|"statm"|/stat\b|/statm\b',
     "home": ("agentkit/host.py", "go/internal/host/process.go"),
     "max": 3},
    # The heavy-suite turn owns its lock files, landing wait marker and child flag.
    {"name": "heavy suite turn",
     "flags": (),
     "pattern": r"\.heavy-|landing_since|AK_HEAVY_TURN",
     "home": ("agentkit/gate.py", "go/internal/host/lines.go"),
     "max": 0},
    # Run admission owns its lock, steady-poll counter and polling knob.
    {"name": "run admission",
     "flags": (),
     "pattern": r"\.slots\.lock|slot_healthy_polls|AK_SLOT_POLL",
     "home": ("agentkit/gate.py",),
     "max": 0},
    # A harness is its adapter pair and its plugin, and a model is bound to its harness and
    # provider by one config.default.toml entry: every other copy of a name is harness
    # knowledge that adding, renaming or dropping a harness has to find and change.
    # Go embeds generated copies; TestEmbeddedDefault and TestEmbeddedAdapters refuse any
    # difference from the sources.
    {"name": "harness and provider names",
     "flags": ("-i", "-w"),
     "pattern": "claude|codex|muse|opencode|grok|grokbuild|antigravity|gemini|anthropic|openai"
                "|xai|mimo|[\"']meta[\"']|[\"']google[\"']",
     "home": ("adapters/", "agentkit/harness/", "config.default.toml",
              "go/internal/config/default.toml", "go/internal/config/adapters/"),
     "max": 186},
    # What a refusal from a provider looks like is the harness's to say (adapters/*.toml,
    # its plugin): a copy in the loop or the watcher is a second classifier to keep in step.
    # Every provider word counts, in code or comment, but none of ak's own names: the
    # `quota_dry` mark and its `QuotaDry` stop, the tests' `.run-quota-` dirs, the cgroup CPU
    # quota (`cpu_quota`, systemd's `CPUQuota`, the user unit's `unit_quota`), the
    # usage-limit reset and its credits as the name of a feature, and what a subscription's
    # week holds in tokens (`capacity.json`, `ak usage --json`'s `capacity_tokens` and
    # `capacity_pairs`).
    {"name": "provider failure words",
     "flags": ("-i",),
     "pattern": "rate[ _-]?limit|quota|capacity|overload|usage[ _-]?limit",
     "names": r"quota[_-]?dry|run-quota|(cpu|unit)[ _]?quota|usage[ -]limit (reset|credit)"
              r"|capacity[._](json|tokens|pairs)",
     "home": ("adapters/", "agentkit/harness/", "go/internal/config/adapters/"),
     "max": 59},
    # The run loop, admission and a stop write run.json through its one writer.
    # Called through the module (`record.save_state`); watch.py's own `save_state` writes the
    # watcher's state, not a run record.
    {"name": "run-record writes",
     "flags": (),
     "pattern": r"\.save_state\(",
     "home": ("agentkit/run.py", "agentkit/gate.py", "agentkit/stop.py", "agentkit/turns.py",
              "agentkit/transitions.py",
              "agentkit/handback.py",
              "agentkit/roundloop.py",
              "agentkit/deliver.py"),
     "max": 0},
    # A run's writer owns the temporary files and recovery lock it leaves on disk, in each program.
    {"name": "run record write",
     "flags": (),
     "pattern": r"run\.tmp|delivery\.tmp|recovery\.lock",
     "home": ("agentkit/record.py", "go/internal/run/write.go"),
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
     "max": 6},
    # A rename leaves a pointer at the old name; each implementation's config follows it.
    # A walk outside config is one more place to keep in step with how renames chain.
    # The one left is seat-state.sh's jq walk.  OpenCode's own `session.renamed` event is no
    # pointer.
    {"name": "rename chain walks",
     "flags": (),
     "pattern": r"[\"']renamed[\"']|\.renamed([^A-Za-z0-9_]|$)",
     "names": r"session\.renamed",
     "home": ("agentkit/config.py", "go/internal/config/session.go"),
     "max": 1},
    # The recorded ending of a turn has one decider. The native hook and the tick
    # supply their own evidence and census; parked-work and wait precedence stay in stop.py.
    {"name": "recorded turn ending",
     "flags": (),
     "pattern": r"^def recorded_ending\(|^def (waiting|parked)\(seat|"
                r"if not (parked|undecided) and",
     "home": ("agentkit/stop.py",),
     "max": 0},
    # A task file's format is read in one module: a pattern for its front-matter fence
    # (`^---\n`) or its `## Done when` heading is a second reader to keep in step.  A task
    # written out (`## Done when\n```bash`) is no reader, and `FRONT` reads AGENTS.md's front
    # matter, the repository's declarations, not a task's.
    {"name": "task file format",
     "flags": (),
     "pattern": r"\^---\\n|Done when\\s",
     "names": r"FRONT = re\.compile\(r\"\^---\\n",
     "home": ("agentkit/task.py", "go/internal/task/"),
     "max": 0},
    # A job's receipt has one home: every read, write, path or fingerprint of it -- gc's,
    # status's, resume's and the menu's included -- asks its job module, so a line elsewhere that
    # names its file, in code or in a comment, is a second idea of where a job keeps it.
    {"name": "job receipt",
     "flags": (),
     "pattern": r"job\.json",
     "home": ("agentkit/job.py", "go/internal/job/"),
     "max": 0},
    # A run's state words are grouped once, in record.py (ACTIVE, FAILED, ENDED, GOING): a
    # literal group elsewhere is a second copy that a new state word would miss. install.sh
    # reads run records before agentkit is installed, so it keeps its own.
    {"name": "run state groups",
     "flags": (),
     "pattern": r'\("(queued|running)", "(queued|running)"[,)]|"fail", "error", "blocked"|'
                r'^(ENDED|GOING) = ',
     "home": ("agentkit/record.py", "go/internal/run/record.go"),
     "max": 1},
    # A run's worktree goes one way: the repo's `cleanup:` line, then git, then its `ak/`
    # branch. Each call of the cleanup line outside worktrees.py spells that order again.
    {"name": "run worktree removal",
     "flags": (),
     "pattern": r"run_repo_cleanup\(",
     "home": ("agentkit/worktrees.py",),
     "max": 0},
    # Typing into a seat is the tick's, under its lock: a second typer needs claims and
    # delivery reports that each review round found a new race in (#439, 3 rounds).  The
    # guard names the typing commands to refuse them in a seat; each call outside watch.py
    # into a watch function that types is the one typer of its kind of line.
    {"name": "typing into a seat",
     "flags": (),
     "pattern": r"\"(send-keys|paste-buffer|send-prefix)\"|"
                r"watch\.(_send_line|_send_enter|type_into|type_checked|type_at_prompt|revive|"
                r"ask_inbox|after_merge_deliver|sync_title)\(",
     "home": ("agentkit/watch.py", "agentkit/guard.py"),
     "max": 8},
    # Every unit ak starts is started by orch.py, which decides what ends it: a seat's scope
    # and detached work's end with what they started, and a run's is stopped by its reaper.
    # Looking the program up starts nothing: Go's manager probe does, as orch.user_manager does.
    {"name": "unit starts",
     "flags": (),
     "pattern": r"\"systemd-run\"|StartTransientUnit",
     "names": r'LookPath\("systemd-run"\)',
     "home": ("agentkit/orch.py",),
     "max": 0},
    # Foreground and detached callers share the receipt and plain fallback in orch.py.
    {"name": "slice placement protocol",
     "flags": (),
     "pattern": r"\b(WITNESS|marked_pid|stop_placed)\b",
     "home": ("agentkit/orch.py",),
     "max": 0},
]

# Every model ak runs is handed these whole, so each word costs every task some of its attention
# (the owner's yes, 15 Oct 2026, set at their size of 16 Oct).  A line added makes room: a rule
# turned into a check, what one area needs moved to a comment at that code, or what is stale
# deleted.  No task raises a max; the owner raises one by merging that change by hand.
WORDS = {"AGENTS.md": 2977, "orchestrator.md": 2140}


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


def where_change_left_main(test, path):
    """`path`'s text where this change left origin/main; an unreadable one skips `test`."""
    # against where this change started: a commit main has since moved past (as the host's
    # live check tests) is not held to what main changed after it
    base = subprocess.run(["git", "-C", str(REPO), "merge-base", "HEAD", "origin/main"],
                          capture_output=True, text=True).stdout.strip() or "origin/main"
    proc = subprocess.run(["git", "-C", str(REPO), "show", f"{base}:{path}"],
                          capture_output=True, text=True)
    if proc.returncode:
        print(f"origin/main:{path} is not readable; skipping the comparison")
        test.skipTest("origin/main is not readable")
    return proc.stdout


class Boundaries(unittest.TestCase):
    def test_no_max_rises_above_origin_main(self):
        source = where_change_left_main(self, "tests/test_boundaries.py")
        # Literal parsing keeps target code from running during the comparison.
        found = {target.id: ast.literal_eval(node.value) for node in ast.parse(source).body
                 if isinstance(node, ast.Assign) for target in node.targets
                 if isinstance(target, ast.Name) and target.id in ("RULES", "WORDS")}
        maxima = {rule["name"]: rule["max"] for rule in found["RULES"]} | found.get("WORDS", {})
        for name, most in ({rule["name"]: rule["max"] for rule in RULES} | WORDS).items():
            if name in maxima:
                with self.subTest(name):
                    self.assertLessEqual(
                        most, maxima[name],
                        f"{name}: max {most} exceeds the max {maxima[name]} where this change "
                        "left origin/main; a max only goes down")

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

    def test_no_file_grows_past_its_word_max(self):
        for path, most in WORDS.items():
            with self.subTest(path):
                words = len((REPO / path).read_text().split())
                self.assertLessEqual(
                    words, most,
                    f"{path}: {words} words, max {most}; a max only goes down, so make room: "
                    "turn a rule into a check, move what one area needs to its code, or delete "
                    "what is stale")
                if words < most:
                    print(f"{path}: {words} words, under max {most}: lower its max in "
                          f"tests/test_boundaries.py to {words}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
