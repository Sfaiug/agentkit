package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// A home under a folder named like a pattern is still read as the path it is.
func TestSeatFilesUnderAHomeNamedLikeAPattern(t *testing.T) {
	home := filepath.Join(t.TempDir(), "a[b]")
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	state := filepath.Join(Home(), "state")
	if err := os.MkdirAll(state, 0700); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"session-fix-web.json", "notes.json", "session-fix-api.json"} {
		if err := os.WriteFile(filepath.Join(state, name), []byte("{}"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	want := []string{filepath.Join(state, "session-fix-api.json"), filepath.Join(state, "session-fix-web.json")}
	if got := SeatFiles(); fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("SeatFiles() = %q, want %q", got, want)
	}
}

func TestSessionRenameRefusals(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	state := filepath.Join(Home(), "state")
	if err := os.MkdirAll(state, 0700); err != nil {
		t.Fatal(err)
	}
	set := func(name, data string) {
		t.Helper()
		if err := os.WriteFile(filepath.Join(state, "session-"+name+".json"), []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
	}
	set("old", `{"renamed":"new"}`)
	set("new", `{"renamed":"old"}`)
	t.Setenv("AGENTKIT_SESSION", " old ")
	if _, _, err := CurrentSession(); err == nil || !strings.HasSuffix(err.Error(), "the rename chain loops through old -> new") {
		t.Fatalf("rename cycle: %v", err)
	}
	for i := 0; i < renameHops; i++ {
		set(fmt.Sprint(i), fmt.Sprintf(`{"renamed":"%d"}`, i+1))
	}
	set(fmt.Sprint(renameHops), `{"repo":"acme"}`)
	t.Setenv("AGENTKIT_SESSION", "0")
	name, record, err := CurrentSession()
	if err != nil || name != fmt.Sprint(renameHops) || record["repo"] != "acme" {
		t.Fatalf("allowed rename chain: %q %v %v", name, record, err)
	}
	set(fmt.Sprint(renameHops), fmt.Sprintf(`{"renamed":"%d"}`, renameHops+1))
	if _, _, err := CurrentSession(); err == nil || !strings.HasSuffix(err.Error(), "more than 8 renames deep") {
		t.Fatalf("excessive rename chain: %v", err)
	}
	t.Setenv("AGENTKIT_SESSION", "../outside")
	if _, _, err := CurrentSession(); err == nil || err.Error() != "invalid AGENTKIT_SESSION name '../outside'" {
		t.Fatalf("invalid session path: %v", err)
	}
}

// A spaced name no record holds is the seat name Python's session_name makes of it, where
// Python's lower() and Go's ToLower part ways too.
func TestSpacedNameIsPythonsSeatName(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	for raw, want := range map[string]string{"Fix Api": "fix-api", "F\u0130x Api": "fi-x-api", "KELVIN \u212a": "kelvin-k"} {
		if name, _, err := ResolveSession(raw); err != nil || name != want {
			t.Errorf("ResolveSession(%q) = %q, %v; Python names it %q", raw, name, err, want)
		}
	}
}
