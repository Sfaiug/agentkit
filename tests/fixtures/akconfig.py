"""The config.toml an answer-key Home's ak reads: the models it may run, each on a harness and a
provider, and which of them orchestrate and work.

A Home starts with the shipped config.default.toml.  `write` replaces it with one naming only
the models a test gives, so ak can pick no other.  A model the shipped config names keeps its
entry there, a test's keys over it; any other name is its own model id on the harness given,
at effort `high`, on that harness's shipped provider.  Each provider named gets its shipped
table, else `mode = "subscription"`.  The audit is off unless `audit=True`: on, a tick opens
an audit seat by itself.

    from fixtures.akbin import Home
    from fixtures import akconfig
    with Home() as home:
        akconfig.write(home, {"opus": "claude", "beta": {"harness": "codex", "effort": "low"}},
                       workers=["beta"], providers={"openai": {"mode": "payg"}})
        assert akconfig.read(home)["models"]["beta"]["provider"] == "openai"
"""

import json
from pathlib import Path
import tomllib

SHIPPED_CONFIG = Path(__file__).resolve().parents[2] / "config.default.toml"
_SHIPPED = tomllib.loads(SHIPPED_CONFIG.read_text())
SHIPPED = _SHIPPED["models"]               # name -> its [models.<name>] table as shipped
PROVIDER = {entry["harness"]: entry["provider"] for entry in reversed(SHIPPED.values())}


def write(home, models, *, workers=None, orchestrator=None, providers=None, settings=None,
          audit=False, extra=""):
    """Write HOME/.agentkit/config.toml and return its path.  `models` maps a name to its
    harness or to keys of its table, or is a list of shipped names; `workers` (all of them
    unless given) and `orchestrator` (the first unless given) are [defaults]; `providers` maps
    a provider to its table's keys; `settings` are top-level keys; `extra` is TOML appended."""
    models = {name: {} for name in models} if isinstance(models, (list, tuple)) else models
    tables = {}
    for name, spec in models.items():
        entry = {**SHIPPED.get(name, {}), **({"harness": spec} if isinstance(spec, str) else spec)}
        entry.setdefault("model", name)
        entry.setdefault("effort", "high")
        entry.setdefault("provider", PROVIDER.get(entry["harness"], "acme"))
        tables[f"models.{json.dumps(name)}"] = entry
    named = {entry["provider"]: None for entry in tables.values()} | dict(providers or {})
    for provider, keys in named.items():
        tables[f"providers.{json.dumps(provider)}"] = (
            keys if keys is not None else
            _SHIPPED["providers"].get(provider, {"mode": "subscription"}))
    if not audit:
        tables["audit"] = {"on": False}
    defaults = {"orchestrator": orchestrator or next(iter(models)),
                "workers": list(models) if workers is None else workers}
    text = _keys(settings or {}) + "\n[defaults]\n" + _keys(defaults)
    for table, keys in tables.items():
        text += f"\n[{table}]\n" + _keys(keys)
    path = home.path / ".agentkit" / "config.toml"
    path.write_text(text + (f"\n{extra.strip()}\n" if extra else ""))
    return path


def read(home):
    """The config ak reads now, parsed."""
    return tomllib.loads((home.path / ".agentkit" / "config.toml").read_text())


def _keys(table):
    # A JSON string, number, boolean or list of them is the same value written in TOML.
    return "".join(f"{key} = {json.dumps(value)}\n" for key, value in table.items())
