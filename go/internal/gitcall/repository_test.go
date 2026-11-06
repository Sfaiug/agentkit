package gitcall

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

// A version of ak's own checkout is named after ~/agentkit as Python spells it, a `..` in HOME
// kept, so it finds the records Python keeps under that name.
func TestAksOwnVersionIsNamedAfterHomeAsSpelled(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows reads USERPROFILE")
	}
	box := t.TempDir()
	if err := os.Mkdir(filepath.Join(box, "alias"), 0o700); err != nil {
		t.Fatal(err)
	}
	home := box + "/alias/.."
	t.Setenv("HOME", home)
	t.Setenv("GIT_CONFIG_GLOBAL", filepath.Join(box, "gitconfig"))
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	git := func(repo string, args ...string) {
		t.Helper()
		if _, err := (Git{Repo: repo}).Must(args...); err != nil {
			t.Fatal(err)
		}
	}
	source, bare, tree := filepath.Join(box, "acme"), filepath.Join(box, ".agentkit", "agentkit.git"), filepath.Join(box, "fix-api")
	git(box, "init", "-q", source)
	git(source, "-c", "user.name=acme", "-c", "user.email=acme@example.com", "commit", "-qm", "init", "--allow-empty")
	git(box, "clone", "-q", "--bare", source, bare)
	git(bare, "worktree", "add", "-q", "--detach", tree, "HEAD")
	sum := sha256.Sum256([]byte(home + "/agentkit"))
	if got, want := RepositoryID(tree), hex.EncodeToString(sum[:6]); got != want {
		t.Errorf("RepositoryID = %s, want %s, the name of %s/agentkit", got, want, home)
	}
}
