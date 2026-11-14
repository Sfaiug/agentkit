package cli

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

func TestALineAJobLeftIsShownOnceAfterTheUpdatesResult(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	state := filepath.Join(home, ".agentkit", "state")
	result, notices := filepath.Join(state, "update-result"), filepath.Join(state, "notices")
	write(t, result, "update: done (acme)\n")
	write(t, notices, "stop: fix-api is still running\n")
	if got, want := menuNotices(), []string{"update: done (acme)", "stop: fix-api is still running"}; !slices.Equal(got, want) {
		t.Fatalf("menuNotices gave %q, want %q", got, want)
	}
	if _, err := os.Stat(result); !os.IsNotExist(err) {
		t.Fatalf("update-result is still there (%v)", err)
	}
	if data, err := os.ReadFile(notices); err != nil || len(data) != 0 {
		t.Fatalf("notices holds %q (%v), want it there and empty", data, err)
	}
	if got := menuNotices(); got != nil {
		t.Fatalf("asked again, menuNotices gave %q", got)
	}
	os.Remove(notices)
	if got := menuNotices(); got != nil {
		t.Fatalf("with neither file, menuNotices gave %q", got)
	}
	for _, path := range []string{result, notices} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Fatalf("%s was made (%v)", filepath.Base(path), err)
		}
	}
}
