package harness

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/config/adapters"
)

// A TurnEnding is what a turn's own output says of how it ended, Python's harness outcomes.
type TurnEnding int

const (
	Unsaid  TurnEnding = iota // it said none of the words
	Fault                     // the harness never ran the turn
	Quota                     // the account's window is spent, or only rate limited
	Refused                   // the provider declined the turn
	Outage                    // the provider is down
)

// Ending is what a turn's own output says, in its harness's `[stall]` words, and the word that says
// it, as Python's Harness.failure reads it: said is the harness's own, never the model's answer.  In
// a turn that never ran, a fault word outranks the rest, unless an outage word stands beside it;
// otherwise a spent window outranks a refusal, and a refusal an outage.
func Ending(name, said string, ran bool) (TurnEnding, string) {
	heard := func(key string, common []string) []string {
		words, _ := config.Words(name, "stall", key)
		return slices.DeleteFunc(slices.Concat(words, common), func(word string) bool { return !says(said, word) })
	}
	listed := map[string][]string{}
	for _, kind := range adapters.Failures {
		listed[kind.Key] = heard(kind.Key, kind.Words)
	}
	outage := listed["outages"]
	if faults := heard("faults", adapters.Faults); !ran && len(outage) == 0 && len(faults) > 0 {
		return Fault, faults[0]
	}
	for _, each := range []struct {
		ending TurnEnding
		words  []string
	}{{Quota, listed["quotas"]}, {Refused, listed["refusals"]}, {Outage, outage}} {
		if len(each.words) > 0 {
			return each.ending, each.words[0]
		}
	}
	return Unsaid, ""
}
