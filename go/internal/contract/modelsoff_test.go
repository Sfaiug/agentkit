package contract

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// A home whose `models_off` names a model hands its whole check to Python before anything is
// written: a turn judges the config's model of the harness's name off, where Python judges the
// `[check]` model itself.
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
	write(filepath.Join(home, ".agentkit", "config.toml"), "models_off = ['acme-5']\n")
	snapshot, counts := filepath.Join(home, "usage.json"), filepath.Join(home, "counts")
	var out, errOut bytes.Buffer
	if code := Main([]string{"acme", "--snapshot", snapshot, "--counts", counts}, &out, &errOut); code != 3 {
		t.Fatalf("exit %d, want 3: %s%s", code, out.String(), errOut.String())
	}
	if out.Len() > 0 {
		t.Errorf("printed %q", out.String())
	}
	for _, path := range []string{snapshot, counts} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Errorf("%s written (%v)", path, err)
		}
	}
}
