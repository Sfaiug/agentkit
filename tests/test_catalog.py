"""Each harness lists the models it can run and the efforts each one takes.

`adapters/<h>.sh models` prints one `id<TAB>label<TAB>efforts` line per model: live where the
harness lists its own (`opencode api model.list`, `agy models`, `grok models`, `codex debug models`, and
Claude's and Muse's in tests/test_live_catalog.py), else the `[catalog]` table of its manifest,
and fails where that listing fails.  `none` is
the one effort of a model that runs at no effort; an empty efforts field, one whose efforts
its harness does not say.  `config.catalog()` reads that as data and keeps it, the table
standing in for a login never listed; `config.efforts()` answers from it for one model, and
`ak doctor` names a model set to an effort it does not take.

Offline and deterministic: every HOME is a temporary directory, PATH holds only a stub
directory and the system's own, and every harness that can list live has a stub there -- one
that fails unless a test hands it one of the real listings captured under tests/fixtures/ (see
the README there) -- or, for Claude, a models API on a closed loopback port.  No real harness
or provider is asked anything.
"""

import io
import json
import os
import shlex
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
        paths = patch.multiple(config, RUNS=self.home / "runs", STATE=self.home / "state")
        paths.start()
        self.addCleanup(paths.stop)
        for name in (config.ADAPTER_DIR_ENV, config.ACCOUNT_ENV, "GROK_BIN_DIR", "GROK_HOME",
                     "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR"):
            os.environ.pop(name, None)
        # every harness that can list live has a stub first on PATH, failing until a test
        # hands it a listing, so no path through an adapter reaches an installed CLI; Claude's
        # models API is a port nothing listens on, whatever login a Keychain holds
        os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"
        for name in ("agy", "opencode", "grok", "codex", "muse"):
            self.stub(name, rc=1)
        cache = patch.dict(config._ASKED, clear=True)
        cache.start()
        self.addCleanup(cache.stop)

    def stub(self, name, listing="/dev/null", rc=0, sleep=0):
        path = self.bin / name
        path.write_text(STUB.format(listing=shlex.quote(str(listing)), rc=rc, sleep=sleep))
        path.chmod(0o755)

    def models(self, harness, code=0):
        proc = subprocess.run(["bash", str(REPO / f"adapters/{harness}.sh"), "models"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, code, proc.stderr)
        return proc.stdout

    def rows(self, harness):         # its `[catalog]` table, as an adapter's lines say it
        return [[model["id"], model["label"], " ".join(model["efforts"])]
                for model in config.catalog_table(harness)]

    def table(self, harness):
        with open(REPO / f"adapters/{harness}.toml", "rb") as fh:
            return tomllib.load(fh)["catalog"]

    # -- the static tables, one per shape ---------------------------------------------------

    def test_claude_table_differs_per_model_and_names_none_for_haiku(self):
        got = {model: (label, efforts) for model, label, efforts in self.rows("claude")}
        self.assertEqual(list(got), list(self.table("claude")))
        self.assertEqual(got["claude-opus-5-5"], ("Opus 5.5", "low medium high xhigh max"))
        # Sonnet 4.6 has no xhigh; Haiku 4.5 runs at no effort
        self.assertEqual(got["claude-sonnet-4-6"][1], "low medium high max")
        self.assertEqual(got["claude-haiku-4-5"], ("Haiku 4.5", "none"))

    def test_codex_lists_every_model_for_a_chatgpt_login_and_an_api_key(self):
        auth = self.home / ".codex/auth.json"
        auth.parent.mkdir()
        self.stub("codex", listing=FIXTURES / "codex-models.json")
        # either login runs any model codex lists, refreshed, each with its own levels, and
        # none it hides
        listed = [
            ["default", "Codex's own model", "low medium high xhigh max ultra"],
            ["gpt-6-astra", "GPT-6-Astra", "low medium high xhigh max ultra"],
            ["gpt-5.6-sol", "GPT-5.6-Sol", "low medium high xhigh max ultra"],
            ["gpt-5.6-terra", "GPT-5.6-Terra", "low medium high xhigh max ultra"],
            ["gpt-5.6-luna", "GPT-5.6-Luna", "low medium high xhigh max"],
            ["gpt-5.5", "GPT-5.5", "low medium high xhigh"],
        ]
        for login in ('{"auth_mode": "chatgpt", "OPENAI_API_KEY": null, "tokens": {}}',
                      '{"auth_mode": "apikey", "OPENAI_API_KEY": "sk-dummy"}'):
            self.log.write_text("")
            auth.write_text(login)
            self.assertEqual(lines(self.models("codex")), listed, login)
            self.assertEqual(self.log.read_text(), "debug models\n",
                             "not --bundled: it never refreshes")
        # and a listing that fails fails
        self.stub("codex", listing=FIXTURES / "codex-models.json", rc=1)
        self.assertEqual(self.models("codex", 1), "")

    def test_muse_table_labels_models_by_their_ids(self):
        rows = self.rows("muse")
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
        self.assertEqual(self.models("grokbuild", 1), "")

    def test_opencode_listing_is_parsed_and_cached_a_minute(self):
        self.stub("opencode", listing=FIXTURES / "opencode-model-list.json")
        # each id the table knows takes its label and efforts, and any other OpenCode's own
        # name, a hyphen a space (config.model_label), and variants, `none` for one with none
        table = {model["id"]: model for model in config.catalog_table("opencode")}
        listed = json.loads((FIXTURES / "opencode-model-list.json").read_text())["data"]
        want = [table.get(f"{model['providerID']}/{model['id']}") or {
            "id": f"{model['providerID']}/{model['id']}", "label": model["name"].replace("-", " "),
            "efforts": [variant["id"] for variant in model["variants"]] or ["none"]}
            for model in listed]
        self.assertEqual(want[-1], {"id": "mimo/mimo-v2.6-flash", "label": "MiMo V2.6 Flash",
                                    "efforts": ["none", "high"]})
        self.assertEqual(config.catalog("opencode"), want)
        self.assertEqual(self.log.read_text(), "api model.list\n",
                         "not --standalone: it lists nothing")
        # a second ask within the minute is the first answer; past it, the harness is asked again
        now = time.monotonic()
        with patch.object(config.time, "monotonic", return_value=now + 30):
            self.assertEqual(config.catalog("opencode"), want)
        self.assertEqual(self.log.read_text().count("model.list"), 1)
        with patch.object(config.time, "monotonic", return_value=now + config.CATALOG_TTL + 1):
            self.assertEqual(config.catalog("opencode"), want)
        self.assertEqual(self.log.read_text().count("model.list"), 2)

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

    def test_a_listing_that_fails_or_says_nothing_fails(self):
        self.stub("agy", listing=FIXTURES / "antigravity-models.txt", rc=1)   # failed, half said
        self.assertEqual(self.models("antigravity", 1), "")
        self.stub("opencode")                                                  # said nothing
        self.assertEqual(self.models("opencode", 1), "")

    def test_a_listing_read_stands_until_a_newer_one_is_read(self):
        # an adapter answering what `listing` holds after $ACME_SLEEP seconds, failing without one
        fake = self.root / "adapters"
        fake.mkdir()
        (fake / "antigravity.sh").write_text(
            '#!/usr/bin/env bash\nd=$(dirname "$0")\nl=$(cat "$d/listing") || exit 1\n'
            'sleep "${ACME_SLEEP:-0}" && echo "$l"\n')
        (fake / "antigravity.sh").chmod(0o755)

        def look(again=True):
            if again:                 # a login asked anew, as after a sign-in
                config.forget_catalog("antigravity")
            return [model["id"] for model in config.catalog("antigravity")]

        def answers(*models):
            (fake / "listing").write_text("".join(f"{model}\t{model}\tlow\n" for model in models))

        with patch.dict(os.environ, {config.ADAPTER_DIR_ENV: str(fake)}):
            table = [model["id"] for model in config.catalog_table("antigravity")]
            self.assertEqual(look(), table, "never listed: the table")
            answers("acme-9")
            self.assertEqual(look(), ["acme-9"])
            (fake / "listing").unlink()
            self.assertEqual(look(), ["acme-9"], "a failure replaces nothing")
            answers("acme-9", "acme-10")
            self.assertEqual(look(), ["acme-9", "acme-10"], "a newer listing replaces it")
            # one answering past the wait is kept, for the next look, though an ask after it failed
            answers("acme-11")
            os.environ["ACME_SLEEP"] = "1"
            with patch.object(config, "CATALOG_WAIT", 0.1):
                self.assertEqual(look(), ["acme-9", "acme-10"])
                late = config._ASKED["antigravity", config.DEFAULT_ACCOUNT][1]
                with patch.dict(os.environ, ACME_SLEEP="never"):     # an ask that fails
                    self.assertEqual(look(), ["acme-9", "acme-10"])
            late.wait()
            self.assertEqual(look(again=False), ["acme-11"])
            # and one past its time replaces nothing
            answers("acme-12")
            with patch.object(config, "CATALOG_TTL", 0.1):
                config._keep(config._kept("antigravity"), "antigravity", config.DEFAULT_ACCOUNT)
            with patch.object(config, "_logins", return_value={config.DEFAULT_ACCOUNT: [], "acme": []}):
                self.assertEqual([model["id"] for model in config.catalog_held("antigravity")],
                                 ["acme-11", *table], "acme: never listed")

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
        self.assertEqual(config.efforts("opencode", "mimo/mimo-v2.6-pro"), ["none", "high"])
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
        self.stub("opencode", listing=FIXTURES / "opencode-model-list.json")
        with patch.object(config, "HOME", self.home), \
                patch.object(orch, "slice_line", return_value="slice test"), \
                patch.object(watch, "tick_health", return_value=("lock free", False)), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(watch.doctor([]), 0)
        self.assertEqual(out.getvalue().splitlines()[:-1], [    # the last is the rented machine
            "slice test", "tick  lock free",
            "runs  0 started in the last day · 0 ended · 0 going · 0 endings owed",
            "gates  admission never held · suite turns never held · memory never held",
            "night review  disarmed · last two weeks no merges · no merges",
            "machine  this one: new · never answered",
            "effort  haiku: claude-haiku-4-5 takes none, not low",
            "effort  grok: grok-4.5 takes low medium high, not xhigh"])
        self.assertEqual(path.read_text(), text, "flagged, never changed")
        # `none` is how a model that runs at no effort is configured
        path.write_text(default + haiku.format("none"))
        config._ASKED.clear()
        with patch.object(config, "HOME", self.home), \
                patch.object(orch, "slice_line", return_value="slice test"), \
                patch.object(watch, "tick_health", return_value=("lock free", False)), \
                redirect_stdout(io.StringIO()) as out:
            self.assertEqual(watch.doctor([]), 0)
        self.assertEqual(out.getvalue().splitlines()[-2],
                         "effort  every model takes the effort it is set to")


if __name__ == "__main__":
    unittest.main()
