package loop

import (
	"cmp"
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/run"
)

// landingStack keeps only the green prefix: each next member is integrated on top of it.
// The commit objects survive removal of scratch checkouts; noAutoGC protects this pass.
type landingStack struct {
	top      string
	after    *run.Object
	multiple bool
}

func checkTurn(turn, code string, said io.Writer) error {
	members := lineMembers(filepath.Base(turn))
	index := slices.IndexFunc(members, func(m member) bool { return m.record.Str("state") == "waiting" })
	if index < 0 {
		return nil
	}
	saved := members[index].record
	repo := cmp.Or(saved.Str("worktree"), saved.Str("repo"))
	if err := noAutoGC(repo); err != nil {
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
	upstream := cmp.Or(saved.Str("target"), saved.Str("base"))
	if !strings.HasPrefix(upstream, "origin/") {
		upstream = "origin/" + upstream
	}
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
	stack := &landingStack{top: tip, after: run.NewObject(), multiple: len(members) > 1}
	prefix := []member{}
	for _, m := range members {
		dir, saved := m.dir, m.record
		wait := saved.Dict("waiting_on")
		if saved.Truthy("review_pr") || saved.Truthy("repair") {
			return nil // PR heads and target repairs are Python's
		}
		if wait.Has("fix") {
			if !stack.multiple && landingFixHandoff(wait) == "" && saved.Str("state") == "waiting" && unchanged(dir, saved) {
				publish(dir, saved, run.Fields("fix", wait.Get("fix")), said)
			}
			return nil
		}
		if review := saved.Dict("review"); review == nil || review.Str("verdict") != "PASS" {
			return nil
		}
		l := &loop{ctx: context.Background(), dir: dir, id: filepath.Base(dir), voice: said,
			silence: minutes(saved, "silence_minutes", run.SilenceMinutes), ceiling: time.Duration(number(saved, "ceiling_hours", run.CeilingHours) * float64(time.Hour))}
		if green(wait) {
			if tested := wait.Str("tested"); tested != "" && tested != wait.Str("land") {
				return nil // a batch covering a different tree is Python's
			}
			top, err := l.prefixTop(saved, repo, tip, upstream, stack.top)
			if err != nil || top == "" {
				return err
			}
			stack.top = top
			if saved.Str("state") == "waiting" && unchanged(dir, saved) {
				withPrefix(prefix, func() bool { return publish(dir, saved, wait, said) })
			}
		} else {
			if saved.Str("state") != "waiting" || !unchanged(dir, saved) || !withPrefix(prefix, func() bool { return true }) {
				return nil
			}
			answer, err := l.checkMember(turn, code, saved, repo, tip, target, upstream, stack)
			if err != nil || answer == nil {
				return err
			}
			if answer.Has("fix") && stack.multiple {
				return nil // conflicts and rules refusals on a stack are Python's too
			}
			answer.Set("after", stack.after.Copy())
			if !withPrefix(prefix, func() bool { return publish(dir, saved, answer, said) }) {
				return nil
			}
			wait = run.SetAll(wait.Copy(), pairs(answer)...)
			saved = saved.Copy()
			saved.Set("waiting_on", wait)
			m.record = saved
			if !green(wait) {
				return nil
			}
			// A reparked member must retry red suffixes discarded during rebuilding.
			note(turn, func(_, _, redStacks *run.Object) {
				for _, key := range redStacks.Keys() {
					redStacks.Delete(key)
				}
			})
		}
		stack.after.Set(filepath.Base(dir), wait.Get("land"))
		prefix = append(prefix, m)
	}
	return nil
}

// A persisted stack red stays Python's even after its predecessors have left the line.
func landingFixHandoff(wait *run.Object) string {
	fix := wait.Dict("fix")
	if fix.Str("piece") != "" || fix.Has("tests") {
		return "a landing red a helper or a shard reported"
	}
	if after := wait.Dict("after"); after != nil && len(after.Keys()) > 0 {
		return "a landing red on a stack"
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
	return !run.Ended(current) && run.Equal(current.Get("waiting_on"), wait) &&
		(current.Str("state") == "waiting" || run.ProcessActive(current)) &&
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
