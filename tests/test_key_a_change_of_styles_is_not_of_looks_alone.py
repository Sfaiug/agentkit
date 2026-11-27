"""A change of styles is not of looks alone.

A change of a stylesheet alone, `.css`, `.scss`, `.sass` or `.less`, is not of looks alone
(tests/test_key_a_change_of_looks_alone_lands_on_its_quick_checks.py), nor is one of a page,
`.html`, whose text alone or `<style>` alone changes: a style can hide or cover a login or payment
control, which a whole suite that drives a browser sees.  Each waits for the whole suite as any
change of logic, while an image, and a prose file, behind them land with no whole run.  A verdict
of looks alone an older lander saved for a reviewed stylesheet never lands it: its resume, or a
retry of its failed delivery, rejoins the line with none.

Black-box, as tests/test_key_a_change_of_looks_alone_brings_its_tests.py and with its fixtures:
the program `AK_BIN` names, on a busy host where a whole suite waits for company, checks a landing
line through tests/fixtures/akline.py; the older verdict is saved and followed as
tests/test_key_a_run_without_review_is_not_landed_as_looks_alone.py does.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_key_a_change_of_looks_alone_brings_its_tests as brings
import test_key_a_run_without_review_is_not_landed_as_looks_alone as unreviewed

PAGE = "<style>p { color: black }</style>\n<p>Welcome to acme.</p>\n"
NEWS = "Old news.\n"
WAITS = {suffix: {f"site{suffix}": "p { color: navy }\n"}
         for suffix in (".css", ".scss", ".sass", ".less")}
WAITS.update(text={"index.html": PAGE.replace("Welcome to acme.", "Welcome to the acme shop.")},
             style={"shop.html": PAGE.replace("black", "navy")})
# prose outside the project's `content:` only shrinks
LANDS = {"image": {"logo.png": "navy\n"}, "prose": {"news.md": NEWS}}


class AChangeOfStylesIsNotOfLooksAlone(unittest.TestCase):
    # that key's line on a busy host, through its module: its tests are not this file's
    line, join, land, checked = (vars(brings.AChangeOfLooksAloneBringsItsTests)[name]
                                 for name in ("line", "join", "land", "checked"))
    task, settled, rejoins_under_the_installed_ak, rejoins = (
        vars(unreviewed.ARunWithoutReviewIsNotLandedAsLooksAlone)[name]
        for name in ("task", "settled", "rejoins_under_the_installed_ak", "rejoins"))

    def test_stylesheets_and_pages_wait_while_an_image_and_prose_behind_them_land(self):
        line = self.line(**{"index.html": PAGE, "shop.html": PAGE,
                            "news.md": NEWS + "More news.\n"})
        for files in (*WAITS.values(), *LANDS.values()):
            self.join(line, files)
        self.land(line)
        whole, verdicts = self.checked(line)
        self.assertEqual((whole, dict(zip([*WAITS, *LANDS], verdicts))),
                         (0, {**dict.fromkeys(WAITS, set()), **dict.fromkeys(LANDS, {"land"})}),
                         line.runs())

    def test_a_reviewed_stylesheet_an_older_lander_let_through_rejoins_the_line(self):
        self.rejoins_under_the_installed_ak(WAITS[".css"])


if __name__ == "__main__":
    unittest.main()
