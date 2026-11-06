package harness

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/config/adapters"
)

// Refusal is whether a seat's error says its window refused the turn, in the words its harness's
// `[stall]` table and every harness's failures use for a spent window, and whether only for now:
// as Python's Harness.failure tells LIMITED from SPENT, where each of them it says is one Limited
// reads.
func Refusal(name, said string) (refused, limited bool) {
	words, _ := config.Words(name, "stall", adapters.Failures[0].Key)
	heard := slices.DeleteFunc(slices.Concat(words, adapters.Failures[0].Words), func(word string) bool { return !says(said, word) })
	return len(heard) > 0, !slices.ContainsFunc(heard, func(word string) bool { return !Limited(word) })
}
