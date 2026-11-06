package loop

import (
	"cmp"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/helper"
	"agentkit/internal/run"
)

func checkTurn(turn, code string, said io.Writer) error {
	said = &sharedOut{out: said}
	defer waking(filepath.Base(turn), said)()
	members := lineMembers(filepath.Base(turn))
	index := slices.IndexFunc(members, func(m member) bool {
		return m.record.Str("state") == "waiting" && !m.record.Dict("waiting_on").Has("fix") && !run.ProcessActive(m.record)
	})
	if index < 0 {
		return nil
	}
	saved := members[index].record
	repo := cmp.Or(saved.Str("worktree"), saved.Str("repo"))
	if err := gitcall.NoAutoGC(repo); err != nil {
		return err
	}
	// the repository's machine-side settings, as a run's own checks get them
	env, err := config.RepoEnv(saved.Str("repo"))
	if err != nil {
		return err
	}
	for key, value := range env {
		os.Setenv(key, value)
	}
	upstream := lineUpstream(saved)
	g := gitcall.Git{Repo: repo}
	if fetched, out, err := g.Fetch("origin", "--prune"); err != nil || fetched != 0 {
		return cmp.Or(err, fmt.Errorf("git fetch origin --prune failed in %s: %s", repo, out))
	}
	tip, err := g.Must("rev-parse", upstream+"^{commit}")
	if err != nil {
		return err
	}
	target, err := g.Must("rev-parse", tip+"^{tree}")
	if err != nil {
		return err
	}
	if evidence(turn, "red").Has(target) {
		return nil // the target's own red waits on its probes or its repair: Python's
	}
	return narrowLine(turn, code, repo, tip, upstream, members, said)
}

// lineUpstream is the remote branch a member of the line lands on, Python's land._upstream.
func lineUpstream(record *run.Object) string {
	upstream := cmp.Or(record.Str("target"), record.Str("base"))
	if !strings.HasPrefix(upstream, "origin/") {
		upstream = "origin/" + upstream
	}
	return upstream
}

// landingFixHandoff is what of a red Go's woken run does not carry, "" for none.
func landingFixHandoff(wait *run.Object) string {
	fix := wait.Dict("fix")
	if fix.Truthy("moved") {
		return "a moved PR head"
	}
	if helper.May() {
		return "a landing red with suite helpers"
	}
	return ""
}

// orderMembers is Python's line order: green deliveries in tested order, then join order.
func orderMembers(members []member) []member {
	deliveries := map[string]string{}
	for _, m := range members {
		if wait := m.record.Dict("waiting_on"); green(wait) {
			deliveries[filepath.Base(m.dir)] = wait.Str("land")
		}
	}
	depth := func(wait *run.Object) int {
		n := 0
		after := cmp.Or(wait.Dict("after"), run.NewObject())
		for _, name := range after.Keys() {
			if tree, ok := deliveries[name]; ok && tree == after.Str(name) {
				n++
			}
		}
		return n
	}
	slices.SortFunc(members, func(a, b member) int {
		aw, bw := a.record.Dict("waiting_on"), b.record.Dict("waiting_on")
		if green(aw) != green(bw) {
			if green(aw) {
				return -1
			}
			return 1
		}
		if green(aw) {
			if order := cmp.Compare(depth(aw), depth(bw)); order != 0 {
				return order
			}
		}
		aj, _ := aw.Num("joined")
		bj, _ := bw.Num("joined")
		return cmp.Or(cmp.Compare(aj, bj), strings.Compare(a.dir, b.dir))
	})
	return members
}

// withPrefix validates and holds the prefix through publication. Delivery may rebase or finish
// during a check, but may not substitute different reviewed work or a different tested tree.
func withPrefix(prefix []member, publish func() bool) bool {
	for _, m := range prefix {
		release, err := run.Hold(m.dir)
		if err != nil {
			return false
		}
		defer release()
		current, _ := run.Read(m.dir)
		if !sameDelivery(m.record, current) {
			return false
		}
	}
	return publish()
}

