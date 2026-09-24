"""One gentle probe cadence, host-wide, and a refused probe that is not a logout.

Fake adapters in a temporary HOME: the `usage` and `auth` verbs answer out of files this test
writes, so nothing here reaches a real usage endpoint or a real credential.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, menu, terminal, usage

NOW = 1000000.0
WEEK = 604800

CONFIG = """
[tiers]
A = ["one"]
B = ["one", "two"]

[models.one]
harness = "fake"
model = "m-one"
effort = "high"
provider = "alpha"

[models.two]
harness = "other"
model = "m-two"
effort = "high"
provider = "beta"

[providers.alpha]
mode = "subscription"

[providers.beta]
mode = "subscription"
"""

# One script, linked as every harness: its usage and auth answers are files the test writes,
# named for the harness asked, and every call is appended to `asked` -- so the cadence and the
# lock are both read off one log of what the adapters were really asked.
HARNESS = {"alpha": "fake", "beta": "other", "meta": "muse"}
ADAPTER = """#!/usr/bin/env bash
printf '%s %s\\n' "$(basename "$0" .sh)" "${1:-}" >>"$FAKE/asked"
case "${1:-}" in
usage)
  sleep "$(cat "$FAKE/delay" 2>/dev/null || echo 0)"
  cat "$FAKE/$(basename "$0" .sh)-usage.json" ;;
auth)
  cat "$FAKE/auth-line"; exit "$(cat "$FAKE/auth-code")" ;;
