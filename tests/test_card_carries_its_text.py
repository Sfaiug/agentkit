"""A page carries what it is about: its lead where a phone's push shows a message, the rest under it.

A Discord push shows a message's content, not its embed, and the content of a card used to be the
owner's mention alone.  Now it is the lead -- a question up to its "?", a result's first sentence --
and the seat, with the mention last and the only one it may ping; the embed holds the whole text.
A done must say its result first, as a question must ask first.  Offline: no webhook, no tmux.
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import config, notify


class CardCarriesItsText(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(notify, "_secret",
                               side_effect=lambda env, name: "42" if name == "discord_user_id" else "")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_question_leads_up_to_its_mark(self):
        self.assertEqual(notify.lead("needs", "Fix landed. Should it ship today? It is Friday."),
                         "Fix landed. Should it ship today?")
        self.assertEqual(notify.lead("needs", "\n  Which branch?\nmain is frozen"), "Which branch?")

    def test_a_result_leads_with_its_first_sentence(self):
        self.assertEqual(notify.lead("done", "All four gaps are live. 1) The waitlist form."),
                         "All four gaps are live.")
        self.assertEqual(notify.lead("done", "Live on v2.1.292 at last\nthe details"),
                         "Live on v2.1.292 at last")

    def test_the_card_is_the_lead_and_the_seat_with_the_mention_last(self):
        payload = notify.card_payload("needs", "acme-api", "Which schema should acme use? The old one breaks.")
        self.assertEqual(payload["content"], "Which schema should acme use? · acme-api <@42>")
        self.assertEqual(payload["allowed_mentions"], {"users": ["42"]})
        self.assertEqual(payload["embeds"][0]["description"],
                         "Which schema should acme use? The old one breaks.")
        self.assertEqual(payload["embeds"][0]["title"], "Needs you · acme-api")

    def test_words_in_a_card_ping_nobody_but_the_owner(self):
        payload = notify.card_payload("done", "acme-api", "Shipped for <@99> and @everyone.")
        self.assertEqual(payload["allowed_mentions"], {"users": ["42"]})
        with patch.object(notify, "_secret", return_value=""):
            payload = notify.card_payload("done", "acme-api", "Shipped.")
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(payload["content"], "Shipped. · acme-api")

    def test_a_link_in_the_lead_does_not_unfold(self):
        payload = notify.card_payload("needs", "acme-api", "Can you approve https://acme.example/pr/7? It waits.")
        self.assertIn("<https://acme.example/pr/7?>", payload["content"])

    def test_what_discord_would_refuse_is_cut_to_what_it_takes(self):
        payload = notify.card_payload("done", "acme-api", "x" * 5000)
        self.assertLessEqual(len(payload["content"]), 2000)
        self.assertEqual(len(payload["embeds"][0]["description"]), notify.DESCRIPTION_CAP)
        self.assertTrue(payload["embeds"][0]["description"].endswith("…"))

    def test_a_done_says_its_result_first(self):
        notify.results_first("Parser fix is live. The details follow, as long as they need to be.")
        with self.assertRaises(config.Error) as refused:
            notify.results_first("ATLAS: the column drag and typed Buy Box price fixes are all live, "
                                 "on the Monitor and the MOV Helper.")
        self.assertIn("put the result first", str(refused.exception))
        with patch.dict(os.environ, {"AK_RUN_ROLE": ""}), \
                patch.object(notify, "shaped", return_value=0) as shaped:
            with self.assertRaises(config.Error):
                notify.main(["done", "Everything the owner asked for this week is now built, "
                                     "reviewed, merged and live on every host."])
            shaped.assert_not_called()


if __name__ == "__main__":
    unittest.main()
