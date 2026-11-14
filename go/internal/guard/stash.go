package guard

import (
	"os/exec"
	"slices"
	"strings"
)

// gitRefusal is why the seat's git may not run: a checkout it makes in ~/code (worktreeRefusal),
// or a stash in a repository whose checkouts share one stash list (stashRefusal).
func gitRefusal(args []string, real string) (string, error) {
	if reason, err := worktreeRefusal(args, real); reason != "" || err != nil {
		return reason, err
	}
	return stashRefusal(args, real)
}

// stashRefusal is why the seat's `git stash`, its command read past git's own options before it,
// may not run: its repository has more than one checkout, as the real git given those options
// lists them, and they share one stash list, so a pop, apply or drop takes the entry on top,
// whoever put it there.  `list` and `show` only read it; no word, or an option, is `push`.  Where
// that git cannot list the checkouts nothing is refused, and git answers the call as typed.
func stashRefusal(args []string, real string) (string, error) {
	i := 0
	for i < len(args) && strings.HasPrefix(args[i], "-") {
		i++
		if slices.Contains(gitValued, args[i-1]) {
			i++
		}
	}
	if i >= len(args) || args[i] != "stash" || i+1 < len(args) && (args[i+1] == "list" || args[i+1] == "show") {
		return "", nil
	}
	listed, err := exec.Command(real, slices.Concat(args[:i], []string{"worktree", "list", "--porcelain"})...).Output()
	// each checkout's record opens with a line of its own starting `worktree `
	if err != nil || strings.Count("\n"+string(listed), "\nworktree ") < 2 {
		return "", nil
	}
	return "ak refused `git stash`: this repository's checkouts share one stash list, so an entry " +
		"is any checkout's to take and the one on top may not be yours. Keep the change in a " +
		"file (`git diff HEAD > FILE`, and `git apply FILE` brings it back) or on a commit of " +
		"its own.", nil
}
