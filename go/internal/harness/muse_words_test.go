package harness

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestMuseScreenLeavesReportedSessionsToPython(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	token := strings.Repeat("a", 32)
	path := filepath.Join(home, ".agentkit", "state", "muse-launch-"+token, "session")
	record := run.NewObject()
	record.Set("conversation", "legacy")
	record.Set("id_source", "launcher")
	record.Set("resumable", true)
	check := func(ready bool) {
		t.Helper()
		before := run.Encode(record)
		if _, known := For("muse").Reconciled(record); known != ready || run.Encode(record) != before {
			t.Fatalf("readiness differs or record changed: %s, ready=%v", run.Encode(record), known)
		}
	}
	check(true)
	record.Set("muse_launch", token)
	check(true) // no receipt yet
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	check(true) // prepare has not reported a session
	for session, ready := range map[string]bool{
		"": true, "acme/session": true, "acme.session": true, " session": true,
		"session\n": true, "session\r\n": true, "one two": true,
		"session_1-abc": false, "séance_½中": false, "-": false,
	} {
		if err := os.WriteFile(path, []byte(session), 0o600); err != nil {
			t.Fatal(err)
		}
		check(ready) // Muse's SESSION fullmatch, without OpenCode's whitespace stripping
	}
	if err := os.WriteFile(path, []byte("session_1"), 0o600); err != nil {
		t.Fatal(err)
	}
	record.Set("conversation", "session_1")
	check(false) // even a bound session can move in Muse's registry or hold a question card
	record.Set("muse_launch", "../"+token)
	check(true)
	if !RecordReadOnly("muse") {
		t.Fatal("Muse's record must remain Python's")
	}
	for entry, kept := range map[string]bool{
		"muse-launch-" + token: true, "muse-launch-" + token + ".gone": true,
		"muse-launch-x": false, "muse-launch-" + token + ".json": false,
	} {
		if KeptInState(entry) != kept {
			t.Errorf("%s kept: %v", entry, !kept)
		}
	}
}
