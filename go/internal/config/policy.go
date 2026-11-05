package config

import (
	"fmt"
	"math/big"
	"strings"
)

// defaultRounds is the review rounds a change has before it goes back to its orchestrator.
const defaultRounds = 3

// roundsMeaning, reviewLines and seatLines mean what Python's config.POLICY says of them, in a
// refusal's words.
const (
	roundsMeaning = "the review rounds a change has before it goes back to its orchestrator to split or re-scope"
	reviewLines   = "the most added lines a first review reads"
	seatLines     = "the most added lines an orchestrator builds"
)

// policy is Python's config.POLICY: each number's key, its floor and what it means, in the order
// of Numbers.limits.
var policy = []struct {
	key     string
	floor   int64
	meaning string
}{
	{"review_rounds", 0, roundsMeaning},
	{"executor_lines", 1, reviewLines},
	{"orchestrator_lines", 0, seatLines},
}

// defaults is ak's own numbers, in force where nothing names one.
var defaults = Numbers{defaultRounds, AtMost(DefaultReviewLines), AtMost(50)}

// policyIn is the numbers given names, those of over where it names none, refused as Python's
// config._policy_in refuses them: a whole number at the floor or above, or a line limit's
// "no limit".  A number an int cannot hold Go refuses too.
func policyIn(given func(key string) (any, bool), over Numbers) (Numbers, error) {
	read := over.limits()
	for i, number := range policy {
		value, set := given(number.key)
		if !set {
			continue
		}
		if held, isInt := value.(int); isInt {
			value = big.NewInt(int64(held))
		}
		unlimited := ""
		if _, text := value.(string); text && strings.HasSuffix(number.key, "_lines") {
			unlimited = ` or "no limit"`
		}
		whole, isWhole := value.(*big.Int)
		switch {
		case unlimited != "" && value == noLimit:
			read[i] = NoLimit
		case isWhole && whole.Cmp(big.NewInt(number.floor)) >= 0 && whole.IsInt64():
			read[i] = AtMost(int(whole.Int64()))
		default:
			return over, fmt.Errorf("%s must be a whole number of at least %d%s, %s (got %s)", number.key, number.floor, unlimited, number.meaning, valueRepr(value))
		}
	}
	rounds, _ := read[0].Most() // never "no limit": only a line limit takes that
	return Numbers{rounds, read[1], read[2]}, nil
}

// limits is the numbers in policy's order, the rounds as the limit they are.
func (n Numbers) limits() [3]Lines { return [3]Lines{AtMost(n.Rounds), n.ReviewLines, n.SeatLines} }

// hostPolicy is the numbers config.toml's own root names, over ak's defaults.
func hostPolicy(root *table) (Numbers, error) {
	return policyIn(func(key string) (any, bool) {
		value, set := root.values[key]
		return value, set
	}, defaults)
}

// Recorded is the numbers a run's record holds, as given names them, ak's default for one it
// names none of.
func Recorded(given func(key string) (any, bool)) (Numbers, error) {
	return policyIn(given, defaults)
}
