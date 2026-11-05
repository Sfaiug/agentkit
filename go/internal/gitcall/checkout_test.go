package gitcall

import (
	"path/filepath"
	"testing"
)

func TestCheckoutPreparationDisablesCollectionInALinkedWorktree(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("GIT_CONFIG_GLOBAL", filepath.Join(home, "gitconfig"))
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	git := func(repo string, args ...string) string {
		t.Helper()
		out, err := (Git{Repo: repo}).Must(args...)
		if err != nil {
			t.Fatal(err)
		}
		return out
	}
	repo, tree := filepath.Join(home, "acme"), filepath.Join(home, "fix-api")
	git(home, "init", "-q", "-b", "main", repo)
	git(repo, "-c", "user.name=acme", "-c", "user.email=acme@example.com", "commit", "-qm", "init", "--allow-empty")
	git(repo, "config", "extensions.worktreeConfig", "true")
	git(repo, "worktree", "add", "--detach", tree, "HEAD")
	git(tree, "config", "--worktree", "gc.auto", "1")
	git(tree, "config", "--worktree", "maintenance.auto", "true")
	held, err := PrepareCheckout(tree)
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	for key, want := range map[string]string{"gc.auto": "0", "maintenance.auto": "false"} {
		if got := git(repo, "config", "--local", "--get", key); got != want {
			t.Errorf("shared %s = %q, want %q", key, got, want)
		}
		if got := git(tree, "config", "--get", key); got != want {
			t.Errorf("worktree %s = %q, want %q", key, got, want)
		}
	}
}
