import json, shlex, sys, time
from fixtures import akconfig, fakeadapter
from fixtures.akseat import FIXTURES, PANE
from fixtures.akbin import Home
from test_key_usage_return_resumes_every_harness import parked, ACCOUNT_LINE
from test_key_a_refill_resumes_waiting_seats_in_the_same_tick import reading
with Home() as home:
    akconfig.write(home, ["spark"])
    adapter = fakeadapter.install(home, muse="pass")["muse"]
    now = time.time()
    seat = parked(home, "muse", now)
    asks = home.write("muse-asks.json", {ACCOUNT_LINE[:20]: (FIXTURES / "muse-working-pane.txt").read_text()})
    adapter.answer("interactive", shlex.join([sys.executable, str(PANE), str(FIXTURES / "muse-prompt-pane.txt"), str(seat.typed_file), "❯", str(asks)]))
    adapter.answer("usage", json.dumps(reading(now, 10)))
    provider = akconfig.PROVIDER["muse"]
    home.write(".agentkit/state/usage.json", {"providers": {provider: {**reading(now, 100), "provider": provider, "resets": 0, "probed_at": now - 3600}}, "fetched_at": now, "reset_checked_at": now})
    home.write(f".agentkit/state/{provider}-probe.lock", repr(now - 3600))
    tick = home.tick()
    state = json.loads((home.path / f".agentkit/state/seat-{seat.name}.json").read_text())
    landed, shown = seat.lines() == [ACCOUNT_LINE], "Thinking" in seat.capture()
    print("tick", tick.code, "line landed", landed, "pane working", shown, "usage_wait", state["usage_wait"], "word", state["word"], "state", state["state"])
    sys.exit(0 if tick.code == 0 and landed and shown and state["usage_wait"] is None and state["word"] == "working" else 1)
