package loop

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"sort"
	"strings"

	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// sandboxPrefix is what the suites name every sandbox they leave inside a checkout when a test is
// killed mid-way: never committed, and removed before the next turn.
const sandboxPrefix = ".ak-test-"

// excludeJunk hides the usual build junk from git in the checkout, Python's exclude_junk: the
// executor's own __pycache__ is there when the leftover sweep looks.  `--git-path` names the
// shared exclude file, which belongs to the repository: only the patterns it is missing are
// appended, nothing is rewritten.  Failing ends the run, before any model call.
func (r *repoPlace) excludeJunk(l *loop) error {
	path, missing, err := r.excluded()
	var stopped *gitcall.Stopped
	if errors.As(err, &stopped) {
		return err
	}
	if err != nil {
		return fmt.Errorf("cannot exclude build junk in %s: %w; without that git would hand the executor's own __pycache__ to the leftover sweep", r.wt, err)
	}
	if len(missing) > 0 {
		l.say(fmt.Sprintf("excluded build junk in %s: %s", path, strings.Join(missing, ", ")))
	}
	return nil
}

func (r *repoPlace) excluded() (string, []string, error) {
	path, err := r.git().Must("rev-parse", "--git-path", "info/exclude")
	if err != nil {
		return "", nil, err
	}
	if !filepath.IsAbs(path) {
		path = filepath.Join(r.wt, path)
	}
	data, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return "", nil, err
	}
	text := gitcall.Decoded(string(data))
	lines := strings.Split(strings.ReplaceAll(text, "\r\n", "\n"), "\n")
	var missing []string
	for _, pattern := range gitcall.Junk {
		if !slices.Contains(lines, pattern) {
			missing = append(missing, pattern)
		}
	}
	if len(missing) == 0 {
		return path, nil, nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		return "", nil, err
	}
	file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o666)
	if err != nil {
		return "", nil, err
	}
	defer file.Close()
	lead := ""
	if text != "" && !strings.HasSuffix(text, "\n") {
		lead = "\n"
	}
	_, err = file.WriteString(lead + "# agentkit: build junk a run must never commit\n" + strings.Join(missing, "\n") + "\n")
	return path, missing, err
}

// sweepSandboxes removes killed tests' sandboxes from the checkout before a turn starts: the
// next executor would otherwise find stub binaries and fake adapters in it.
func (r *repoPlace) sweepSandboxes(l *loop) {
	entries, err := os.ReadDir(r.wt)
	if err != nil {
		l.say(fmt.Sprintf("WARN could not list test sandboxes in %s: %v", r.wt, err))
		return
	}
	var removed []string
	for _, entry := range entries {
		if !strings.HasPrefix(entry.Name(), sandboxPrefix) {
			continue
		}
		if err := os.RemoveAll(filepath.Join(r.wt, entry.Name())); err != nil {
			l.say(fmt.Sprintf("WARN could not remove test sandbox %s: %v", entry.Name(), err))
			continue
		}
		removed = append(removed, entry.Name())
	}
	if len(removed) > 0 {
		l.say("removed test sandboxes left by a killed test: " + strings.Join(removed, ", "))
	}
}

