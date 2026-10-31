package update

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/host"
)

// The swap of ~/agentkit for its next version, as Python's agentkit/versions.py makes it: each
// version a worktree of ak's repository at ~/.agentkit/agentkit.git, checked out whole under
// ~/.agentkit/versions and exchanged with ~/agentkit in one step (exchange), so a move cut off
// anywhere before that leaves ~/agentkit as it was.  A clone at ~/agentkit is adopted at its
// first move: its repository goes to agentkit.git, a link left in its place.

func repository() string {
	return filepath.Join(config.Home(), "agentkit.git")
}

// swap puts commit live at live, as Python's versions.switch: "" once it is or there is nothing
// to move, else why not, live then as it was.  Forward only, as a fast-forward went: a commit
// live already has moves nothing, and one beside it is refused.
func swap(env []string, live, commit string) string {
	live = config.Resolve(live) // a link at ~/agentkit stays, and what it names is swapped
	if _, ok := versionGit(env, live, "merge-base", "--is-ancestor", commit, "HEAD"); ok {
		return ""
	}
	if _, ok := versionGit(env, live, "merge-base", "--is-ancestor", "HEAD", commit); !ok {
		return fmt.Sprintf("%s is not ahead of what %s has", short(commit), live)
	}
	if why := adopt(live); why != "" {
		return why
	}
	versions := filepath.Join(config.Home(), "versions")
	tidy(env, live, versions)
	os.MkdirAll(versions, 0o777)
	next, err := os.MkdirTemp(versions, short(commit)+".")
	if err != nil {
		return pyError(err)
	}
	if said, ok := versionGit(env, repository(), "worktree", "add", "--quiet", "--detach", "--lock",
		"--reason", locked, next, commit); !ok {
		remove(env, next)
		return fmt.Sprintf("%s could not be checked out in %s: %s", short(commit), next, said)
	}
	info, err := os.Stat(live)
	if err == nil { // MkdirTemp's mode is the owner's alone
		err = os.Chmod(next, info.Mode()&(os.ModePerm|os.ModeSetuid|os.ModeSetgid|os.ModeSticky))
	}
	if err == nil {
		err = exchange(live, next)
	}
	if err != nil {
		remove(env, next)
		return fmt.Sprintf("%s could not be swapped in for %s: %s", next, live, pyError(err))
	}
	repair(env, live, next)
	return ""
}

// owned is git's record of live, the one its .git file names, when it is a version checked out
// here; "" for somebody's clone.
func owned(live string) string {
	named, err := os.ReadFile(filepath.Join(live, ".git"))
	if err != nil { // a repository of its own, a link to one, or none
		return ""
	}
	record := config.Resolve(under(live, strings.TrimFunc(strings.TrimPrefix(string(named), "gitdir: "), config.Space)))
	if filepath.Dir(filepath.Dir(record)) != config.Resolve(repository()) {
		return ""
	}
	return record
}

// adopt makes the clone at live one a version can be swapped in for: "" once it is, or why not.
func adopt(live string) string {
	repo, dot := repository(), filepath.Join(live, ".git")
	if owned(live) != "" {
		return ""
	}
	if _, err := os.Lstat(repo); err != nil {
		if info, err := os.Lstat(dot); err != nil || !info.IsDir() {
			return dot + " is no repository of its own"
		}
		if err := os.Rename(dot, repo); err != nil {
			return fmt.Sprintf("%s could not move to %s: %s", dot, repo, pyError(err))
		}
	}
	finish(live)
	if config.Resolve(dot) != config.Resolve(repo) {
		return fmt.Sprintf("%s is not %s, which is there already", dot, repo)
	}
	// a worktree added from the clone names its repository by the clone's path, which goes
	// with the clone: each is pointed at where the repository is now, as git itself would
	entries, _ := os.ReadDir(filepath.Join(repo, "worktrees"))
	for _, entry := range entries {
		admin := config.Resolve(filepath.Join(repo, "worktrees", entry.Name()))
		gitdir, err := os.ReadFile(filepath.Join(admin, "gitdir"))
		if err != nil {
			continue
		}
		gitfile := under(admin, strings.TrimFunc(string(gitdir), config.Space))
		said, err := os.ReadFile(gitfile)
		if err != nil {
			continue // gone, or none of this repository's: `git worktree prune`'s
		}
		named := under(filepath.Dir(gitfile), strings.TrimFunc(strings.TrimPrefix(string(said), "gitdir: "), config.Space))
		if named != admin && config.Resolve(named) == admin {
			os.WriteFile(gitfile, []byte("gitdir: "+admin+"\n"), 0o666)
		}
	}
	return ""
}

