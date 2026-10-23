package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

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
