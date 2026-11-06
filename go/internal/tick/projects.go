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

// declares reads the default branch as Python does: no readable AGENTS.md declares nothing.
func declares(checkout, key string) bool {
	return gitcall.DeclaredAt(checkout, rulesRef, key, gitcall.ProjectEnv(checkout)...) != ""
}

// fetchProjects is the project rules row (orch.fetch_projects): each checkout's, and each project's
// a seat is filed under, every branch fetched and origin/HEAD set again to origin's default branch,
// which the later rows read. One that fails is named, after every other is fetched.
func (t *ticking) fetchProjects() error {
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
		if err := gitcall.Refresh(repo); err != nil {
			failed = append(failed, err.Error())
		} else {
			t.fetched = append(t.fetched, repo)
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
