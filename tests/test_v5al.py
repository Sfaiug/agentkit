"""v5al: a harness is a plugin -- an adapter pair and a config.toml line, never code.

Offline throughout.  The fifth harness is tests/fixtures/adapters/echo.sh and echo.toml, a
fake with nothing behind it; the four real ones keep their own adapters/*.toml -- the screen,
update and usage knowledge this is about -- beside stub scripts that answer `run`, `usage` and
`interactive` without a model, and refuse `reset`/`reset-status` outright.  No real harness, no
real reset, no tmux server and no network is reached from here.
"""

import ast
from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, harness, menu, notify, orch, run, terminal, update, usage, watch
from agentkit.harness import codex as codex_plugin

FIXTURES = REPO / "tests/fixtures/adapters"
REAL = ("claude", "codex", "muse", "opencode")  # the names no module outside the package may compare

# A stub for each real harness: the model calls replaced, the screen knowledge left alone.
# `reset`/`reset-status` exit without JSON, so a test that asked for one would see nothing --
# spending a real usage-limit reset from a test is not something a fixture can do by accident.
STUB = '''#!/bin/sh
case "${1:-}" in
  usage) printf '{"meters":[{"name":"weekly","used":50,"resets_at":%s,"window_secs":604800}],"error":null}\\n' "$(( $(date +%s) + 3600 ))" ;;
  interactive) [ "$#" -le 3 ] || exit 3; printf 'sleep 600\\n' ;;
  run) mkdir -p -- "$6"
       printf 'VERDICT: PASS\\n\\n## Findings\\n- none\\n' >"$6/final.md"
       printf 'sid-%s\\n' "$2" >"$6/session_id"
       printf 'stub\\n' >"$6/stderr.log" ;;
  hooks) printf 'nothing to install\\n' ;;
  *) printf 'the v5al fixture never speaks %s\\n' "${1:-}" >&2; exit 2 ;;
esac
'''

PANES = {
    "idle": "reading the prompt\n❯\n? for shortcuts\n",
    "working": "thinking about it\nesc to interrupt\n? for shortcuts\n",
    "asking": "Overwrite it?\n1. yes\n2. no\npress enter to choose\n",
}


class Boundary(unittest.TestCase):
    """The boundary itself: the core may not name a harness, and no table may hold them."""

    def modules(self):
        """Every module under agentkit/, the harness package excepted: it is the exception."""
        return sorted(path for path in (REPO / "agentkit").glob("*.py"))

    def test_v5al_no_core_module_compares_a_harness_name(self):
        found = set()
        for path in self.modules():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                for side in [node.left, *node.comparators]:
                    parts = side.elts if isinstance(side, (ast.Tuple, ast.List, ast.Set)) else [side]
                    for part in parts:
                        if isinstance(part, ast.Constant) and part.value in REAL:
                            found.add((path.name, part.value))
        # agentkit/worker.py keeps one: the shell-timeout cap a Claude turn is given, which is
        # outside this change's file list.  It is pinned here so that nothing new joins it.
        self.assertEqual(found, {("worker.py", "claude")})

    def test_v5al_no_harness_table_is_left_in_the_core(self):
        self.assertFalse(hasattr(update, "HARNESSES"))
        self.assertNotIn("HARNESSES = (", (REPO / "agentkit/update.py").read_text())
        self.assertFalse(hasattr(usage, "RESET_HARNESS"))
        # and the package that may name them is the only one that imports a harness module
        for path in self.modules():
            self.assertNotIn("from .harness import codex", path.read_text(), path.name)