// finish puts in the link an adoption cut off between its two renames left out: until then git
// finds no repository at live, and nothing could move it.  The version live is locked: the code
// before the lock put it live without one.
func finish(live string) {
	repo, dot := repository(), filepath.Join(live, ".git")
	if info, err := os.Stat(repo); err == nil && info.IsDir() {
		if _, err := os.Lstat(dot); err != nil {
			os.Symlink(repo, dot)
		}
	}
	// as `git worktree lock` writes it, which finds a record by the path held in it
	if record := owned(live); record != "" {
		if info, err := os.Stat(record); err == nil && info.IsDir() {
			os.WriteFile(filepath.Join(record, "locked"), []byte(locked+"\n"), 0o666)
		}
	}
}

// tidy takes away each version under versions no process uses, and that holds nothing git finds
// changed or added in it.  Each version's record of where it is is put right first: one swap cut
// off before it left the two crossed, and git would remove the wrong one's.
func tidy(env []string, live, versions string) {
	entries, err := os.ReadDir(versions)
	if err != nil {
		return
	}
	found := make([]string, len(entries))
	for i, entry := range entries {
		found[i] = filepath.Join(versions, entry.Name())
	}
	if !repair(env, append([]string{live}, found...)...) {
		return // a record still crossed would have git remove the live one's
	}
	held, proof := host.Held()
	for _, path := range found {
		changes, ok := versionGit(env, path, "--no-optional-locks", "status", "--porcelain")
		// a checkout cut off part way lists only what it never wrote: nobody's work; a status
		// git could not read proves nothing
		kept := !ok || slices.ContainsFunc(config.SplitLines(changes), func(line string) bool {
			return line[:min(2, len(line))] != " D" && line[:min(2, len(line))] != "D "
		})
		resolved := config.Resolve(path)
		busy := !proof || slices.ContainsFunc(held, func(named string) bool {
			return named == resolved || strings.HasPrefix(named, resolved+"/")
		})
		if !kept && !busy {
			remove(env, path)
		}
	}
}

// repair is whether each version's record of where it is came out right: a swap leaves the two
// crossed.
func repair(env []string, paths ...string) bool {
	// the clone adopted is no worktree of the repository, and git would fail the lot over it
	paths = slices.DeleteFunc(paths, func(path string) bool { return !regular(filepath.Join(path, ".git")) })
	_, ok := versionGit(env, repository(), append([]string{"worktree", "repair"}, paths...)...)
	return ok
}

// remove takes a version under ~/.agentkit/versions, and git's record of it, away.
func remove(env []string, path string) {
	if _, ok := versionGit(env, repository(), "worktree", "remove", "--force", "--force", path); ok {
		return
	}
	if unlinked(path) {
		os.RemoveAll(path)
	}
	versionGit(env, repository(), "worktree", "unlock", path)
	versionGit(env, repository(), "worktree", "prune")
}

// unlinked is whether neither path nor a folder above it is a link, as Python's retention.safe
// asks before it removes anything; the rest it asks, that it is this user's own, holds for all
// of ~/.agentkit, which only its owner writes to.
func unlinked(path string) bool {
	for {
		info, err := os.Lstat(path)
		if err != nil || info.Mode()&os.ModeSymlink != 0 {
			return false
		}
		if path == filepath.Dir(path) {
			return true
		}
		path = filepath.Dir(path)
	}
}

// versionGit is one git command at where as Python's versions.git runs it, looking for no
// repository above it: what it said, stripped, and whether it exited 0.
func versionGit(env []string, where string, args ...string) (string, bool) {
	argv := append([]string{"git", "-C", where}, args...)
	ceiling := "GIT_CEILING_DIRECTORIES=" + filepath.Dir(where)
	stdout, stderr, code, err := output(append(slices.Clip(env), ceiling), stepCap, argv...)
	if err != nil {
		return failure(err, argv, stepCap), false
	}
	return strings.TrimFunc(string(stdout)+string(stderr), config.Space), code == 0
}

// under is name as Python's Path(base, name) reads it: base's where name is relative.
func under(base, name string) string {
	if filepath.IsAbs(name) {
		return filepath.Clean(name)
	}
	return filepath.Join(base, name)
}
