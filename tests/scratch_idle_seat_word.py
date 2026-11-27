import json, shlex, sys, time
from fixtures import akconfig, fakeadapter
from fixtures.akseat import PANE
from fixtures.akbin import Home
from test_key_usage_return_resumes_every_harness import parked, MODELS
from test_key_a_refill_resumes_waiting_seats_in_the_same_tick import reading
words = {}
for harness in ("muse", "antigravity"):
    with Home() as home:
        akconfig.write(home, [MODELS[harness]])
        adapter = fakeadapter.install(home, **{harness: "pass"})[harness]
        now = time.time()
        seat = parked(home, harness, now)
        seat.show(f"{harness}-prompt-pane.txt")
        path = home.path / f".agentkit/state/seat-{seat.name}.json"
        record = json.loads(path.read_text())
        record["state"] = "at_prompt"
        record["usage_wait"]["continue"] = False
        path.write_text(json.dumps(record))
        adapter.answer("interactive", shlex.join([sys.executable, str(PANE), str(seat.screen_file), str(seat.typed_file)]))
        adapter.answer("usage", json.dumps(reading(now, 10)))
        provider = akconfig.PROVIDER[harness]
        home.write(".agentkit/state/usage.json", {"providers": {provider: {**reading(now, 100), "provider": provider, "resets": 0, "probed_at": now - 3600}}, "fetched_at": now, "reset_checked_at": now})
        home.write(f".agentkit/state/{provider}-probe.lock", repr(now - 3600))
        tick = home.tick()
        state = json.loads(path.read_text())
        words[harness] = (tick.code, len(adapter.calls("interactive")), state["usage_wait"], state["state"], state["word"])
print("harness: (tick exit, relaunches, usage_wait, state, published word)", words)
sys.exit(0 if all(code == 0 and wait is None and word == "idle" for code, _, wait, _, word in words.values()) else 1)
