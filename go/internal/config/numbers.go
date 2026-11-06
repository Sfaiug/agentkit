package config

import (
	"fmt"
	"math/big"
	"path/filepath"
	"regexp"
)

// DefaultReviewLines is ak's own first-review ceiling.
const DefaultReviewLines = 300

var wholeNumber = regexp.MustCompile(`^[0-9]+$`)

// The numbers a run holds to, Python's config.policy: Rounds 0 is review off.
type Numbers struct {
	Rounds                 int
	ReviewLines, SeatLines Lines
}

// HostNumbers is config.toml's numbers, ak's default for one it does not name, Python's
// host_policy: the home file's own, whatever its other tables hold.
func HostNumbers() (Numbers, error) {
	_, numbers, err := homeFile()
	return numbers, err
}

// ProjectNumbers is the numbers in force for the checkout whose default branch declares what
// `declared` answers, "" for none, over the host's, refused naming its AGENTS.md as Python's
// _policy_in refuses them: front matter is text, a whole number where it is all digits.
func ProjectNumbers(checkout string, declared func(string) string) (Numbers, error) {
	numbers, err := HostNumbers()
	if err != nil {
		return numbers, err
	}
	numbers, err = policyIn(func(key string) (any, bool) {
		said := declared(key)
		if number, whole := new(big.Int).SetString(said, 10); whole && wholeNumber.MatchString(said) {
			return number, true
		}
		return said, said != ""
	}, numbers)
	if err != nil {
		return numbers, fmt.Errorf("%s: %w", filepath.Join(checkout, "AGENTS.md"), err)
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
