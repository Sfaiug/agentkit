package config

import (
	"fmt"
	"math/big"
	"path/filepath"
	"regexp"
	"strconv"
)

// DefaultReviewLines is ak's own first-review ceiling, which the rules Go carries say.
const DefaultReviewLines = 300

var wholeNumber = regexp.MustCompile(`^[0-9]+$`)

// The numbers a run holds to, Python's config.policy.
type Numbers struct{ Rounds, ReviewLines, SeatLines int }

// HostNumbers is config.toml's numbers, ak's default for one it does not name; load has refused
// what is out of range.
func HostNumbers() (Numbers, error) {
	root, err := load()
	if err != nil {
		return Numbers{}, err
	}
	rounds, err := Rounds()
	if err != nil {
		return Numbers{}, err
	}
	number := func(key string, fallback int) int {
		if value, set := root.get(key).(*big.Int); set && value.IsInt64() {
			return int(value.Int64())
		}
		return fallback
	}
	return Numbers{rounds, number("executor_lines", DefaultReviewLines), number("orchestrator_lines", 50)}, nil
}

// ProjectNumbers is the numbers in force for the checkout whose default branch declares what
// `declared` answers, "" for none, over the host's, refused naming its AGENTS.md as Python's
// _policy_in refuses them.
func ProjectNumbers(checkout string, declared func(string) string) (Numbers, error) {
	numbers, err := HostNumbers()
	if err != nil {
		return numbers, err
	}
	path := filepath.Join(checkout, "AGENTS.md")
	for _, each := range []struct {
		key     string
		value   *int
		floor   int
		meaning string
	}{
		{"review_rounds", &numbers.Rounds, 1, roundsMeaning},
		{"executor_lines", &numbers.ReviewLines, 1, reviewLines},
		{"orchestrator_lines", &numbers.SeatLines, 0, seatLines},
	} {
		said := declared(each.key)
		if said == "" {
			continue
		}
		shown := "'" + said + "'"
		if wholeNumber.MatchString(said) {
			shown = said
			if parsed, err := strconv.Atoi(said); err == nil && parsed >= each.floor {
				*each.value = parsed
				continue
			}
		}
		return numbers, fmt.Errorf("%s: %s must be a whole number of at least %d, %s (got %s)", path, each.key, each.floor, each.meaning, shown)
	}
	if numbers.SeatLines > numbers.ReviewLines {
		return numbers, fmt.Errorf("%s: orchestrator_lines %d, %s, is over executor_lines %d, %s", path, numbers.SeatLines, seatLines, numbers.ReviewLines, reviewLines)
	}
	return numbers, nil
}

// ReadLimit is the most of a project's AGENTS.md every harness reads on its own and whose limit
// it is, Python's instruction_ceiling: 0 where no manifest declares one.
func ReadLimit() (int, string) {
	found, err := manifests()
	if err != nil {
		return 0, ""
	}
	least, whose := 0, ""
	for harness, manifest := range found {
		block, _ := manifest.get("instructions").(*table)
		if block == nil {
			continue
		}
		limit, _ := block.get("read_limit").(*big.Int)
		if limit == nil || limit.Sign() < 1 || !limit.IsInt64() {
			continue
		}
		if value := int(limit.Int64()); least == 0 || value < least || value == least && harness < whose {
			least, whose = value, harness
		}
	}
	return least, whose
}
