"""A model runs at an effort per role: `exec_effort` for an executor's or a fixer's turn,
`review_effort` for a reviewer's, and `effort` for a seat and for either key it does not set.

config.role_effort is the one reader: worker.call hands its answer to the adapter's `run`, and
orch.command to its `interactive`.  A role effort is checked where `effort` is: `ak doctor`
names one the model does not take, by its key.  A load asks no harness what a model takes (the
status bar loads the config every few seconds), so it refuses neither key, as it refuses no
`effort`.

Offline: a temporary HOME, and a fake harness `acme` in a temporary adapter directory whose
script prints what it was asked and whose `[catalog]` says what its model takes.  The worker
turn stops where its sandbox would start, with the command it was handed; nothing is run.
"""

from contextlib import ExitStack, redirect_stdout
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, terminal, watch, worker

ADAPTER = """#!/bin/sh
case "$1" in
  interactive) printf 'seat %s %s\\n' "$2" "$3" ;;
  *) exit 1 ;;
esac
"""
MANIFEST = """version = 1
[worker]
state = []
[catalog]
"acme-1" = { efforts = ["low", "medium", "high", "xhigh", "max"] }
"""
CONFIG = """[defaults]
orchestrator = "acme"
workers = ["acme"]

[models.acme]
harness = "acme"
model = "acme-1"
effort = "xhigh"
{roles}provider = "acme"

[providers.acme]
mode = "subscription"
"""
ROLES = 'exec_effort = "max"\nreview_effort = "high"\n'


class Started(Exception):
    """The turn reached its sandbox: what it was handed is in `cmd`."""

    def __init__(self, cmd):
        self.cmd = cmd


def boxed(cmd, *_args, **_kw):
    raise Started(cmd)


class Acme(unittest.TestCase):
    """A throwaway HOME whose config has the one model `acme` of the fake harness."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="effort-per-role-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        adapters = self.root / "adapters"
        adapters.mkdir()
        (adapters / "acme.sh").write_text(ADAPTER)
        (adapters / "acme.sh").chmod(0o755)
        (adapters / "acme.toml").write_text(MANIFEST)
        self.home = self.root / "home"
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.home), config.ADAPTER_DIR_ENV: str(adapters), "NO_COLOR": "1",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}))
        stack.enter_context(patch.object(config, "HOME", self.home))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, self.home / name.lower()))
        stack.enter_context(patch.dict(config._MANIFESTS))
        stack.enter_context(patch.dict(config._CATALOGS))
        stack.enter_context(patch.object(terminal, "width", return_value=100))
        stack.enter_context(patch.object(terminal, "height", return_value=30))
        config.ensure_dirs()
        self.path = self.home / "config.toml"

    def write(self, roles):
        self.path.write_text(CONFIG.format(roles=roles))
        return config.load()


class EffortPerRole(Acme):
    def turn(self, cfg, role):
        """The effort the adapter's `run` is handed for a turn in that worker role."""
        workspace, out = self.root / "ws", self.root / f"out-{role}"
        workspace.mkdir(exist_ok=True)
        with patch.object(worker, "auth_ok", return_value=(True, "")), \
                patch.object(worker.box, "command", boxed), \
                self.assertRaises(Started) as started:
            worker.call(cfg, "acme", "do the thing", workspace, out, role)
        cmd = started.exception.cmd
        self.assertEqual(cmd[1:3], ["run", "acme-1"])
        return cmd[3]

    def seat(self, cfg):
        """The effort the adapter's `interactive` is handed for a seat."""
        rulebook = self.root / "rulebook.md"
        rulebook.write_text("rules\n")
        return orch.command(cfg, "acme", rulebook=rulebook)[-1]

    def test_each_role_runs_at_its_own_key_and_at_effort_without_it(self):
        cfg = self.write(ROLES)
        self.assertEqual({role: config.role_effort(cfg["models"]["acme"], role)
                          for role in ("orchestrator", "executor", "reviewer")},
                         {"orchestrator": "xhigh", "executor": "max", "reviewer": "high"})
        self.assertEqual([self.turn(cfg, role) for role in ("executor", "fixer", "reviewer")],
                         ["max", "max", "high"])
        self.assertEqual(self.seat(cfg), "xhigh")
        cfg = self.write("")
        self.assertEqual([self.turn(cfg, role) for role in ("executor", "fixer", "reviewer")],
                         ["xhigh", "xhigh", "xhigh"])
        self.assertEqual(self.seat(cfg), "xhigh")
        # saved, the two keys follow the effort they fall back on
        cfg = self.write(ROLES)
        block = config.dump(cfg).split("[models.acme]\n")[1].split("\n\n")[0]
        self.assertEqual([line.split(" = ")[0] for line in block.splitlines()],
                         ["harness", "model", "effort", "exec_effort", "review_effort", "provider"])

    def test_doctor_names_a_role_effort_the_model_does_not_take_by_its_key(self):
        text = CONFIG.format(roles='exec_effort = "ultra"\nreview_effort = "high"\n')
        self.path.write_text(text)

        def doctor():
            with patch.object(orch, "slice_line", return_value="slice test"), \
                    patch.object(watch, "tick_health", return_value="lock free"), \
                    redirect_stdout(io.StringIO()) as out:
                self.assertEqual(watch.doctor([]), 0)
            return out.getvalue().splitlines()[3:-1]   # past slice, tick, this machine; not rented
        self.assertEqual(doctor(), ["exec_effort  acme: acme-1 takes low medium high xhigh max, "
                                    "not ultra"])
        self.assertEqual(self.path.read_text(), text, "named, never changed")
        self.write(ROLES)
        self.assertEqual(doctor(), ["effort  every model takes the effort it is set to"])


if __name__ == "__main__":
    unittest.main()
