"""One rulebook reaches every harness, and no harness carries rules of its own.

An orchestrator behaves one way whatever harness runs it, and so does a worker:
every adapter's `interactive` line injects the text `tools/rulebook.py` assembles
and nothing else as instructions, every `run` hands its harness exactly the prompt
`worker.call` wrote, and no install ever writes a global instruction file for any
harness.  The adapter loops read `adapters/*.toml`, so a harness added later is
covered the way the three here are.

Offline: the real adapters and the real install.sh, run against a sandbox HOME
with fake harness binaries on PATH; no harness, no network, and nothing outside
that HOME is touched.
"""

from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, worker

spec = importlib.util.spec_from_file_location("rulebook", REPO / "tools/rulebook.py")
rulebook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rulebook)

# Every harness agentkit knows, by its adapter manifest; the loops below stay
# generic so a fourth and a fifth harness are covered without touching this file.
HARNESSES = sorted(path.stem for path in (REPO / "adapters").glob("*.toml"))
# The global instruction file of every harness, present or planned: Claude's and
# Codex's by name, Grok's as the task names it, OpenCode's under its config dir,
# Muse's equivalent beside its own settings, and Gemini's.  agentkit writes none of them.
GLOBAL_INSTRUCTIONS = (".claude/CLAUDE.md", ".codex/AGENTS.md", ".grok/GROK.md",
                       ".config/opencode/AGENTS.md", ".config/muse/AGENTS.md",
                       ".gemini/GEMINI.md")
# Anything on an `interactive` line that would be instructions besides the one
# rulebook mechanism: another system prompt, another instructions file, or one of
# the global files above named where only the rulebook belongs.
STRAY = re.compile(r"system.?prompt|developer.?instructions|instructions?.?file"
                   r"|agents\.md|claude\.md|grok\.md|muse\.md|gemini\.md", re.IGNORECASE)

# A harness that keeps everything it was given -- its stdin, and every existing
# file named on its command line -- and then answers the three event shapes every
# adapter's jq reads, so each adapter finishes the way it does against its own.
FAKE_HARNESS = """#!/bin/sh
dir=${FAKE_SEEN:?}
name=$(basename "$0")
ofile=""; prev=""
for a in "$@"; do
  if [ -n "$prev" ]; then
    [ "$prev" = -o ] && ofile=$a
    prev=""; continue
  fi
  case $a in -o|--prompt-file) prev=$a;; esac
done
if [ -t 0 ]; then : >"$dir/$name.stdin"; else cat >"$dir/$name.stdin"; fi
n=0
for a in "$@"; do
  [ -n "$ofile" ] && [ "$a" = "$ofile" ] && continue
  case $a in /*) ;; *) continue;; esac   # absolute paths only: a flag word that
  [ -f "$a" ] || continue                 # happens to match a file here is not one
  n=$((n + 1)); cp "$a" "$dir/$name.argv$n"
done
[ -n "$ofile" ] && printf 'fake final\\n' >"$ofile"
# every argument, so a prompt passed as a word rather than a file is visible
# too. A file the harness was told to read is copied above; this list is not one.
python3 - "$dir/$name.argv" "$@" <<'PY'
import json, sys
open(sys.argv[1], "w").write(json.dumps(sys.argv[2:]))
PY
printf '%s\\n' '{"type":"result","result":"fake final","session_id":"fake-sid"}'
printf '%s\\n' '{"type":"thread.started","thread_id":"fake-sid"}'
printf '%s\\n' '{"stream":{"kind":"session","id":"fake-sid"},' \\
  '"payload":{"kind":"run_terminal","text":"fake final"}}'
"""


