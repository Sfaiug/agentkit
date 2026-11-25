"""Which changes are of looks alone, and the tests each brings: every path a change names against
its target -- added, edited, removed, either side of a rename -- a stylesheet, a raster image, a
font or prose, or a page it edits whose words and styles alone change (`_markup`); or, beside one
such path at least, a test of the project's own it edits or removes, a path both the project's
time record (`suite_times`) and the path itself call a test.  AGENTS.md, which holds ak's own
rules for the project, is never one of them, nor a schema path (`change_rules.schema`), which a
revert cannot undo.  It brings those it edits, as the record spells them.
Only on a target that declares both `health:` and `deployed:`, so ak reverts a release whose
health breaks (`watch.after_merge_revert`), and whose project has a time record of its suite
(`suite_times`), so a repository whose runner reports no tests completes whole landing checks and
its sessions are told (`stop.untested`, `suite_times.unreported`; owner, 18 Nov 2026: "Keep
trying to enforce"), does such a change land on the tests it brings and its own quick checks, no
whole suite (`land._looks`), its merge saying so with TRAILER.  What it breaks the next whole run
finds as any red on the target.

A change that adds a test waits as before, even one a round timed before the change was on the
target, and so does a change of tests alone, as the owner's yes was to changes of looks: a test is
never a path of looks, whatever its suffix, a doctest page among them.  The record's word alone is
not enough: a suite times a module whose doctests it runs, and tests written inside a source
file, and those ship.  Unclear is not a test.

Owner, 16 Nov 2026: "Yes, once auto-undo works" -- such a change waited a median 3.2 h in a line
for a suite that reads almost none of it.  Of one project's month of changes 28 named looks alone
and 46 more looks and tests of their own, 28 of them only tests the record timed; of its 63 to
pages, which carry their styles and script inline, and at most their own tests, 33 changed words
and styles alone.
"""

from html.parser import HTMLParser
from pathlib import PurePosixPath
import re

from . import change_rules, gitcall, suite_times

TRAILER = "Looks-Alone-Tree"
# SVG is not here: it can hold a script.  Nor MDX, whose prose imports and runs components.
SUFFIXES = {".css", ".scss", ".sass", ".less",
            ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".ico",
            ".woff", ".woff2", ".ttf", ".otf", ".eot",
            *change_rules.PROSE} - {".mdx"}
PAGES = {".html", ".htm"}
# A page holding one of these anywhere holds a template's logic, which html.parser cannot tell from
# markup: a quoted `</style>` inside an expression, a character reference, a tag's name joined to
# a conditional.  Such a page is never of looks alone, whatever its edit, a CSS selector `{#id`
# or an opener inside a script's string among them.
OPENERS = ("{{", "{%", "{#", "<%")
# A page's words and styles, which `_markup` takes out: its text, what stands inside `style` and
# these attributes' values; never text inside VERBATIM, nor text or a value holding a `{` or `<%`
# (`_words`).
WORDY = {"style", "alt", "title", "placeholder", "aria-label"}
VERBATIM = {"script", "template", "textarea", "option"}
# A path calls itself a test by a directory of one of these names, or one of them a word of its
# file's stem: `tests/a.py`, `test_a.py`, `a_test.go`, `a.spec.ts`.
TEST = {"test", "tests", "spec"}


def changes(repo, target, heads):
    """{each of `heads` whose change against `target` is of looks alone: the tests it brings},
    where `target` declares both `health:` and `deployed:` and the project has a time record of
    its suite (`suite_times`); none elsewhere, `heads` then never read, nor where git cannot say.
    Only a target with a `tests:` line has tests to bring."""
    if not (all(gitcall.declared_at(repo, target, key) for key in ("health", "deployed"))
            and (times := suite_times.read(suite_times.handed(repo)))):
        return {}
    # A record's `./tests/a.py::part` is git's `tests/a.py`.
    timed = {PurePosixPath(file): file for file in (
        test.partition("::")[0] for test in times)
        } if gitcall.declared_at(repo, target, "tests") else {}
    alone = {}
    for head in heads:
        code, out = gitcall.git_out(repo, "diff", "--raw", "--no-abbrev", "--no-renames", "-z",
                                    f"{target}...{head}")
        if code:
            continue
        fields, named = out.split("\0"), {}
        for meta, path in zip(fields[::2], fields[1::2]):
            *_, before, after, status = meta.split()    # `:<mode> <mode> <blob> <blob> <status>`
            named[PurePosixPath(path)] = status, before, after
        if any(path.name == "AGENTS.md" or change_rules.schema(path) for path in named):
            continue
        tests = {path for path in named
                 if path in timed and TEST & {*path.parent.parts, *re.split(r"[._-]", path.stem)}}
        looks = named.keys() - tests
        if (looks and all(named[path][0] in ("M", "D") for path in tests)
                and all(_looks(repo, path, *named[path]) for path in looks)):
            alone[head] = sorted(timed[path] for path in tests if named[path][0] == "M")
    return alone


def _looks(repo, path, status, before, after):
    """Is `path`, `status` from blob `before` to blob `after`, a path of looks?"""
    if path.suffix.lower() in PAGES and status == "M":
        markup = _markup(repo, before)
        return markup is not None and markup == _markup(repo, after)
    return path.suffix.lower() in SUFFIXES


def _markup(repo, blob):
    """All `html.parser` reads in the page `blob` but its words and styles, in order: None where
    it holds one of OPENERS, is not UTF-8 or html.parser cannot read it."""
    page, reader = gitcall.git_bytes(repo, "cat-file", "blob", blob), _Markup()
    if any(opener in page for opener in OPENERS):
        return None
    try:
        page.encode()   # `git_bytes` keeps a byte that is not UTF-8 as a surrogate
        reader.feed(page)
        reader.close()
    # a UnicodeEncodeError is a ValueError, as is a `&#...;` too long to read; and AssertionError is
    # html.parser's word for markup it cannot read
    except (ValueError, AssertionError):
        return None
    return reader.events


def _words(text):
    """Is `text`, its character references decoded, free of a `{` or `<%`, which could open a
    template's logic OPENERS cannot find in the source (`${ }`, `&lt;%`)?"""
    return "{" not in text and "<%" not in text


class _Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.events, self.open, self.text = [], [], ""

    def event(self, *event):
        """Record `event`, after the text before it unless that is of words and styles."""
        if self.text and (VERBATIM & {*self.open}
                          or "style" not in self.open and not _words(self.text)):
            self.events.append(("text", self.text))
        self.text = ""
        self.events.append(event)

    def handle_starttag(self, tag, attrs, kind="<"):
        self.event(kind, tag, [(name, None if name in WORDY and _words(value or "") else value)
                               for name, value in attrs])
        if kind == "<":     # `<style/>` holds nothing, as html.parser reads it
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs, "/>")

    def handle_endtag(self, tag):
        self.event("</", tag)
        if tag in self.open:    # it closes what it holds: `</select>` an `<option>` left open
            del self.open[len(self.open) - self.open[::-1].index(tag) - 1:]

    def handle_data(self, data):
        self.text += data   # in pieces, one at each `<` that opens no tag

    def handle_comment(self, data):
        self.event("<!--", data)

    def handle_decl(self, data):
        self.event("<!", data)

    def unknown_decl(self, data):
        self.event("<![", data)

    def handle_pi(self, data):
        self.event("<?", data)

    def close(self):
        super().close()
        self.handle_data(self.rawdata)  # Python 3.11 leaves unclosed `<script>` or `<style>` unread
        self.event("end")
