package plan

import (
	"os"
	"path/filepath"
	"testing"
)

func TestOutcomesKeepDistinctDoneWorkAndLeaveDeferredWorkToPython(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	path := seatFile("plan", "acme", "md")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("- [x] API ships\n- [ ] Still open\n- [x] API ships\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	work, err := Outcomes("acme")
	if err != nil || len(work) != 1 || work[0].([]any)[1] != "API ships" {
		t.Fatal(work, err)
	}
	line := "- [x] API ships · check: `true` · ~/code/api#abc1234 · deferred · written 2026-11-03 10:00 on abc1234 · done abc1234 merged"
	if err := os.WriteFile(path, []byte(line), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Outcomes("acme"); err != ErrUnread {
		t.Fatal("deferred completion was guessed", err)
	}
}
