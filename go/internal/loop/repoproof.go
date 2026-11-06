package loop

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/gitcall"
	"agentkit/internal/handin"
	"agentkit/internal/run"
	"agentkit/internal/uncommitted"
)

var (
	hunkHeader = regexp.MustCompile(`(?m)^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@`)
	beforeName = regexp.MustCompile(`^(?:base\s+)?([^\s:]+)(?::|\s|$)`)
)

// resetCheckout discards tracked changes and only the paths created since the checkout was
// recorded.
func resetCheckout(g gitcall.Git, head string, before []string) error {
	if _, err := g.Try("reset", "--quiet", "--hard", head); err != nil {
		return err
	}
	dirty, err := uncommitted.Paths(g)
	if err != nil {
		return err
	}
	args := []string{"clean", "--quiet", "-fd", "--"}
	for _, path := range dirty {
		if !slices.Contains(before, path) {
			args = append(args, ":(literal)"+path)
		}
	}
	if len(args) == 4 {
		return nil
	}
	_, err = g.Try(args...)
	return err
}

// proofOn replays a command on a revision, Python's prompts.proof_on: the checkout goes there, the
// tests from `from` laid over, with what restores it on the record first, as a hard exit skips any
// restoring: its evidence as a record holds it.
func (r *repoPlace) proofOn(l *loop, command, path, revision, from string) (*run.Object, error) {
	if err := l.stopCheck(); err != nil {
		return nil, err
	}
	g := r.git()
	head, err := g.Must("rev-parse", "HEAD")
	if err != nil {
		return nil, err
	}
	branch, err := g.Try("symbolic-ref", "--quiet", "--short", "HEAD")
	if err != nil {
		return nil, err
	}
	before, err := uncommitted.Paths(g)
	if err != nil {
		return nil, err
	}
	var tests []string
	if from != "" {
		if tests, err = r.changedTests(l, from, true); err != nil {
			return nil, err
		}
	}
	label := "proof on " + revision
	kept := []any{}
	for _, each := range slices.Sorted(slices.Values(before)) {
		kept = append(kept, each)
	}
	if err := l.save(func(record *run.Object) {
		record.Set("probe_checkout", run.Fields("head", head, "branch", branch, "before", kept, "label", label))
	}); err != nil {
		return nil, err
	}
	proof, err := r.probe(l, command, path, revision, from, head, before, tests)
	if failed := r.restoreProbe(l, head, branch, before, label); err == nil {
		err = failed
	}
	return proof, err
}

func (r *repoPlace) probe(l *loop, command, path, revision, from, head string, before, tests []string) (*run.Object, error) {
	g := r.git()
	if err := resetCheckout(g, head, before); err != nil {
		return nil, err
	}
	if _, err := g.Must("checkout", "--quiet", "--detach", revision); err != nil {
		return nil, err
	}
	if len(tests) > 0 {
		args := []string{"restore", "--source=" + from, "--staged", "--worktree", "--"}
		for _, each := range tests {
			args = append(args, ":(literal)"+each)
		}
		if _, err := g.Must(args...); err != nil {
			return nil, err
		}
	}
	code, output, killed, err := l.proved(r.wt, command, path, revision)
	if err != nil {
		return nil, err
	}
	return run.Fields("returncode", code, "output", output, "killed", killed), nil
}

// restoreProbe discards the probe's edits, recovery pending on the record until the original
// checkout is back.
func (r *repoPlace) restoreProbe(l *loop, head, branch string, before []string, label string) error {
	g := r.git()
	if err := resetCheckout(g, "HEAD", before); err != nil {
		return err
	}
	want := branch
	if want == "" {
		want = head
	}
	if _, err := g.Try("checkout", "--quiet", want); err != nil {
		return err
	}
	now, err := g.Try("rev-parse", "HEAD")
	if err != nil {
		return err
	}
	if now != head {
		if _, err := g.Try("checkout", "--quiet", head); err != nil {
			return err
		}
	}
	moved, _, err := g.Out("diff", "--quiet", "HEAD")
	if err != nil {
		return err
	}
	on, err := g.Try("symbolic-ref", "--quiet", "--short", "HEAD")
	if err != nil {
		return err
	}
	if now, err = g.Try("rev-parse", "HEAD"); err != nil {
		return err
	}
	dirty, err := uncommitted.Paths(g)
	if err != nil {
		return err
	}
	fresh := slices.ContainsFunc(dirty, func(path string) bool { return !slices.Contains(before, path) })
	if now != head || branch != "" && on != branch || moved != 0 || fresh {
		l.say(fmt.Sprintf("WARN the probe of %s did not restore %s cleanly; checkout recovery is still pending", label, want))
		return fmt.Errorf("could not restore the checkout after the probe of %s", label)
	}
	return l.save(func(record *run.Object) { record.Delete("probe_checkout") })
}