class Fixture(unittest.TestCase):
    """A sandboxed home, five adapters and a config that names all five harnesses."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".v5al-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.adapters = self.root / "adapters"
        self.adapters.mkdir(parents=True)
        for name in REAL:
            shutil.copy2(REPO / "adapters" / f"{name}.toml", self.adapters / f"{name}.toml")
            stub = self.adapters / f"{name}.sh"
            stub.write_text(STUB)
            stub.chmod(0o755)
        for name in ("echo.sh", "echo.toml"):
            shutil.copy2(FIXTURES / name, self.adapters / name)
        (self.adapters / "echo.sh").chmod(0o755)
        sockets = self.root / "sockets"
        sockets.mkdir(mode=0o700)
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "NO_COLOR": "1", "AGENTKIT_SESSION": "",
            "AGENTKIT_RUN_DIR": "", "AGENTKIT_DISCORD_WEBHOOK": "off",
            "AGENTKIT_TMUX_SOCKET": "agentkit-test", "TMUX_TMPDIR": str(sockets), "TMUX": "",
            "PYTHONDONTWRITEBYTECODE": "1", config.ADAPTER_DIR_ENV: str(self.adapters)}))
        self.cfg = self.models()
        self.stack.enter_context(patch.object(config, "load", lambda: self.cfg))
        self.stack.enter_context(patch.object(orch, "sessions", return_value=[]))
        config.ensure_dirs()

    def models(self):
        """This checkout's default config with one line added: a model on the fifth harness."""
        cfg = tomllib.loads((REPO / "config.default.toml").read_text())
        # Six real harnesses ship. This fixture stubs the four in REAL and adds echo,
        # so grok and gemini are scoped out and echo stays the harness the fixture itself adds.
        cfg["models"].pop("grok", None)
        cfg["providers"].pop("xai", None)
        cfg["models"].pop("gemini", None)
        cfg["providers"].pop("google", None)
        cfg["models"]["echo"] = {"harness": "echo", "model": "echo-1", "effort": "low",
                                 "provider": "test"}
        cfg["providers"]["test"] = {"mode": "subscription"}
        return cfg

    def seat(self, name, model, **extra):
        """A record for a seat tmux no longer holds, as `ak orch` would have written it."""
        config.save_session(self.cfg, name, model, ["astra"],
                            {"cwd": str(self.root), "repo": None, "created": 9000, **extra})
        return config.session_records()[name]


class Plugins(Fixture):
    def test_v5al_echo_answers_every_hook_with_the_default(self):
        plugin = harness.load("echo")
        self.assertIsNone(plugin.module)            # no agentkit/harness/echo.py at all
        self.assertEqual(plugin.conversation({"conversation": "c"}, self.root), "c")
        self.assertIsNone(plugin.conversation({}, self.root))
        self.assertTrue(plugin.resumable({"conversation": "c", "id_source": harness.LAUNCHER},
                                         self.root, "c"))
        self.assertFalse(plugin.resumable({"conversation": "c", "id_source": "discovered"},
                                          self.root, "c"))
        self.assertIsNone(plugin.restart_word({}))
        self.assertEqual(plugin.reconcile({"conversation": "c", "id_source": "discovered"}),
                         {"conversation": None, "resumable": False})
        self.assertEqual(plugin.reconcile({"conversation": "c",
                                           "id_source": harness.LAUNCHER}), {})
        self.assertTrue(plugin.opened(self.root, "c"))
        self.assertEqual(plugin.identity("1.0.0", ["echo", "1.0.0"]), "1.0.0")
        self.assertFalse(plugin.usage_policy({"model": "echo-1"}, "low"))
        self.assertFalse(plugin.always_offered)
        self.assertEqual(plugin.fresh_words, harness.FRESH_WORDS)
        self.assertFalse(plugin.hooks_from_config)
        self.assertEqual(plugin.usage, harness.USAGE)
        # the default `launched` writes the launcher's own id down and asks for no environment
        self.seat("echo-seat", "echo")
        self.assertEqual(plugin.launched("echo-seat", self.root, "issued"), {})
        record = config.session_records()["echo-seat"]
        self.assertEqual((record["conversation"], record["id_source"], record["resumable"]),
                         ("issued", harness.LAUNCHER, True))
        # a harness nobody has written a module or a manifest for still answers
        missing = harness.load("nobody")
        self.assertIsNone(missing.module)
        self.assertEqual(missing.update, harness.UPDATE)
        self.assertTrue(missing.opened(self.root, "c"))

    def test_v5al_codex_finds_the_conversation_its_receipt_proves(self):
        self.seat("codex-seat", "astra")
        path = self.root / ".codex/sessions/2026/09/10/rollout-new.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"type": "session_meta", "payload": {
            "cwd": str(self.root), "timestamp": "1970-01-01T00:03:00Z", "id": "seat-thread"}}) + "\n")
        receipt = codex_plugin.prepare("codex-seat", self.root, None)
        codex_plugin.capture(receipt, {"hook_event_name": "SessionStart", "source": "startup",
                                       "session_id": "seat-thread", "transcript_path": str(path),
                                       "cwd": str(self.root)})
        record = config.session_records()["codex-seat"]
        plugin = harness.load("codex")
        self.assertEqual(plugin.conversation(record, self.root), "seat-thread")
        self.assertEqual(orch.seat_conversation(record), "seat-thread")
        self.assertTrue(plugin.resumable(record, self.root, "seat-thread"))
        self.assertEqual(plugin.reconcile(record),
                         {"resumable": True, "conversation": "seat-thread",
                          "id_source": codex_plugin.SOURCE})
        self.assertTrue(plugin.always_offered)
        self.assertEqual(plugin.restart_word(record), codex_plugin.FRESH)
        self.assertEqual(plugin.fresh_words, "Codex ownership unverified; it starts fresh")
        # a launch nobody reported owns nothing, and the record alone is never evidence
        codex_plugin.forget(record)
        self.assertIsNone(plugin.conversation(record, self.root))
        self.assertEqual(plugin.reconcile(record), {"resumable": False})
        self.assertFalse(orch.resumable(record))
        # Claude's own store, and the transcript it writes at the first message
        claude = harness.load("claude")
        slug = str(self.root).replace("/", "-").replace(".", "-").replace("_", "-")
        self.assertFalse(claude.opened(self.root, "c"))
        transcript = self.root / ".claude/projects" / slug / "c.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text("{}\n")
        self.assertTrue(claude.opened(self.root, "c"))
        self.assertTrue(claude.hooks_from_config)


