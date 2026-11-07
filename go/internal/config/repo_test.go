package config

import (
	"os/exec"
	"path/filepath"
	"testing"
)

// A git hook's GIT_DIR and GIT_WORK_TREE name the repository it runs for, never ak's own.
func TestRepoIsWhereTheExecutableSitsWhateverGitVariablesName(t *testing.T) {
	want, foreign := Repo(), t.TempDir()
	if out, err := exec.Command("git", "init", "-q", foreign).CombinedOutput(); err != nil {
		t.Fatal(string(out), err)
	}
	t.Setenv("GIT_DIR", filepath.Join(foreign, ".git"))
	t.Setenv("GIT_WORK_TREE", foreign)
	if got := Repo(); got != want {
		t.Fatalf("Repo is %s, not %s", got, want)
	}
}
