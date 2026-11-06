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
	// an old name is refused beside its new one too, and both builders off however the host and the
	// project share it
	for _, example := range []struct {
		host string
		said map[string]string
		want string
	}{
		{"", map[string]string{"seat_lines": "10", "orchestrator_lines": "10"}, "use orchestrator_lines instead of seat_lines"},
		{"executor_lines=0\n", map[string]string{"orchestrator_lines": "0"}, "executor_lines and orchestrator_lines cannot both be 0: nobody could build a change"},
		{"orchestrator_lines=0\n", map[string]string{"executor_lines": "0"}, "executor_lines and orchestrator_lines cannot both be 0: nobody could build a change"},
	} {
		if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(example.host), 0o600); err != nil {
			t.Fatal(err)
		}
		_, err := ProjectNumbers("/acme", declaring(example.said))
		if want := filepath.Join("/acme", "AGENTS.md") + ": " + example.want; err == nil || err.Error() != want {
			t.Errorf("%v: %v, want %s", example.said, err, want)
		}
	}
}
