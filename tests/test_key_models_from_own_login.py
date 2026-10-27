"""A provider's models are the ones its subscriptions' logins list: `Models` on `c` offers
every model each of them lists, each once, and none only the usual login lists where no
subscription is that login.  A subscription just signed in is listed by its own login, even
when the harness was listed moments before.

On 26 Oct the owner, subscribed to Google AI Pro under a named account, could not pick Gemini 4
Argon: ak listed the harness's models off its usual login, a free account, whatever the
provider's subscriptions were.  Black-box: the program `AK_BIN` names, its menu in a person's
terminal (tests/fixtures/akterm.py), its harnesses the fakes of tests/fixtures/fakeadapter.py,
the fake Claude's `models` answering by AGENTKIT_ACCOUNT, as one harness signed in to different
plans does, and its `login` giving the account it signs in the plan NEXT lists.  Judged by what
the terminal shows; this test fails against `/bin/false`.
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter
from fixtures.akbin import REAL_TMUX, Home
from fixtures.akterm import SERVER, Terminal
from test_key_models_page_defaults import FABLE_LISTED as FABLE
from test_key_new_subscription_signs_in_afresh import (ADD, LIST_KEYS, MAIN_KEYS, PAGE,
                                                       lines, offered, title)

FREE, ARGON, NOVA, VELA = (f"claude-{name}\t{name.title()}\thigh"
                           for name in ("free", "argon", "nova", "vela"))
PLANS = {"default": [FABLE, FREE], "pro": [FABLE, ARGON], "max": [FABLE, NOVA], "next": [VELA]}
# before the fake itself: `models` says the plan of the account it is asked for, and `login`
# gives the account it signs in the plan `next`
BY_ACCOUNT = """d=%s
case "$1" in
  login) cp "$d/plan.next" "$d/plan.$AGENTKIT_ACCOUNT" ;;
  models) cat "$d/plan.${AGENTKIT_ACCOUNT:-default}" 2>/dev/null; exit 0 ;;
esac
"""


def ticks(screen):
    """The models `Models` lists under a harness, each as `■ label` or `□ label`."""
    return [line.lstrip("› ") for line in lines(screen) if line.lstrip("› ")[:2] in ("■ ", "□ ")]


@unittest.skipUnless(REAL_TMUX, "no tmux installed")
class ModelsFromOwnLogin(unittest.TestCase):
    def open(self, accounts):
        """The menu on `c`, for one model on Claude whose provider lists `accounts`."""
        self.home = Home()
        self.addCleanup(self.home.close)
        fake = fakeadapter.install(self.home, claude="pass")["claude"]
        for plan, models in PLANS.items():
            (fake.dir / f"plan.{plan}").write_text("\n".join(models) + "\n")
        fake.script.write_text(fake.script.read_text().replace(
            "#!/bin/sh\n", "#!/bin/sh\n" + BY_ACCOUNT % fake.dir, 1))
        akconfig.write(self.home, {"fable": "claude"},
                       providers={"anthropic": {"mode": "subscription", "accounts": accounts}})
        self.term = Terminal(self.home, size=(100, 40), env={"NO_COLOR": "1"})
        self.addCleanup(self.home.tmux, "respawn-pane", "-k", "-t", self.term.pane,
                        "sleep 86400", server=SERVER)
        self.term.wait(lambda screen: MAIN_KEYS in lines(screen))
        self.term.keys("c")
        self.term.wait("› Fable 5.1")

    def to(self, row):
        """The highlight moved, a line at a time, onto the line that reads `row`."""
        for _ in range(20):
            shown = lines(self.term.screen())
            if f"› {row}" in shown:
                return
            now = next(n for n, line in enumerate(shown) if line.startswith("› "))
            self.term.keys("Down" if shown.index(f"  {row}") > now else "Up")
            self.term.wait(lambda screen: lines(screen)[now] != shown[now])
        self.fail(f"the highlight never reached {row}")

    def models(self):
        """What `Models` lists under Claude Code, and back on `c`."""
        self.to("Models")
        self.term.keys("Enter")
        self.term.wait("› Claude Code")
        self.term.keys("Enter")
        listed = ticks(self.term.wait(lambda screen: "■ Fable 5.1" in ticks(screen)))
        self.term.keys("Escape")
        self.term.wait(lambda screen: "› Claude Code" in screen and "■" not in screen)
        self.term.keys("Escape")
        self.term.wait("› Models")
        return listed

    def test_a_named_subscription_lists_its_own_models_and_not_the_usual_logins(self):
        self.open(["pro"])
        self.assertEqual(self.models(), ["■ Fable 5.1", "□ Argon"])

    def test_two_subscriptions_list_both_each_model_once(self):
        self.open(["pro", "max"])
        self.assertEqual(self.models(), ["■ Fable 5.1", "□ Argon", "□ Nova"])

    def test_a_subscription_just_signed_in_lists_its_own_models(self):
        self.open(["pro"])
        self.assertEqual(self.models(), ["■ Fable 5.1", "□ Argon"])
        self.to("Subscriptions")
        self.term.keys("Enter")
        self.term.wait(lambda screen: title(screen) == PAGE)
        self.to("+ add a subscription")
        self.term.keys("Enter")
        rows = offered(self.term.wait(lambda screen: title(screen) == ADD
                                      and LIST_KEYS in lines(screen) and "Claude II" in screen))
        self.term.keys(*["Down"] * rows.index("Claude II"), "Enter")
        self.term.wait(lambda screen: title(screen) == PAGE and "Claude II" in screen)
        self.term.keys("Escape")
        self.term.wait("› Subscriptions")
        self.assertEqual(self.models(), ["■ Fable 5.1", "□ Argon", "□ Vela"])


if __name__ == "__main__":
    unittest.main()
