package config

import (
	"fmt"
	"math/big"
	"path/filepath"
)

// defaultRounds is the review rounds a change has before it goes back to its orchestrator.
const defaultRounds = 3

// roundsMeaning, reviewLines and seatLines mean what Python's config.POLICY says of them, in a
// refusal's words.
const (
	roundsMeaning = "the review rounds a change has before it goes back to its orchestrator to split or re-scope"
	reviewLines   = "the most added lines a first review reads"
	seatLines     = "the added lines a seat's own change stays under"
)

// Rounds is config.toml's `rounds`, Python's config.policy: its default where the file names none.
// load has refused anything under 1; what is left to refuse is a number an int cannot hold.
func Rounds() (int, error) {
	root, err := load()
	if err != nil {
		return 0, err
	}
	number, set := root.get("rounds").(*big.Int)
	if !set {
		return defaultRounds, nil
	}
	if !number.IsInt64() {
		return 0, fmt.Errorf("%s: rounds must be a whole number of at least 1, %s (got %v)",
			filepath.Join(Home(), "config.toml"), roundsMeaning, number)
	}
	return int(number.Int64()), nil
}

// checkPolicy refuses the numbers of config.toml Python's config._policy_in refuses.
func checkPolicy(root *table) error {
	numbers := map[string]*big.Int{}
	for _, number := range []struct {
		key             string
		fallback, floor int64
		meaning         string
	}{
		{"rounds", defaultRounds, 1, roundsMeaning},
		{"review_lines", 300, 1, reviewLines},
		{"seat_lines", 50, 0, seatLines},
	} {
		value, set := root.values[number.key]
		whole, isWhole := value.(*big.Int)
		if !set {
			whole, isWhole = big.NewInt(number.fallback), true
		}
		if !isWhole || whole.Cmp(big.NewInt(number.floor)) < 0 {
			return fmt.Errorf("%s must be a whole number of at least %d, %s (got %s)", number.key, number.floor, number.meaning, valueRepr(value))
		}
		numbers[number.key] = whole
	}
	if numbers["seat_lines"].Cmp(numbers["review_lines"]) > 0 {
		return fmt.Errorf("seat_lines %s, %s, is over review_lines %s, %s", numbers["seat_lines"], seatLines, numbers["review_lines"], reviewLines)
	}
	return nil
}
