package tick

import (
	"cmp"
	"errors"
	"path/filepath"
	"strings"

	"agentkit/internal/gitcall"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// revertRun is the rest of after_merge_revert for a broken release whose diff a code revert
// undoes: one run its seat owns, launched ahead of the queue as the repair of the target it merged
// into, holding `git revert`, `-m 1` for a merge commit, and checked by the target's tip being the
// release's revert.  An older revert of it, whatever became of it, is that release's revert still.
// The line its seat is told instead of a break, "" where none starts; errLeft, nothing written,
// where Go does not carry its launch.
func revertRun(each *merge, say func(string)) (string, error) {
	code, parents, err := gitcall.Git{Repo: each.record.Str("repo")}.Out("rev-list", "--parents", "-n", "1", each.sha)
	if err != nil || code != 0 {
		return "", err
	}
	command := "git revert " + each.sha
	if len(strings.Fields(parents)) > 2 {
		command = "git revert -m 1 " + each.sha
	}
	state := each.record.Copy()
	state.Set("target", mergedInto(each.record))
	name, err := loop.StartRepair(state, filepath.Join(run.Runs(), each.name), run.Fields("revert", each.sha, "sha", each.sha,
		"command", command,
		"text", "Revert the broken live release from run "+each.name+" with `"+command+"`. Make no other changes; "+
			"review and land through the normal line.",
		"check", "tree=$(git merge-tree --write-tree --merge-base="+each.sha+" HEAD^ "+each.sha+"^) && "+
			`test "$(git rev-parse HEAD^{tree})" = "$tree"`), say)
	if errors.Is(err, loop.ErrLeft) {
		return "", errLeft
	}
	if name == "" {
		return "", err
	}
	return "Live health fails; revert run " + name + ".", err
}

// mergedInto is the branch a merge's run merged into, short: `origin/main` is `main` (after_merge_target).
func mergedInto(record *run.Object) string {
	branch := any("main")
	for _, key := range []string{"base", "target"} {
		if record.Truthy(key) {
			branch = record.Get(key)
		}
	}
	target, _ := branch.(string)
	return cmp.Or(strings.TrimPrefix(target, "origin/"), "main")
}
