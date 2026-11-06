package gc

import (
	"fmt"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// How the collector takes a checkout, and what it does with one it cannot take whole.

// takeStale takes a checkout staleWorktree planned, once it proves the same again under its run's
// recovery lock, where a resume commits: an orphan cleared by hand, a passed run's dropped as a
// run's checkout goes, its branch kept (gc.gc).
func takeStale(wt string, orphan bool) func(*collection) (bool, error) {
	return func(c *collection) (bool, error) {
		dir := filepath.Join(runsDir(), filepath.Base(wt))
		if present(dir) && (!safe(dir) || !recoverySafe(dir)) {
			return false, nil
		}
		r := &reads{now: epoch(), paths: processPaths()} // read before our own lock is open
		if present(dir) {
			release, err := run.Hold(dir)
			if err != nil {
				return false, err
			}
			defer release()
		}
		r.left = r.leftovers()
		if _, ok := r.staleWorktree(wt); !ok {
			return false, nil
		}
		if orphan {
			c.clearTree(wt)
			return !c.leftBehind(wt), nil
		}
		return c.dropTree(orEmpty(r.json(filepath.Join(dir, "run.json"))), wt, false, false)
	}
}

// dropTree takes a run's checkout as every ending does, true once it is gone (gc.drop_tree).
// What a removal it was allowed to make could not take is leftBehind's to judge; a refusal (a
// loop still going, a tree not the run's own, one through a link or under ~/code) is never
// followed by a removal by hand.  dropBranch takes the branch whatever the run, as the collection
// taking the run whole does; withRun releases a run whose loop is gone, as that collection proved
// it old.
func (c *collection) dropTree(state *run.Object, tree string, dropBranch, withRun bool) (bool, error) {
	released := provablyFinal(state) || withRun && pidGone(state)
	allowed := tree != "" && ownTree(state) == tree && released && clearable(tree)
	if state.Truthy("scratch") {
		allowed = allowed && filepath.Dir(tree) == workDir() && withRun
	} else {
		allowed = allowed && state.Truthy("repo") && state.Truthy("worktree") && config.Pure(state.Str("worktree")) != config.Pure(state.Str("repo"))
	}
	if err := c.dropCheckout(state, dropBranch, withRun, released); err != nil {
		if !allowed || c.leftBehind(tree) && !(&reads{}).leftovers()[tree] {
			return false, err
		}
		return !present(tree), nil
	}
	if !allowed || state.Truthy("checkout_kept") && !dropBranch && !state.Truthy("merged") {
		return tree == "" || !present(tree), nil
	}
	return !c.leftBehind(tree), nil
}

// dropCheckout is a released run's checkout gone, its branch with it where merged or dropped; a
// scratch run's workspace only with the run (worktrees.drop_checkout).
func (c *collection) dropCheckout(state *run.Object, dropBranch, withRun, released bool) error {
	wt, _ := state.Get("worktree").(string)
	if !released || wt == "" || config.UnderCode(wt) {
		return nil
	}
	id, _ := state.Get("run_id").(string)
	if state.Truthy("scratch") {
		if id != "" && config.Pure(wt) == filepath.Join(workDir(), id) && isDir(wt) && !isLink(wt) && safe(wt) && withRun {
			return os.RemoveAll(wt)
		}
		return nil
	}
	loop.StopCheckout(filepath.Join(runsDir(), id), state, c.report, !dropBranch && !state.Truthy("merged"))
	return nil
}

// ownTree is a run's own checkout or scratch workspace, ~/.agentkit/wt/<id> or work/<id>: the
// one tree of a run gc removes; "" for anything else (gc.own_tree).
func ownTree(state *run.Object) string {
	id, _ := state.Get("run_id").(string)
	wt, _ := state.Get("worktree").(string)
	if id == "" || wt == "" {
		return ""
	}
	if tree := config.Pure(wt); tree == filepath.Join(wtDir(), id) || tree == filepath.Join(workDir(), id) {
		return tree
	}
	return ""
}

// clearTree takes all of a tree this user can remove, then git's registration of it in the
// repository git names, unlocked first: git never prunes a locked one (gc.clear_tree).
func (c *collection) clearTree(tree string) {
	common, linked, ok := gitDirs(tree)
	os.RemoveAll(tree)
	if !ok || !linked || !isDir(common) {
		return
	}
	// named, not found by looking: git's safe.bareRepository refuses one it only finds
	g := gitcall.Git{Repo: common}
	for _, args := range [][]string{{"worktree", "unlock", tree}, {"worktree", "prune"}} {
		if _, _, err := g.Out(append([]string{"--git-dir=" + common}, args...)...); err != nil {
			c.report(fmt.Sprintf("gc: %s: %s", tree, err))
			return
		}
	}
}

// leftBehind is whether a tree gc just tried to remove is still there (gc.left_behind).  One
// holding what this user cannot remove, root's from a container build, gives up what is ours and
// is written down in gc-leftovers.json and said once: no daily retry changes it, so every plan
// passes it by from then on.  One there for any other reason, or not clearable, is left as it is.
func (c *collection) leftBehind(tree string) bool {
	if !present(tree) {
		return false
	}
	if !clearable(tree) || !unremovable(tree) {
		return true
	}
	c.clearTree(tree)
	if !present(tree) {
		return false
	}
	left := run.NewObject()
	if record := (&reads{}).json(filepath.Join(config.Home(), "state", "gc-leftovers.json")); record != nil {
		for _, path := range record.Keys() {
			if present(path) {
				left.Set(path, record.Get(path))
			}
		}
	}
	if !left.Has(tree) {
		left.Set(tree, run.Float(epoch()))
		writeJSON(filepath.Join(config.Home(), "state", "gc-leftovers.json"), left)
		c.report(fmt.Sprintf("gc: left %s: it holds files this user cannot remove; `sudo rm -rf %s` takes them, "+
			"and gc will not try again", tree, tree))
	}
	return true
}

// unremovable is a tree holding a folder this user cannot empty: another user's, or one shut to
// writing (gc.unremovable).
func unremovable(tree string) bool {
	found := shut(tree)
	filepath.WalkDir(tree, func(path string, entry os.DirEntry, err error) error {
		if found || err != nil || path == tree {
			return nil
		}
		if entry.IsDir() && shut(path) {
			found = true
		}
		return nil
	})
	return found
}

// recoverySafe is a recovery lock retention may open: no link, and ours where it stands.
func recoverySafe(dir string) bool {
	recovery := filepath.Join(dir, run.RecoveryLock)
	return !isLink(recovery) && !unsafe(recovery)
}

func orEmpty(record *run.Object) *run.Object {
	if record == nil {
		return run.NewObject()
	}
	return record
}

func workDir() string { return filepath.Join(config.Home(), "work") }
