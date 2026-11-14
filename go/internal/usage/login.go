package usage

import (
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/logins"
)

const lowFloor = 5.0 // points of room under which a meter runs low whatever its drain, Python's LOW_FLOOR

// auth is what the adapter's `auth` verb says of that login of the provider, "" for its one, as
// Python's worker.auth_ok asks it outside a run: unmarked, as a probe is nobody's to sweep.
func auth(adapter, provider, account string) (answered, yes bool) {
	env, _ := config.ChildEnv()
	var told []string
	for _, pair := range env {
		if !strings.HasPrefix(pair, host.Marker+"=") {
			told = append(told, pair)
		}
	}
	answered, yes, _ = logins.Auth(adapter, append(told, config.AccountEnv(account), "AGENTKIT_PROVIDER="+provider))
	return answered, yes
}

// low is whether a meter gating that model has less room than lowFloor, or than its drain so far
// eats until ak reads it again, in its provider's probe cadence: Python's usage.model_low.
func (r *Readings) low(name string) bool {
	every := cadence(r.models[name].Provider)
	meters, _ := r.gating(name)
	for _, meter := range meters {
		spent, known := number(meter.Get("used"))
		elapsed, _ := number(meter.Get("elapsed"))
		window, _ := number(meter.Get("window_secs"))
		floor := lowFloor
		if elapsed > 0 && window > 0 {
			floor = max(floor, spent/(elapsed/100*window)*every)
		}
		if known && 100-spent < floor {
			return true
		}
	}
	return false
}

// cadence is how long one ask of that provider's adapter answers for, in seconds, Python's
// usage._probe_every: its harness's `[usage] probe_every`, else probeEvery.
func cadence(provider string) float64 {
	subs, _ := config.Subscriptions()
	for _, sub := range subs {
		if sub.Name != provider {
			continue
		}
		if facts, err := config.Usage(sub.Harness); err == nil && facts.ProbeEvery > 0 {
			return facts.ProbeEvery
		}
	}
	return probeEvery
}
