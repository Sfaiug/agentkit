package guard

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// git is hot: the real one is asked about checkouts only for a stash that may write, and with the
// call's own options before its command, as they name the repository.
func TestOnlyAStashThatMayWriteAsksTheRealGit(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the real git here is a shell script")
	}
	seated(t, "acme")
	asked := filepath.Join(t.TempDir(), "asked")
	real := filepath.Join(t.TempDir(), "git")
	put(t, real, "#!/bin/sh\necho \"$*\" >> '"+asked+"'\nprintf 'worktree /a\\nHEAD x\\n\\nworktree /b\\n'\n")
	if err := os.Chmod(real, 0o777); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{{"status"}, {"-c", "stash", "log"}, {"stash", "list"}, {"-C", "x", "stash", "show", "-p"}, {"-C"}} {
		if refused, _ := Decide("git", real, args); refused != "" {
			t.Errorf("%q: %q", args, refused)
		}
	}
	if _, err := os.Stat(asked); err == nil {
		t.Fatal("asked the real git of a call that is no stash that may write")
	}
	if refused, _ := Decide("git", real, []string{"-C", "x", "--git-dir", "y", "stash", "pop"}); !strings.HasPrefix(refused, "ak refused `git stash`") {
		t.Errorf("%q", refused)
	}
	if said, _ := os.ReadFile(asked); string(said) != "-C x --git-dir y worktree list --porcelain\n" {
		t.Errorf("%q", said)
	}
}
