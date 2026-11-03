package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAProjectsNumbersHoldOverTheHostsAndABadOneIsRefusedNamingItsFile(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(filepath.Join(home, ".agentkit"), 0o777); err != nil {
		t.Fatal(err)
	}
	declaring := func(said map[string]string) func(string) string {
		return func(key string) string { return said[key] }
	}
	numbers, err := ProjectNumbers("/acme", declaring(map[string]string{"review_rounds": "2", "executor_lines": "120", "orchestrator_lines": "20"}))
	if err != nil || numbers != (Numbers{2, 120, 20}) {
		t.Fatalf("%v %v", numbers, err)
	}
	if numbers, err := ProjectNumbers("/acme", declaring(nil)); err != nil || numbers != (Numbers{defaultRounds, DefaultReviewLines, 50}) {
		t.Fatalf("%v %v", numbers, err)
	}
	for said, want := range map[string]string{
		"abc": "/acme/AGENTS.md: executor_lines must be a whole number of at least 1, " + reviewLines + " (got 'abc')",
		"0":   "/acme/AGENTS.md: executor_lines must be a whole number of at least 1, " + reviewLines + " (got 0)",
		"10":  "/acme/AGENTS.md: orchestrator_lines 50, " + seatLines + ", is over executor_lines 10, " + reviewLines,
	} {
		_, err := ProjectNumbers("/acme", declaring(map[string]string{"executor_lines": said}))
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%s: %v", said, err)
		}
	}
}
