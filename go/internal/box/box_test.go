//go:build linux

package box

import (
	"os"
	"path/filepath"
	"slices"
	"testing"
)

func TestTheRunCopyLeavesOutWhatIsHiddenByItsPathAndByTheInodeItHasAsTheCopyStarts(t *testing.T) {
	source, copied := t.TempDir(), t.TempDir()
	for _, name := range []string{"hosts.yml", "motd", "renamed"} {
		if err := os.WriteFile(filepath.Join(source, name), []byte("fixture-"+name), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	// the credential replaced by rename once its mask was made, its new file linked from elsewhere
	if err := os.Link(filepath.Join(source, "renamed"), filepath.Join(source, "linked")); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(filepath.Join(source, "renamed"), filepath.Join(source, "hosts.yml")); err != nil {
		t.Fatal(err)
	}
	if err := copyRun(source, copied, "", []string{filepath.Join(source, "hosts.yml")}); err != nil {
		t.Fatal(err)
	}
	var names []string
	entries, _ := os.ReadDir(copied)
	for _, entry := range entries {
		names = append(names, entry.Name())
	}
	if !slices.Equal(names, []string{"motd"}) {
		t.Fatalf("the copy holds %q", names)
	}
}
