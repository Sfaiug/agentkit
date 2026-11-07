// Package uncommitted is the one rule of what a run's uncommitted work is, Python's dirty_paths,
// committable_paths, add_paths and leftover_tree: what the loop commits of a checkout after a
// turn, and what `ak hand-in done` counts before the turn ends.
package uncommitted

import (
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// SandboxPrefix is what the suites name every sandbox they leave inside a checkout when a test is
// killed mid-way: never committed, and removed before the next turn.
const SandboxPrefix = ".ak-test-"

// names splits git's NUL-separated names, none empty.
func names(listed ...string) []string {
	var found []string
	for _, text := range listed {
		for _, path := range strings.Split(text, "\x00") {
			if path != "" {
				found = append(found, path)
			}
		}
	}
	return found
}

// Paths is every uncommitted path, no ignored one, Python's dirty_paths: `--no-renames` keeps
// both paths, so a selected commit takes a rename's deletion too.
func Paths(g gitcall.Git) ([]string, error) {
	tracked, err := g.Try("diff", "--no-renames", "--name-only", "-z", "HEAD")
	if err != nil {
		return nil, err
	}
	untracked, err := g.Try("ls-files", "--others", "--exclude-standard", "-z")
	if err != nil {
		return nil, err
	}
	return names(tracked, untracked), nil
}

// Junk is whether path in wt is a test sandbox, a run lock, a dependency tree or a Go build cache,
// Python's leftover_junk.  Names match, not targets: a dependency symlink is junk even when git
// ignores only directories.
func Junk(wt, path string) bool {
	parts := strings.Split(strings.TrimRight(path, "/"), "/")
	return strings.HasPrefix(parts[0], SandboxPrefix) || slices.ContainsFunc(parts, func(part string) bool {
		return part == run.RecoveryLock || part == "delivery.lock" || part == "node_modules" || part == "venv" || part == ".venv"
	}) || goBuildCache(wt, path)
}

// Committable is the dirty paths a commit of the checkout would take and the leftover junk it
// leaves, Python's committable_paths.
func Committable(g gitcall.Git, artifacts map[string]bool) (real, left []string, err error) {
	dirty, err := Paths(g)
	if err != nil {
		return nil, nil, err
	}
	for _, path := range dirty {
		if artifacts[path] {
			continue
		}
		ignored := Junk(g.Repo, path)
		if !ignored {
			code, _, err := g.Out("check-ignore", "-q", "--", path)
			if err != nil {
				return nil, nil, err
			}
			ignored = code == 0
		}
		if ignored {
			left = append(left, path)
		} else {
			real = append(real, path)
		}
	}
	return real, left, nil
}

// Add stages selected work that still has a file or an entry in g's index: a staged rename
// already removed its old entry, so add cannot match that path.
func Add(g gitcall.Git, selected []string) error {
	listed, err := g.Must("ls-files", "-z")
	if err != nil {
		return err
	}
	indexed := names(listed)
	var args []string
	for _, path := range selected {
		_, statErr := os.Lstat(filepath.Join(g.Repo, path))
		if slices.Contains(indexed, path) || statErr == nil {
			args = append(args, ":(literal)"+path)
		}
	}
	if len(args) == 0 {
		return nil
	}
	_, err = g.Must(append([]string{"add", "--"}, args...)...)
	return err
}

// Tree is the tree of the commit the loop makes of the checkout's uncommitted work, Python's
// leftover_tree: HEAD's, with the committable paths as the checkout holds them and the junk staged
// as deleted gone, built in an index of its own, as the loop builds its commit.  That index file,
// index, is then the checkout's as the loop leaves it (leave), for the reads Git makes in one.
func Tree(g gitcall.Git, artifacts map[string]bool, index string) (string, error) {
	real, left, err := Committable(g, artifacts)
	if err != nil {
		return "", err
	}
	deleted, err := g.Must("diff", "--cached", "--name-only", "--no-renames", "--diff-filter=D", "-z", "HEAD")
	if err != nil {
		return "", err
	}
	staged := names(deleted)
	gone := slices.DeleteFunc(slices.Clone(left), func(path string) bool { return !slices.Contains(staged, path) })
	private := gitcall.Git{Repo: g.Repo, Env: append(slices.Clone(g.Env), "GIT_INDEX_FILE="+index), Cap: g.Cap}
	if _, err := private.Must("read-tree", "HEAD"); err != nil {
		return "", err
	}
	if err := Add(private, real); err != nil {
		return "", err
	}
	if len(gone) > 0 {
		if _, err := private.Must(append([]string{"rm", "-q", "--cached", "--"}, gone...)...); err != nil {
			return "", err
		}
	}
	tree, err := private.Must("write-tree")
	if err != nil {
		return "", err
	}
	return tree, leave(g, private, index, real, slices.DeleteFunc(left, func(path string) bool { return slices.Contains(gone, path) }))
}