*) exit 2 ;;
esac
"""


class GentleProbe(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix=".usage-probe-", dir=REPO)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.fake = self.root / "fake"
        self.fake.mkdir()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("HOME", "RUNS", "WT", "STATE", "SECRETS", "TMP", "ENV", "WORK", "CODE"):
            self.stack.enter_context(patch.object(config, name, self.root / name.lower()))
        self.stack.enter_context(patch.dict(os.environ, {
            "HOME": str(self.root), "NO_COLOR": "1", "FAKE": str(self.fake),
            config.ADAPTER_DIR_ENV: str(self.fake)}))
        config.ensure_dirs()
        (config.HOME / config.CONFIG_NAME).write_text(CONFIG)
        for harness in HARNESS.values():
            script = self.fake / f"{harness}.sh"
            script.write_text(ADAPTER)
            script.chmod(0o755)
            (self.fake / f"{harness}.toml").write_text("[usage]\n")
        (self.fake / "auth-line").write_text("token in ~/.fake/token\n")
        (self.fake / "auth-code").write_text("0")
        self.answer("alpha", [self.meter("weekly", 40)])
        self.answer("beta", [self.meter("weekly", 60)])
        self.now = [NOW]
        self.stack.enter_context(patch.object(usage.time, "time", side_effect=lambda: self.now[0]))
        self.cfg = config.load()

    # --- the fixture ------------------------------------------------------

    def meter(self, name, used, window=WEEK):
        return {"name": name, "used": used, "resets_at": NOW + window / 2,
                "window_secs": window}

    def answer(self, provider, meters=None, error=None):
        """What that provider's adapter says the next time its `usage` verb is called."""
        blob = {"provider": provider, "meters": meters or [], "error": error}
        (self.fake / f"{HARNESS[provider]}-usage.json").write_text(json.dumps(blob))

    def asked(self, verb="usage"):
        """Every adapter call of that verb so far, as a list."""
        try:
            said = (self.fake / "asked").read_text().split("\n")
        except OSError:
            return []
        return [line for line in said if line.endswith(" " + verb)]

    def rows(self, width=100):
        """The menu's usage block, plain: the heading, then one row per provider."""
        return [terminal.plain(line) for line in menu.usage_lines(self.cfg, width)]

    def refused(self, provider="alpha"):
        """A cache holding one good reading, then one probe the endpoint answered with a 429.

        The probe is a refresh, as the menu's and the tick's are: a minute is inside the
        snapshot's own five, which a plain read is still answered out of.
        """
        usage.collect(self.cfg)
        self.now[0] += usage.PROBE_EVERY
        self.answer(provider, [], "unknown: HTTP 429 from api.example/usage; token may be expired")
        return usage.collect(self.cfg, refresh=True)[provider]

    # --- the cadence ------------------------------------------------------

    def test_a_second_caller_inside_the_cadence_reads_the_cache_and_never_probes(self):
        usage.collect(self.cfg)
        self.assertEqual(len(self.asked()), 2)          # one per provider, and no more
        # Every later caller inside PROBE_EVERY is answered out of the cache: a menu's refresh,
        # `ak usage`, a pick. The tick's refresh is not a licence to probe either.
        self.assertEqual(usage.PROBE_EVERY, 60)
        for step in (0, 1, usage.PROBE_EVERY - 1):
            self.now[0] = NOW + step
            usage.collect(self.cfg)
            usage.collect(self.cfg, refresh=True)
            self.assertEqual(len(self.asked()), 2, step)
        self.now[0] = NOW + usage.PROBE_EVERY
        usage.collect(self.cfg, refresh=True)
        self.assertEqual(len(self.asked()), 4)          # the first caller past the age, and one
        for _ in range(3):
            usage.collect(self.cfg, refresh=True)
        self.assertEqual(len(self.asked()), 4)

    def test_each_provider_is_timed_when_it_is_asked_not_when_the_collection_began(self):
        # alpha's adapter takes 25 seconds, so beta is asked at NOW + 25 and not at NOW: a
        # minute after NOW, alpha is due again and beta has 25 seconds to go.
        real = usage._probe

        def slow(cfg, provider, now):
            out = real(cfg, provider, now)
            self.now[0] += 25 if provider == "alpha" else 0
            return out

        with patch.object(usage, "_probe", side_effect=slow):
            usage.collect(self.cfg)
        self.now[0] = NOW + usage.PROBE_EVERY
        providers = usage.collect(self.cfg, refresh=True)
        self.assertEqual(self.asked(), ["fake usage", "other usage", "fake usage"])
        self.assertEqual(providers["beta"]["probed_at"], NOW + 25)

    def test_nothing_asks_again_inside_the_minute_not_a_refusal_nor_a_lost_snapshot(self):
        usage.collect(self.cfg)
        (config.STATE / "usage.json").unlink()
        usage.collect(self.cfg, refresh=True)
        usage.replenish(self.cfg, "alpha")
        self.assertEqual(len(self.asked()), 2)
        self.now[0] += usage.PROBE_EVERY
        usage.replenish(self.cfg, "alpha")
        self.assertEqual(self.asked()[2:], ["fake usage"])

    def test_two_concurrent_callers_make_one_probe_and_share_its_answer(self):
        (self.fake / "delay").write_text("1")
        readings = []
        start = threading.Barrier(3)

        def caller():
            start.wait(10)
            readings.append(usage.collect(self.cfg)["alpha"]["meters"][0]["used"])

        with ThreadPoolExecutor(max_workers=2) as pool:
            done = [pool.submit(caller), pool.submit(caller)]
            start.wait(10)
            for future in done:
                future.result(30)
        # Two callers, one probe per provider: the second waited on the lock and then found the
        # first one's answer in the cache rather than making a request of its own.
        self.assertEqual(len(self.asked()), 2, self.asked())
        self.assertEqual(readings, [40, 40])

    def test_a_caller_arriving_mid_probe_waits_for_its_answer(self):
        # The first caller has written the minute down and is still asking alpha: the second is
        # inside that minute, and its reading is the first one's answer, not the empty cache.
        (self.fake / "delay").write_text("1")
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(usage.collect, self.cfg)
            deadline = time.monotonic() + 10
            while not self.asked() and time.monotonic() < deadline:
                time.sleep(0.05)
            second = pool.submit(usage.collect, self.cfg)
            readings = [f.result(30)["alpha"]["meters"][0]["used"] for f in (first, second)]
        self.assertEqual(readings, [40, 40])
        cached = json.loads((config.STATE / "usage.json").read_text())
        self.assertEqual(cached["providers"]["alpha"]["meters"][0]["used"], 40)
        self.assertEqual(len(self.asked()), 2)

    # --- a refused probe --------------------------------------------------

    def test_a_rate_limited_probe_keeps_the_last_reading_and_says_rate_limited(self):
        prov = self.refused()
        self.assertEqual([m["used"] for m in prov["meters"]], [40])
        self.assertEqual(prov["fetched_at"], NOW)                   # the reading's own moment
        self.assertEqual(prov["probed_at"], NOW + usage.PROBE_EVERY)   # when it was asked again
        self.assertEqual(prov["probe_failed_at"], NOW + usage.PROBE_EVERY)
        self.assertEqual(prov["stale_since"], NOW + usage.PROBE_EVERY)
        self.assertIn("429", prov["probe_error"])
        self.assertIsNone(prov["error"])         # the refusal is not the reading's own error
        # The row keeps its bar and its percentage, and wears the two words and no age.
        row = self.rows()[1]
        self.assertRegex(row, r"Alpha\s+[█░]+\s+60% left")
        self.assertIn("rate limited", row)
        self.assertNotIn("old", row)
        self.assertNotIn("no login", row)
        self.assertNotIn("?", row)
        # `ak usage` says the same two words under its table.
        rendered = usage.render(self.cfg, usage.collect(self.cfg), ["one", "two"])
        self.assertIn("note: alpha rate limited", rendered)
        # A 5xx and a timeout are the other way a probe is refused, and say `unavailable`.
        for error in ("unknown: HTTP 503 from api.example/usage",
                      "unknown: fake.sh usage timed out after 30s"):
            self.now[0] += usage.PROBE_EVERY
            self.answer("alpha", [], error)
            prov = usage.collect(self.cfg, refresh=True)["alpha"]
            self.assertEqual([m["used"] for m in prov["meters"]], [40])
            self.assertIn("unavailable", self.rows()[1])
            self.assertEqual(prov["stale_since"], NOW + usage.PROBE_EVERY)   # since the first

    def test_no_login_is_said_only_when_the_auth_verb_says_no(self):
        # The line that started this: a 429 whose text mentions a token. Nothing asks `auth`,
        # because the endpoint answered, and the row never reads `no login`.
        self.refused()
        self.assertEqual(self.asked("auth"), [])
        self.assertNotIn("no login", "\n".join(self.rows()))
        # A probe that failed some other way asks, and a yes is not a logout either: the row
        # says the probe was not reached, and the reading it had is kept nowhere to be shown.
        self.now[0] += usage.PROBE_EVERY
        self.answer("alpha", [], "unknown: no fake token (~/.fake/token); run 'fake' to log in")
        prov = usage.collect(self.cfg, refresh=True)["alpha"]
        self.assertEqual(self.asked("auth"), ["fake auth"])   # only the one that failed
        self.assertTrue(prov["logged_in"])
        self.assertEqual(self.rows()[1].split(), ["Alpha", "—", "not", "reached"])
        # And a no is the one thing that puts `no login` on a row.
        (self.fake / "auth-code").write_text("1")
        (self.fake / "auth-line").write_text("no fake token; run 'fake' to log in\n")
        self.now[0] += usage.PROBE_EVERY
        prov = usage.collect(self.cfg, refresh=True)["alpha"]
        self.assertIs(prov["logged_in"], False)
        self.assertEqual(self.rows()[1].split(), ["Alpha", "—", "no", "login"])

    def test_the_picker_ranks_on_the_last_known_budget_after_a_failed_probe(self):
        # alpha has 60% of its week left and beta 40%, in the same window: alpha ranks first,
        # and a rate limit on its meter must not be what hands every run to beta.
        self.refused()
        providers = usage.collect(self.cfg)
        self.assertIsNone(providers["alpha"]["budget_reason"])
        self.assertEqual(usage.pick_order(self.cfg, providers, ["one", "two"], quiet=True),
                         ["one", "two"])
        # Six hours of refusals later nobody can say what it has left, and unknown ranks last.
        self.now[0] = NOW + usage.PROBE_EVERY + usage.PROBE_TRUSTED_FOR + 1
        providers = usage.collect(self.cfg)
        self.assertEqual([m["used"] for m in providers["alpha"]["meters"]], [40])
        self.assertIn("429", providers["alpha"]["budget_reason"])
        self.assertEqual(usage.pick_order(self.cfg, providers, ["one", "two"], quiet=True),
                         ["two", "one"])

    def test_the_week_a_reset_reads_back_ends_the_refusals_before_it(self):
        # Six hours of refusals leave alpha unknown.  A refused worker spends a credit inside
        # the minute, and the week that spend read back is a fresh reading, ranked on at once.
        manifest = self.fake / "fake.toml"
        manifest.write_text("[usage]\nreset = true\n")
        os.utime(manifest, (NOW, NOW))
        answers = {"reset-status": {"available": 2},
                   "reset": {"code": "reset", "available": 1, "weekly_used": 5,
                             "resets_at": NOW + WEEK}}
        self.stack.enter_context(patch.object(usage, "_adapter_json",
                                              side_effect=lambda h, verb, t: answers[verb]))
        self.refused()
        self.now[0] = NOW + usage.PROBE_EVERY + usage.PROBE_TRUSTED_FOR + 1
        self.assertIn("429", usage.collect(self.cfg)["alpha"]["budget_reason"])
        self.assertEqual(usage.replenish(self.cfg, "alpha"), (True, 1.0))
        prov = usage.collect(self.cfg)["alpha"]
        self.assertEqual([m["used"] for m in prov["meters"]], [5])
        self.assertIsNone(prov["budget_reason"])
        self.assertNotIn("probe_error", prov)

    def test_usage_json_carries_the_probe_error_and_when_the_reading_went_stale(self):
        self.refused()
        out = io.StringIO()
        with redirect_stdout(out), patch.object(usage.time, "time", return_value=self.now[0]):
            self.assertEqual(usage.main(["--json"]), 0)
        prov = json.loads(out.getvalue())["providers"]["alpha"]
        self.assertIn("429", prov["probe_error"])
        self.assertEqual(prov["probe_failed_at"], NOW + usage.PROBE_EVERY)
        self.assertEqual(prov["stale_since"], NOW + usage.PROBE_EVERY)
        self.assertEqual(prov["fetched_at"], NOW)
        self.assertIsNone(prov["error"])

    # --- a quota the harness recorded -------------------------------------

    def test_a_recorded_weekly_muse_refusal_renders_spent_with_its_reset(self):
        # alpha's seat is Muse's here: its probe reads 40% used, then a run is refused for the
        # week and adapters/muse.sh writes the quota down.  That record is the reading at once,
        # with no request, and it renders as a probed reading does: spent, and when it resets.
        (config.HOME / config.CONFIG_NAME).write_text(
            CONFIG.replace('"fake"', '"muse"').replace("alpha", "meta"))
        self.cfg = config.load()
        self.answer("meta", [self.meter("weekly", 40)])
        usage.collect(self.cfg)
        resets = NOW + WEEK / 2
        record = config.STATE / "usage-meta.json"
        record.write_text(json.dumps({"meters": [{"name": "quota", "used": 100,
                                                  "resets_at": resets, "window_secs": WEEK}]}))
        os.utime(record, (NOW, NOW))
        when = usage.reset_when({"resets_at": resets}, NOW)
        prov = usage.collect(self.cfg)["meta"]
        self.assertTrue(prov["exhausted"])
        self.assertEqual(prov["meters"][0]["elapsed"], 50.0)
        with patch.object(terminal, "width", return_value=170):
            rendered = usage.render(self.cfg, usage.collect(self.cfg), ["two"])
        self.assertRegex(rendered, rf"\nmeta\s+one\s+0%\s+{when}\s+50%.*exhausted")
        # The menu draws the snapshot its probe thread refreshed, and that holds the record too.
        usage.collect(self.cfg, refresh=True)
        row = self.rows(170)[1]
        self.assertRegex(row, rf"Muse\s+░+\s+0% left · resets {when}$")
        self.assertEqual(len(self.asked()), 2)

    def test_the_lock_is_one_file_per_provider_and_outlives_no_probe(self):
        usage.collect(self.cfg)
        locks = sorted(path.name for path in config.STATE.glob("*-probe.lock"))
        self.assertEqual(locks, ["alpha-probe.lock", "beta-probe.lock"])
        # A lock nothing holds is a lock nothing waits on: the next caller past the age takes it.
        self.now[0] += usage.PROBE_EVERY
        started = time.monotonic()
        usage.collect(self.cfg, refresh=True)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(len(self.asked()), 4)


if __name__ == "__main__":
    unittest.main()
