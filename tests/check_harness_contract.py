"""Live adapter contract: python3 tests/check_harness_contract.py [harness]."""

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from agentkit import config, hand_in, run, usage, worker
from check4_pair import providers


def unavailable(harness, seat=False):
    """Missing binary/login is not coverage; a broken saved login fails."""
    manifest = config.manifest(harness)
    binary = manifest.get("update", {}).get("version", [harness])[0]
    if not config.harness_binary(binary):
        return f"{binary} is not installed", False
    authenticated, why = worker.auth_ok(harness, seat=seat)
    if authenticated is not False:
        return "", False
    missing = re.match(r"^\S+: no (OAuth credentials in |provider key in )?(.+?)"
                       r"(?: and no CLAUDE_CODE_OAUTH_TOKEN| and none saved)?; run ", why)
    settings, keys = False, set()
    if missing and missing[1] == "provider key in ":
        try:
            with open(missing[2]) as fh:
                settings = isinstance(json.load(fh, object_hook=lambda o: keys.update(o) or o),
                                      dict) and "apiKey" not in keys
        except (OSError, ValueError):
            pass
    token = manifest.get("worker_token", {}).get("file")
    broken = (not missing or (os.path.lexists(missing[2]) and not settings)
              or (token and os.path.lexists(config.SECRETS / token)))
    return why, bool(broken)


def spent_until(cfg, model, snapshot, host_home):
    provider = config.model(cfg, model)["provider"]
    read = providers(snapshot)
    record = read.get(provider, {})
    if not usage.model_exhausted(cfg, model, read)[0]:
        if record.get("meters"):
            return ""
        # An empty sandbox read shares the host's cadence, so borrow only the same login's
        # cache, dropping windows already reset. Another subscription cannot answer for it.
        read = providers(Path(host_home) / ".agentkit/state/usage.json")
        record = usage._without_past(read.get(provider, {}), time.time(), "the host cache")
        read[provider] = record
        if not usage.model_exhausted(cfg, model, read)[0]:
            return ""
    meters, _ = usage._gating_meters(cfg, model, read)
    ends = max((m["resets_at"] for m in meters if m.get("exhausted")
                and isinstance(m.get("resets_at"), (int, float))),
               default=record.get("exhausted_until"))
    when = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(ends)) if ends else "unknown"
    return f"{provider} {when}"


def refused(cfg, model, code, out, snapshot):
    if code == 0:
        return ""
    entry = config.model(cfg, model)
    out, snapshot = Path(out), Path(snapshot)
    text = run.tail(out / "final.md" if out.is_dir() else out)
    said = text if not run.answered(text) else ""
    if out.is_dir():
        said += "\n" + run.harness_said(out, text, entry["harness"], failures_only=True)
        if not text.strip():
            said += "\n" + run.harness_said(out, text, entry["harness"])
    word = run.ran_dry(code, said, entry["harness"])
    if not word:
        return ""
    read = providers(snapshot)
    record = read.get(entry["provider"], {})
    now, until = time.time(), run.try_again_at(said)
    if until is None or until <= now:
        until = usage._next_window(record, now) or now + usage.DRY_FOR
    # Keep the refusal in this check's snapshot for later smoke checks, never the host cache.
    read[entry["provider"]] = {**{k: v for k, v in record.items() if k not in usage.MARK},
                                 "exhausted_until": until}
    snapshot.write_text(json.dumps({"providers": read}))
    when = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(until))
    return f"{text.strip() or word}; comes back {when}"


