"""Finding 16: public help and parser contracts, with only repo-local offline fixtures."""

from contextlib import ExitStack
import importlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys
import tempfile
import tomllib
import unittest
import urllib.request
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Independent expectations: command, first usage line, incomplete/extra arguments,
# and every supported public flag (help itself is implicit).
MATRIX = [
    ("", "usage: ak [", ["--client"], None),
    ("usage", "usage: ak usage [--json]", ["--json"], {"--json"}),
    ("worker", "usage: ak worker MODEL TASK", ["MISSING", "missing.md", "--role"],
     {"--workspace", "--out", "--session", "--role"}),
    ("run", "usage: ak run TASK", ["missing.md", "--exec"],
     {"--rounds", "--exec", "--review", "--anyway", "--no-worktree", "--no-merge", "--bg",
      "--parallel", "--review-pr", "--history", "--why", "--plain", "--json", "--dry-run",
      "--keep"}),
    ("run status", "usage: ak run status [ID]", ["MISSING", "--history"],
     {"--history", "--why", "--plain", "--json"}),
    ("run resume", "usage: ak run resume ID", ["MISSING", "--rounds"],
     {"--rounds", "--bg"}),
    ("run stop", "usage: ak run stop ID", ["MISSING", "--keep"],
     {"--keep"}),
    ("run merge", "usage: ak run merge ID", ["MISSING"], set()),
    ("run clean", "usage: ak run clean ID", ["MISSING"], set()),
    ("run gc", "usage: ak run gc [--dry-run]", ["--dry-run"], {"--dry-run"}),
    ("orch", "usage: ak orch [NAME]", ["missing-seat", "--model"],
     {"--model", "--workers", "--dry-run", "--why"}),
    ("orch list", "usage: ak orch list [--why]", ["unexpected"], {"--why"}),
    ("orch why", "usage: ak orch why NAME", ["MISSING"], set()),
    ("orch stop", "usage: ak orch stop NAME", ["MISSING"], set()),
    ("orch rename", "usage: ak orch rename [OLD] NEW", ["MISSING", "NEW"], set()),
    ("notify", "usage: ak notify needs", ["--check"],
     {"--session", "--dry-run", "--pr", "--check"}),
    ("notify needs", "usage: ak notify needs", ["Question?", "--session"],
     {"--session", "--dry-run"}),
    ("notify done", "usage: ak notify done", ["Summary", "--pr"],
     {"--session", "--dry-run", "--pr"}),
    ("update", "usage: ak update [--dry-run]", ["--dry-run"], {"--dry-run"}),
    ("watch", "usage: ak watch [--dry-run]", ["--dry-run"], {"--dry-run"}),
    ("doctor", "usage: ak doctor", ["unexpected"], set()),
    ("browser", "usage: ak browser <status|login|mcp-register|install>", ["unexpected"], set()),
    ("browser status", "usage: ak browser status", ["unexpected"], set()),
    ("browser login", "usage: ak browser login", ["unexpected"], set()),
    ("browser mcp-register", "usage: ak browser mcp-register", ["unexpected"], set()),
    ("browser install", "usage: ak browser install", ["unexpected"], set()),
    ("attach", "usage: ak attach [--client]", ["--client", "--overlay"],
     {"--client", "--overlay", "--dry-run"}),
    ("fetch", "usage: ak fetch PATH", ["--serve"], {"--serve"}),
    ("macbridge", "usage: ak macbridge [--reader]", ["--lock-fd"], {"--reader"}),
]


