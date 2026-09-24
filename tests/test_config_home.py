"""The config lives in ~/.agentkit/config.toml, and opening the menu never pulls the repo.

Entirely offline, and nothing here touches the account's own ~/.agentkit: every case that
reads a config patches config.HOME at a throwaway directory first.  What is pinned is the
one file and the one fallback -- the home file when it is there, the checkout's shipped
config.default.toml when it is not, and the same home file max_runs() has always read, so an
install from before the models moved into it is not a broken config.  The last three cases
are about the way into a seat: install.sh copies once and overwrites nothing, `orch.maintenance`
-- the whole of that way -- still reaps a dead loop but starts no process at all, and the menu's
own loop reads no version, so pressing a key for the menu can move no code anywhere.
"""

from contextlib import ExitStack
import inspect
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, orch, run, watch

SANDBOXED = ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE")
COLLECTOR = [sys.executable, "-m", "agentkit.retention", "collect"]
DEAD = 99999999   # a pid no loop of ours holds, so the run reads as one whose process is gone

DEFAULT = REPO / "config.default.toml"

OWN = """max_runs = 7

[tiers]
A = ["only"]
B = ["only"]

[models.only]
harness = "claude"
model = "claude-opus-5"
effort = "xhigh"
provider = "anthropic"

[providers.anthropic]
mode = "subscription"
"""


class ConfigHome(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".config-home-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.path = self.home / "config.toml"
        patcher = patch.object(config, "HOME", self.home)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_load_reads_the_home_file(self):
        self.path.write_text(OWN)
        cfg = config.load()
        self.assertEqual(cfg["defaults"], {"orchestrator": "only", "workers": ["only"]})
        self.assertEqual(sorted(cfg["models"]), ["only"])
        self.assertEqual(config.model(cfg, "only")["model"], "claude-opus-5")
        # the same file, read by the same call it has always been read by
        self.assertEqual(config.max_runs(), 7)

    def test_load_falls_back_to_the_shipped_default_when_the_home_file_is_missing(self):
        self.assertFalse(self.path.exists())
        self.assertEqual(config.load(), tomllib.loads(DEFAULT.read_text()))
        # silently: a checkout nobody has installed from has nothing to fix
        self.assertEqual(config.max_runs(), config.RUN_DEFAULTS["max_runs"])

    def test_a_home_file_with_only_max_runs_still_loads_the_models(self):
        """What an install from before the config held the models leaves behind."""
        self.path.write_text("max_runs = 5\n")
        self.assertEqual(config.max_runs(), 5)
        self.assertEqual(config.load(), tomllib.loads(DEFAULT.read_text()))

    def test_a_home_file_that_configures_models_badly_is_still_an_error(self):
        """The fallback is for a file that configures no models, never for a broken one."""
        self.path.write_text('max_runs = 5\n[models.only]\nharness = "claude"\n')
        with self.assertRaises(config.Error) as raised:
            config.load()
        self.assertIn(str(self.path), str(raised.exception))
        self.assertIn("[providers]", str(raised.exception))

    def head(self):
        """This checkout's commit, read outside every patch: the before and the after."""
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                              encoding="utf-8").stdout

    def sandbox(self):
        """Every agentkit path under the throwaway home, so no real run is ever reaped."""
        stack = ExitStack()
        for name in SANDBOXED:
            stack.enter_context(patch.object(config, name, self.home / name.lower()))
        # tmux is the seats\' own business and no part of this: sessions() would ask a server
        stack.enter_context(patch.object(orch, "sessions", return_value=[]))
        return stack

    def dead_loop(self):
        """A run whose loop process is gone, for maintenance to find and mark interrupted."""
        directory = config.RUNS / "20260920-0000-config-home"
        directory.mkdir(parents=True)
        run.save_state(directory, {"run_id": directory.name, "title": "A loop that died",
                                   "state": "running", "verdict": None, "merged": False,
                                   "reported": False, "executor": "opus", "reviewer": "astra",
                                   "pid": DEAD, "started_at": 0, "finished_at": None})
        return directory

    def test_the_shipped_default_parses_and_names_every_model_it_offers_and_defaults_to(self):
        cfg = tomllib.loads(DEFAULT.read_text())
        self.assertIsInstance(cfg.get("max_runs"), int)
        # every model in the file is offered both ways, so every one of them has to be whole
        for names in (list(cfg["models"]), [cfg["defaults"]["orchestrator"]],
                      cfg["defaults"]["workers"]):
            self.assertTrue(names)
            for name in names:
                entry = config.model(cfg, name)
                for field in ("harness", "model", "effort", "provider"):
                    self.assertTrue(entry[field], (name, field))
                self.assertIn(entry["provider"], cfg["providers"])

    def test_install_copies_the_default_once_and_never_overwrites_it(self):
        text = (REPO / "install.sh").read_text()
        self.assertIn('if [ ! -e "$AK/config.toml" ]; then', text)
        self.assertIn('cp -- "$REPO/config.default.toml" "$AK/config.toml"', text)
        # the guard is the only place that names the path at all: nothing outside it writes
        guard = 'if [ ! -e "$AK/config.toml" ]; then'
        block = text.split(guard, 1)[1].split("\nfi\n", 1)[0]
        self.assertEqual(text.count("$AK/config.toml"), 1 + block.count("$AK/config.toml"))
        self.assertEqual(text.count("config.default.toml"), block.count("config.default.toml"))

    def test_maintenance_reaps_a_dead_loop_and_starts_no_process_at_all(self):
        """`orch.maintenance` is the whole way into a seat: every command it makes is read."""
        self.assertFalse(hasattr(orch, "refresh"))
        self.assertFalse(hasattr(orch, "PULL_TIMEOUT"))
        head = self.head()
        commands = []

        def record(argv, *args, **kwargs):
            commands.append([str(part) for part in argv])
            return subprocess.CompletedProcess(argv, 0, "", "")

        with self.sandbox():
            directory = self.dead_loop()
            with patch("subprocess.run", side_effect=record), \
                    patch("subprocess.Popen", side_effect=record):
                orch.maintenance(lambda message: None)
            state = run.read_state(directory)
        # the reconciliation stays: a loop whose process is gone is recoverable work, not `working`
        self.assertEqual(state["state"], "interrupted", state)
        self.assertTrue(run.needs_recovery(state), state)
        # and nothing at all is started -- no git, and no collector that could reach one
        self.assertEqual(commands, [])
        self.assertNotIn(COLLECTOR, commands)
        self.assertEqual(self.head(), head)   # so the checkout cannot have moved

    def test_the_menu_loop_reads_no_version_and_schedules_no_collection(self):
        for source in (inspect.getsource(menu.loop), inspect.getsource(orch.maintenance)):
            self.assertNotIn("installed(", source)
            self.assertNotIn("pull", source)
            self.assertNotIn("schedule_gc(", source)
        # collection did not go away with it: the watch tick is where it is scheduled now
        self.assertIn("schedule_gc", inspect.getsource(watch.main))
        for module in (orch, menu):
            text = Path(module.__file__).read_text()
            self.assertNotIn("pull", text, module.__name__)
            self.assertNotIn("orch.refresh", text, module.__name__)
        # menu.installed() is read in exactly one place: the `i` screen, the one
        # screen allowed to ask git what build this is
        self.assertEqual([path.name for path in (REPO / "agentkit").rglob("*.py")
                          if "installed(" in path.read_text()], ["menu.py"])
        self.assertEqual(Path(menu.__file__).read_text().count("installed("), 2)
        self.assertIn("installed()", inspect.getsource(menu.show_info))


if __name__ == "__main__":
    unittest.main()