func sameDelivery(saved, current *run.Object) bool {
	if current == nil {
		return false
	}
	review := current.Dict("review")
	wait := saved.Dict("waiting_on")
	if review == nil || review.Str("verdict") != "PASS" || passedReviewHead(current) != passedReviewHead(saved) {
		return false
	}
	tree := wait.Str("land")
	if current.Truthy("merged") || current.Truthy("on_target") {
		return review.Str("tree_sha") == tree
	}
	return run.Equal(current.Get("waiting_on"), wait) && run.Member(current) &&
		(review.Str("tree_sha") == saved.Dict("review").Str("tree_sha") || review.Str("tree_sha") == tree)
}

func (l *loop) prefixTop(saved *run.Object, repo, tip, upstream, top string) (string, error) {
	checkout, failure, err := l.stackMember(saved, repo, tip, top, upstream)
	if checkout != nil {
		defer checkout.close()
	}
	if err != nil || failure != nil {
		return "", err
	}
	head, tree, err := (&repoPlace{wt: checkout.path}).identity()
	if tree != saved.Dict("waiting_on").Str("land") {
		return "", err
	}
	return head, err
}

type landingCheckout struct{ repo, path string }

func (c *landingCheckout) close() {
	gitcall.Git{Repo: c.repo}.Out("worktree", "remove", "--force", c.path)
	os.RemoveAll(c.path)
}

// stackMember is Python's _stack_member, shared by new checks and already checked prefixes.
// Try the bare tip first: changes ahead must not hide a member's conflict with its target.
func (l *loop) stackMember(saved *run.Object, repo, tip, top, upstream string) (*landingCheckout, *run.Object, error) {
	head := saved.Dict("review").Str("head_sha")
	g := gitcall.Git{Repo: repo}
	// One remote's line can hold private commits from separate clones.
	if found, _, err := g.Out("cat-file", "-e", head+"^{commit}"); err != nil || found != 0 {
		if err != nil {
			return nil, nil, err
		}
		source := cmp.Or(saved.Str("worktree"), saved.Str("repo"), repo)
		if fetched, out, err := g.Out("fetch", "--no-tags", "--no-write-fetch-head", "--", source, head); err != nil || fetched != 0 {
			return nil, l.fixed("lander.log", fmt.Sprintf("[exit %d]\nERROR: reviewed commit %s is unavailable\n%s", fetched, head, out), false), err
		}
	}
	if err := os.MkdirAll(filepath.Join(config.Home(), "wt"), 0o777); err != nil {
		return nil, nil, err
	}
	path, err := os.MkdirTemp(filepath.Join(config.Home(), "wt"), "land-")
	if err != nil {
		return nil, nil, err
	}
	checkout := &landingCheckout{repo: repo, path: path}
	if added, out, err := addScratch(repo, path, head); err != nil || added != 0 {
		return checkout, l.fixed("lander.log", fmt.Sprintf("[exit %d]\nERROR: checkout of %s failed\n%s", added, head, out), false), err
	}
	in := gitcall.Git{Repo: path}
	how, err := (&repoPlace{wt: path, baseSHA: cmp.Or(saved.Str("base_sha"), tip)}).how(saved)
	if err != nil {
		return checkout, nil, err
	}
	for index, onto := range []string{tip, top} {
		if index > 0 {
			if top == tip {
				break
			}
			if _, err := in.Must("checkout", "--force", "--detach", head); err != nil {
				return checkout, nil, err
			}
			if _, err := in.Must("clean", "-fdx"); err != nil {
				return checkout, nil, err
			}
		}
		args := []string{"merge", "--no-edit", onto}
		if how == "rebase" {
			// A detached rebase must not rewrite the member's branch through Git config.
			args = []string{"-c", "rebase.updateRefs=false", "rebase", onto}
		}
		if took, out, err := in.Out(args...); err != nil || took != 0 {
			return checkout, l.fixed("lander.log", fmt.Sprintf("$ git %s\n[exit %d]\nERROR: %s of %s failed\n%s", strings.Join(args, " "), took, how, upstream, out), true), err
		}
	}
	return checkout, nil, nil
}
