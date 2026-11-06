package tick

import (
	"os"
	"path/filepath"
	"testing"
)

func TestAStopItsHookJudgesIsUnowedOnlyWhileItsPlanOwesNothing(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	plan := filepath.Join(home, ".agentkit", "state", "plan-acme.md")
	if err := os.MkdirAll(filepath.Dir(plan), 0o700); err != nil {
		t.Fatal(err)
	}
	if !stopUnowed("acme") {
		t.Fatal("a seat with no plan owes a line")
	}
	// an open line is owed, and a plan all done may owe its done check
	for _, text := range []string{"- [ ] Ship it\n", "- [x] Ship it\n"} {
		if err := os.WriteFile(plan, []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
		if stopUnowed("acme") {
			t.Fatalf("%q owes nothing", text)
		}
	}
}
