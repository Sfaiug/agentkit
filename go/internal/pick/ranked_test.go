package pick

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
)

func TestOnlyALineupPlacingAModelOrOneUnreadIsLeftToPython(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	path := filepath.Join(config.Home(), "state", "matrix.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	models := map[string]config.Model{"anvil": {Provider: "acme", ID: "anvil-1", Harness: "claude"}}
	if ranked(models) {
		t.Fatal("no matrix.json is ranked")
	}
	for held, want := range map[string]bool{
		`{"matrix": ["unsupported"]}`:             true,
		`["unsupported"]`:                         true,
		`{"matrix": {"lineup": "x"}}`:             true,
		`{"matrix": {}}`:                          false,
		`{"matrix": {"lineup": [{"yours": []}]}}`: false,
		`{"matrix": {"lineup": [{"yours": [{"harness": "codex", "model": "anvil-1"}]}]}}`:  false,
		`{"matrix": {"lineup": [{"yours": [{"harness": "claude", "model": "anvil-1"}]}]}}`: true,
	} {
		if err := os.WriteFile(path, []byte(held), 0o600); err != nil {
			t.Fatal(err)
		}
		if got := ranked(models); got != want {
			t.Errorf("%s: ranked %v, want %v", held, got, want)
		}
	}
}
