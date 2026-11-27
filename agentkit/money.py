"""Where a plan's price a month in a currency comes from: first what config.toml keeps for that
currency, provider and plan under `[money.paid.<currency>.<provider>]`; else the `price` on its
provider's table in the config where it is one number (the owner's own word in what they pay in);
else the plan's list price before tax on the manifest table of that currency (`TABLES`) of the
harness that asks the provider's logins.  No price is ever converted from another currency: a plan
none of these holds in that currency has none.
"""

import decimal
import math
import re

from . import config, logins

# Each currency `[money] currency` may name, and the table of a harness's manifest holding each
# plan its `login-end` names at its list price a month in that currency before tax.
TABLES = {"USD": "plans", "EUR": "plans_eur"}
MAX_PRICE = 1_000_000


def currency(cfg):
    """`[money] currency` of `cfg`, USD where it names none; config.load refuses any other."""
    return cfg.get("money", {}).get("currency", "USD")


def typed(cfg, provider, plan, paid="USD"):
    """The price kept in `[money.paid.<currency>.<provider>]` for one login of `provider` on
    `plan` in `paid`, or None where none is kept."""
    table = cfg.get("money")
    for key in ("paid", paid, provider):
        table = table.get(key) if isinstance(table, dict) else None
    return _price(table.get(plan), positive=True) if isinstance(table, dict) else None


def parse(text):
    """`text` as a price a month: digits, with at most two more after one `.`, above zero and at
    most MAX_PRICE, int where whole else float; None for anything else."""
    if not isinstance(text, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", text):
        return None
    value = decimal.Decimal(text)
    if not (0 < value <= MAX_PRICE):
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def price(cfg, provider, plan, paid="USD"):
    """What one login of `provider` on `plan` costs a month in `paid`, or None: the price kept
    for it in `paid` (`typed`), else the provider's own numeric `price` in `cfg` (never a `price`
    table by login, as usage is kept by plan), else the plan's list price in `paid` on the
    manifest of the harness that asks its logins."""
    given = typed(cfg, provider, plan, paid)
    if given is not None:
        return given
    table = (cfg.get("providers") or {}).get(provider)
    own = _price(table.get("price")) if isinstance(table, dict) else None
    if own is not None:
        return own
    listed = config.manifest(logins.harness(cfg, provider)).get(TABLES[paid])
    return _price(listed.get(plan)) if isinstance(listed, dict) else None


def month(cfg, plans):
    """`ak models --json`'s `money`: `currency`, and what one login of each plan of each provider
    `plans` ({provider: {plan: ...}}) names costs a month in it."""
    paid = currency(cfg)
    return {"currency": paid, "month": {
        provider: {plan: price(cfg, provider, plan, paid) for plan in found}
        for provider, found in plans.items()}}


def _price(value, *, positive=False):
    """`value`, as the table holds it, when it is a finite number (no boolean) up to MAX_PRICE,
    at least 0 or above 0 with `positive`, else None."""
    ok = (lambda n: 0 < n <= MAX_PRICE) if positive else (lambda n: 0 <= n <= MAX_PRICE)
    if type(value) is int:
        return value if ok(value) else None
    if isinstance(value, float) and math.isfinite(value) and ok(value):
        return value
    return None
