package config

import "testing"

// A number the host sets reaches ak's words, and only ak's placeholders are read.
func TestInForce(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	const words = "$Review_rounds review round$s, ${executor_lines} lines, $orchestrator_lines yours, not $one_over; $$review_rounds $other $"
	if got, want := InForce(words), "Three review rounds, 300 lines, 50 yours, not a fourth; $review_rounds $other $"; got != want {
		t.Errorf("%q, want %q", got, want)
	}
}
