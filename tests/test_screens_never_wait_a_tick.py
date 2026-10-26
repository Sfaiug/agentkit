"""A screen a test drives on a pty shows what it drew without waiting for the main screen's idle
redraw, `menu.TICK`: one case of each file that drives one, its child's tick pushed far past
the helper's wait, finishes.

Each case runs as its own file runs it, through tests/test_config_matrix.py's Screen or
tests/test_close_and_info.py's Menu, with only the tick changed in the child.
"""

import sys
import unittest
from unittest import mock

import test_add_opencode_provider
import test_add_subscription
import test_close_and_info
import test_config_matrix
import test_models_page
import test_past_sessions
import test_provider_screen

FAR = "from agentkit import menu\nmenu.TICK = 10 ** 6\n"     # never, within the helper's wait
SCREENS = [test_provider_screen.ProviderScreen("test_the_last_provider_stays"),
           test_models_page.ModelsPage("test_a_harness_ticks_its_models_in_and_out"),
           test_add_subscription.RemoveSubscription(
               "test_one_subscription_goes_and_its_login_files_are_left_alone"),
           test_add_opencode_provider.AddOpenCodeProvider(
               "test_a_provider_is_logged_in_then_its_model_added_at_its_own_mode"),
           test_add_subscription.AddSubscription(
               "test_another_subscription_logs_in_under_a_fresh_name_and_joins_accounts")]
MENUS = [test_past_sessions.Keys("test_p_lists_it_with_its_number_and_enter_reopens_it")]


def far(child, before):
    return child.replace(before, FAR + before, 1)


def screen(case, *args, child=test_config_matrix.CHILD, **kwargs):
    return test_config_matrix.Screen(case, *args, child=far(child, "with closing("), **kwargs)


class NeverATick(unittest.TestCase):
    def finishes(self, case, where, name, value):
        with self.subTest(case.id()), mock.patch.object(where, name, value):
            result = unittest.TestResult()
            case.run(result)
            self.assertTrue(result.wasSuccessful(), result.failures + result.errors)

    def test_a_config_screen_draws_without_its_tick(self):
        for case in SCREENS:
            self.finishes(case, sys.modules[type(case).__module__], "Screen", screen)

    def test_the_menu_s_pages_draw_without_its_tick(self):
        for case in MENUS:
            self.finishes(case, test_close_and_info, "CHILD",
                          far(test_close_and_info.CHILD, "sys.exit(menu.loop("))


if __name__ == "__main__":
    unittest.main()