// paths splits git's NUL-separated names, none empty.
func paths(listed ...string) []string {
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

// dirtyPaths is every uncommitted path, no ignored one, Python's dirty_paths: `--no-renames` keeps
// both paths, so a selected commit takes a rename's deletion too.
func dirtyPaths(g gitcall.Git) ([]string, error) {
	tracked, err := g.Try("diff", "--no-renames", "--name-only", "-z", "HEAD")
	if err != nil {
		return nil, err
	}
	untracked, err := g.Try("ls-files", "--others", "--exclude-standard", "-z")
	if err != nil {
		return nil, err
	}
	return paths(tracked, untracked), nil
}

// leftoverJunk matches names, not targets: a dependency symlink is junk even when git ignores only
// directories.
func leftoverJunk(path string) bool {
	parts := strings.Split(strings.TrimRight(path, "/"), "/")
	return strings.HasPrefix(parts[0], sandboxPrefix) || slices.ContainsFunc(parts, func(part string) bool {
		return part == run.RecoveryLock || part == "delivery.lock" || part == "node_modules" || part == "venv" || part == ".venv"
	})
}

// committablePaths is the dirty paths a commit of the checkout would take and the leftover junk it
// leaves, Python's committable_paths, the one rule of what a run's uncommitted work is.
func committablePaths(g gitcall.Git, artifacts map[string]bool) (real, left []string, err error) {
	dirty, err := dirtyPaths(g)
	if err != nil {
		return nil, nil, err
	}
	for _, path := range dirty {
		if artifacts[path] {
			continue
		}
		ignored := leftoverJunk(path)
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

// addPaths stages selected work that still has a file or an entry in this index: a staged rename
// already removed its old entry, so add cannot match that path.
func addPaths(g gitcall.Git, wt string, selected []string) error {
	listed, err := g.Must("ls-files", "-z")
	if err != nil {
		return err
	}
	indexed := paths(listed)
	var args []string
	for _, path := range selected {
		_, statErr := os.Lstat(filepath.Join(wt, path))
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

// ignoredSandboxes is ignored sandbox files, run locks and dependencies, invisible to dirtyPaths,
// each collapsed directory listed by its files, for the line that counts them.
func (r *repoPlace) ignoredSandboxes() ([]string, error) {
	listed, err := r.git().Try("ls-files", "--others", "--ignored", "--exclude-standard", "-z")
	if err != nil {
		return nil, err
	}
	var found []string
	for _, entry := range paths(listed) {
		if r.artifacts[entry] || !leftoverJunk(entry) {
			continue
		}
		if !strings.HasSuffix(entry, "/") {
			found = append(found, entry)
			continue
		}
		filepath.WalkDir(filepath.Join(r.wt, entry), func(path string, item fs.DirEntry, err error) error {
			if err == nil && !item.IsDir() {
				if relative, _ := filepath.Rel(r.wt, path); !r.artifacts[relative] {
					found = append(found, relative)
				}
			}
			return nil
		})
	}
	return found, nil
}

// commitLeftovers commits what the executor left uncommitted, Python's commit_leftovers: the
// reviewer reads only `base...HEAD`, and a review of nothing is worse than no review.  What the
// done-when generated, sandboxes, run locks and dependency trees stay out, nothing of them staged.
// The commit is built in an index of its own, as `git commit -- venv` would add the link back from
// the worktree and the real index keeps whatever else the executor staged.
func (r *repoPlace) commitLeftovers(l *loop) error {
	g := r.git()
	real, left, err := committablePaths(g, r.artifacts)
	if err != nil {
		return err
	}
	status, err := g.Try("diff", "--cached", "--name-status", "--no-renames", "-z", "HEAD")
	if err != nil {
		return err
	}
	fields := strings.Split(status, "\x00")
	staged := map[string]string{}
	for i := 0; i+1 < len(fields); i += 2 {
		staged[fields[i+1]] = fields[i]
	}
	var gone, unstage []string
	for _, path := range left {
		if letter, found := staged[path]; found && letter == "D" {
			gone = append(gone, path)
		} else if found {
			unstage = append(unstage, path)
		}
	}
	sort.Strings(gone)
	sort.Strings(unstage)
	ignored, err := r.ignoredSandboxes()
	if err != nil {
		return err
	}
	sandbox := slices.Compact(slices.Sorted(slices.Values(append(left, ignored...))))
	if len(sandbox) > 0 {
		l.say(fmt.Sprintf("left %d untracked sandbox files uncommitted: %s", len(sandbox), strings.Join(sandbox[:min(3, len(sandbox))], ", ")))
	}
	err = r.commitPaths(l, real, gone, unstage)
	var stopped *gitcall.Stopped
	if errors.As(err, &stopped) {
		return err // a git that stopped verifies nothing: the round ends on the stop
	}
	if err != nil {
		l.say(fmt.Sprintf("WARN could not commit the executor's uncommitted changes: %v", err))
	}
	return nil
}

func (r *repoPlace) commitPaths(l *loop, real, gone, unstage []string) error {
	g := r.git()
	if len(unstage) > 0 {
		if _, err := g.Must(append([]string{"reset", "-q", "--"}, unstage...)...); err != nil {
			return err
		}
		l.say(fmt.Sprintf("unstaged %d sandbox files the executor staged: %s", len(unstage), strings.Join(unstage[:min(3, len(unstage))], ", ")))
	}
	if len(real) == 0 && len(gone) == 0 {
		return nil
	}
	if len(real) > 0 {
		if err := addPaths(g, r.wt, real); err != nil {
			return err
		}
	}
	tmp, err := os.MkdirTemp("", "ak-index-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(tmp)
	private := r.git("GIT_INDEX_FILE=" + filepath.Join(tmp, "index"))
	if _, err := private.Must("read-tree", "HEAD"); err != nil {
		return err
	}
	if len(real) > 0 {
		if err := addPaths(private, r.wt, real); err != nil {
			return err
		}
	}
	if len(gone) > 0 {
		if _, err := private.Must(append([]string{"rm", "-q", "--cached", "--"}, gone...)...); err != nil {
			return err
		}
	}
	if _, err := private.Must("commit", "-m", r.title); err != nil {
		return err
	}
	l.say("WARN committed uncommitted executor changes: " + strings.Join(append(append([]string{}, real...), gone...), ", "))
	return nil
}