def probe():
    """Fresh imports against a private HOME, including guards inside the CLI process."""
    request = json.load(sys.stdin)
    args, mode = request["args"], request["mode"]
    root = Path(os.environ["HELP_FIXTURE"])
    from agentkit import config
    assert config.HOME == root / ".agentkit"
    module = None
    if mode == "module":
        name = {"attach": "menu", "fetch": "macbridge", "doctor": "watch"}.get(args[0], args[0])
        module = importlib.import_module(f"agentkit.{name}")
    elif mode == "notify":
        from agentkit import notify

    calls = []

    def blocked(name):
        def fail(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"operational work: {name}")
        return fail

    def audit(event, values):
        if event in ("subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork",
                     "os.kill", "os.killpg", "socket.connect", "socket.bind", "socket.getaddrinfo"):
            if (mode == "worker" and event in ("subprocess.Popen", "os.posix_spawn") and
                    Path(values[0]).parent == root / "adapters"):
                return
            blocked(event)()
        if event == "open" and isinstance(values[0], (str, bytes)):
            path = os.fsdecode(values[0])
            if path.startswith("/proc/"):
                blocked("process inspection")()
            flags = values[2]
            if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                if mode in ("help", "module") or not Path(path).resolve().is_relative_to(root):
                    blocked(f"write {path}")()
        if event in ("os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.chmod", "os.symlink"):
            if mode in ("help", "module"):
                blocked(event)()

    sys.addaudithook(audit)
    with ExitStack() as stack:
        stack.enter_context(patch.object(urllib.request, "urlopen", side_effect=blocked("HTTP")))
        if mode in ("help", "module"):
            for name in ("ensure_dirs", "load", "current_session", "resolve_session", "server_alias"):
                stack.enter_context(patch.object(config, name, side_effect=blocked(f"config.{name}")))
        if mode == "notify":
            def parsed(name):
                def record(*args, **kwargs):
                    print(json.dumps({"call": name, "args": args, "kwargs": kwargs}))
                    return 0
                return record
            for name in ("shaped", "check"):
                stack.enter_context(patch.object(notify, name, side_effect=parsed(name)))
        if mode == "check":
            response = io.BytesIO(b'{}')
            response.status = request["status"]
            stack.enter_context(patch.object(urllib.request, "urlopen", return_value=response))
        try:
            if module:
                # the same entry points bin/ak's ENTRY names, under the same names
                entry = getattr(module, {"fetch": "fetch_main",
                                         "doctor": "doctor"}.get(args[0], "main"))
                try:
                    code = entry(args[1:])
                except config.Error as exc:
                    print(str(exc), file=sys.stderr)
                    code = 2
            else:
                sys.argv = [str(REPO / "bin/ak"), *args]
                try:
                    runpy.run_path(str(REPO / "bin/ak"), run_name="__main__")
                except SystemExit as exc:
                    code = exc.code
            if mode == "help":
                # Public help must return before command imports.
                loaded = [name for name in ("usage", "worker", "run", "notify", "orch", "menu",
                                            "update", "watch", "browser", "macbridge")
                          if f"agentkit.{name}" in sys.modules]
                assert not loaded, f"help imported operational modules: {loaded}"
        finally:
            assert not calls, f"command/network spies fired: {calls}"
    return code


