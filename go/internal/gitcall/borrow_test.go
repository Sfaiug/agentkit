package gitcall

import (
	"path/filepath"
	"testing"
)

// A check's clone, a mirror too, names the repository it borrows from, so a suite it sends a
// machine finds that repository's copy there.
func TestACloneNamesTheRepositoryItBorrowsFrom(t *testing.T) {
	box := t.TempDir()
	t.Setenv("HOME", box)
	t.Setenv("GIT_CONFIG_GLOBAL", filepath.Join(box, "gitconfig"))
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	source := filepath.Join(box, "acme")
	if _, err := (Git{Repo: box}).Must("init", "-q", source); err != nil {
		t.Fatal(err)
	}
	if _, err := (Git{Repo: source}).Must("-c", "user.name=acme", "-c", "user.email=acme@example.com", "commit", "-qm", "init", "--allow-empty"); err != nil {
		t.Fatal(err)
	}
	for _, how := range [][]string{{"--no-checkout"}, {"--mirror"}} {
		clone := filepath.Join(t.TempDir(), "checkout")
		if err := (Git{Repo: source}).CloneBorrowing(clone, how...); err != nil {
			t.Fatal(err)
		}
		if got, want := RepositoryID(clone), RepositoryID(source); got != want {
			t.Errorf("a clone made %s is named %s, want %s", how[0], got, want)
		}
	}
}
