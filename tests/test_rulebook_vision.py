"""The checkout's vision opens each new rulebook, once: a seat whose project's AGENTS.md carries it reads
it there; launched seats keep their copy."""

from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config
from tools import rulebook

VISION = "## What ak is for\n\nBuild acme with fewer steps.\n\n### Quality\n\nCheck the result.\n"
LOCAL = "# This host\n\nThe printer is upstairs.\n"


class RulebookVision(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        root = Path(stack.enter_context(tempfile.TemporaryDirectory(
            prefix=".ak-test-rulebook-vision-", dir=REPO)))
        self.repo = root / "checkout"
        self.repo.mkdir()
        self.home = root / "home"
        (self.home / ".agentkit").mkdir(parents=True)
        self.agents = self.repo / "AGENTS.md"
        self.local = self.home / ".agentkit/rules.md"
        self.body = "# You are the orchestrator\n\nBuild acme.\n\n"
        (self.repo / "orchestrator.md").write_text(self.body)
        stack.enter_context(patch.object(config, "REPO", self.repo))
        stack.enter_context(patch.object(config, "HOME", self.home / ".agentkit"))
        stack.enter_context(patch.object(config, "STATE", self.home / ".agentkit/state"))
        stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.home), config.RULEBOOK_DIR_ENV: ""}))

    def test_only_the_vision_precedes_orchestrator_and_host_rules(self):
        self.agents.write_text("---\nusers: none\n---\n# acme\n\n## Before\n\nOther rules.\n\n"
                               + VISION + "\n## Working here\n\nPrivate conventions.\n")
        self.local.write_text(LOCAL)
        self.assertEqual(rulebook.text(),
                         VISION.rstrip() + "\n\n" + self.body.rstrip() + "\n\n" + LOCAL)

    def test_vision_can_end_at_eof_with_or_without_a_final_newline(self):
        for vision in (VISION, VISION.rstrip(), "## What ak is for"):
            with self.subTest(vision=vision):
                self.agents.write_text("# acme\n\n" + vision)
                self.assertEqual(rulebook.text(), vision.rstrip() + "\n\n" + self.body)

    def test_missing_file_or_section_preserves_the_old_rulebook_exactly(self):
        for agents in (None, "# acme\n", "### What ak is for\n\nOther rules.\n"
                       "## What ak is for acme\n\nOther rules.\n"
                       "Mention ## What ak is for in prose.\n"):
            if agents is not None:
                self.agents.write_text(agents)
            for local in (None, "", " \n\t\n", LOCAL):
                with self.subTest(agents=agents, local=local):
                    if local is None:
                        self.local.unlink(missing_ok=True)
                    else:
                        self.local.write_text(local)
                    expected = (self.body.rstrip() + "\n\n" + local
                                if local and local.strip() else self.body)
                    self.assertEqual(rulebook.text(), expected)

    def test_a_seat_whose_projects_agents_md_carries_the_vision_reads_it_once(self):
        self.agents.write_text("# acme\n\n" + VISION)
        for project, opens in (("# acme\n\n" + VISION + "\n## Working here\n\nTests.\n", False),
                               ("# widget\n\n## Working here\n\nTests.\n", True),
                               # a copy quoted in a template is no section of the project's own
                               ("# widget\n\nEvery README holds:\n\n```markdown\n" + VISION + "```\n", True)):
            with self.subTest(opens=opens), \
                    patch.object(config, "session_records", return_value={"acme": {"repo": "/x/acme"}}), \
                    patch("agentkit.run.agents_body", return_value=project):
                text = config.seat_rulebook("acme")
                self.assertEqual(text.count("## What ak is for"), 1 + (opens and VISION in project), text)
                self.assertEqual(text.startswith(VISION.rstrip()), opens, text)
                self.assertIn(project, text)            # the project's AGENTS.md stays whole

    def test_a_later_launch_reads_the_vision_without_changing_a_running_seat(self):
        self.agents.write_text(VISION)
        first = rulebook.write("acme-one")
        original = first.read_text()
        self.assertEqual(original, VISION.rstrip() + "\n\n" + self.body)
        updated = "## What ak is for\n\nDeliver the finished result.\n"
        self.agents.write_text(updated)
        second = rulebook.write("acme-two")
        self.assertEqual(second.read_text(), updated.rstrip() + "\n\n" + self.body)
        self.assertEqual(first.read_text(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
