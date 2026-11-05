package harness

import (
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/config/adapters"
)

// Refusal is whether a seat's error says its window refused the turn, in its harness's `[stall]
// quotas` words, and whether only for a rate limit: as Python's Harness.failure tells LIMITED from
// SPENT, where every one of them it says is a rate limit.
func Refusal(name, said string) (refused, limited bool) {
	words, _ := config.Words(name, "stall", adapters.Failures[0].Key)
	heard := slices.DeleteFunc(slices.Concat(words, adapters.Failures[0].Words), func(word string) bool { return !says(said, word) })
	return len(heard) > 0, !slices.ContainsFunc(heard, func(word string) bool { return !Limited(word) })
}
