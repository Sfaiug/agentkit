"""A card is its emoji, two words and its seat, and nothing the seat asked or did.

The owner keeps a seat's questions and results out of Discord: a card says whose and which, the
owner's mention last and the only one it may ping.  Offline: no webhook, no tmux.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentkit import notify  # noqa: E402


class CardCarriesNoText(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(notify, "_secret",
                               side_effect=lambda env, name: "42" if name == "discord_user_id" else "")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_card_is_its_kind_and_seat_and_nothing_it_said(self):
        for kind, line in (("needs", "🙋 Needs you · acme-api <@42>"), ("done", "✅ Done · acme-api <@42>")):
            with self.subTest(kind=kind):
                payload = notify.card_payload(kind, "acme-api")
                self.assertEqual(payload["content"], line)
                self.assertNotIn("embeds", payload)
        self.assertEqual(notify.title("done", None), "✅ Done · agentkit")   # outside a seat

    def test_words_in_a_card_ping_nobody_but_the_owner(self):
        self.assertEqual(notify.card_payload("done", "acme-api")["allowed_mentions"], {"users": ["42"]})
        with patch.object(notify, "_secret", return_value=""):
            payload = notify.card_payload("done", "acme-api")
        self.assertEqual((payload["content"], payload["allowed_mentions"]),
                         ("✅ Done · acme-api", {"parse": []}))


if __name__ == "__main__":
    unittest.main()