class OneRulebook(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".one-rulebook-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.state = self.home / ".agentkit/state"
        self.state.mkdir(parents=True)
        self.ws = self.home / "ws"
        self.ws.mkdir()
        # This HOME is the whole host, for what runs in this process as much as
        # for what it starts; without the tmux socket no server of the account's
        # is ever named, and without a config dir nothing outside this HOME is.
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(config, "HOME", self.home / ".agentkit"))
        stack.enter_context(patch.object(config, "STATE", self.state))
        stack.enter_context(patch.dict(os.environ, {"HOME": str(self.home)}))
        os.environ.pop(config.ADAPTER_DIR_ENV, None)   # the checkout's adapters, never a copy
        os.environ.pop("AGENTKIT_TMUX_SOCKET", None)
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.seen = self.home / "seen"
        self.seen.mkdir()
        fakes = self.home / "bin"
        fakes.mkdir()
        (fakes / "harness").write_text(FAKE_HARNESS)
        (fakes / "harness").chmod(0o755)
        stack.enter_context(patch.dict(os.environ, {"PATH": f"{fakes}:{os.environ['PATH']}",
                                                   "FAKE_SEEN": str(self.seen)}))
        for harness in HARNESSES:
            (fakes / self.binary(harness)).symlink_to("harness")
        self.assertGreaterEqual(set(HARNESSES), {"claude", "codex", "muse"})

    def interactive(self, harness, seat="atoll"):
        """One `interactive` line, as `ak orch` asks for it, split into words."""
        proc = subprocess.run([str(REPO / f"adapters/{harness}.sh"), "interactive",
                               "test-model", "high"],
                              capture_output=True, text=True,
                              env={**os.environ, "AGENTKIT_SESSION": seat})
        self.assertEqual(proc.returncode, 0, f"{harness}: {proc.stderr}")
        return shlex.split(proc.stdout)

    def binary(self, harness):
        """The program this adapter finally execs: the first word after the last
        `--` on its `interactive` line, past `env` and its `NAME=value` pins."""
        words = self.interactive(harness)
        seps = [i for i, word in enumerate(words) if word == "--"]
        tail = words[seps[-1] + 1:] if seps else words
        at = 1 if tail[:1] == ["env"] else 0
        while at < len(tail) and re.match(r"[A-Za-z_][A-Za-z0-9_]*=", tail[at]):
            at += 1
        self.assertLess(at, len(tail), f"{harness}: no program on its line")
        return tail[at]

    @staticmethod
    def value_of(word):
        """The value a word carries: past `NAME=`, or the whole word."""
        if re.match(r"[A-Za-z_][A-Za-z0-9_]*=", word):
            return word.split("=", 1)[1]
        return word

    def doc_others(self, value, want):
        """The strings beside the rulebook in the document this value holds, or
        None where it holds no document carrying the rulebook."""
        try:
            doc = json.loads(value)
        except ValueError:
            return None
        if not isinstance(doc, (dict, list)):
            return None
        strings, stack = [], [doc]
        while stack:
            node = stack.pop()
            if isinstance(node, str):
                strings.append(node)
            elif isinstance(node, dict):
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        if want not in strings:
            return None
        return [s for s in strings if s != want]

    def candidate_path(self, word):
        """A word that might name a file. Inlined rulebook text is not one.

        A rulebook carried as the text itself, or as a document holding it, is
        no path. Statting either asks the kernel for a name longer than PATH_MAX.
        """
        value = self.value_of(word)
        if (not value or "\n" in value or len(value) > 1024 or value[0] in "{["
                or not (value.startswith("/") or value.startswith("."))):
            return None
        return Path(value)

    def rulebook_files(self, words):
        """State files of rulebook.py's making named on the line."""
        found = []
        for word in words:
            path = self.candidate_path(word)
            if path is None:
                continue
            try:
                is_file = path.is_file()
            except OSError:
                continue
            if is_file and path.parent == self.state and path.name.startswith("rulebook-"):
                found.append(path)
        return found

    def inlined_rulebooks(self, words):
        """Rulebook text carried on the line, not as a path: a word that is the
        text itself, or a document holding it beside the launch's other pins."""
        want = rulebook.text()
        found = []
        for word in words:
            value = self.value_of(word)
            if value == want:
                found.append(value.encode())
            elif self.doc_others(value, want) is not None:
                found.append(want.encode())
        return found

    def definitions(self, words):
        """{word: front matter lines}, and the bodies, of the definition files a directory
        of the state dir's named on the line holds: a harness whose system prompt is an
        agent definition is handed one.  Every file under it is front matter and then a
        body, and the whole file is the body where it is not, so no other file there can
        carry text of its own past both checks."""
        heads, bodies = {}, []
        for word in words:
            path = self.candidate_path(word)
            try:
                if path is None or not path.is_dir() or self.state not in path.parents:
                    continue
            except OSError:
                continue
            for item in sorted(p for p in path.rglob("*") if p.is_file()):
                text = item.read_text()
                head, sep, body = text[4:].partition("\n---\n")
                if not (text.startswith("---\n") and sep):
                    head, body = "", text
                heads.setdefault(word, []).extend(head.splitlines())
                bodies.append(body.encode())
        return heads, bodies

    def carried(self, harness, words):
        """(files, texts) this line uses to hand over the rulebook."""
        files = self.rulebook_files(words)
        texts = ([path.read_bytes() for path in files] + self.inlined_rulebooks(words)
                 + self.definitions(words)[1])
        self.assertTrue(texts, f"{harness}: no rulebook on its line")
        return files, texts

    def bare(self, harness, words, paths):
        """That line with the one rulebook mechanism taken out: a word naming an
        existing rulebook file is read, any other rulebook word is the text itself,
        a document holding it or a directory of definitions, and the flag that named
        a bare word goes with it.  Whatever is left has to carry no instructions, and
        a definition's front matter is left in the directory's place."""
        names = {str(path) for path in paths}
        want = rulebook.text()
        heads = self.definitions(words)[0]
        keep, taken = [], 0
        for word in words:
            value = self.value_of(word)
            if value in names or value == want:
                others = []
            elif word in heads:
                others = heads[word]
            else:
                others = self.doc_others(value, want)
                if others is None:
                    keep.append(word)
                    continue
            # A bare word was named by the flag before it, whatever that flag
            # is called; a `NAME=value` word names itself, and the word before
            # it is some other argument that stays under scrutiny.  A document's
            # other pins stay under it too, in the document's place.
            if word == value and keep and keep[-1].startswith("-") and "=" not in keep[-1]:
                keep.pop()
            keep.extend(others)
            taken += 1
        self.assertGreater(taken, 0, f"{harness}: the mechanism was not found")
        return keep

    def test_interactive_injects_the_same_rulebook_on_every_harness(self):
        texts = {}
        for harness in HARNESSES:
            _, copies = self.carried(harness, self.interactive(harness))
            texts[harness] = copies
        for harness, copies in texts.items():
            for copy in copies:
                self.assertEqual(copy, rulebook.text().encode(), harness)
        first = next(iter(texts))
        for harness in texts:
            self.assertEqual(texts[harness], texts[first],
                             f"{harness} is handed other rules than {first}")

    def test_interactive_adds_no_instructions_of_its_own(self):
        for harness in HARNESSES:
            words = self.interactive(harness)
            paths, _ = self.carried(harness, words)
            rest = self.bare(harness, words, paths)
            stray = [word for word in rest if STRAY.search(word)]
            self.assertEqual(stray, [], f"{harness} adds instructions: {stray}")
            others = []
            for word in rest:
                path = self.candidate_path(word)
                if path is not None and path.is_file() and path.parent == self.state:
                    others.append(word)
            self.assertEqual(others, [], f"{harness} names another state file: {others}")
            self.seat_wrapper_passes_the_rulebook_through(harness, words, paths)

    def seat_wrapper_passes_the_rulebook_through(self, harness, words, paths):
        """Where the rulebook reaches the harness through a seat wrapper -- a program
        on the line whose own arguments name the rulebook file -- the wrapper is run
        against a fake harness and the text it hands over is the file's, byte for
        byte.  A harness with no wrapper has nothing to pass through."""
        names = {str(path) for path in paths}
        for at, word in enumerate(words):
            if not word.endswith(".py"):
                continue
            end = next((j for j in range(at + 1, len(words)) if words[j] == "--"),
                       len(words))
            if not any(self.value_of(w) in names for w in words[at + 1:end]):
                continue
            echo = self.home / "echobin"
            echo.mkdir(exist_ok=True)
            (echo / self.binary(harness)).write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            (echo / self.binary(harness)).chmod(0o755)
            start = at - 1 if at > 0 else at
            proc = subprocess.run(words[start:], capture_output=True, text=True,
                                  env={**os.environ, "PATH": f"{echo}:{os.environ['PATH']}"})
            self.assertEqual(proc.returncode, 0, f"{harness}: {proc.stderr}")
            for path in paths:
                self.assertIn(path.read_text(), proc.stdout, harness)
            return

    def test_host_rules_ride_the_same_text_on_every_harness(self):
        (self.home / ".agentkit/rules.md").write_text("# This host\n\nThe printer is upstairs.\n")
        want = rulebook.text().encode()
        self.assertIn(b"The printer is upstairs.", want)
        for harness in HARNESSES:
            _, copies = self.carried(harness, self.interactive(harness))
            for copy in copies:
                self.assertEqual(copy, want, harness)

    def test_run_hands_the_harness_exactly_what_worker_call_wrote(self):
        cfg = {"models": {f"probe-{h}": {"harness": h, "model": "test-model",
                                         "effort": "high", "provider": "p"}
                          for h in HARNESSES},
               "providers": {"p": {"mode": "subscription"}}}
        with patch.object(worker, "auth_ok", return_value=(None, "")):
            for harness in HARNESSES:
                binary = self.binary(harness)
                for role in ("executor", "reviewer"):
                    out = self.home / f"out-{harness}-{role}"
                    code, _, _, _ = worker.call(cfg, f"probe-{harness}",
                                                "Do the thing.", self.ws, out, role)
                    self.assertEqual(code, 0, harness)
                    prompt = (out / "prompt.md").read_bytes()
                    self.assertEqual(
                        prompt,
                        f"{worker.PREAMBLES[role].format(workspace=self.ws)}\n\n"
                        f"Do the thing.".encode(), f"{harness} {role}")
                    argv_path = self.seen / f"{binary}.argv"
                    argv = json.loads(argv_path.read_text()) if argv_path.exists() else []
                    received = [path.read_bytes() for path in sorted(self.seen.glob(
                        f"{binary}.*"))
                                if path.name != f"{binary}.argv" and path.stat().st_size]
                    handed = received or [arg.encode() for arg in argv if arg.encode() == prompt]
                    self.assertTrue(handed, f"{harness} was handed nothing to read")
                    for copy in received:
                        self.assertEqual(copy, prompt, f"{harness} {role} got other words")
                    if not received:
                        self.assertIn(prompt, [arg.encode() for arg in argv],
                                      f"{harness} {role}")
                    for path in self.seen.glob(f"{binary}.*"):
                        path.unlink()

    def installed(self, home):
        """A full install.sh into that HOME, offline: under a HOME that is not the
        account's own it touches nothing outside it, and the python3 running this
        suite plus the system dirs are the whole PATH, so the real harnesses are
        not found and nothing is registered with them."""
        path = os.pathsep.join(dict.fromkeys(
            (os.path.dirname(sys.executable), "/usr/bin", "/bin")))
        proc = subprocess.run(["bash", str(REPO / "install.sh")], capture_output=True,
                              text=True, env={**os.environ, "HOME": str(home),
                                              "PATH": path})
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        return proc

    def test_install_writes_no_global_instruction_file(self):
        home = self.home / "fresh"
        home.mkdir()
        self.installed(home)
        for rel in GLOBAL_INSTRUCTIONS:
            self.assertFalse((home / rel).exists() or (home / rel).is_symlink(),
                             f"install.sh created {rel}")

    def test_install_leaves_the_user_s_own_instruction_files_alone(self):
        home = self.home / "owned"
        for rel in GLOBAL_INSTRUCTIONS:
            path = home / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"the user's own {rel}\n")
        self.installed(home)
        for rel in GLOBAL_INSTRUCTIONS:
            path = home / rel
            self.assertTrue(path.is_file() and not path.is_symlink(), rel)
            self.assertEqual(path.read_text(), f"the user's own {rel}\n", rel)

    def adding_a_harness(self):
        """The adapter contract, from its heading to the next section's."""
        text = (REPO / "docs/guide.md").read_text()
        start = text.index("### Adding a harness")
        end = text.index("\n## ", start + 1)
        return text[start:end]

    def test_adding_a_harness_names_the_shared_rulebook_rule(self):
        section = self.adding_a_harness()
        self.assertIn("shared helper", section)
        self.assertIn("may not add instructions of its own", section)

    def test_project_agent_files_are_conventions_not_rules(self):
        text = (REPO / "docs/guide.md").read_text()
        self.assertIn("conventions", text)
        self.assertIn("never the place for agentkit's rules", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
