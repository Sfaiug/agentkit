package tick

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/gitcall"
	"agentkit/internal/seat"
	"agentkit/internal/task"
)

// rulesRef is a project's default branch as last fetched, Python's config.RULES_REF.
const rulesRef = "refs/remotes/origin/HEAD"

// checkoutsSeen is whether every place a checkout may stand could be looked at.
func checkoutsSeen() bool {
	_, seen := seat.Checkouts()
	return seen
}

// noneDeclares is whether every checkout could be looked at and none declares key, read as
// declares reads it.
func noneDeclares(key string, written bool) bool {
	checkouts, seen := seat.Checkouts()
	return seen && !slices.ContainsFunc(checkouts, func(checkout string) bool {
		return declares(checkout, key) || written && gitcall.Declared(checkout, key) != ""
	})
}

// declares is whether the AGENTS.md of the checkout's default branch declares key, or cannot be
// read for it.
func declares(checkout, key string) bool {
	text, err := gitcall.Git{Repo: checkout, Env: gitcall.ProjectEnv(checkout)}.Try("show", rulesRef+":AGENTS.md")
	return err != nil || task.FrontValue(text, key) != ""
}

// fetchProjects is the project rules row (orch.fetch_projects): each checkout's, and each project's
// a seat is filed under, every branch fetched and origin/HEAD set again to origin's default branch,
// which the later rows read. One that fails is named, after every other is fetched.
func fetchProjects() error {
	repos, err := seatProjects()
	if err != nil {
		return err
	}
	checkouts, _ := seat.Checkouts()
	for _, repo := range repos {
		if !slices.Contains(checkouts, filepath.Clean(repo)) {
			checkouts = append(checkouts, filepath.Clean(repo))
		}
	}
	slices.Sort(checkouts)
	var failed []string
	for _, repo := range checkouts {
		g := gitcall.Git{Repo: repo, Env: gitcall.ProjectEnv(repo)}
		args := []string{"--quiet", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*"}
		code, said, err := g.Fetch(args...)
		if err == nil && code != 0 {
			err = fmt.Errorf("git fetch %s failed in %s: %s", strings.Join(args, " "), repo, said)
		}
		if err == nil {
			_, err = g.Must("remote", "set-head", "origin", "--auto")
		}
		if err != nil {
			failed = append(failed, err.Error())
		}
	}
	if len(failed) > 0 {
		return errors.New(strings.Join(failed, "; "))
	}
	return nil
}

// replaceFile writes data to path whole (orch.replace_file): a reader sees the old file or the
// new one, never half.
func replaceFile(path, data string) error {
	tmp := fmt.Sprintf("%s.%d.tmp", path, os.Getpid())
	if err := os.WriteFile(tmp, []byte(data), 0o666); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// gitless is env without git's own variables: a repository, index or setting inherited would
// answer for another checkout.
func gitless(env []string) []string {
	return slices.DeleteFunc(slices.Clone(env), func(pair string) bool { return strings.HasPrefix(pair, "GIT_") })
}
