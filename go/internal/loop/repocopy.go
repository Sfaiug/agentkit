package loop

import (
	"fmt"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/uncommitted"
)

// inCopy runs a reviewer's turn in a mirror of its own, Python's reviewer_checkout: it keeps the
// source's base refs but owns its refs and index, where a linked worktree would still let a
// reviewer move the task branch.  Its edits survive only in the round's patch.
func (r *repoPlace) inCopy(l *loop, out string, turn func(string) error) error {
	wt := config.Resolve(r.wt)
	g := gitcall.Git{Repo: wt}
	checkout := filepath.Join(filepath.Dir(out), "review-checkout")
	gone := func() {
		writableDirs(l, checkout)
		os.RemoveAll(checkout)
	}
	gone()
	defer gone()
	if err := g.CloneBorrowing(filepath.Join(checkout, ".git"), "--mirror"); err != nil {
		return err
	}
	c := gitcall.Git{Repo: checkout}
	// keep the copied refs without a mirror push destination back into the source
	if _, err := c.Must("config", "--remove-section", "remote.origin"); err != nil {
		return err
	}
	if _, err := c.Must("config", "core.bare", "false"); err != nil {
		return err
	}
	// a mirror copies origin/HEAD as a commit; it names the default branch here as there
	named, err := g.Try("symbolic-ref", "-q", "refs/remotes/origin/HEAD")
	if err != nil {
		return err
	}
	if named != "" {
		if _, err := c.Must("symbolic-ref", "refs/remotes/origin/HEAD", named); err != nil {
			return err
		}
	}
	tree, err := g.Must("write-tree")
	if err != nil {
		return err
	}
	if _, err := c.Must("read-tree", tree); err != nil {
		return err
	}
	copyFiles(l, wt, checkout, true)
	for _, key := range []string{"user.name", "user.email"} {
		value, err := g.Try("config", "--get", key)
		if err != nil {
			return err
		}
		if value != "" {
			if _, err := c.Must("config", key, value); err != nil {
				return err
			}
		}
	}
	exclude, err := g.Must("rev-parse", "--git-path", "info/exclude")
	if err != nil {
		return err
	}
	if !filepath.IsAbs(exclude) {
		exclude = filepath.Join(wt, exclude)
	}
	if data, err := os.ReadFile(exclude); err == nil {
		os.WriteFile(filepath.Join(checkout, ".git", "info", "exclude"), data, 0o666)
	}
	return reviewerChanges(l, checkout, out, func() error { return turn(checkout) })
}

// copyFiles copies a checkout's files, links as links, leaving its .git and test sandboxes out; a
// file the live suite removed before it was copied is no loss.
func copyFiles(l *loop, source, destination string, top bool) {
	os.Mkdir(destination, 0o777)
	entries, err := os.ReadDir(source)
	if err != nil {
		l.say(fmt.Sprintf("WARN skipped %s in review checkout: %v", source, err))
		return
	}
	for _, entry := range entries {
		if top && (entry.Name() == ".git" || strings.HasPrefix(entry.Name(), uncommitted.SandboxPrefix)) {
			continue
		}
		from, to := filepath.Join(source, entry.Name()), filepath.Join(destination, entry.Name())
		info, err := entry.Info()
		switch {
		case os.IsNotExist(err):
		case err != nil:
			l.say(fmt.Sprintf("WARN skipped %s in review checkout: %v", from, err))
		case info.IsDir():
			copyFiles(l, from, to, false)
			os.Chmod(to, info.Mode().Perm())
			os.Chtimes(to, info.ModTime(), info.ModTime())
		case info.Mode()&os.ModeSymlink != 0:
			target, err := os.Readlink(from)
			if err == nil {
				err = os.Symlink(target, to)
			}
			if err != nil && !os.IsNotExist(err) {
				l.say(fmt.Sprintf("WARN skipped %s in review checkout: %v", from, err))
			}
		case info.Mode().IsRegular():
			data, err := os.ReadFile(from)
			if err == nil {
				err = os.WriteFile(to, data, info.Mode().Perm())
			}
			if err == nil {
				os.Chtimes(to, info.ModTime(), info.ModTime())
			}
			if err != nil && !os.IsNotExist(err) {
				l.say(fmt.Sprintf("WARN skipped %s in review checkout: %v", from, err))
			}
		default:
			l.say(fmt.Sprintf("WARN skipped %s in review checkout: not a regular file or link", from))
		}
	}
}

// writableDirs makes a copy's folders removable: git does not record directory modes.
func writableDirs(l *loop, path string) {
	info, err := os.Lstat(path)
	if err != nil || !info.IsDir() {
		return
	}
	if info.Mode().Perm()&0o700 != 0o700 {
		if os.Chmod(path, info.Mode().Perm()|0o700) == nil {
			l.say("WARN made reviewer directory writable for cleanup: " + path)
		}
	}
	entries, err := os.ReadDir(path)
	if err != nil {
		l.say(fmt.Sprintf("WARN skipped %s during reviewer cleanup: %v", path, err))
		return
	}
	for _, entry := range entries {
		if entry.IsDir() {
			writableDirs(l, filepath.Join(path, entry.Name()))
		}
	}
}

