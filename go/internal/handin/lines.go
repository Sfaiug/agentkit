package handin

import (
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/size"
)

// oversize is the refusal of a first build adding more lines than the turn's checks allow, "" for
// none, Python's hand_in.oversize: the commit the loop will make of the workspace's tree, counted
// as the gate after the turn counts it, so the builder learns it with its work in front of it.
func (t *turn) oversize(g gitcall.Git, base, tree string) (string, error) {
	limit, limited := t.checks.Int("lines") // a number, else "no limit"
	if !limited {
		return "", nil
	}
	head, err := gitcall.Git{Repo: g.Repo, Env: gitcall.Stamp}.Must("commit-tree", tree, "-p", "HEAD", "-m", "hand-in")
	if err != nil {
		return "", err
	}
	why, err := size.Refusal(g, "this change", base, head, config.AtMost(limit))
	if why == "" || err != nil {
		return "", err
	}
	// A cut that drops asked-for behaviour fails review or the checks later, at more cost than a
	// split; so does packing code denser, which a reviewer reads no faster than the lines it saved.
	return why + "\nMake the same change in fewer lines, every asked-for behaviour kept and " +
		"every line formatted as the project formats code (a denser line is no smaller a change), " +
		"or hand in `ak hand-in blocked \"why\"` naming the pieces it splits into.", nil
}
