"""Check 4's pair, `executor reviewer`, as ak would pick them now; nothing when every one is spent.

tests/smoke.sh asks this before check 4 takes a smoke target, so its one real `ak run` goes on
whichever configured models have budget and names none.  The pick is ak's own, `run.pick_models`
over every model the config offers, on the suite's usage snapshot, each provider on the usual
login the sandbox borrows and each harness asked whether it can run here.  When models have an
open window and none of them can run here, it says why and exits 3: the host lacks them.  A provider that snapshot knows nothing of -- the host asked
inside the shared probe cadence -- reads as the host's own cache, as `spent_until` reads it.

    python3 tests/check4_pair.py <the suite's usage.json> <the host's usage.json>
"""

import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentkit import config, run, usage


def providers(path):
    """The providers a usage snapshot holds, each the usual login's; {} when it says nothing."""
    try:
        read = json.loads(Path(path).read_text())["providers"]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    read = read if isinstance(read, dict) else {}
    for name, record in read.items():
        if isinstance(record, dict) and isinstance(record.get("accounts"), dict):
            read[name] = record["accounts"].get(config.DEFAULT_ACCOUNT)
    return {name: record for name, record in read.items() if isinstance(record, dict)}


def main(suite, host):
    cfg, read, now = config.load(), providers(suite), time.time()
    for name, record in providers(host).items():
        mine = read.get(name, {})
        # The suite's read stands where it measured something or holds a refusal still ahead.
        if not mine.get("meters") and not (usage._number(mine.get("exhausted_until")) or 0) > now:
            read[name] = usage._without_past(record, now, "the host cache")
    offered = config.offered(cfg)
    unspent = [name for name in offered if not usage.model_exhausted(cfg, name, read)[0]]
    if not unspent:
        return
    ready = usage.readiness(cfg, usage.Readings(read))
    try:
        print(*run.pick_models(cfg, ready, None, None, None, quiet=True, workers=offered))
    except run.QuotaDry:
        # every model with an open window has a harness that cannot run here
        print("; ".join(dict.fromkeys(usage.unready(cfg, name, ready) for name in unspent)))
        sys.exit(3)


if __name__ == "__main__":
    main(*sys.argv[1:])
