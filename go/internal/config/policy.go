package config

import (
	"errors"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
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
	{"executor_lines", 0, reviewLines},
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
	if read[1] == AtMost(0) && read[2] == AtMost(0) {
		return over, errors.New("executor_lines and orchestrator_lines cannot both be 0: nobody could build a change")
	}
	rounds, _ := read[0].Most() // never "no limit": only a line limit takes that
	return Numbers{rounds, read[1], read[2]}, nil
}

// limits is the numbers in policy's order, the rounds as the limit they are.
func (n Numbers) limits() [3]Lines { return [3]Lines{AtMost(n.Rounds), n.ReviewLines, n.SeatLines} }

// homeFile is config.toml as the home holds it, empty where there is none, and the numbers it
// names over ak's defaults (Python's host_policy), refused naming it where it does not read or a
// number is out of range: what its other tables hold is load's to judge.
func homeFile() (*table, Numbers, error) {
	path := filepath.Join(Home(), "config.toml")
	data, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		return nil, Numbers{}, fmt.Errorf("cannot read %s: %w", path, err)
	}
	root, err := parseDocument(string(data))
	if err != nil {
		return nil, Numbers{}, fmt.Errorf("%s: %w", path, err)
	}
	renamePolicy(root)
	numbers, err := policyIn(func(key string) (any, bool) {
		value, set := root.values[key]
		return value, set
	}, defaults)
	if err != nil {
		return nil, Numbers{}, fmt.Errorf("%s: %w", path, err)
	}
	return root, numbers, nil
}

// Recorded is the numbers a run's record holds, as given names them, ak's default for one it
// names none of.
func Recorded(given func(key string) (any, bool)) (Numbers, error) {
	return policyIn(given, defaults)
}
