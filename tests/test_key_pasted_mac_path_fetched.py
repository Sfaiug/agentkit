"""Pasted Mac paths arrive with the owner's prompt, as files here or a bounded fallback.

Black-box: fire Claude's registered prompt hook and answer its requests as the Mac bridge
does. Shell words are read from each path, leaving apostrophes elsewhere in the sentence alone.
"""

from pathlib import Path
import shlex
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.hookdrive import Hooks, read_rules
from test_key_fetch_inbox import Mac, publish

CONVERSATION = "7d3c1e2a-5b4f-4a6e-8c9d-0e1f2a3b4c5d"
SCREENSHOT = "/var/folders/ab/T/TemporaryItems/Screenshot 2026-11-03 at 10.45.04.png"
REPORT = "/Users/acme/Desktop/owner's report.pdf"
DATA = "bytes sent by the fake Mac\n"


class PastedMacPath(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.hooks = Hooks(self.home)
        self.seat()
        self.prompt("go")
        read_rules(self.home, "acme")
        self.bridge = self.home.path / ".agentkit/macbridge"

    def seat(self, model="opus"):
        self.home.write(".agentkit/state/session-acme.json", {
            "orchestrator": model, "workers": [model], "reviewers": [model],
            "cwd": str(self.home.path), "conversation": CONVERSATION,
            "id_source": "launcher", "resumable": True})

    def prompt(self, text, **payload):
        fired = self.hooks.fire("UserPromptSubmit", {
            "prompt": text, "session_id": CONVERSATION, **payload}, seat="acme")
        self.assertEqual((fired.code, fired.err), (0, ""))
        return "\n".join(part["hookSpecificOutput"]["additionalContext"] for part in fired.said)

    def fetched(self, text, path):
        mac = Mac(self.home, lambda inbox, ident: publish(
            inbox, f"{ident}{Path(path).suffix}", DATA))
        mac.start()
        try:
            news = self.prompt(text)
        finally:
            mac.stop.set()
            mac.join(5)
        self.assertIsNotNone(mac.asked, news)
        self.assertEqual(mac.asked["path"], path)
        copy = self.bridge / "inbox" / f"{mac.request}{Path(path).suffix}"
        self.assertIn(f"{path} is at {copy}", news)
        self.assertEqual(copy.read_text(), DATA)
        self.assertEqual(list((self.bridge / "requests").iterdir()), [])

    def test_a_backslash_escaped_screenshot_arrives_with_its_prompt(self):
        self.fetched("Read " + SCREENSHOT.replace(" ", "\\ ") + " please", SCREENSHOT)

    def test_shell_quotes_are_read_from_the_path_not_the_sentence(self):
        cases = [(r"'/Users/acme/Desktop/owner'\''s report.pdf'", REPORT),
                 (shlex.quote(REPORT), REPORT),
                 ('"/Users/acme/a report.pdf"', "/Users/acme/a report.pdf"),
                 (r"/Users/acme/owner\'s\ report.pdf", "/Users/acme/owner's report.pdf"),
                 (r"'/Users/acme/literal\ space.pdf'", r"/Users/acme/literal\ space.pdf"),
                 ('/Users/acme/"a report".pdf', "/Users/acme/a report.pdf"),
                 ("/Users/acme/report#one.pdf", "/Users/acme/report#one.pdf")]
        for pasted, path in cases:
            with self.subTest(pasted=pasted):
                self.fetched(f"Please don't lose {pasted} today", path)

    def test_an_unclosed_word_and_paths_in_tool_output_are_not_fetched(self):
        for text, payload in [("Read '/Users/acme/unclosed.pdf", {}),
                              ('Read "/Users/acme/unclosed.pdf', {}),
                              ("go", {"tool_response": {"content": REPORT}})]:
            with self.subTest(text=text):
                self.assertEqual(self.prompt(text, **payload), "")
                self.assertFalse(self.bridge.exists())

    def test_a_harness_whose_hook_carries_no_context_fetches_nothing(self):
        self.seat("grok")
        self.assertEqual(self.prompt(shlex.quote(REPORT)), "")
        self.assertFalse(self.bridge.exists())

    def test_a_mac_that_never_answers_leaves_a_command_for_later(self):
        news = self.prompt(shlex.quote(REPORT))
        self.assertIn(REPORT, news)
        self.assertIn("Mac did not answer", news)
        self.assertIn(f"ak fetch {shlex.quote(REPORT)}", news)
        self.assertEqual(list((self.bridge / "requests").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