class UpdatePlan(Fixture):
    def plan(self):
        out = io.StringIO()
        with patch.object(update, "version", lambda h: "1.0.0"), redirect_stdout(out):
            self.assertEqual(update.main(["--dry-run"]), 0)
        return out.getvalue().splitlines()

    def test_v5al_the_update_plan_comes_from_each_manifest(self):
        lines = self.plan()
        self.assertEqual(lines[:5], [
            "claude 1.0.0 (versioned reinstall available): claude install latest",
            "codex 1.0.0 (versioned reinstall available): npm i -g @openai/codex@latest",
            "muse 1.0.0 (frozen installed release, not a reproducible versioned install; "
            "cannot be reverted by its channel installer; requires a complete local snapshot "
            "for rollback, checked before upgrading): muse",
            "opencode 1.0.0 (versioned reinstall available): opencode upgrade",
            "echo 1.0.0 (cannot be reverted: it is a fixture and has no installer at all): "
            "echo already-current",
        ])
        self.assertIn("dry run, nothing changed", lines[5])
        plan = {h["name"]: h for h in update.harnesses(self.cfg)}
        self.assertEqual(list(plan), ["claude", "codex", "muse", "opencode", "echo"])
        self.assertEqual(plan["echo"]["revert"], None)
        self.assertEqual(plan["echo"]["snapshot_dir"], "")
        self.assertEqual(plan["muse"]["snapshot_dir"], "launcher")
        self.assertEqual(plan["muse"]["env"], {"MUSE_LAUNCHER_INSTALL": "1"})
        self.assertEqual(plan["claude"]["revert"], ["claude", "install", update.VERSION_KEY])
        self.assertEqual(plan["opencode"]["revert"], ["opencode", "upgrade", update.VERSION_KEY])
        self.assertEqual(plan["codex"]["version"], ["codex", "--version"])

    def test_v5al_a_versioned_revert_is_the_manifests_words_with_the_version_in_them(self):
        commands = []
        before = {"claude": "1.0.0", "codex": "1.0.0", "muse": "", "opencode": "1.0.0",
                  "echo": "1.0.0"}
        after = {"claude": "2.0.0", "codex": "2.0.0", "muse": "", "opencode": "2.0.0",
                 "echo": "2.0.0"}
        with patch.object(update, "version", lambda h: before[h["name"]]), \
                patch.object(update, "step", lambda cmd, *a: commands.append(cmd) or True):
            landed = update.revert(update.harnesses(self.cfg), before, after, None, lambda m: None)
        self.assertEqual(commands, [["claude", "install", "1.0.0"],
                                    ["npm", "i", "-g", "@openai/codex@1.0.0"],
                                    ["opencode", "upgrade", "1.0.0"]])
        self.assertEqual(landed["claude"], ("reverted", "back on 1.0.0"))
        self.assertEqual(landed["opencode"], ("reverted", "back on 1.0.0"))
        self.assertEqual(landed["muse"], ("unchanged", "not installed here"))
        # nothing puts the fifth harness back, and it says so in its own words
        self.assertEqual(landed["echo"][0], "cannot revert")
        self.assertIn("it is a fixture and has no installer at all", landed["echo"][1])

    def test_v5al_a_harness_that_says_nothing_about_updates_is_left_alone(self):
        (self.adapters / "echo.toml").write_text("version = 1\n")
        self.assertEqual([h["name"] for h in update.harnesses(self.cfg)], list(REAL))
        self.assertNotIn("echo", "\n".join(self.plan()[:4]))


