"""A page whose words and styles alone change is of looks alone.

A change that edits an `.html` page so that, read by Python's `html.parser` on both sides, only
its text and what stands inside `style` differ is of looks alone
(tests/test_key_a_change_of_looks_alone_lands_on_its_quick_checks.py): it lands with no whole run,
its merge ending with `Looks-Alone-Tree: <tree>`.  One that edits a line inside `script`,
changes a `class` or an `onclick`, rewords text holding a `{`, a `&lt;%` or an `option`, adds a
page, makes one html.parser cannot read, or edits a page either side of which holds a template's
opener (`{{`, `{%`, `{#`, `<%`) anywhere, though only a colour changes, waits for the whole run as
any member.

Black-box, as that key and with its fixtures: the program `AK_BIN` names, on a busy host where a
whole suite waits for company, checks a landing line through tests/fixtures/akline.py; the run
that delivers is scripted by fakeadapter.py and merged by fakegh.py's GitHub.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures import akconfig, fakeadapter, taskfile
from fixtures.fakegh import GitHub
import test_key_a_change_of_looks_alone_lands_on_its_quick_checks as quick

# `<style/>` holds nothing: the text holding a `{` after it is no style.
PAGE = """<!DOCTYPE html>
<html>
<head>
<style>p { color: black }</style>
<script>
var total = 1;
</script>
</head>
<body>
<p class="lead">Welcome to acme.</p>
<button onclick="buy()">Buy</button>
<style/><p>Hello, {name}.</p>
<select><option>Small</option></select>
</body>
</html>
"""
REWORDED = PAGE.replace("Welcome to acme.", "Welcome to the acme shop.").replace("black", "navy")
# PAGE holding each opener: in its text, its style block, an attribute or its script
TEMPLATED = {"text.html": PAGE.replace("Welcome to acme.", "Welcome, {{ name }}."),
             "style.html": PAGE.replace("</style>", "{% if dark %}p { color: white }</style>"),
             "attribute.html": PAGE.replace('class="lead"', 'class="lead" title="{# hi #}"'),
             "script.html": PAGE.replace("total = 1", "total = <%= total %>")}


class APageOfWordsAndStylesIsOfLooksAlone(unittest.TestCase):
    # that key's line on a busy host, through its module: its tests are not this file's
    line, join, land, checked = (vars(quick.AChangeOfLooksAloneLandsOnItsQuickChecks)[name]
                                 for name in ("line", "join", "land", "checked"))

    def test_a_page_reworded_and_restyled_lands_with_no_whole_run(self):
        line = self.line(**{"index.html": PAGE})
        home = line.home
        GitHub(home).grant(line.rig.slug, "WRITE")
        akconfig.write(home, ["opus", "astra"], workers=["opus"], reviewers=["astra"])
        fakeadapter.install(home, claude={**fakeadapter.WORK, "write": {"index.html": REWORDED},
                                          "commit": "reword"}, codex="pass")
        done = home.ak("run", str(taskfile.write(home, line.rig.path, "Reword the page",
                                                 done_when=("grep -q navy index.html",))),
                       timeout=300)
        self.assertEqual(done.code, 0, done.out + done.err)
        run_dir, = (path for path in taskfile.runs(home) if path.name.endswith("-reword-the-page"))
        self.assertTrue(quick.record(run_dir).get("merged"), quick.record(run_dir))
        self.assertEqual(line.whole(), 0, line.runs())
        tree = line.rig.origin("rev-parse", "main^{tree}")
        self.assertTrue(line.rig.origin("log", "-1", "--format=%B", "main").rstrip().endswith(
            f"\n\nLooks-Alone-Tree: {tree}"))

    def waits(self, files):
        """A member whose branch writes `files` waits, while one behind it rewording the page
        lands."""
        line = self.line(**{"index.html": PAGE})
        self.join(line, files)
        self.join(line, {"index.html": REWORDED})
        self.land(line)
        self.assertEqual(self.checked(line), (0, [False, True]), line.runs())

    def test_one_that_edits_a_line_inside_script_waits(self):
        self.waits({"index.html": PAGE.replace("total = 1", "total = 2")})

    def test_one_that_changes_a_class_waits(self):
        self.waits({"index.html": PAGE.replace('class="lead"', 'class="intro"')})

    def test_one_that_changes_an_onclick_waits(self):
        self.waits({"index.html": PAGE.replace("buy()", "sell()")})

    def test_one_that_rewords_text_holding_a_brace_waits(self):
        self.waits({"index.html": PAGE.replace("Hello,", "Hi,")})

    def test_one_that_rewords_text_holding_an_opener_by_a_character_reference_waits(self):
        self.waits({"index.html": PAGE.replace("Welcome to acme.", "&lt;%= name %&gt;")})

    def test_one_that_rewords_an_option_waits(self):
        self.waits({"index.html": PAGE.replace("Small", "Little")})

    def test_one_that_adds_a_page_waits(self):
        self.waits({"about.html": REWORDED})

    def test_one_html_parser_cannot_read_waits(self):
        self.waits({"index.html": PAGE.replace("Buy", "&#" + "0" * 5000 + "65;")})

    def test_one_that_recolours_a_page_holding_a_template_s_opener_waits(self):
        line = self.line(**{"index.html": PAGE}, **TEMPLATED)
        for path, page in TEMPLATED.items():
            self.join(line, {path: page.replace("black", "navy")})
        self.join(line, {"index.html": REWORDED})
        self.land(line)
        self.assertEqual(self.checked(line), (0, [False] * len(TEMPLATED) + [True]), line.runs())

    def test_one_that_adds_a_template_s_opener_to_a_page_waits(self):
        self.waits({"index.html": TEMPLATED["style.html"]})


if __name__ == "__main__":
    unittest.main()
