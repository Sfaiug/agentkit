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
	Lost                      // the harness holds no such conversation to go on
	Fault                     // the harness never ran the turn
	Spent                     // the account's window has run out, or is only limited for now
	Refused                   // the provider declined the turn
	Outage                    // the provider is down
)

// Ending is what a turn's own output says, in its harness's `[stall]` words, and the word that says
// it, as Python's Harness.failure reads it: said is the harness's own, never the model's answer.  A
// `lost` word outranks the rest, as Python's Harness.lost is read first: whatever else a harness
// says that cannot open the conversation is not of the turn.  In a turn that never ran, a fault word
// outranks the others, unless an outage word stands beside it; otherwise the kinds of word are tried
// strongest first.
func Ending(name, said string, ran bool) (TurnEnding, string) {
	heard := func(key string, common []string) []string {
		words, _ := config.Words(name, "stall", key)
		return slices.DeleteFunc(slices.Concat(words, common), func(word string) bool { return !says(said, word) })
	}
	if lost := heard("lost", nil); len(lost) > 0 {
		return Lost, lost[0]
	}
	kinds := make([][]string, len(adapters.Failures))
	for rank, kind := range adapters.Failures {
		kinds[rank] = heard(kind.Key, kind.Words)
	}
	if faults := heard("faults", adapters.Faults); !ran && len(kinds[len(kinds)-1]) == 0 && len(faults) > 0 {
		return Fault, faults[0]
	}
	for rank, words := range kinds {
		if len(words) > 0 {
			return []TurnEnding{Spent, Refused, Outage}[rank], words[0]
		}
	}
	return Unsaid, ""
}
