package loop

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/gh"
	"agentkit/internal/run"
)

// A seat's own pull request lands as a task's work does, Python's merge_own_pr: once its review
// passed it joins the landing line, the line's lander checks the reviewed head on the target's tip,
// and the run, woken on green, puts the very commit checked on the PR branch and merges the PR at
// it.  A red, and a PR moved or closed since its review, go back to its writer, which is Python's
// (fail_pr_landing).

// land joins the line or lands from it, Python's merge_own_pr as settle_pr_round and review_pr
// leave it: a run no longer waiting is out of the line and owes no round.
func (p *ownPull) land(l *loop) error {
	upstream := p.upstream()
	if err := p.joinLine(l, upstream, func() error { return p.deliverPull(l, upstream) }); err != nil {
		return err
	}
	return l.save(func(record *run.Object) {
		record.Delete("landing_fix") // a new landing red still owes its fixer
		if record.Str("state") != "waiting" {
			record.Delete("own_pr_round_pending")
			record.Delete("waiting_on")
		}
	})
}

// deliverPull is the delivery of what the line checked, Python's merge_own_pr deliver: only a PR
// still open on a head this run reviewed or pushed, aimed at the target, takes the checked commit
// on its branch, and merges at it once its required checks are green.  One GitHub merged already
// is recorded so.
func (p *ownPull) deliverPull(l *loop, upstream string) error {
	current, err := prHead(l.dir, p.url)
	if err != nil {
		return err
	}
	record, err := read(l)
	if err != nil {
		return err
	}
	remote, target := current.Dict("head"), strings.TrimPrefix(upstream, "origin/")
	sha := remote.Str("sha")
	ours := (sha == record.Str("head_sha") || sha == record.Str("delivery_sha")) &&
		cmp.Or(current.Dict("base"), run.NewObject()).Str("ref") == target
	switch {
	case current.Truthy("merged") && ours:
		return p.mergedAt(l, sha)
	case current.Str("state") != "open" || !ours:
		return notYet("the PR head or target changed, or the PR closed, since review", "a PR's landing fix")
	}
	pinned, err := p.git().Must("rev-parse", "HEAD")
	if err != nil {
		return err
	}
	// written down before git is called: a killed push may have gone through
	if err := l.save(func(record *run.Object) { record.Set("delivery_sha", pinned) }); err != nil {
		return err
	}
	if sha != pinned {
		if err := p.pushPull(l, remote, sha); err != nil {
			return err
		}
	}
	if err := l.save(func(record *run.Object) { record.Set("head_sha", pinned) }); err != nil {
		return err
	}
	if ok, err := p.waitChecks(l, p.url, target); err != nil || !ok {
		return err
	}
	return p.doMerge(l, p.url, upstream)
}

// pushPull puts the checkout's HEAD on the PR branch GitHub names (remote, the PR's head) over
// lease and nothing else, Python's push_pr_branch: a push made by hand meanwhile is never
// overwritten.
func (p *ownPull) pushPull(l *loop, remote *run.Object, lease string) error {
	branch, source := remote.Str("ref"), ""
	if repo := remote.Dict("repo"); repo != nil {
		source = repo.Str("clone_url")
	}
	if branch == "" || source == "" {
		return errors.New("cannot locate the PR branch to push to")
	}
	code, out, err := p.gitPush(l, "--force-with-lease=refs/heads/"+branch+":"+lease, "--", source, "HEAD:refs/heads/"+branch)
	if err != nil {
		return err
	}
	if code != 0 {
		return errors.New("pushing to the PR branch failed: " + tail(out, 400))
	}
	return nil
}

// unmoved is the lander's pending members less each whose PR's head moved past its review, Python's
// _pr_moved: its seat pushed since, so checking the reviewed head tests code nobody will land, and
// the red that sends it back for review is published at once.
func unmoved(prefix, pending []member, said io.Writer) []member {
	var kept []member
	for _, m := range pending {
		moved := pullMoved(m.record)
		if moved == "" {
			kept = append(kept, m)
			continue
		}
		path := filepath.Join(m.dir, "lander.log")
		if os.WriteFile(path, []byte(moved+"\n"), 0o666) == nil {
			verdict := run.Fields("fix", run.Fields("line", moved, "log", path, "moved", true))
			withCandidates(prefix, []member{m}, func() bool { return publish(m.dir, m.record, verdict, said) })
		}
	}
	return kept
}

// pullMoved is why the PR a member reviews no longer holds a head of its run, "" for none, for a
// member of no PR, and for a head GitHub cannot say.
func pullMoved(record *run.Object) string {
	if !record.Truthy("review_pr") {
		return ""
	}
	pull, err := gh.View(record.Str("review_pr"))
	if err != nil || pull.Head == "" || pull.Head == record.Str("head_sha") || pull.Head == record.Str("delivery_sha") {
		return ""
	}
	reviewed := cmp.Or(record.Str("head_sha"), "?")
	return fmt.Sprintf("its PR's head moved to %s after review of %s: the new commits are reviewed before the line checks them",
		pull.Head[:min(12, len(pull.Head))], reviewed[:min(12, len(reviewed))])
}
