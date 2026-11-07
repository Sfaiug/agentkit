package matrix

import (
	"os"
	"path/filepath"
	"testing"
)

// A model is off where the release it runs is listed and `models_off` holds it; a release with no
// scores is never listed, so nothing turns its model off.
func TestAModelIsOffWhereItsListedReleaseIsTurnedOff(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	write := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	scores := `{"aa.intelligenceIndex": 50, "arena.agent": 0.6, "aa.frontierCode20": 0.6, "aa.omniscience": 50}`
	write(filepath.Join(home, ".agentkit", "state", "matrix.json"), `{"matrix": {"lineup": [
		{"release": "acme-5", "maker": "Acme", "effort": "high", "values": `+scores+`, "yours": [{"harness": "echo", "model": "echo-5"}]},
		{"release": "acme-flash", "maker": "Acme", "effort": "high", "values": {}, "yours": [{"harness": "echo", "model": "echo-flash"}]}]}}`)
	for _, example := range []struct {
		settings, model string
		off             bool
	}{
		{"models_off = ['acme-5']\n", "five", true},
		{"", "five", false},
		{"models_off = ['acme-flash']\n", "flash", false},
		{"models_off = ['acme-5']\n", "other", false},
	} {
		write(filepath.Join(home, ".agentkit", "config.toml"), example.settings+"companies = ['Acme']\n"+
			"[models.five]\nharness = 'echo'\nmodel = 'echo-5'\neffort = 'low'\nprovider = 'p'\n"+
			"[models.flash]\nharness = 'echo'\nmodel = 'echo-flash'\neffort = 'low'\nprovider = 'p'\n"+
			"[models.other]\nharness = 'echo'\nmodel = 'echo-6'\neffort = 'low'\nprovider = 'p'\n"+
			"[providers.p]\nmode = 'subscription'\n")
		if off, err := Off(example.model); err != nil || off != example.off {
			t.Errorf("%q: %s off=%v (%v)", example.settings, example.model, off, err)
		}
	}
}
