//go:build linux

package loop

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"agentkit/internal/gitcall"
)

func TestFetchAndBranchDeletionExcludeEachOther(t *testing.T) {
	_, r := repoRig(t)
	shell(t, r.repo, "git branch ak/finished")
	git, err := exec.LookPath("git")
	if err != nil {
		t.Fatal(err)
	}
	bin := t.TempDir()
	// Force the competing operation at the Git command itself, without a scheduler's wait.
	// A fetch enumerating a ref as cleanup deletes it can read that ref as a bad object.
	script := fmt.Sprintf(`#!/usr/bin/env python3
import fcntl, os, subprocess, sys
real = %q
args = sys.argv[1:]
repo, command = args[1], args[2:]
if command[0] == "fetch" or command[:2] == ["branch", "-D"]:
    common = subprocess.check_output([real, "-C", repo, "rev-parse",
                                      "--path-format=absolute", "--git-common-dir"], text=True).strip()
    fd = os.open(common, os.O_RDONLY)
    how = fcntl.LOCK_EX if command[0] == "fetch" else fcntl.LOCK_SH
    try:
        fcntl.flock(fd, how | fcntl.LOCK_NB)
    except BlockingIOError:
        pass
    else:
        sys.exit("fetch and branch deletion can overlap")
    os.close(fd)
    if command[0] == "fetch":
        sys.exit(0)
os.execv(real, [real, *args])
`, git)
	if err := os.WriteFile(filepath.Join(bin, "git"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Run("fetch from a linked worktree", func(t *testing.T) {
		if code, out, err := (gitcall.Git{Repo: r.wt}).Fetch("origin"); err != nil || code != 0 {
			t.Fatalf("fetch: %d %s %v", code, out, err)
		}
	})
	t.Run("delete from its repository", func(t *testing.T) {
		g := gitcall.Git{Repo: r.repo}
		if !dropBranch(g, "ak/finished", func(line string) { t.Log(line) }) {
			t.Fatal("branch was not deleted")
		}
		if found, err := g.Try("rev-parse", "--verify", "--quiet", "refs/heads/ak/finished"); err != nil || found != "" {
			t.Fatalf("deleted branch: %q %v", found, err)
		}
	})
}
