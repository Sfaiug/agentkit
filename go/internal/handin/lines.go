package handin

import (
	"errors"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/size"
	"agentkit/internal/uncommitted"
)

// stamp is ak's own temporary commits' author and date: identical trees and parents give every
// attempt the same commit.
var stamp = []string{"GIT_AUTHOR_NAME=ak", "GIT_AUTHOR_EMAIL=ak@localhost", "GIT_COMMITTER_NAME=ak",
	"GIT_COMMITTER_EMAIL=ak@localhost", "GIT_AUTHOR_DATE=2000-01-01T00:00:00Z", "GIT_COMMITTER_DATE=2000-01-01T00:00:00Z"}

// oversize refuses a first build's done while it adds more lines than the turn's checks allow,
// Python's hand_in.oversize: the commit the loop will make of the workspace's uncommitted work,
// counted from the base the gate after the turn counts from, so the builder learns it with its
// work in front of it.
func (t *turn) oversize() error {
	if t.checks == nil {
		return nil
	}
	limit, limited := t.checks.Int("lines") // a number, else "no limit"
	if !limited || t.checks.Str("base") == "" || t.checks.Truthy("scratch") {
		return nil
	}
	workspace, ok := t.workspace.(string)
	if !ok {
		return ErrPython
	}
	g := gitcall.Git{Repo: workspace}
	base, err := gitcall.IntegratedBase(g, t.checks.Str("base"), t.checks.Str("upstream"))
	if err != nil {
		return err
	}
	artifacts := map[string]bool{}
	for _, name := range t.checks.List("artifacts") {
		if name, ok := name.(string); ok {
			artifacts[name] = true
		}
	}
	tree, err := uncommitted.Tree(g, artifacts)
	if err != nil {
		return err
	}
	head, err := gitcall.Git{Repo: workspace, Env: stamp}.Must("commit-tree", tree, "-p", "HEAD", "-m", "hand-in")
	if err != nil {
		return err
	}
	why, err := size.Refusal(g, "this change", base, head, config.AtMost(limit))
	if why == "" || err != nil {
		return err
	}
	// A cut that drops asked-for behaviour fails review or the checks later, at more cost than a
	// split; so does packing code denser, which a reviewer reads no faster than the lines it saved.
	return errors.New("done refused: " + why + "\nMake the same change in fewer lines, every asked-for behaviour kept and " +
		"every line formatted as the project formats code (a denser line is no smaller a change), " +
		"or hand in `ak hand-in blocked \"why\"` naming the pieces it splits into.")
}
