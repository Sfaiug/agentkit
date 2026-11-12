//go:build unix

package tick

import (
	"fmt"
	"path/filepath"
	"testing"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// A Claude seat's conversation not written yet is kept to be read from its start.
func TestSeatTokensKeepASourceToReadFromItsStart(t *testing.T) {
	ak, _ := idleHome(t, "")
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non=false\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	seat := func(name string) {
		put(t, filepath.Join(ak, "state", "session-"+name+".json"),
			fmt.Sprintf(`{"orchestrator":"opus","conversation":"conv-%s","cwd":%q,"repo":"/src/api"}`, name, t.TempDir()))
	}
	sources := func() []history.Row {
		db := history.Look()
		defer db.Close()
		return db.Select("SELECT path, harness, repo, cursor, account FROM seat_sources")
	}
	seat("acme")
	history.Start(run.Fields("run_id", "fix-api"), nil)
	if err := seatTokens(); err != nil {
		t.Fatal(err)
	}
	kept := sources()
	if len(kept) != 1 || filepath.Base(kept[0].Text("path")) != "conv-acme.jsonl" || kept[0].Text("harness") != "claude" ||
		kept[0].Text("repo") != "api" || kept[0].Text("cursor") != "{}" || kept[0].Text("account") != "default" {
		t.Fatalf("kept %v", kept)
	}
}
