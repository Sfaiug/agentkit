package cli

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

func TestANewSeatStepsOnlyTheEffortsItsCatalogLists(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the fake adapter is a shell script")
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	adapters := filepath.Join(home, "adapters")
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	put := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	put(filepath.Join(home, ".agentkit", "config.toml"), "[defaults]\norchestrator='one'\nworkers=['one']\n[models.one]\nharness='acme'\nmodel='m1'\neffort='low'\nprovider='fuel'\n[providers.fuel]\nmode='subscription'\n")
	put(filepath.Join(adapters, "acme.toml"), "[effort]\nlevels=['low','medium','high']\n")
	put(filepath.Join(adapters, "acme.sh"), "#!/bin/sh\nprintf 'm1\tModel One\tlow high\n'\n")
	for role, key := range []string{"effort", "exec_effort", "review_effort"} {
		d, err := menu.NewDraft("fix-api", nil)
		if err != nil {
			t.Fatal(err)
		}
		d.Key(terminal.Key{Name: "tab"})
		if !draftLevels(d, configCatalog{}) || !d.Picker {
			t.Fatal("the models screen did not open")
		}
		d.Column = role // on its mark, then the effort beside it
		for _, name := range []string{"right", "space"} {
			d.Key(terminal.Key{Name: name})
		}
		if got := d.Models["one"].Efforts[key]; got != "high" {
			t.Errorf("%s stepped from low to %q, not to high, the next its catalog lists", key, got)
		}
	}
}
