package contract

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// A home whose model list switches a release off, by `models_off` or by `companies`, hands its
// whole check to Python before anything is written; one switching nothing off is Go's.
func TestAContractCheckWithAModelSwitchedOffGoesToPython(t *testing.T) {
	home, adapters := t.TempDir(), t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	t.Setenv("AK_HANDOVER", "")
	write := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	write(filepath.Join(adapters, "acme.toml"), "version = 1\n[check]\nmodel = 'acme-1'\neffort = 'low'\n")
	scores := `{"aa.intelligenceIndex": 50, "arena.agent": 0.6, "aa.frontierCode20": 0.6, "aa.omniscience": 50}`
	write(filepath.Join(home, ".agentkit", "state", "matrix.json"), `{"matrix": {"lineup": [
		{"release": "acme-5", "maker": "Acme", "effort": "high", "values": `+scores+`, "yours": [{"harness": "acme", "model": "acme-5"}]},
		{"release": "bolt-1", "maker": "Bolt", "effort": "high", "values": `+scores+`, "yours": [{"harness": "acme", "model": "acme-1"}]}]}}`)
	snapshot, counts := filepath.Join(home, "usage.json"), filepath.Join(home, "counts")
	for _, example := range []struct {
		settings string
		off      bool
	}{
		{"models_off = ['acme-9']\n", true}, // even a release no lineup lists
		{"companies = ['Acme']\n", true},    // bolt-1, the check model's
		{"companies = ['Acme', 'Bolt']\n", false},
	} {
		write(filepath.Join(home, ".agentkit", "config.toml"), example.settings)
		if !example.off {
			if switchedOff() {
				t.Errorf("%q: switched off", example.settings)
			}
			continue
		}
		var out, errOut bytes.Buffer
		if code := Main([]string{"acme", "--snapshot", snapshot, "--counts", counts}, &out, &errOut); code != 3 {
			t.Fatalf("%q: exit %d, want 3: %s%s", example.settings, code, out.String(), errOut.String())
		}
		if out.Len() > 0 {
			t.Errorf("%q: printed %q", example.settings, out.String())
		}
		for _, path := range []string{snapshot, counts} {
			if _, err := os.Stat(path); !os.IsNotExist(err) {
				t.Errorf("%q: %s written (%v)", example.settings, path, err)
			}
		}
	}
}
