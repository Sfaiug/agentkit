package logins

import (
	"cmp"

	"agentkit/internal/config"
)

// Harness is the harness that asks and signs in sub's logins, Python's logins.harness: its first
// model's, else the one the shipped default runs it on, so a login whose models were all removed is
// still asked; "" where neither names one.
func Harness(sub config.Subscription) string {
	return cmp.Or(sub.Harness, config.ShippedHarness(sub.Name))
}
