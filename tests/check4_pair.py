"""Check 4's `executor reviewer`, as ak would pick them now; nothing when all it can run are spent.

tests/smoke.sh asks this before check 4 takes a smoke target, so its one real `ak run` goes on
whichever configured models have budget and names none.  The pick is ak's own, `run.pick_models`
over every model the config offers, on the suite's usage snapshot, each provider on the usual
login the sandbox borrows and each harness asked whether it can run here.  When this host can
run no model at all, it says why and exits 3: the host lacks them.  A provider that snapshot
knows nothing of -- the host asked inside the shared probe cadence -- reads as the host's own
cache, as `spent_until` reads it.

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
    if all(usage.model_exhausted(cfg, name, read)[0] for name in offered):
        return
    ready = usage.readiness(cfg, usage.Readings(read))
    try:
        print(*run.pick_models(cfg, ready, None, None, None, quiet=True, workers=offered))
    except run.QuotaDry:
        # A host that can run some model has them all spent, which holds the gate as any spent
        # window does; only one that can run none lacks something.
        why = [usage.unready(cfg, name, ready) for name in offered]
        if all(why):
            print("; ".join(dict.fromkeys(why)))
            sys.exit(3)


if __name__ == "__main__":
    main(*sys.argv[1:])