def read_text(path):
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def check(cfg, root, snapshot, host_home, harness=None):
    directory = Path(os.environ.get(config.ADAPTER_DIR_ENV) or REPO / "adapters").expanduser()
    names = [harness] if harness else sorted(p.stem for p in directory.glob("*.toml"))
    passed = failed = skipped = calls = installed = 0

    def report(kind, name, message):
        print(f"{kind}  3 {name}: {message}", flush=True)

    for name in names:
        try:
            why, broken = unavailable(name)
            if why:
                report("FAIL" if broken else "NOT CHECKED", name, why)
                failed += int(broken)
                continue
            installed += 1
            block = config.manifest(name).get("check", {})
            if any(not isinstance(block.get(k), str) or not block[k].strip()
                   for k in ("model", "effort")) or block["model"] == config.DEFAULT_MODEL:
                raise config.Error("adapter .toml needs [check] with an explicit model and effort")
            previous = next((e for e in cfg["models"].values() if e.get("harness") == name
                             and e.get("model") == block["model"]), None)
            previous = previous or next((e for e in cfg["models"].values()
                                         if e.get("harness") == name), {})
            provider = previous.get("provider", name)
            mine = {**cfg, "models": {**cfg["models"], name: {
                "harness": name, "model": block["model"], "effort": block["effort"],
                "provider": provider}}, "providers": {**cfg["providers"],
                provider: cfg["providers"].get(provider, {"mode": "subscription"})}}
            spent = spent_until(mine, name, snapshot, host_home)
            if spent:
                company, _, when = spent.partition(" ")
                report("SKIP", name, f"the {company} subscription window is spent until {when}")
                skipped += 1
                continue
            workspace, out = root / name, root / f"{name}-make"
            workspace.mkdir()
            filename = f"hello-{os.urandom(4).hex()}.txt"
            body = (f"Run: printf 'hello\\n' > {filename}\n"
                    f"Run: {shlex.quote(str(REPO / 'bin/ak'))} hand-in done\nReply DONE.\n")
            report("CHECK", name, f"{block['model']} at {block['effort']}")
            # No build or review instructions: both turns ask only what this contract proves.
            with patch.dict(worker.PREAMBLES, {"executor-scratch": ""}):
                code, final, sid, _, _ = worker.turn(mine, name, body, workspace, out,
                                                     role="executor-scratch")
                refusal = refused(mine, name, code, out, snapshot)
                if refusal:
                    report("SKIP", name, f"was refused: {refusal}")
                    skipped += 1
                    continue
                closing = hand_in.read(out / "hand-in.jsonl")
                missing = []
                if code:
                    missing.append(f"adapter exited {code}")
                if read_text(workspace / filename) != "hello\n":
                    missing.append("file did not match the prompt")
                if not final.strip():
                    missing.append("final.md is empty")
                if not closing or not closing.done:
                    missing.append("no checked hand-in done")
                if not read_text(out / "session_id").strip():
                    missing.append("no session_id")
                if missing:
                    report("FAIL", name, "; ".join(missing))
                    failed += 1
                    continue
                calls += 1
                # Recall must come from the resumed conversation, not a listing of the workspace.
                (workspace / filename).unlink()
                out = root / f"{name}-recall"
                code, final, _, _, _ = worker.turn(
                    mine, name, "What file did you just create? Reply with the filename only.\n",
                    workspace, out, role="executor-scratch", session=sid)
            refusal = refused(mine, name, code, out, snapshot)
            if refusal:
                report("SKIP", name, f"resume was refused: {refusal}")
                skipped += 1
            elif code or final.strip() != filename:
                report("FAIL", name, f"resume exited {code}; final.md = {final[:120]!r}")
                failed += 1
            else:
                report("PASS", name, "wrote the file, handed in done, returned final.md and "
                       "session_id, resumed and recalled the file")
                passed += 1
                calls += 1
        except (config.Error, worker.LoginExpired, OSError, ValueError) as exc:
            report("FAIL", name, str(exc))
            failed += 1
    if not installed:
        print("FAIL  3: no harness here is installed with its login; the check needs one", flush=True)
        failed += 1
    return passed, failed, skipped, calls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("harness", nargs="?")
    parser.add_argument("--snapshot", type=Path, default=config.STATE / "usage.json")
    parser.add_argument("--counts", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    host_home = os.environ.get("SMOKE_CALLER_HOME") or Path.home()
    with tempfile.TemporaryDirectory(prefix=".ak-test-contract-", dir=REPO) as tmp:
        root = Path(tmp)
        snapshot = args.snapshot
        if not args.counts:
            # A standalone check owns its refusal snapshot too.
            snapshot = root / "usage.json"
            snapshot.write_text(json.dumps({"providers": providers(args.snapshot)}))
        counts = check(config.load(), root, snapshot, host_home, args.harness)
    passed, failed, skipped, calls = counts
    if args.counts:
        args.counts.write_text(" ".join(map(str, counts)) + "\n")
    else:
        print(f"{passed} passed, {failed} failed, {skipped} skipped")
        if skipped and not calls:
            print("acceptance: INCOMPLETE; skipped coverage was not exercised")
    return 1 if failed else 2 if skipped and not calls and os.environ.get(
        "AGENTKIT_ACCEPTANCE_REQUIRED") == "1" else 0


if __name__ == "__main__":
    sys.exit(main())
