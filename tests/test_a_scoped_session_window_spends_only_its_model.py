"""A full 5h window its provider names for one model spends that model alone.

The seat choice (`model_spent`), the new-session screen (`spent_meter`) and the credits rank
(`on_credits`) read the same meters the pick does: a session window scoped to Fable neither stops
Opus nor puts it on credits, nor one scoped to Opus a Fable naming its own weekly `meter`, while
one naming no scope stops every model of the subscription, a model naming its `meter` too.
"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import usage

MODELS = {"opus": "acme-opus-5-5", "fable": "acme-fable-5-2"}


def spent(name, scope=None, meter=None, credits=None):
    """(model_spent, spent_meter, on_credits) for `name` beside a full 5h window in `scope`."""
    models = {n: {"harness": "claude", "model": m, "effort": "high", "provider": "acme"}
              for n, m in MODELS.items()}
    if meter:
        models[name]["meter"] = meter
    window = {"name": "session", "used": 100, "window_secs": usage.SESSION_SECS,
              "resets_at": 4102444800, "exhausted": True, **({"scope": scope} if scope else {})}
    prov = {"meters": [window], **({"credits": credits} if credits else {})}
    cfg, providers = {"models": models, "providers": {"acme": {}}}, {"acme": prov}
    return (usage.model_spent(cfg, name, providers)[0], usage.spent_meter(cfg, name, providers),
            usage.on_credits(cfg, name, providers))


class ScopedSessionCap(unittest.TestCase):
    def test_a_window_scoped_to_fable_leaves_opus_alone(self):
        self.assertEqual(spent("opus", scope="Fable"), (False, None, False))
        self.assertFalse(spent("opus", scope="Fable", credits=1)[2])

    def test_a_window_scoped_to_fable_spends_fable(self):
        done, worst, _ = spent("fable", scope="Fable")
        self.assertTrue(done)
        self.assertEqual(worst["name"], "session")
        self.assertTrue(spent("fable", scope="Fable", credits=1)[2])

    def test_a_window_scoped_to_opus_leaves_a_model_naming_its_meter_alone(self):
        self.assertEqual(spent("fable", scope="Opus", meter="weekly_scoped"), (False, None, False))
        self.assertFalse(spent("fable", scope="Opus", meter="weekly_scoped", credits=1)[2])

    def test_a_window_naming_no_scope_spends_every_model(self):
        for name in MODELS:
            for meter in (None, "weekly_own"):
                with self.subTest(name=name, meter=meter):
                    done, worst, _ = spent(name, meter=meter)
                    self.assertTrue(done)
                    self.assertEqual(worst["name"], "session")


if __name__ == "__main__":
    unittest.main()
