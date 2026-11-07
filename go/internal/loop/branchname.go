package loop

import (
	"context"
	"fmt"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// makeBranch makes a run's branch in repo from that commit, `ak/<slug>` or the first free
// `ak/<slug>-N`, as Python's make_worktree names it. A name origin has is taken: two runs that
// picked one locally would both push it, and the second is rejected after its work has passed.
// An origin that cannot say is the empty set: naming is not worth failing a run over.
func makeBranch(repo, slug, start string) (string, error) {
	g := gitcall.Git{Repo: repo}
	taken := map[string]bool{}
	asked := g
	asked.Cap = time.Minute
	if code, out, _, err := asked.Run("ls-remote", "--heads", "origin", "refs/heads/ak/"+slug+"*"); err == nil && code == 0 {
		for _, line := range config.SplitLines(out) {
			if _, ref, found := strings.Cut(line, "\t"); found {
				taken[strings.TrimPrefix(ref, "refs/heads/")] = true
			}
		}
	}
	// One run names a branch at a time, the repository's `refs` locked from the look to the
	// branch made: two runs of one title started together would both find a name free, and the
	// second fail to make it. Its checkout comes after, so a slow one holds no other run.
	common, err := g.Must("rev-parse", "--path-format=absolute", "--git-common-dir")
	if err != nil {
		return "", err
	}
	held, err := lock.Wait(context.Background(), filepath.Join(common, "refs"))
	if err != nil {
		return "", err
	}
	defer held.Close()
	// A name a run's record holds stays that run's once its branch is gone: an ending takes its
	// branch by name more than once, and a run of the same title given the name in between lost
	// its branch before its checkout held it.
	records, err := run.Records()
	if err != nil {
		return "", err
	}
	for _, record := range records {
		if record.Str("repo") == repo {
			taken[record.Str("branch")] = true
		}
	}
	branch := "ak/" + slug
	for suffix := 2; ; suffix++ {
		found, err := g.Try("rev-parse", "--verify", "--quiet", "refs/heads/"+branch)
		if err != nil {
			return "", err
		}
		if !taken[branch] && found == "" {
			break
		}
		branch = fmt.Sprintf("ak/%s-%d", slug, suffix)
	}
	if _, err := g.Must("branch", branch, start); err != nil {
		return "", err
	}
	return branch, nil
}