class UsageCalls(Fixture):
    def setUp(self):
        super().setUp()
        self.asked = []
        self.captured = []

        def adapter_json(name, verb, timeout):
            self.asked.append((name, verb))
            return {"available": 2} if verb == "reset-status" else {}

        def capture(argv):
            self.captured.append(argv)
            return usage.subprocess.CompletedProcess(argv, 0, self.meters, "")

        self.meters = json.dumps({"meters": [{"name": "weekly", "used": 50,
                                             "resets_at": 20000, "window_secs": 604800}],
                                  "error": None})
        self.stack.enter_context(patch.object(usage, "_adapter_json", adapter_json))
        self.stack.enter_context(patch.object(usage.usage_probe, "capture", capture))

    def test_v5al_only_a_manifest_that_asks_for_them_gets_a_capture_or_a_reset(self):
        for provider, harness_name in (("anthropic", "claude"), ("openai", "codex"),
                                       ("meta", "muse"), ("test", "echo")):
            with self.subTest(provider=provider):
                out = usage._probe(self.cfg, provider, 10000)
                self.assertEqual(out["harness"], harness_name)
                self.assertEqual(out["meters"][0]["used"], 50 if harness_name != "echo" else 42)
        # `[usage] capture` is Muse's alone, and `[usage] reset` Codex's: one captured probe
        # for the four providers, and one `reset-status`, asked of the one adapter that has any
        self.assertEqual([argv[1] for argv in self.captured], ["usage"])
        self.assertEqual(self.asked, [("codex", "reset-status")])
        self.assertEqual(usage._probe(self.cfg, "openai", 10000)["resets"], 2.0)
        self.assertEqual(usage._probe(self.cfg, "test", 10000)["resets"], 0.0)
        self.assertEqual(self.asked, [("codex", "reset-status")] * 2)
        # ... and a provider whose adapter cannot spend one is never asked to
        prov = {"harness": "echo", "meters": [{"name": "weekly", "used": 99,
                                               "window_secs": 604800}]}
        self.assertEqual(usage._reset_policy(self.cfg, "test", prov, 10000, True), (prov, False))
        self.assertEqual(self.asked, [("codex", "reset-status")] * 2)

    def test_v5al_a_stripped_timestamp_is_dated_by_its_own_plugin(self):
        cached = config.STATE / "usage-meta.json"
        cached.write_text(self.meters)
        out = usage._probe(self.cfg, "meta", 10000)
        self.assertEqual(out["fetched_at"], cached.stat().st_mtime)
        cached.write_text(json.dumps({"meters": [], "error": None}))
        self.assertIsNone(usage._probe(self.cfg, "meta", 10000)["fetched_at"])
        # an adapter that dates its own answer keeps it: nothing here strips a timestamp
        self.assertNotIn("fetched_at", usage._probe(self.cfg, "test", 10000))