// proved is a command's replay in cwd under a check's walls, in a log of its own, cut as a
// hand-in's.
func (l *loop) proved(cwd, command, path, label string) (int, string, bool, error) {
	l.say("--- review proof: checking " + label)
	progress, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE|os.O_TRUNC|os.O_APPEND, 0o666)
	if err != nil {
		return 0, "", false, err
	}
	defer progress.Close()
	fmt.Fprintf(progress, "$ %s (on %s)\n", command, label)
	start, _ := progress.Seek(0, io.SeekEnd)
	outcome, err := l.boxed(cwd, command, "", l.ceiling, progress, path, true)
	if err != nil {
		return 0, "", false, err
	}
	progress.Seek(0, io.SeekEnd)
	output, err := handin.Excerpt(progress, start)
	if err != nil {
		return 0, "", false, err
	}
	status := "exit " + strconv.Itoa(outcome.code)
	if outcome.stopped != "" || outcome.code < 0 {
		status = "did not finish"
	}
	fmt.Fprintf(progress, "\n[%s]\n", status)
	return outcome.code, output, outcome.stopped != "", nil
}

// changedLine is whether the line is inside the new side of the diff of its path to head from since:
// a pure removal leaves an anchor between the two surviving neighbouring lines.
func (r *repoPlace) changedLine(row *run.Object, head, since string) (bool, error) {
	found, err := r.hunks(row.Str("path"), since, head)
	if err != nil {
		return false, err
	}
	line := lineOf(row)
	for _, each := range found {
		if each.nowCount > 0 && each.now <= line && line < each.now+each.nowCount || each.nowCount == 0 && (line == each.now || line == each.now+1) {
			return true, nil
		}
	}
	return false, nil
}

// beforeAtBase is whether a follow-up's --before names a commit in base's history, or lines of the
// named file at base.
func (r *repoPlace) beforeAtBase(row *run.Object) (bool, error) {
	before := gitcall.Strip(row.Str("before"))
	if before == "" {
		return false, nil
	}
	g := r.git()
	if named := beforeName.FindStringSubmatch(before); named != nil {
		commit, err := g.Try("rev-parse", "--verify", "--end-of-options", named[1]+"^{commit}")
		if err != nil {
			return false, err
		}
		if commit != "" {
			code, _, err := g.Out("merge-base", "--is-ancestor", commit, r.baseSHA)
			if err != nil {
				return false, err
			}
			if code == 0 {
				return true, nil
			}
		}
	}
	code, content, err := g.Out("show", r.baseSHA+":"+row.Str("path"))
	return code == 0 && strings.Contains(content, before), err
}

// merged is evidence with what a proof found.
func merged(evidence, proof *run.Object) *run.Object {
	for _, key := range proof.Keys() {
		evidence.Set(key, proof.Get(key))
	}
	return evidence
}

