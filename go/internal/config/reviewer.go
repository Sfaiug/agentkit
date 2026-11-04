package config

import "slices"

// CanReview uses the same restriction for role marks and a run's reviewers: a
// harness that loads the checkout's instructions would review under the branch's rules.
func CanReview(harness string) (bool, error) {
	files, err := Words(harness, "instructions", "workspace")
	return !slices.ContainsFunc(files, func(file string) bool { return file != "" }), err
}