class Seats(Fixture):
    def test_v5al_a_gone_seat_is_offered_only_where_its_harness_says_so(self):
        self.seat("echo-owned", "echo", conversation="c", id_source=harness.LAUNCHER,
                  resumable=True)
        self.seat("echo-guessed", "echo", conversation="guessed", id_source="discovered")
        self.seat("codex-unbound", "astra")
        self.seat("claude-fresh", "fable")
        rows = {row["name"]: row for row in orch.listing()}
        self.assertEqual(sorted(rows), ["codex-unbound", "echo-owned"])
        self.assertTrue(rows["echo-owned"]["resumable"])
        self.assertNotIn("restart", rows["echo-owned"])
        self.assertFalse(rows["codex-unbound"]["resumable"])
        self.assertEqual(rows["codex-unbound"]["restart"], codex_plugin.FRESH)
        # nobody is in it, whatever the harness says it will do with its conversation
        self.assertEqual(orch.state_word(rows["codex-unbound"], self.cfg), "needs you")
        # the guessed id is dropped from the record rather than offered back
        self.assertFalse(config.session_records()["echo-guessed"].get("conversation"))
        # and the menu's numbering agrees with the rows the notifications name
        self.assertEqual(notify.session_number("codex-unbound"), 1)
        self.assertEqual(notify.session_number("echo-owned"), 2)
        self.assertIsNone(notify.session_number("claude-fresh"))

    def test_v5al_orch_dry_run_plans_a_seat_on_the_fifth_harness(self):
        out = io.StringIO()
        with patch.object(terminal, "ask", return_value=""), redirect_stdout(out), \
                patch.object(orch, "attach", side_effect=AssertionError("no seat is started")):
            self.assertEqual(orch.main(["echo-seat", "--model", "echo", "--dry-run"]), 0)
        # one spacer, the blank line the worker question prints before its prompt,
        # and then the plan. A second blank would be a new question, not this one.
        printed = out.getvalue().splitlines()
        self.assertEqual(printed[0], "")
        self.assertEqual(printed[1], "orch: echo (--model)")
        self.assertIn("session echo-seat in ", printed[2])
        self.assertEqual(printed[-1], os.environ.get("SHELL") or "/bin/sh")
        record = config.session_records()["echo-seat"]
        self.assertEqual(record["orchestrator"], "echo")
        # its TUI cannot be told an id (echo.sh exits 3), so the seat is given none
        self.assertNotIn("conversation", record)

    def test_v5al_the_menu_draws_the_seat_from_its_own_screen_rules(self):
        self.seat("echo-seat", "echo")
        seat = {"name": "echo-seat", "path": str(self.root), "created": 9000, "attached": False,
                "exited": False, "legacy": False, "resumable": False, "repo": None}
        self.stack.enter_context(patch.object(watch, "announce", lambda *a: None))
        self.stack.enter_context(patch.object(orch, "tmux_out", return_value=(1, "")))
        for kind, word, rule in (("idle", "needs you", "prompt.composer"),
                                 ("working", "working", "working.interrupt"),
                                 ("asking", "needs you", "asking.chooser")):
            with self.subTest(kind=kind), patch.object(watch, "pane_text",
                                                       return_value=PANES[kind]):
                found = watch.live_state(seat, cfg=self.cfg)
                self.assertEqual((found["state"], found["rule"], found["authority"]),
                                 (kind if kind != "idle" else "at_prompt", rule, "screen"))
                self.assertEqual(menu.row(self.cfg, 1, seat)[:4],
                                 ["1", "echo-seat", "echo", word])
        # ... and `ak orch why` names the same rule, out of the same manifest
        with patch.object(watch, "pane_text", return_value=PANES["asking"]):
            why = "\n".join(orch.explain(seat, self.cfg))
        self.assertIn("asking.chooser", why)


class ScratchRun(Fixture):
    """One whole loop through the fifth harness: it executes, another provider reviews."""

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(run, "gh", side_effect=AssertionError("GitHub")))
        self.stack.enter_context(patch.object(run.notify, "shaped",
                                             side_effect=AssertionError("notification")))
        self.stack.enter_context(patch.object(run.time, "sleep"))
        self.stack.enter_context(patch.object(run, "host_readings", return_value={
            "free_mb": 4096, "mem_total_mb": 16384, "load": 1, "cpus": 8,
            "unit_memory_current_mb": 100, "unit_memory_high_mb": 1000}))
        self.providers = {name: {"resets": 0, "meters": [
            {"name": "weekly_all", "used": 0, "pace": None, "exhausted": False}]}
            for name in self.cfg["providers"]}
        self.stack.enter_context(patch.object(usage, "collect", lambda cfg: self.providers))
        self.task = self.root / "task.md"
        self.task.write_text("---\nrepo: none\nrounds: 1\n---\n# Echo harness run\n\n"
                             "## Goal\nNothing: the echo adapter answers with the last line.\n\n"
                             "## Done when\n```bash\ntrue\n```\n")

    def test_v5al_a_scratch_run_through_the_echo_adapter_passes(self):
        before = set(run.run_dirs())
        with redirect_stdout(io.StringIO()) as out:
            code = run.main([str(self.task), "--exec", "echo", "--review", "astra"])
        directory = (set(run.run_dirs()) - before).pop()
        state = run.read_state(directory)
        self.assertEqual((code, state["state"], state["verdict"]), (0, "pass", "PASS"))
        self.assertEqual((state["executor"], state["reviewer"]), ("echo", "astra"))
        self.assertTrue(run.review_pass(state, self.cfg))
        self.assertEqual(state["review"]["executor_provider"], "test")
        self.assertTrue(state["scratch"])
        # the executor's own words came back through the adapter, and nothing else did
        asked = (directory / "round-1/executor/prompt.md").read_text()
        self.assertEqual((directory / "round-1/executor/final.md").read_text().strip(),
                         asked.strip().splitlines()[-1].strip())
        self.assertIn("PASS", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
