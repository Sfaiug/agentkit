package harness

import "agentkit/internal/config/adapters"

// Heard is the first of that harness's words of a kind adapters.Failures names (`quotas`,
// `outages`) its own output says, "" for none: Python's Harness.outage for `outages`, and the
// word its ran_dry takes for a spent window for `quotas`, whatever else the output says beside it.
func Heard(name, key, said string) string {
	for _, kind := range adapters.Failures {
		if kind.Key != key {
			continue
		}
		if words := heard(name, key, said, kind.Words); len(words) > 0 {
			return words[0]
		}
	}
	return ""
}
