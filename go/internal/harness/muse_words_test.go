package harness

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestMuseRecordStaysPythonsAndOwnsOnlyASessionMuseNames(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	token := strings.Repeat("a", 32)
	path := filepath.Join(home, ".agentkit", "state", "muse-launch-"+token, "session")
	record := run.NewObject()
	record.Set("conversation", "legacy")
	record.Set("id_source", "launcher")
	record.Set("resumable", true)
	check := func(owned string) {
		t.Helper()
		before := run.Encode(record)
		if _, known := For("muse").Reconciled("acme", record); !known || run.Encode(record) != before {
			t.Fatalf("not read, or record changed: %s, ready=%v", run.Encode(record), known)
		}
		if got := museConversation(map[string]any{"muse_launch": record.Get("muse_launch")}); got != owned {
			t.Fatalf("owns %q, want %q", got, owned)
		}
	}
	check("")
	record.Set("muse_launch", token)
	check("") // no receipt yet
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	check("") // prepare has not reported a session
	for session, owned := range map[string]bool{
		"": false, "acme/session": false, "acme.session": false, " session": false,
		"session\n": false, "session\r\n": false, "one two": false,
		"session_1-abc": true, "séance_½中": true, "-": true,
	} {
		if err := os.WriteFile(path, []byte(session), 0o600); err != nil {
			t.Fatal(err)
		}
		want := ""
		if owned {
			want = session
		}
		check(want) // Muse's SESSION fullmatch, without OpenCode's whitespace stripping
	}
	record.Set("muse_launch", "../"+token)
	check("")
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
