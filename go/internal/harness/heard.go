package harness

import "agentkit/internal/config/adapters"

// Heard is the first of that harness's words its own output says for ending (Spent, Refused or
// Outage), "" for none: Python's Harness.outage for Outage, and the word its ran_dry takes for a
// spent window for Spent, whatever else the output says beside it.
func Heard(name string, ending TurnEnding, said string) string {
	kind := adapters.Failures[ending-Spent] // in Ending's order
	if words := heard(name, kind.Key, said, kind.Words); len(words) > 0 {
		return words[0]
	}
	return ""
}
