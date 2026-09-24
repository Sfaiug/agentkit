"""Each harness lists the models it can run and the efforts each one takes.

`adapters/<h>.sh models` prints one `id<TAB>label<TAB>efforts` line per model: live where the
harness lists its own (`opencode models`, `agy models`, `grok models`, `codex debug models`),
else the `[catalog]` table of its manifest, which is also where a failed or unbounded listing lands.  `none` is
the one effort of a model that runs at no effort; an empty efforts field, one whose efforts
its harness does not say.  `config.catalog()` reads that as data,
`config.efforts()` answers from it for one model, and `ak doctor` names a model set to an
effort it does not take.

Offline and deterministic: every HOME is a temporary directory, PATH holds only a stub
directory and the system's own, and every harness that can list live has a stub there -- one
that fails unless a test hands it one of the real listings captured under tests/fixtures/ (see
the README there).  No real harness is asked anything.
"""

import io
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, orch, watch  # noqa: E402

FIXTURES = REPO / "tests/fixtures"

# A stub harness binary: every call is logged in $STUB_LOG, and each sleeps its seconds, says
# agy's own stderr line, prints its listing and exits with its code.
STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$STUB_LOG"
[ {sleep} = 0 ] || sleep {sleep}
echo "Fetching available models..." >&2
cat -- {listing}
exit {rc}
"""


def lines(text):
    return [line.split("\t") for line in text.splitlines()]


class Catalog(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".catalog-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "calls.log"
        self.log.touch()
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/local/bin:/usr/bin:/bin",
                    "STUB_LOG": str(self.log), "LANG": "C.UTF-8"}
        patcher = patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in (config.ADAPTER_DIR_ENV, "GROK_BIN_DIR", "GROK_HOME"):
            os.environ.pop(name, None)
        # every harness that can list live has a stub first on PATH, failing until a test
        # hands it a listing, so no path through an adapter reaches an installed CLI
        for name in ("agy", "opencode", "grok", "codex"):
            self.stub(name, rc=1)
        cache = patch.dict(config._CATALOGS, clear=True)
        cache.start()
        self.addCleanup(cache.stop)

    def stub(self, name, listing="/dev/null", rc=0, sleep=0):
        path = self.bin / name
        path.write_text(STUB.format(listing=shlex.quote(str(listing)), rc=rc, sleep=sleep))
        path.chmod(0o755)

    def models(self, harness):
        proc = subprocess.run(["bash", str(REPO / f"adapters/{harness}.sh"), "models"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def table(self, harness):
        with open(REPO / f"adapters/{harness}.toml", "rb") as fh:
            return tomllib.load(fh)["catalog"]

    # -- the static tables, one per shape ---------------------------------------------------

    def test_claude_table_differs_per_model_and_names_none_for_haiku(self):
        out = self.models("claude")
        got = {model: (label, efforts) for model, label, efforts in lines(out)}
        self.assertEqual(list(got), list(self.table("claude")))
        self.assertEqual(got["claude-opus-5-5"], ("Opus 5.5", "low medium high xhigh max"))
        # Sonnet 4.6 has no xhigh; Haiku 4.5 runs at no effort
        self.assertEqual(got["claude-sonnet-4-6"][1], "low medium high max")
        self.assertEqual(got["claude-haiku-4-5"], ("Haiku 4.5", "none"))
        self.assertEqual(self.log.read_text(), "", "claude itself is never asked")

    def test_codex_offers_a_chatgpt_login_default_alone(self):
        auth = self.home / ".codex/auth.json"
        auth.parent.mkdir()
        auth.write_text('{"auth_mode": "chatgpt", "OPENAI_API_KEY": null, "tokens": {}}')
        self.stub("codex", listing=FIXTURES / "codex-models.json")
        self.assertEqual(lines(self.models("codex")),
                         [["default", "Codex's own model", "low medium high xhigh max ultra"]])
        self.assertEqual(self.log.read_text(), "", "a ChatGPT login's codex is never asked")
        # an API key runs any model codex lists, refreshed, each with its own levels, and
        # none it hides
        auth.write_text('{"auth_mode": "apikey", "OPENAI_API_KEY": "sk-dummy"}')
        self.assertEqual(lines(self.models("codex")), [
            ["default", "Codex's own model", "low medium high xhigh max ultra"],
            ["gpt-6-astra", "GPT-6-Astra", "low medium high xhigh max ultra"],
            ["gpt-5.6-sol", "GPT-5.6-Sol", "low medium high xhigh max ultra"],
            ["gpt-5.6-terra", "GPT-5.6-Terra", "low medium high xhigh max ultra"],
            ["gpt-5.6-luna", "GPT-5.6-Luna", "low medium high xhigh max"],
            ["gpt-5.5", "GPT-5.5", "low medium high xhigh"],
        ])
        self.assertEqual(self.log.read_text(), "debug models\n", "not --bundled: it never refreshes")
        # and a listing that fails leaves the table
        self.stub("codex", listing=FIXTURES / "codex-models.json", rc=1)
        got = {model: efforts for model, _, efforts in lines(self.models("codex"))}
        self.assertEqual(list(got), list(self.table("codex")))
        self.assertEqual(got["gpt-5.2"], "low medium high xhigh")

    def test_muse_table_labels_models_by_their_ids(self):
        rows = lines(self.models("muse"))
        self.assertEqual([row[0] for row in rows], list(self.table("muse")))
        self.assertTrue(all(model == label for model, label, _ in rows), rows)
        got = {model: efforts for model, _, efforts in rows}
        self.assertEqual(got["muse-spark-1.3-contributor"], "minimal low medium high xhigh max")
        self.assertEqual(got["muse-spark-1.2"], "minimal low medium high xhigh")

    # -- the live listings --------------------------------------------------------------------

    def test_grokbuild_lists_live_and_takes_the_efforts_from_its_table(self):
        listing = self.root / "grok-models.txt"
        listing.write_text((FIXTURES / "grok-models.txt").read_text() + "  - grok-5-preview\n")
        self.stub("grok", listing=listing)
        self.assertEqual(lines(self.models("grokbuild")), [
            ["grok-4.7", "Grok 4.7", "low medium high xhigh"],
            ["grok-4.7-build-fast", "Grok 4.7 Fast", "low medium high xhigh"],
            ["grok-4.6", "Grok 4.6", "low medium high xhigh"],
            ["grok-4.5", "Grok 4.5", "low medium high"],
            ["grok-5-preview", "grok-5-preview", ""],     # the table does not know it: unsaid
        ])
        self.assertEqual(self.log.read_text(), "models\n")
        self.stub("grok", listing=listing, rc=1)
        self.assertEqual([row[0] for row in lines(self.models("grokbuild"))],
                         list(self.table("grokbuild")))

    def test_opencode_listing_is_parsed_and_cached_a_minute(self):
        self.stub("opencode", listing=FIXTURES / "opencode-models.txt")
        # each id the table knows takes its label and efforts, and any other goes unsaid
        table = {model["id"]: model for model in config.catalog_table("opencode")}
        want = [table.get(model) or {"id": model, "label": model, "efforts": []}
                for model in (FIXTURES / "opencode-models.txt").read_text().split()]
        self.assertEqual(want[0], {"id": "mimo/mimo-v2.6-flash", "label": "MiMo V2.6 Flash",
                                   "efforts": ["none"]})
        self.assertEqual(config.catalog("opencode"), want)
        self.assertEqual(self.log.read_text(), "models\n", "not --standalone: it lists nothing")
        # a second ask within the minute is the first answer; past it, the harness is asked again
        now = time.monotonic()
        with patch.object(config.time, "monotonic", return_value=now + 30):
            self.assertEqual(config.catalog("opencode"), want)
        self.assertEqual(self.log.read_text().count("models"), 1)
        with patch.object(config.time, "monotonic", return_value=now + config.CATALOG_TTL + 1):
            self.assertEqual(config.catalog("opencode"), want)
        self.assertEqual(self.log.read_text().count("models"), 2)

    def test_agy_folds_each_effort_suffixed_id_into_its_model(self):
        self.stub("agy", listing=FIXTURES / "antigravity-models.txt")
        self.assertEqual(lines(self.models("antigravity")), [
            ["gemini-3.8-flash", "Gemini 3.8 Flash", "low medium high"],
            ["gemini-3.7-flash", "Gemini 3.7 Flash", "low medium high"],
            ["gemini-3.6-flash", "Gemini 3.6 Flash", "low medium high"],
            ["gemini-3.1-pro", "Gemini 3.1 Pro", "low high"],
            ["claude-sonnet-4-6", "Claude Sonnet 4.6 (Thinking)", "none"],
            ["claude-opus-4-6-thinking", "Claude Opus 4.6 (Thinking)", "none"],
            ["gpt-oss-120b", "GPT-OSS 120B", "medium"],
        ])
        self.assertEqual(self.log.read_text(), "models\n")

    def test_a_listing_that_fails_or_hangs_falls_back_to_the_table(self):
        static = [[model, entry.get("label", model), " ".join(entry.get("efforts", []))]
                  for model, entry in self.table("antigravity").items()]
        self.stub("agy", listing=FIXTURES / "antigravity-models.txt", rc=1)   # failed, half said
        self.assertEqual(lines(self.models("antigravity")), static)
        self.stub("opencode")                                                  # said nothing
        self.assertEqual([row[0] for row in lines(self.models("opencode"))],
                         list(self.table("opencode")))
        self.stub("agy", listing=FIXTURES / "antigravity-models.txt", sleep=30)
        started = time.monotonic()
        self.assertEqual(lines(self.models("antigravity")), static)
        self.assertLess(time.monotonic() - started, 20, "the listing is given ten seconds")
        # a host with no `timeout` to bound a listing never starts one
        tools = self.root / "tools"
        tools.mkdir()
        for name in ("bash", "python3", "awk", "dirname", "cat"):
            (tools / name).symlink_to(shutil.which(name))
        self.log.write_text("")
        with patch.dict(os.environ, {"PATH": f"{self.bin}:{tools}"}):
            for harness, binary in (("antigravity", "agy"), ("opencode", "opencode"),
                                    ("grokbuild", "grok")):
                self.stub(binary, listing=FIXTURES / f"{harness}-models.txt")
                self.assertEqual([row[0] for row in lines(self.models(harness))],
                                 list(self.table(harness)))
        self.assertEqual(self.log.read_text(), "")
        # and an adapter that fails, even one that said something first, leaves
        # config.catalog() the same table
        fake = self.root / "adapters"
        fake.mkdir()
        (fake / "antigravity.sh").write_text(
            "#!/usr/bin/env bash\nprintf 'half\\tsaid\\tlow\\n'; exit 1\n")
        (fake / "antigravity.sh").chmod(0o755)
        with patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(fake)}):
            self.assertEqual(config.catalog("antigravity"), config.catalog_table("antigravity"))

    # -- what the rest of agentkit makes of it ------------------------------------------------

    def test_efforts_answer_per_model_and_fall_back_to_the_harness_words(self):
        self.assertEqual(config.efforts("grokbuild", "grok-4.5"), ["low", "medium", "high"])
        self.assertEqual(config.efforts("grokbuild", "grok-4.7"),
                         ["low", "medium", "high", "xhigh"])
        self.assertEqual(config.efforts("claude", "claude-sonnet-4-6"),
                         ["low", "medium", "high", "max"])
        # a model that runs at no effort takes `none` alone; one whose efforts go unsaid, or
        # that is not listed at all, takes its harness's words
        self.assertEqual(config.efforts("claude", "claude-haiku-4-5"), ["none"])
        self.assertEqual(config.efforts("opencode", "mimo/mimo-v2.6-pro"), ["none"])
        levels = config.manifest("claude")["effort"]["levels"]
        self.assertEqual(config.efforts("claude", "claude-unknown"), levels)
        # and without a model nothing is asked: the `c` screen's cycle stays the harness's words
        with patch.object(config, "catalog", side_effect=AssertionError("asked")):
            self.assertEqual(config.efforts("claude"), levels)

    def test_doctor_names_a_model_set_to_an_effort_it_does_not_take(self):
        default = (REPO / "config.default.toml").read_text()
        haiku = ('\n[models.haiku]\nharness = "claude"\nmodel = "claude-haiku-4-5"\n'
                 'effort = "{}"\nprovider = "anthropic"\n')
        text = default.replace('model = "grok-4.7"', 'model = "grok-4.5"') + haiku.format("low")
        path = self.home / "config.toml"
        path.write_text(text)
        (self.home / ".codex").mkdir()
        (self.home / ".codex/auth.json").write_text('{"auth_mode": "chatgpt"}')
        self.stub("agy", listing=FIXTURES / "antigravity-models.txt")
        self.stub("opencode", listing=FIXTURES / "opencode-models.txt")
        with patch.object(config, "HOME", self.home), \
                patch.object(orch, "slice_line", return_value="slice test"), \
                patch.object(watch, "tick_health", return_value="lock free"), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(watch.doctor([]), 0)
        self.assertEqual(out.getvalue().splitlines(), [
            "slice test", "tick  lock free",
            "effort  grok: grok-4.5 takes low medium high, not xhigh",
            "effort  haiku: claude-haiku-4-5 takes none, not low"])
        self.assertEqual(path.read_text(), text, "flagged, never changed")
        # `none` is how a model that runs at no effort is configured
        path.write_text(default + haiku.format("none"))
        config._CATALOGS.clear()
        with patch.object(config, "HOME", self.home), \
                patch.object(orch, "slice_line", return_value="slice test"), \
                patch.object(watch, "tick_health", return_value="lock free"), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(watch.doctor([]), 0)
        self.assertEqual(out.getvalue().splitlines()[-1],
                         "effort  every model takes the effort it is set to")


if __name__ == "__main__":
    unittest.main()
