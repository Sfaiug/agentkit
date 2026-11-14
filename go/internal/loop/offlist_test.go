package loop

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// offHome is a home whose model list turns five off, and where six's harness is not installed.
func offHome(t *testing.T) {
	t.Helper()
	home := t.TempDir()
	for name, value := range map[string]string{"HOME": home, "USERPROFILE": home, "PATH": t.TempDir(),
		"AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": ""} {
		t.Setenv(name, value)
	}
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
}

// A model the model list turned off cannot run here for that, before its harness is asked: one
// not installed says only that it is off.
func TestAModelOffInTheModelListIsUnableBeforeItsHarnessIsAsked(t *testing.T) {
	offHome(t)
	cannot := unable()
	if cannot["five"] != "off in the model list" || cannot["six"] != "claude is not installed" {
		t.Fatalf("unable: %v", cannot)
	}
}

// A dry tick asks no harness, yet a saved executor the model list turned off cannot go on: the
// resume it previews takes another, as the resume itself would.
func TestADryResumeLeavesOutASavedExecutorThatIsOff(t *testing.T) {
	offHome(t)
	adapters := t.TempDir() // a usage read Go's, not the pick's to hand over
	if err := os.WriteFile(filepath.Join(adapters, "claude.toml"), []byte("version = 1\n"), 0o666); err != nil {
		t.Fatal(err)
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	record := run.Fields("state", "exhausted", "quota_dry", true, "step", "executor", "workers", []any{"five", "six"},
		"reviewers", []any{"six"}, "executor", "five", "reviewer", "six")
	executor, reviewer, dry, ok := ResumeModels(record, true)
	if !ok || executor != "six" || reviewer != "six" || dry != "" {
		t.Fatalf("a dry resume went on with %q and %q (%q, %v)", executor, reviewer, dry, ok)
	}
}
