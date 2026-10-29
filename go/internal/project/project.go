// Package project is which project a folder is filed under: a named checkout directly under
// ~/code, or ak's own at ~/agentkit beside it, which a git worktree added from one of them, a
// second clone of agentkit and any folder inside one stand for too.
package project

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"agentkit/internal/config"
)

// Of is the checkout of the project dir is filed under, the nearest of dir and the folders
// above it that is one, and "" for none.
func Of(dir string) string {
	found := listed()
	for dir = config.Resolve(dir); ; dir = filepath.Dir(dir) {
		if project := checkoutOf(dir, found); project != "" || dir == filepath.Dir(dir) {
			return project
		}
	}
}

// A checkout is one listed checkout and the project's checkout it stands for.
type checkout struct{ path, project string }

func checkoutOf(path string, found []checkout) string {
	for _, each := range found {
		if config.Resolve(each.path) == path {
			return each.project
		}
	}
	if common, added, ok := gitDirs(path); ok && added {
		for _, each := range found {
			if theirs, _, ok := gitDirs(each.path); ok && theirs == common {
				return each.project
			}
		}
	}
	if filepath.Dir(path) == config.Resolve(code()) {
		for _, each := range found {
			if filepath.Base(each.project) == filepath.Base(path) {
				return each.project
			}
		}
	}
	return ""
}

// listed are the checkouts that stand for a project: each repository's own checkout under
// ~/code, never a worktree of one listed, and agentkit's own, which a clone named like it
// stands for.
func listed() []checkout {
	var found []string
	entries, _ := os.ReadDir(code())
	for _, entry := range entries {
		path := filepath.Join(code(), entry.Name())
		if isDir(path) && exists(filepath.Join(path, ".git")) {
			found = append(found, path)
		}
	}
	sort.Strings(found)
	own := config.Expand("~/agentkit")
	type dirs struct {
		common      string
		added, repo bool
	}
	known := map[string]dirs{}
	mains := map[string]bool{}
	for _, path := range append(found, own) {
		common, added, ok := gitDirs(path)
		known[path] = dirs{common, added, ok}
		if ok && (!added || path == own || filepath.Base(path) == filepath.Base(own)) {
			mains[common] = true
		}
	}
	var kept []checkout
	ownListed := false
	for _, path := range found {
		if each := known[path]; !each.repo || !mains[each.common] || !each.added || filepath.Base(path) == filepath.Base(own) {
			kept = append(kept, checkout{path, path})
			ownListed = ownListed || config.Resolve(path) == config.Resolve(own)
		}
	}
	if !exists(filepath.Join(own, ".git")) || ownListed {
		return kept
	}
	for i := range kept {
		if filepath.Base(kept[i].path) == filepath.Base(own) {
			kept[i].project = own
		}
	}
	return append(kept, checkout{own, own})
}

// gitDirs are the repository's common git directory and whether path is a worktree added from
// another checkout, for the checkout at path; git is asked about no folder above it.
func gitDirs(path string) (string, bool, bool) {
	dot := filepath.Join(path, ".git")
	info, err := os.Lstat(dot)
	if err != nil {
		return "", false, false
	}
	if info.IsDir() && !exists(filepath.Join(dot, "commondir")) {
		return config.Resolve(dot), false, true
	}
	ask := func(flags ...string) ([]string, bool) {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		git := exec.CommandContext(ctx, "git", append([]string{"rev-parse", "--path-format=absolute"}, flags...)...)
		git.Dir = path
		for _, entry := range os.Environ() {
			if !strings.HasPrefix(entry, "GIT_") {
				git.Env = append(git.Env, entry)
			}
		}
		parent, _ := filepath.Abs(filepath.Dir(path))
		git.Env = append(git.Env, "GIT_CEILING_DIRECTORIES="+parent)
		out, err := git.Output()
		return strings.Split(strings.TrimSuffix(string(out), "\n"), "\n"), err == nil
	}
	lines, ok := ask("--git-dir", "--git-common-dir")
	if ok && len(lines) != 2 { // a path holding a newline: one at a time
		gitDir, mine := ask("--git-dir")
		common, theirs := ask("--git-common-dir")
		lines, ok = []string{strings.Join(gitDir, "\n"), strings.Join(common, "\n")}, mine && theirs
	}
	if !ok {
		return "", false, false
	}
	gitDir, common := config.Resolve(lines[0]), config.Resolve(lines[1])
	return common, gitDir != common, true
}

func code() string { return config.Expand("~/code") }

func isDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