// weigh is Python's weigh_review: a quote shows where to look; only a failing command decides what
// must be fixed.  A finding's command runs on this commit and on the base with the changed tests
// laid over: a defect elsewhere that fails on base too is a follow-up.  A follow-up from before the
// task is proven on base; one without --before on this commit too, and blocks as a finding where
// it passes on base: the change caused it.  In a later round a new finding blocks only inside the
// fix delta, or with a proof that passes on the commit the last review judged; one at an earlier
// finding's site upholds it.
func (r *repoPlace) weigh(l *loop, row *run.Object, index int, j *judging) (*run.Object, error) {
	head, err := r.git().Must("rev-parse", "HEAD")
	if err != nil {
		return nil, err
	}
	evidence := row.Dict("evidence")
	kind := row.Str("kind")
	deferred := kind == "follow-up" && !row.Has("before")
	logOf := func(side string) string {
		return filepath.Join(l.roundDir(), fmt.Sprintf("proof-%d-%s.log", index+1, side))
	}
	command := evidence.Str("run")
	switch {
	case kind == "follow-up" && evidence.Has("run"):
		base, err := r.proofOn(l, command, logOf("base"), r.baseSHA, head)
		if err != nil {
			return nil, err
		}
		evidence = merged(run.Fields("run", command, "commit", r.baseSHA), base)
		if deferred {
			proof, err := r.proofOn(l, command, logOf("commit"), head, "")
			if err != nil {
				return nil, err
			}
			evidence = merged(run.Fields("run", command, "commit", head), proof)
			evidence.Set("base", merged(run.Fields("sha", r.baseSHA), base))
			// passing on base and failing here shows the change caused it, wherever its site
			if code, _ := base.Int("returncode"); handin.ProofFailed(evidence) && code == 0 && !base.Truthy("killed") {
				kind = "finding"
			}
			deferred = !(handin.ProofFailed(evidence) && handin.ProofFailed(base))
		}
	case kind == "follow-up":
	case evidence.Has("quote"):
		kind = "note"
	default:
		proof, err := r.proofOn(l, command, logOf("commit"), head, "")
		if err != nil {
			return nil, err
		}
		evidence = merged(run.Fields("run", command, "commit", head), proof)
		base, err := r.proofOn(l, command, logOf("base"), r.baseSHA, head)
		if err != nil {
			return nil, err
		}
		evidence.Set("base", merged(run.Fields("sha", r.baseSHA), base))
		if !handin.ProofFailed(evidence) {
			kind = "note"
		} else {
			changed, err := r.changedLine(row, head, r.baseSHA)
			if err != nil {
				return nil, err
			}
			code, _ := base.Int("returncode")
			switch {
			case changed:
			case handin.ProofFailed(base):
				kind = "follow-up"
			case code != 0 || base.Truthy("killed"):
				kind = "note"
			}
		}
	}
	outside, err := r.outsideDelta(l, row, kind, evidence, head, logOf("since"), j)
	if err != nil {
		return nil, err
	}
	weighed := row.Copy()
	weighed.Set("kind", kind)
	weighed.Set("evidence", evidence)
	if outside {
		weighed.Set("kind", "note")
		weighed.Set("outside", fmt.Sprintf("the fix delta since %s; judged in an earlier round", j.since[:min(len(j.since), 12)]))
		l.say(fmt.Sprintf("Kept as a note %s:%d: outside the fix delta", row.Str("path"), lineOf(row)))
	}
	if kind == "follow-up" {
		if !weighed.Has("before") && !deferred {
			weighed.Set("before", "base "+r.baseSHA+": the proof fails there too")
		}
		reason, err := r.dropReason(weighed, evidence, deferred)
		if err != nil {
			return nil, err
		}
		if reason != "" {
			weighed.Set("kind", "note")
			weighed.Set("dropped", reason)
			l.say(fmt.Sprintf("Dropped follow-up %s:%v: %s", row.Str("path"), row.Get("line"), reason))
		}
	}
	return weighed, nil
}

// outsideDelta is whether a finding is new, outside what the fix changed, and shows no break by a
// proof that passes on the commit the last review judged: one that cannot run or finish there shows
// none, as on base.
func (r *repoPlace) outsideDelta(l *loop, row *run.Object, kind string, evidence *run.Object, head, path string, j *judging) (bool, error) {
	if kind != "finding" || j.since == "" || j.sites[siteKey(row.Str("path"), lineOf(row))] {
		return false, nil
	}
	changed, err := r.changedLine(row, head, j.since)
	if err != nil || changed {
		return false, err
	}
	onSince, err := r.proofOn(l, evidence.Str("run"), path, j.since, head)
	if err != nil {
		return false, err
	}
	code, _ := onSince.Int("returncode")
	return code != 0 || onSince.Truthy("killed"), nil
}

// dropReason is why a follow-up does not stand, "" where it does.
func (r *repoPlace) dropReason(row, evidence *run.Object, deferred bool) (string, error) {
	switch {
	case !evidence.Has("run") && deferred:
		return "needs a --run proof", nil
	case !evidence.Has("run"):
		return "needs a --run proof that fails on base", nil
	}
	proven := evidence
	if base := evidence.Dict("base"); !deferred && base != nil {
		proven = base
	}
	if !handin.ProofFailed(proven) {
		if deferred {
			return "the command did not fail on this commit", nil
		}
		return "the command did not fail on base", nil
	}
	if deferred {
		return "", nil
	}
	found, err := r.beforeAtBase(row)
	if err != nil || found {
		return "", err
	}
	return "--before names no commit in base's history or quote present at base", nil
}
