package loop

import (
	"os"
	"path/filepath"
	"testing"
)

// A model the model list turned off cannot run here for that, before its harness is asked: one
// not installed says only that it is off.
func TestAModelOffInTheModelListIsUnableBeforeItsHarnessIsAsked(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("PATH", t.TempDir())
	write := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	write(filepath.Join(home, ".agentkit", "state", "matrix.json"), `{"matrix": {"lineup": [{"release": "acme-5", "maker": "Acme",
		"effort": "high", "values": {"aa.intelligenceIndex": 50, "arena.agent": 0.6, "aa.frontierCode20": 0.6},
		"yours": [{"harness": "claude", "model": "acme-5"}]}]}}`)
	write(filepath.Join(home, ".agentkit", "config.toml"), "companies = ['Acme']\nmodels_off = ['acme-5']\n"+
		"[models.five]\nharness = 'claude'\nmodel = 'acme-5'\neffort = 'high'\nprovider = 'p'\n"+
		"[models.six]\nharness = 'claude'\nmodel = 'acme-6'\neffort = 'high'\nprovider = 'p'\n"+
		"[providers.p]\nmode = 'subscription'\n")
	cannot := unable()
	if cannot["five"] != "off in the model list" || cannot["six"] != "claude is not installed" {
		t.Fatalf("unable: %v", cannot)
	}
}
