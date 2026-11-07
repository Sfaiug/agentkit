//go:build linux

package loop

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"sync"
	"testing"

	"agentkit/internal/run"
)

// git runs it on each ref change; only the first in `ak/` waits, which `mkdir` claims once
const heldHook = "#!/bin/sh\nif [ \"$1\" = prepared ] && grep -q ' refs/heads/ak/' && mkdir %q 2>/dev/null; then sleep 2; fi\n"

func TestRunsOfOneTitleTakeBranchesApart(t *testing.T) {
	home := t.TempDir()
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "GIT_CONFIG_NOSYSTEM": "1",
		"GIT_AUTHOR_NAME": "acme", "GIT_AUTHOR_EMAIL": "acme@example.com", "GIT_COMMITTER_NAME": "acme", "GIT_COMMITTER_EMAIL": "acme@example.com"} {
		t.Setenv(key, value)
	}
	repo := filepath.Join(home, "acme")
	shell(t, home, "git init -q -b main acme && cd acme && git commit -q --allow-empty -m init")
	held := filepath.Join(home, "held")
	if err := os.WriteFile(filepath.Join(repo, ".git", "hooks", "reference-transaction"), []byte(fmt.Sprintf(heldHook, held)), 0o755); err != nil {
		t.Fatal(err)
	}
	cut := func(id string) (string, error) {
		place := &repoPlace{repo: repo}
		err := place.makeWorktree(&loop{id: id}, "add-retry", "main")
		return place.branch, err
	}

	t.Run("started together, the second takes the next name", func(t *testing.T) {
		branches := make([]string, 2)
		var wg sync.WaitGroup
		for n := range branches {
			wg.Add(1)
			go func() {
				defer wg.Done()
				var err error
				if branches[n], err = cut(fmt.Sprintf("together-%d", n)); err != nil {
					t.Error(err)
				}
			}()
		}
		wg.Wait()
		if info, err := os.Stat(held); err != nil || !info.IsDir() {
			t.Fatal("git never held the first branch")
		}
		slices.Sort(branches)
		if !slices.Equal(branches, []string{"ak/add-retry", "ak/add-retry-2"}) {
			t.Fatalf("branches %q", branches)
		}
	})

	t.Run("a name a record of the repository holds stays taken with no branch", func(t *testing.T) {
		for id, fields := range map[string][]any{
			"20260101-0000-gone":  {"repo", repo, "branch", "ak/add-retry-3"},
			"20260101-0000-other": {"repo", filepath.Join(home, "other"), "branch", "ak/add-retry-4"},
		} {
			dir := filepath.Join(run.Runs(), id)
			if err := os.MkdirAll(dir, 0o777); err != nil {
				t.Fatal(err)
			}
			if err := run.Create(dir, run.Fields(fields...)); err != nil {
				t.Fatal(err)
			}
		}
		if branch, err := cut("after"); err != nil || branch != "ak/add-retry-4" {
			t.Fatalf("branch %q: %v", branch, err)
		}
	})
}
