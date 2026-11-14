package cli

import (
	"io"
	"os"
	"path/filepath"
	"slices"
	"testing"

	"github.com/ncruces/go-sqlite3"
)

// A lineup a model runs a row of is Python's to rank in a home whose history.db holds a run, as
// a run of yours may have measured a row of it: `ak usage` hands over before usage.json, or any
// record of ak's, is written.
func TestUsageHandsOverARankWhereHistoryHoldsARun(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	t.Setenv("AGENTKIT_ADAPTER_DIR", t.TempDir()) // a usage read Go's, not the pick's to hand over
	ak := filepath.Join(home, ".agentkit")
	write := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	write(filepath.Join(ak, "state", "matrix.json"), `{"matrix": {"lineup": [{"release": "acme-5", "maker": "Acme",
		"effort": "high", "values": {"aa.intelligenceIndex": 50, "arena.agent": 0.6, "aa.frontierCode20": 0.6},
		"yours": [{"harness": "echo", "model": "acme-5"}]}]}}`)
	write(filepath.Join(ak, "config.toml"), "companies = ['Acme']\n[providers.p]\nmode = 'subscription'\n"+
		"[models.five]\nharness = 'echo'\nmodel = 'acme-5'\neffort = 'high'\nprovider = 'p'\n")
	db, err := sqlite3.Open(filepath.Join(ak, "history.db"))
	if err != nil {
		t.Fatal(err)
	}
	if err := db.Exec("CREATE TABLE runs (run_id TEXT); INSERT INTO runs VALUES ('20261001-1200-fix-api')"); err != nil {
		t.Fatal(err)
	}
	db.Close()
	files := func() (found []string) {
		t.Helper()
		if err := filepath.WalkDir(ak, func(path string, entry os.DirEntry, err error) error {
			if err == nil {
				found = append(found, path)
			}
			return err
		}); err != nil {
			t.Fatal(err)
		}
		return found
	}
	before := files()
	if code := usageAnswer([]string{"--json"}, io.Discard, io.Discard); code != 3 {
		t.Fatalf("ak usage exited %d, not handing over", code)
	}
	if after := files(); !slices.Equal(after, before) {
		t.Fatalf("handing over left %v, where there stood %v", after, before)
	}
}