// reviewerChanges keeps what a reviewer's turn changed, however the turn ended, in the round's
// patch: a private index records untracked files too.  The copy goes after, so nothing is undone
// by hand.
func reviewerChanges(l *loop, checkout, out string, turn func() error) error {
	writableDirs(l, checkout)
	g := gitcall.Git{Repo: checkout}
	head, err := g.Must("rev-parse", "HEAD")
	if err != nil {
		return err
	}
	branch, err := g.Try("symbolic-ref", "--quiet", "HEAD")
	if err != nil {
		return err
	}
	before, err := uncommitted.Paths(g)
	if err != nil {
		return err
	}
	staged, err := g.Must("write-tree")
	if err != nil {
		return err
	}
	tmp, err := os.MkdirTemp("", "ak-index-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(tmp)
	private := gitcall.Git{Repo: checkout, Env: []string{"GIT_INDEX_FILE=" + filepath.Join(tmp, "index")}}
	if _, err := private.Must("read-tree", head); err != nil {
		return err
	}
	var skipped []string
	snapshot := func() (string, error) {
		_, err := private.Must("add", "--ignore-errors", "-A", "--", ".")
		if stopped := asStopped(err); stopped != nil {
			return "", stopped
		}
		if err != nil {
			skipped = append(skipped, err.Error())
			l.say(fmt.Sprintf("WARN skipped unreadable reviewer paths: %v", err))
		}
		return private.Must("write-tree")
	}
	tree, err := snapshot()
	if err != nil {
		return err
	}
	turned := turn()
	writableDirs(l, checkout)
	if err := saveChanges(l, g, snapshot, out, head, branch, tree, staged, before, &skipped); err != nil && turned == nil {
		return err
	}
	return turned
}

func saveChanges(l *loop, g gitcall.Git, snapshot func() (string, error), out, head, branch, tree, staged string, before []string, skipped *[]string) error {
	after, err := g.Try("rev-parse", "--verify", "--quiet", "HEAD^{commit}")
	if err != nil {
		return err
	}
	branchAfter, err := g.Try("symbolic-ref", "--quiet", "HEAD")
	if err != nil {
		return err
	}
	// a conflicted index has no tree, but its staged diff and entries remain readable
	indexDiff, err := g.Must("diff", "--cached", "--binary", staged)
	if err != nil {
		return err
	}
	treeAfter, err := snapshot()
	if err != nil {
		return err
	}
	if len(*skipped) == 0 && indexDiff == "" && after == head && branchAfter == branch && treeAfter == tree {
		return nil
	}
	path := filepath.Join(filepath.Dir(out), "reviewer-changes.patch")
	saved, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o666)
	if err != nil {
		return err
	}
	defer saved.Close()
	shown := after
	if shown == "" {
		shown = "unborn HEAD"
	}
	fmt.Fprintf(saved, "# %s: HEAD %s -> %s\n", filepath.Base(out), head, shown)
	for _, each := range *skipped {
		fmt.Fprintf(saved, "# skipped: %s\n", strings.ReplaceAll(each, "\n", "\n# "))
	}
	if branchAfter != branch {
		fmt.Fprintf(saved, "# checkout: %s -> %s\n", detached(branch), detached(branchAfter))
	}
	dirty, err := uncommitted.Paths(g)
	if err != nil {
		return err
	}
	touched := map[string]bool{}
	for _, each := range dirty {
		if !slices.Contains(before, each) {
			touched[each] = true
		}
	}
	seen := map[string]bool{}
	sections := [][]string{{"checkout", tree, treeAfter}}
	if after != "" {
		sections = append(sections, []string{"commits", head, after})
	}
	sections = append(sections, []string{"index", "--cached", staged})
	for _, section := range sections {
		diff, err := g.Must(append([]string{"diff", "--binary"}, section[1:]...)...)
		if err != nil {
			return err
		}
		names, err := g.Must(append([]string{"diff", "--name-only", "-z"}, section[1:]...)...)
		if err != nil {
			return err
		}
		for _, each := range paths(names) {
			touched[each] = true
		}
		if diff != "" && !seen[diff] {
			fmt.Fprintf(saved, "# %s\n%s\n", section[0], diff)
			seen[diff] = true
		}
	}
	unmerged, err := g.Must("ls-files", "--unmerged")
	if err != nil {
		return err
	}
	if unmerged != "" {
		fmt.Fprintf(saved, "# unmerged index\n# %s\n", strings.ReplaceAll(unmerged, "\n", "\n# "))
	}
	undone := strings.Join(slices.Sorted(maps.Keys(touched)), ", ")
	if undone == "" && len(*skipped) > 0 {
		undone = "unreadable paths"
	}
	if after != head {
		moved := "unborn HEAD"
		if after != "" {
			moved = "commit " + after[:min(len(after), 12)]
		}
		undone = strings.TrimSuffix(fmt.Sprintf("%s back to %s; %s", moved, head[:12], undone), "; ")
	}
	if branchAfter != branch {
		undone = strings.TrimSuffix(fmt.Sprintf("checkout back to %s; %s", detached(branch), undone), "; ")
	}
	l.say(fmt.Sprintf("WARN undid reviewer changes: %s; saved %s", undone, path))
	return nil
}

func detached(branch string) string {
	if branch == "" {
		return "detached HEAD"
	}
	return branch
}
