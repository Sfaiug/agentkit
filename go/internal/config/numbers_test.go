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
	if err != nil || numbers != (Numbers{2, AtMost(120), AtMost(20)}) {
		t.Fatalf("%v %v", numbers, err)
	}
	if numbers, err := ProjectNumbers("/acme", declaring(nil)); err != nil || numbers != defaults {
		t.Fatalf("%v %v", numbers, err)
	}
	// review off, no limit and an orchestrator over its executors are all Python's to take
	numbers, err = ProjectNumbers("/acme", declaring(map[string]string{"review_rounds": "0", "executor_lines": "10", "orchestrator_lines": "no limit"}))
	if err != nil || numbers != (Numbers{0, AtMost(10), NoLimit}) {
		t.Fatalf("%v %v", numbers, err)
	}
	for said, want := range map[string]string{
		"abc":      "/acme/AGENTS.md: executor_lines must be a whole number of at least 0 or \"no limit\", " + reviewLines + " (got 'abc')",
		"No limit": "/acme/AGENTS.md: executor_lines must be a whole number of at least 0 or \"no limit\", " + reviewLines + " (got 'No limit')",
		"0":        "/acme/AGENTS.md: executor_lines and orchestrator_lines cannot both be 0: nobody could build a change",
	} {
		_, err := ProjectNumbers("/acme", declaring(map[string]string{"executor_lines": said, "orchestrator_lines": "0"}))
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%s: %v", said, err)
		}
	}
}
