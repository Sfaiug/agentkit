package harness

import (
	"os"
	"path/filepath"
	"testing"
)

// A Grok Build seat's conversation is opened where its session's folder is there, a link to one
// followed, before it holds any updates.jsonl; not where nothing, or a file, is there.
func TestGrokOpenedIsTheSessionsFolder(t *testing.T) {
	record, updates := grokSeat(t, "")
	session := filepath.Dir(updates)
	if opened, known := Opened("grokbuild", record); !opened || !known {
		t.Fatalf("a session with updates: %v %v", opened, known)
	}
	if os.Remove(updates) != nil {
		t.Fatal(updates)
	}
	if opened, _ := Opened("grokbuild", record); !opened {
		t.Fatal("a session only its folder holds yet")
	}
	elsewhere := filepath.Join(t.TempDir(), "kept")
	if os.Rename(session, elsewhere) != nil || os.Symlink(elsewhere, session) != nil {
		t.Fatal(session)
	}
	if opened, _ := Opened("grokbuild", record); !opened {
		t.Fatal("a link to a session's folder")
	}
	if os.Remove(session) != nil || os.WriteFile(session, nil, 0o600) != nil {
		t.Fatal(session)
	}
	if opened, known := Opened("grokbuild", record); opened || !known {
		t.Fatalf("a file where the folder would be: %v %v", opened, known)
	}
	if os.Remove(session) != nil {
		t.Fatal(session)
	}
	if opened, known := Opened("grokbuild", record); opened || !known {
		t.Fatalf("no session: %v %v", opened, known)
	}
}
