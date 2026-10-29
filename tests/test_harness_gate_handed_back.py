"""A harness's second red gate goes to a seat once, until its gates pass.

Offline: upgrades and gate commands are stand-ins, HOME is temporary, and the real
after-merge delivery path has only a fake receiving seat and typer.
"""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, update, watch


class HarnessGateHandedBack(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".ak-test-harness-gate-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.dict(os.environ, {"HOME": str(self.root)}))
        stack.enter_context(patch.object(config, "HOME", self.root / ".agentkit"))
        for name in ("RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            stack.enter_context(patch.object(config, name, config.HOME / name.lower()))
        config.ensure_dirs()
        checkout = self.root / "agentkit"
        (checkout / "tests").mkdir(parents=True)
        for gate in ("live", "e2e-fresh"):
            (checkout / "tests" / f"{gate}.sh").touch()
        stack.enter_context(patch.object(config, "REPO", checkout))
        self.plan = [{"name": name, "version": [name, "--version"],
                      "upgrade": [name, "upgrade"], "revert": [name, "install", "{version}"],
                      "env": {}, "latest": [name, "latest"]} for name in ("acme", "beta")]
        self.installed = {h["name"]: "1.0.0" for h in self.plan}
        self.failing = "live"
        self.ready, self.seen = True, []
        stack.enter_context(patch.object(update, "harnesses", return_value=self.plan))
        stack.enter_context(patch.object(update, "version",
                                        side_effect=lambda h: self.installed[h["name"]]))
        stack.enter_context(patch.object(update, "latest", return_value=""))
        stack.enter_context(patch.object(config, "harness_binary", return_value="fixture"))
        stack.enter_context(patch.object(update, "step", side_effect=self.step))
        stack.enter_context(patch.object(update, "_git", return_value=(
            0, "https://github.com/acme/agentkit.git")))
        self.fallback = stack.enter_context(patch.object(watch, "after_merge_fallback",
                                                        return_value={"name": "atoll"}))
        stack.enter_context(patch.object(watch, "type_at_prompt", side_effect=self.type_line))

    def step(self, cmd, fh, *_args, **_kw):
        if cmd[0] in self.installed:
            if cmd[1] == "upgrade":
                self.installed[cmd[0]] = "2.0.0"
            else:
                self.installed[cmd[0]] = cmd[2]
            return True
        gate = Path(cmd[1]).stem
        failed = gate == self.failing
        if failed:
            fh.write(f"FAIL  4 {gate}: acme check failed\n      first diagnostic\n"
                     f"FAIL  6 {gate}: beta check failed\n")
        fh.write("".join(f"PASS  {n} fixture check\n" for n in range(20)))
        fh.write(f"acceptance: {'FAILED' if failed else 'PASSED'}\n[exit {int(failed)}]\n")
        fh.flush()
        return not failed

    def type_line(self, seat, line, log, typed=None, receipt=lambda mark: None, **_kw):
        self.seen.append((seat, line, typed))
        receipt({"seat": seat["name"], "line": line})
        return self.ready

    def attempt(self, name="acme", failing="live"):
        self.failing = failing
        self.assertEqual(update.background(name), int(bool(failing)))
        if failing:
            self.assertEqual(self.installed[name], "1.0.0")

    def tick(self):
        said = []
        update.keep_current(said.append, now=1_000_000)
        return said

    def test_second_red_is_handed_back_once_with_failures_and_log_path(self):
        for gate in ("live", "e2e-fresh"):
            with self.subTest(gate=gate):
                self.attempt(failing=gate)
                said = self.tick()
                self.assertEqual(said[0], "WARN the background upgrade of acme failed:")
                self.assertEqual(self.seen, [])
                self.attempt(failing=gate)
                self.tick()
                self.assertEqual(len(self.seen), 1)
                seat, line, typed = self.seen[0]
                self.assertEqual(seat["name"], "atoll")
                self.assertIsNone(typed)
                self.fallback.assert_called_with("github.com/acme/agentkit")
                self.assertIn("acme harness upgrade", line)
                for check in (4, 6):
                    self.assertIn(f"FAIL  {check} {gate}:", line)
                log_path = next(path for path in config.TMP.glob("update-*.log")
                                if config.tilde(path) in line)
                self.assertIn(f"FAIL  4 {gate}:", log_path.read_text())
                self.attempt(failing=gate)
                self.tick()
                self.tick()
                self.assertEqual(len(self.seen), 1)
                self.attempt(failing="")
                self.tick()
                self.seen.clear()
                self.installed["acme"] = "1.0.0"

    def test_a_pass_between_failures_starts_the_count_again(self):
        self.attempt()
        self.tick()
        self.attempt(failing="")
        self.tick()
        self.installed["acme"] = "1.0.0"
        self.attempt()
        self.tick()
        self.assertEqual(self.seen, [])
        self.attempt()
        self.tick()
        self.assertEqual(len(self.seen), 1)

    def test_harnesses_count_separately_and_only_the_passing_one_resets(self):
        self.attempt()
        self.tick()
        self.attempt("beta")
        self.tick()
        self.assertEqual(self.seen, [])
        self.attempt()
        self.tick()
        self.assertEqual(len(self.seen), 1)
        self.attempt(failing="")
        self.tick()
        self.attempt("beta")
        self.tick()
        self.assertEqual(len(self.seen), 2)
        self.assertIn("beta harness upgrade", self.seen[-1][1])

    def test_a_busy_seat_retries_the_saved_line_and_composer_receipt(self):
        self.ready = False
        self.attempt()
        self.tick()
        self.attempt()
        self.tick()
        self.assertEqual(len(self.seen), 1)
        self.attempt()  # another red must keep the line already in the composer
        self.ready = True
        self.tick()
        self.assertEqual(len(self.seen), 2)
        self.assertEqual(self.seen[0][1], self.seen[1][1])
        self.assertEqual(self.seen[1][2], {"seat": "atoll", "line": self.seen[0][1]})
        self.tick()
        self.assertEqual(len(self.seen), 2)


if __name__ == "__main__":
    unittest.main()
