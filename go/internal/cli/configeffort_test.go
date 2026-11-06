package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"agentkit/internal/matrix"
	"agentkit/internal/run"
)

func TestConfigStepsOnlyAdapterEffortsOncePerScreenAndHandsOffRestarts(t *testing.T) {
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
	path := filepath.Join(home, ".agentkit", "config.toml")
	put(path, "[models.one]\nharness='acme'\nmodel='m1'\neffort='high'\nprovider='fuel'\n[providers.fuel]\nmode='subscription'\n")
	put(filepath.Join(adapters, "acme.toml"), "[effort]\nlevels=['low','medium','high','max']\n")
	script := filepath.Join(adapters, "acme.sh")
	put(script, "#!/bin/sh\nprintf 'm1\tModel One\tlow high\n'\n")
	record := filepath.Join(home, ".agentkit", "state", "session-acme.json")
	put(record, "{  \"orchestrator\":\"one\",\"workers\":[\"one\"],\"conversation\":\"first\" }\n")
	c, err := matrix.Configured()
	if err != nil {
		t.Fatal(err)
	}
	catalogs := configCatalog{}
	if err := catalogs.read(c); err != nil {
		t.Fatal(err)
	}
	// The catalog changes after it was read, and another writer changes the record before Space.
	put(script, "#!/bin/sh\nexit 19\n")
	if err := catalogs.read(c); err != nil {
		t.Fatal(err)
	}
	put(record, `{"orchestrator":"one","workers":["one"],"reviewers":["one"],"conversation":"second","custom":17,"efforts":{"one":{"effort":"high","review_effort":"medium"}}}`)
	configBefore, _ := os.ReadFile(path)
	for _, word := range []string{"low", "high", "low"} {
		if note, known := stepConfigEffort(c, "acme", 0, 4, -1); !known || note != "" {
			t.Fatalf("step: %q, %v", note, known)
		}
		saved, err := run.ReadJSON(record)
		if err != nil || saved.Str("conversation") != "second" || saved.Get("custom") != run.Number("17") || saved.Dict("efforts").Dict("one").Str("review_effort") != "medium" || c.Effort("one", 1) != word {
			t.Fatalf("stepped past the adapter or lost record values: %s, %v", run.Line(saved), err)
		}
		if saved.Dict("efforts").Dict("one").Has("exec_effort") != (word != "high") {
			t.Fatal("a build effort at the base effort did not follow it again")
		}
	}
	before, _ := os.ReadFile(record)
	if note, known := stepConfigEffort(c, "acme", 0, 3, -1); known || note != "" {
		t.Fatalf("restart was not handed off: %q, %v", note, known)
	}
	if after, _ := os.ReadFile(record); !bytes.Equal(after, before) {
		t.Fatal("refused restart rewrote the record")
	}
	if after, _ := os.ReadFile(path); !bytes.Equal(after, configBefore) {
		t.Fatal("effort edit rewrote config.toml")
	}
}
