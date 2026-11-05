package config

import (
	"os"
	"path/filepath"
	"testing"
)

// A number the host sets reaches ak's words, and only ak's placeholders are read.
func TestInForce(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	const words = "$Review_rounds review round$s, ${executor_lines} lines, $orchestrator_lines yours, not $one_over; $$review_rounds $other $"
	if got, want := InForce(words), "Three review rounds, 300 lines, 50 yours, not a fourth; $review_rounds $other $"; got != want {
		t.Errorf("%q, want %q", got, want)
	}
}

// Review off says each budget line whole as no review, and no limit says none, as Python does.
func TestInForceSaysReviewOffAndNoLimit(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	os.MkdirAll(Home(), 0o700)
	os.WriteFile(filepath.Join(Home(), "config.toml"), []byte("review_rounds = 0\nexecutor_lines = 'no limit'\n"), 0o600)
	const words = "- $Review_rounds review round$s is the budget; ak refuses $one_over.\n$run_budget\nSize: $executor_size; $executor_lines.\n"
	want := "- No review: a change lands on its checks; no reviewer.\nNo review: a change lands on its checks; no reviewer.\n" +
		"Size: no limit on added lines, tests included; no limit.\n"
	if got := InForce(words); got != want {
		t.Errorf("%q, want %q", got, want)
	}
}