class CommandHelp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".command-help-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        binaries = self.root / "bin"
        binaries.mkdir()
        # Defense in depth: no tool name can reach a real service, model, or tmux server.
        spy = f'''#!{sys.executable}
import os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
if name == "tmux":
    assert sys.argv[1:3] == ["-L", "agentkit-test"]
with pathlib.Path(os.environ["HELP_FIXTURE"], "command-spy").open("a") as fh:
    fh.write(repr(sys.argv) + "\\n")
sys.exit(91)
'''
        for name in ("tmux", "gh", "git", "ssh", "scp", "curl", "wget", "systemctl", "sudo",
                     "ps", "pgrep", "npx", "npm", "claude", "codex", "muse", "launchctl"):
            path = binaries / name
            path.write_text(spy)
            path.chmod(0o755)
        adapters = self.root / "adapters"
        adapters.mkdir()
        self.cfg = tomllib.loads((REPO / "config.default.toml").read_text())
        adapter = f'''#!{sys.executable}
import json, os, pathlib, sys
assert sys.argv[1] == "run"
out = pathlib.Path(sys.argv[6])
assert out.is_relative_to(pathlib.Path(os.environ["HELP_FIXTURE"]))
(out / "adapter.json").write_text(json.dumps(sys.argv[1:]))
(out / "final.md").write_text("offline turn")
(out / "session_id").write_text("fixture-session")
sys.exit(int(os.environ.get("HELP_WORKER_EXIT", "0")))
'''
        for harness in {entry["harness"] for entry in self.cfg["models"].values()}:
            path = adapters / f"{harness}.sh"
            path.write_text(adapter)
            path.chmod(0o755)
        self.env = {
            "HOME": str(self.root), "TMPDIR": str(self.root), "HELP_FIXTURE": str(self.root),
            "PATH": f"{binaries}:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
            "XDG_CONFIG_HOME": str(self.root / ".config"),
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(sockets),
            "AGENTKIT_ADAPTER_DIR": str(adapters), "AGENTKIT_DISCORD_WEBHOOK": "off",
        }

    def cli(self, args, mode="help", env=None, **kwargs):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--probe"],
                                input=json.dumps({"args": args, "mode": mode, **kwargs}),
                                cwd=self.root, env={**self.env, **(env or {})},
                                capture_output=True, text=True, timeout=15)
        self.assertFalse((self.root / "command-spy").exists(), result.stderr)
        return result

    def check_help(self, args, usage, flags, mode="help"):
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
        self.assertFalse((self.root / ".agentkit").exists())
        result = self.cli(args, mode)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        if usage == "usage: ak [":
            self.assertTrue(result.stdout.startswith(usage), result.stdout)
        else:
            # every command's own help starts with its one-line purpose, then
            # its usage as before
            purpose, _, rest = result.stdout.partition("\n\n")
            self.assertTrue(purpose.strip() and "\n" not in purpose, result.stdout)
            self.assertTrue(rest.startswith(usage), result.stdout)
        self.assertRegex(result.stdout, r"(?m)^Example: ak(?: |$)")
        if flags is not None:
            # the usage block carries the flags: the purpose line and the prose
            # around it neither add nor hide one
            parts = result.stdout.split("\n\n")
            syntax = parts[1] if usage != "usage: ak [" and len(parts) > 1 else parts[0]
            self.assertEqual(set(re.findall(r"--[a-z-]+", syntax)), flags)
        self.assertEqual(sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")), before)
        return result.stdout

    def test_public_help_matrix_before_any_operational_work(self):
        for command, usage, extra, flags in MATRIX:
            for flag in ("-h", "--help"):
                for tail in ([flag], [*extra, flag], [flag, *extra]):
                    with self.subTest(command=command, tail=tail):
                        self.check_help([*command.split(), *tail], usage, flags)

    def test_module_entries_share_the_same_early_help(self):
        for command, usage, extra, flags in MATRIX:
            if not command:
                continue
            for flag in ("-h", "--help"):
                with self.subTest(command=command, flag=flag):
                    self.check_help([*command.split(), *extra, flag], usage, flags, mode="module")

    def test_all_public_commands_are_in_the_matrix(self):
        entry = runpy.run_path(str(REPO / "bin/ak"))
        public = {command for command, *_ in MATRIX if command and " " not in command}
        self.assertEqual(public, set(entry["SUBS"]))

    def test_notify_documented_variants_match_parsing(self):
        expected = [
            (["needs", "Question?"], "shaped", ["needs", "Question?", None],
             {"session": None, "dry_run": False}),
            (["needs", "Question?", "--session", "seat", "--dry-run"], "shaped",
             ["needs", "Question?", None], {"session": "seat", "dry_run": True}),
            (["done", "Summary"], "shaped", ["done", "Summary", None],
             {"session": None, "dry_run": False}),
            (["done", "--session", "seat", "Summary", "--pr", "https://example.invalid/pr/1",
              "--dry-run"], "shaped", ["done", "Summary", "https://example.invalid/pr/1"],
             {"session": "seat", "dry_run": True}),
            (["--check"], "check", [], {}),
        ]
        for args, call, parsed, kwargs in expected:
            with self.subTest(args=args):
                result = self.cli(["notify", *args], mode="notify")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout),
                                 {"call": call, "args": parsed, "kwargs": kwargs})
        # The actual notify examples printed by every help variant must also parse.
        for command in ("notify", "notify needs", "notify done"):
            text = self.cli([*command.split(), "--help"]).stdout
            example = next(line.removeprefix("Example: ") for line in text.splitlines()
                           if line.startswith("Example: "))
            result = self.cli(shlex.split(example)[1:], mode="notify")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / ".agentkit").exists())

    def test_all_documented_worker_roles_reach_only_fake_adapters(self):
        from agentkit import worker
        text = self.cli(["worker", "--help"]).stdout
        roles = re.search(r"\[--role ([^\]]+)\]", text)[1].split("|")
        self.assertEqual(set(roles), set(worker.PREAMBLES))
        task = self.root / "task.md"
        task.write_text("Offline task body")
        model = next(iter(self.cfg["models"]))
        entry = self.cfg["models"][model]
        for role in roles:
            with self.subTest(role=role):
                out = self.root / role
                result = self.cli(["worker", "--role", role, model, str(task), "--out", str(out),
                                   "--workspace", str(self.root), "--session", "resume-me"], mode="worker")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), str(out / "final.md"))
                self.assertEqual(json.loads((out / "adapter.json").read_text()),
                                 ["run", entry["model"], entry["effort"], str(self.root),
                                  str(out / "prompt.md"), str(out), "resume-me"])
                self.assertEqual((out / "prompt.md").read_text(),
                                 worker.PREAMBLES[role].format(workspace=self.root) + "\n\nOffline task body")
        result = self.cli(["worker", model, str(task)], mode="worker", env={"HELP_WORKER_EXIT": "7"})
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("exited 7", result.stderr)
        for args in (["worker"], ["worker", "--bogus"]):
            error = self.cli(args, mode="error")
            self.assertEqual(error.returncode, 2)
            self.assertEqual(re.search(r"\[--role ([^\]]+)\]", error.stderr)[1].split("|"), roles)

    def test_non_help_errors_keep_their_exit_codes(self):
        cases = [
            (["bogus"], "unknown subcommand"),
            (["preview"], "unknown subcommand 'preview'"),
            (["usage", "--bogus"], "usage: ak usage"),
            (["worker", "--out"], "--out needs a value"),
            (["worker", "MODEL", "missing", "--role", "bogus"], "--role must be one of"),
            (["worker", "MODEL", "missing"], "no such task file"),
            (["run"], "usage: ak run"),
            (["run", "--exec"], "--exec needs a value"),
            (["run", "missing.md", "--rounds", "0"], "--rounds must be a positive integer"),
            (["run", "missing.md", "--rounds", "5"], "--rounds 5 is over the budget: 3 rounds"),
            (["run", "--review-pr", "bad"], "--review-pr needs a GitHub PR URL"),
            (["run", "status", "MISSING"], "no such run"),
            (["run", "status", "--bogus"], "usage: ak run status"),
            (["run", "resume", "MISSING"], "no resumable run"),
            (["run", "resume", "MISSING", "--rounds", "0"], "usage: ak run resume"),
            (["run", "resume", "MISSING", "--rounds", "5"], "--rounds 5 is over the budget"),
            (["run", "merge", "MISSING"], "merge requires a finished PASS"),
            (["run", "clean", "MISSING"], "no such run"),
            (["run", "gc", "--bogus"], "usage: ak run gc"),
            (["orch", "--model"], "--model needs a model name"),
            (["orch", "list", "extra"], "usage: ak orch list"),
            (["orch", "why"], "usage: ak orch why"),
            (["orch", "why", "a", "b"], "usage: ak orch why"),
            (["orch", "stop"], "usage: ak orch stop"),
            (["orch", "rename"], "usage: ak orch rename"),
            (["notify"], "usage: ak notify"),
            (["notify", "needs", "Question?", "--file", "missing"], "was removed"),
            (["notify", "done", "Summary", "--pr", "bad"], "--pr needs the PR's URL"),
            (["notify", "needs", "Question?", "--session"], "--session needs a session name"),
            (["notify", "message", "--file"], "usage: ak notify"),
            (["notify", "message", "--dry-run"], "usage: ak notify"),
            (["notify", "message", "--session", "seat"], "usage: ak notify"),
            (["update", "--bogus"], "usage: ak update"),
            (["watch", "--bogus"], "usage: ak watch"),
            (["attach", "--bogus"], "usage: ak"),
            (["fetch"], "usage: ak fetch"),
            (["fetch", "--serve", "extra"], "usage: ak fetch"),
            (["browser"], "usage: ak browser"),
            (["browser", "bogus"], "unknown command"),
        ]
        cases += [(["browser", command, "extra"], "takes no arguments")
                  for command in ("status", "login", "mcp-register", "install")]
        for args, message in cases:
            with self.subTest(args=args):
                result = self.cli(args, mode="error")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(message, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)
        for webhook, code in (("", 2), ("bad-url", 1)):
            result = self.cli(["notify", "--check"], mode="error",
                              env={"AGENTKIT_DISCORD_WEBHOOK": webhook})
            self.assertEqual(result.returncode, code, result.stderr)
        for status, code in ((200, 0), (403, 1)):
            result = self.cli(["notify", "--check"], mode="check", status=status,
                              env={"AGENTKIT_DISCORD_WEBHOOK": "https://example.invalid/hook"})
            self.assertEqual(result.returncode, code, result.stderr)

    def test_fetch_literal_help_filename_after_separator(self):
        path = self.root / "--help"
        path.write_text("a local file")
        result = self.cli(["fetch", "--", "--help"], mode="error")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(path))


if __name__ == "__main__":
    if sys.argv[1:] == ["--probe"]:
        sys.exit(probe())
    unittest.main()
