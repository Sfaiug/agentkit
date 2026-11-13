"""A worker turn runs first on a login where another model's own cap is spent.

A Claude login reads a week every model draws on (`weekly_all`) and a cap that is Fable's alone
(`weekly_scoped`, scope `Fable`).  Where the cap is spent, the week left is Opus's alone; where
it has room, the week is the one the Fable seats live on.  An Opus turn took the login with the
most week and spent what Fable could still use.

Black-box: AK_BIN, as tests/test_key_a_turn_s_login_is_ranked_on_what_its_model_reads_there.py
runs it, whose helper this borrows: Opus executes and Fable reviews over the logins `default`,
`second` and `third`, each given (week, cap)% used.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_key_a_turn_s_login_is_ranked_on_what_its_model_reads_there as ranked

OPUS, FABLE = ranked.OPUS, ranked.FABLE


class FirstWhereACapIsSpent(unittest.TestCase):
    logins = ranked.RankedOnItsModel.logins

    def test_an_opus_turn_takes_the_week_fable_cannot_spend(self):
        self.assertEqual(self.logins(default=(10, 10), second=(30, 20), third=(60, 100)),
                         {OPUS: {"third"}, FABLE: {"second"}})
        self.assertEqual(self.logins(default=(10, 10), second=(60, 100), third=(30, 20)),
                         {OPUS: {"second"}, FABLE: {"third"}})

    def test_with_every_cap_left_the_most_week_goes_first(self):
        ran = self.logins(default=(10, 10), second=(30, 20), third=(60, 30))
        self.assertEqual(ran[OPUS], {"second"})

    def test_a_login_running_low_stays_after_one_that_is_not(self):
        ran = self.logins(default=(10, 10), second=(30, 20), third=(99, 100))
        self.assertEqual(ran[OPUS], {"second"})

    def test_the_usual_login_stays_after_the_others(self):
        ran = self.logins(default=(60, 100), second=(30, 20), third=(100, 100))
        self.assertEqual(ran[OPUS], {"second"})


if __name__ == "__main__":
    unittest.main()
