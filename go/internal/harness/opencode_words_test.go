package harness

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestOpenCodeScreenHandsReportedSessionsToPython(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	token := strings.Repeat("a", 32)
	path := filepath.Join(home, ".agentkit", "state", "opencode-launch-"+token, "session")
	record := run.NewObject()
	record.Set("conversation", "legacy")
	record.Set("id_source", "launcher")
	record.Set("resumable", true)
	check := func(ready bool) {
		t.Helper()
		before := run.Encode(record)
		if _, known := For("opencode").Reconciled(record); known != ready || run.Encode(record) != before {
			t.Fatalf("readiness differs or record changed: %s, ready=%v", run.Encode(record), known)
		}
	}
	check(true) // an older launch with no receipt
	record.Set("opencode_launch", token)
	check(true) // a receipt not made yet
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	check(true) // prepare made the directory, but its plugin has reported nothing
	for session, ready := range map[string]bool{
		"": true, "ses_": true, "--session": true, "ses_a/b": true, "ses_a\nses_b": true,
		"ses_A012z": false, " \u0085ses_A012z\n": false,
	} {
		if err := os.WriteFile(path, []byte(session), 0o600); err != nil {
			t.Fatal(err)
		}
		check(ready)
	}
	if err := os.WriteFile(path, []byte("ses_A012z"), 0o600); err != nil {
		t.Fatal(err)
	}
	record.Set("conversation", "ses_A012z")
	check(false) // even an already bound session needs Python's database reader
	record.Set("opencode_launch", "../"+token)
	check(true) // not a receipt token, as Python's path_for decides
}
