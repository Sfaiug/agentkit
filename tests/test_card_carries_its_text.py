"""A page leads with its question or result where a phone shows it, the whole text under it.

A push shows a message's content, not its embed: the content is the lead and the seat, the
owner's mention last and the only one it may ping.  Offline: no webhook, no tmux.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import notify  # noqa: E402


class CardCarriesItsText(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(notify, "_secret",
                               side_effect=lambda env, name: "42" if name == "discord_user_id" else "")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_lead_is_the_question_or_first_sentence_across_its_lines_links_as_written(self):
        for kind, text, lead in (
                ("needs", "Fix landed. Ship it today? It is Friday.", "Fix landed. Ship it today?"),
                ("needs", "Which branch\nshould I use? Main is frozen.", "Which branch should I use?"),
                ("done", "The parser now\naccepts CSV. Details follow.", "The parser now accepts CSV."),
                ("needs", "Approve https://acme.example/build?ref=main for release? It waits.",
                 "Approve https://acme.example/build?ref=main for release?"),
                ("needs", "Can you approve [this build](https://acme.example/build)? It waits.",
                 "Can you approve [this build](https://acme.example/build)?"),
                ("done", "Shipped at https://acme.example/v2. More.", "Shipped at https://acme.example/v2.")):
            with self.subTest(text=text):
                payload = notify.card_payload(kind, "acme-api", text)
                self.assertEqual(payload["content"], f"{lead} · acme-api <@42>")
                self.assertEqual(payload["embeds"][0]["description"], text)

    def test_words_in_a_card_ping_nobody_but_the_owner(self):
        self.assertEqual(notify.card_payload("done", "acme-api", "Shipped for <@99> and @everyone.")
                         ["allowed_mentions"], {"users": ["42"]})
        with patch.object(notify, "_secret", return_value=""):
            payload = notify.card_payload("done", "acme-api", "Shipped.")
        self.assertEqual((payload["content"], payload["allowed_mentions"]),
                         ("Shipped. · acme-api", {"parse": []}))

    def test_a_lead_past_what_discord_takes_is_cut_to_it(self):
        content = notify.card_payload("done", "acme-api", "x" * 5000)["content"]
        self.assertLessEqual(len(content), 2000)
        self.assertTrue(content.endswith("… <@42>"))


if __name__ == "__main__":
    unittest.main()
