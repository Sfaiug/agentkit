package loop

import (
	"bytes"
	"cmp"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/run"
)

// conflictRounds are the fixer rounds one stopped rebase or merge gets, Python's CONFLICT_ROUNDS.
const conflictRounds = 3

// resolve hands a rebase or merge of tip that stopped on conflicts back to the executor, Python's
// resolve_conflicts: whether the branch carries tip now, made its base, and with recheck passes
// there again.  A conflict is the world moving, never a verdict on reviewed work, so its fixer
// rounds spend no task round and never end the run FAIL: a git they leave unfinished parks the run
// waiting on the target.  With recheck the branch is checked and reviewed again on tip: a red the
// target itself has parks it there too, and a failed review is one like any other, its findings
// fixed in the task's own rounds while any are left.  Without, the round under way checks and
// reviews it next.  A conflict beside its lander's red is Python's whole.
func (r *repoPlace) resolve(l *loop, upstream, how, tip, out string, recheck bool) (bool, error) {
	record, err := read(l)
	if err != nil {
		r.abort(l, how, false)
		return false, err
	}
	if wait := record.Dict("waiting_on"); wait != nil && wait.Has("fix") {
		r.abort(l, how, false)
		return false, notYet(fmt.Sprintf("its %s onto %s at %s stopped on a conflict beside its lander's red", how, upstream, tip[:12]), "resolving it")
	}
	what := fmt.Sprintf("the %s of %s", how, upstream)
	summary, landed, err := r.fixConflicts(l, what, how, upstream, tip, out)
	if err != nil {
		return false, err
	}
	if !landed {
		return false, r.park(l, "the fixer did not finish "+what+"; it was aborted", upstream, tip)
	}
	if err := r.setBase(l, tip); err != nil || !recheck {
		return err == nil, err
	}
	again := "Re-review after " + what + "."
	if err := l.save(func(record *run.Object) {
		pending := cmp.Or(record.Dict("review_pending"), run.NewObject())
		record.Set("review_pending", run.SetAll(pending, "round", l.rnd, "summary", summary, "reason", again, "record", false))
	}); err != nil {
		return false, err
	}
	ok, text, err := l.verify()
	if err != nil {
		return false, err
	}
	if ok {
		l.say("done-when after the " + how + ": all passed")
	} else {
		l.say("done-when after the " + how + ": FAILED")
		said, err := r.targetFails(l, upstream, tip, text)
		if err != nil {
			return false, err
		}
		if said != "" {
			return false, r.park(l, upstream+" itself fails: "+said, upstream, tip)
		}
	}
	passed, err := l.review(summary, ok, text, again)
	if err == nil && !passed {
		passed, err = r.fixReview(l, what)
	}
	if err != nil || passed {
		return passed, err
	}
	return false, r.note(l, "done-when or review after "+what+" did not pass", false)
}

// targetFails is what the first failing check says on the pinned tip where it passes on the base
// the last reviewed head was checked on, Python's target_fails: the target's own red, which no fixer
// of this branch mends.  "" where the check needs the branch: it fails on that base too, passes on
// the tip, or there is nothing to probe.  That base is never the tip after a conflict, so a check
// naming a file only the branch has fails there and needs no reading of its own.  Each probe runs
// the check as the re-test did, in pieces where it names AK_SHARD.  A seated run's red is Python's,
// which starts a repair of the target for it.
func (r *repoPlace) targetFails(l *loop, upstream, tip, text string) (string, error) {
	record, err := read(l)
	failed := failingChecks(text)
	if err != nil || len(failed) == 0 {
		return "", err
	}
	cmd := run.Text(failed[0].([]any)[0])
	if repair := record.Dict("repair"); repair != nil && repair.Str("command") == cmd {
		return "", nil // a repair of the target is checked by its own rounds
	}
	if code, _, err := r.git().Out("diff", "--quiet", "HEAD"); err != nil || code != 0 {
		return "", err
	}
	path := filepath.Join(l.dir, "target-probe.log")
	probe := func(sha, where string) (bool, *run.Object, error) {
		proof, err := r.onRevision(l, fmt.Sprintf("`%s` on %s", cmd, where), sha, "", func() (int, string, bool, error) {
			l.say(fmt.Sprintf("--- merge: `%s` failed; probing it once on %s (%s)", cmd, where, sha[:12]))
			return l.suite(r.wt, cmd, path, where+" "+sha)
		})
		if err != nil {
			return false, nil, err
		}
		code, _ := proof.Int("returncode")
		return code != 0 || proof.Truthy("killed"), proof, nil
	}
	red, onTip, err := probe(tip, upstream)
	if err != nil || !red {
		return "", err
	}
	passed := passedReviewHead(record)
	if passed == "" {
		return "", nil
	}
	base, err := r.git().Try("merge-base", passed, tip)
	if err != nil || base == "" {
		return "", err
	}
	if base != tip {
		if red, _, err := probe(base, "old base"); err != nil || red {
			if err == nil {
				l.say(fmt.Sprintf("--- merge: `%s` fails on %s too: needs this branch", cmd, base[:12]))
			}
			return "", err
		}
	}
	if run.Seat(record) != "" {
		return "", notYet(fmt.Sprintf("`%s` fails on %s at %s", cmd, upstream, tip[:12]), "starting its seat's repair of the target")
	}
	code, _ := onTip.Int("returncode")
	return firstFailure(fmt.Sprintf("$ %s\n[exit %d]\n%s", cmd, code, onTip.Str("output"))), nil
}

// suite is cmd's run in cwd as Python's gate.run_suite runs a check with no turn held: in pieces
// where it names AK_SHARD, else whole and once.  Its output is added to the log at path, under
// label, and handed on whole.
func (l *loop) suite(cwd, cmd, path, label string) (int, string, bool, error) {
	progress, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE|os.O_APPEND, 0o666)
	if err != nil {
		return 0, "", false, err
	}
	defer progress.Close()
	fmt.Fprintf(progress, "$ %s (on %s)\n", cmd, label)
	start, _ := progress.Seek(0, io.SeekEnd)
	var outcome ran
	if namesShard.MatchString(cmd) {
		outcome, _, err = l.pieces(cwd, cmd, time.Now().Add(l.ceiling), progress, path, nil)
	} else {
		l.say("suite runs here: command is not sent to the suite helper (does not name AK_SHARD)")
		outcome, err = l.boxed(cwd, cmd, "", l.ceiling, progress, path, false)
	}
	if err != nil {
		return 0, "", false, err
	}
	end, _ := progress.Seek(0, io.SeekEnd)
	said, err := io.ReadAll(io.NewSectionReader(progress, start, end-start))
	return outcome.code, decoded(said), outcome.stopped != "", err
}

// fixReview is the rounds a failed review after a conflict gets, Python's fix_after_failed_review:
// each a task round, its fixer handed the findings and the red the review judged, its work checked
// and reviewed again, until a review passes or the budget is spent.
func (r *repoPlace) fixReview(l *loop, what string) (bool, error) {
	for l.rnd < l.budget {
		if err := l.allowed(); err != nil {
			return false, err
		}
		record, err := read(l)
		if err != nil {
			return false, err
		}
		fix := l.prompt + "\n\n## Reviewer findings to fix\n" + withoutAsides(l.findings)
		if review := record.Dict("review"); review != nil && review.Get("done_when") == false {
			checked, _ := os.ReadFile(filepath.Join(l.roundDir(), "donewhen.log"))
			fix += "\n\n## The done-when commands failed. Fix the root cause.\n```\n" + decoded(checked) + "\n```"
		}
		l.rnd++
		l.say(fmt.Sprintf("--- round %d/%d: fixer %s (findings after %s)", l.rnd, l.budget, l.executor, what))
		summary, err := l.execute("fixer", "executor", fix, filepath.Join(filepath.Dir(l.findingsFile), "findings.json"))
		if err != nil {
			return false, err
		}
		ok, text, err := l.verify()
		if err != nil {
			return false, err
		}
		if ok {
			l.say("done-when after the fix: all passed")
		} else {
			l.say("done-when after the fix: FAILED")
		}
		if err := l.sameFailure(ok, text, true); err != nil {
			return false, err
		}
		if passed, err := l.review(summary, ok, text, "Re-review after fixes for "+what+"."); err != nil || passed {
			return passed, err
		}
	}
	return false, nil
}

// fixConflicts is the fixer rounds on the one stopped git, each on the files no fixer was handed
// yet, each kept in history.db: the last fixer's summary, and whether the branch carries tip after
// them.  A git the rounds leave stopped, or that something stops in them, is aborted, so whoever
// carries the run on starts from a clean tree.
func (r *repoPlace) fixConflicts(l *loop, what, how, upstream, tip, out string) (summary string, landed bool, err error) {
	g, stopped := r.git(), true
	rows := history.NewConflicts(l.id, how, upstream, tip)
	defer func() {
		if stopped {
			r.abort(l, how, false)
		}
		if err := rows.End(landed); err != nil {
			l.say("WARN history: " + err.Error())
		}
	}()
	listed, err := g.Try("diff", "--name-only", "--diff-filter=U")
	if err != nil {
		return "", false, err
	}
	shown, err := cut(out, l.dir, how+"-conflict")
	if err != nil {
		return "", false, err
	}
	var conflicts []string
	for _, path := range config.SplitLines(listed) {
		if path != "" {
			conflicts = append(conflicts, "- "+path)
		}
	}
	l.say(fmt.Sprintf("WARN %s conflicted in %d file(s)", what, len(conflicts)))
	finish := "`git rebase --continue` until the rebase is finished"
	if how == "merge" {
		finish = "`git commit` to finish the merge"
	}
	text := fmt.Sprintf("%s\n\n## Resolve the %s conflict\n`git %s %s` is in progress in %s and has stopped on conflicts. "+
		"Resolve every one keeping both sides' intent -- never drop the other side's work -- then `git add` the files and %s. "+
		"Re-run the done-when commands afterwards.\n\n### Conflicted files\n%s\n\n```\n%s\n```",
		l.prompt, how, how, upstream, r.wt, finish, strings.Join(conflicts, "\n"), shown)
	seen := map[[2]string]bool{}
	for attempt := 1; attempt <= conflictRounds; attempt++ {
		files, err := r.unmerged(how, seen)
		if err != nil {
			return "", false, err
		}
		if err := rows.Add(files); err != nil {
			l.say("WARN history: " + err.Error())
		}
		l.say(fmt.Sprintf("--- merge: conflict round %d/%d: fixer %s (%s conflict)", attempt, conflictRounds, l.executor, how))
		if summary, err = l.execute("fixer", how+"-fixer", text, ""); err != nil {
			return "", false, err
		}
		still, err := inProgress(g)
		if err != nil {
			return "", false, err
		}
		if stopped = still; !stopped {
			break
		}
		if attempt < conflictRounds {
			l.say("WARN the fixer did not finish " + what + "; another conflict round works it")
		}
	}
	if stopped {
		return summary, false, nil
	}
	// what finishes either is the pinned tip in HEAD's history: a fixer can finish the git and leave it out
	code, _, err := g.Out("merge-base", "--is-ancestor", tip, "HEAD")
	return summary, err == nil && code == 0, err
}

// unmerged are the files the stopped git holds unmerged that no fixer was handed at this stop, each
// with git's classification: a later commit of a rebase can stop on the same path again.
func (r *repoPlace) unmerged(how string, seen map[[2]string]bool) ([]history.Conflicted, error) {
	g, stop := r.git(), ""
	if how == "rebase" {
		var err error
		if stop, err = g.Try("rev-parse", "--verify", "--quiet", "REBASE_HEAD"); err != nil {
			return nil, err
		}
	}
	listed, err := g.Try("ls-files", "--unmerged", "-z")
	if err != nil {
		return nil, err
	}
	var files []history.Conflicted
	for _, entry := range strings.Split(listed, "\x00") {
		_, path, _ := strings.Cut(entry, "\t")
		if key := [2]string{stop, path}; entry != "" && !seen[key] {
			seen[key] = true
			files = append(files, history.Conflicted{Path: path, AddedOnly: r.addedOnly(path)})
		}
	}
	return files, nil
}

// addedOnly is whether every conflict in the file has an empty base, both sides only adding there,
// Python's conflict_added_only: read from the index's stages, never the checkout.  What git cannot
// say is not.
func (r *repoPlace) addedOnly(path string) bool {
	g := r.git()
	work, err := os.MkdirTemp("", "ak-conflict-")
	if err != nil {
		return false
	}
	defer os.RemoveAll(work)
	var stages []string
	var source []byte
	for n := 1; n <= 3; n++ {
		code, stage, _, err := g.Bytes("show", fmt.Sprintf(":%d:%s", n, path))
		file := filepath.Join(work, strconv.Itoa(n))
		if err != nil || code != 0 || os.WriteFile(file, stage, 0o666) != nil {
			return false
		}
		stages, source = append(stages, file), append(source, stage...)
	}
	// a line of the file's own that looks like a marker never stands in for git's separator
	size := 7
	for bytes.Contains(source, bytes.Repeat([]byte("<"), size)) || bytes.Contains(source, bytes.Repeat([]byte("|"), size)) ||
		bytes.Contains(source, bytes.Repeat([]byte("="), size)) || bytes.Contains(source, bytes.Repeat([]byte(">"), size)) {
		size++
	}
	code, merged, _, err := g.Bytes("merge-file", "-p", "--diff3", fmt.Sprintf("--marker-size=%d", size),
		"-L", "ours", "-L", "base", "-L", "theirs", stages[1], stages[0], stages[2])
	if err != nil || code <= 0 || code >= 128 {
		return false
	}
	bases := regexp.MustCompile(`(?s)`+regexp.QuoteMeta(strings.Repeat("|", size)+" base")+`\r?\n(.*?)`+
		regexp.QuoteMeta(strings.Repeat("=", size))+`\r?\n`).FindAllSubmatch(merged, -1)
	for _, base := range bases {
		if len(base[1]) > 0 {
			return false
		}
	}
	return len(bases) > 0
}

// cut is text as a model is handed it, Python's turns.cut: whole up to outCap characters, else its
// end under the line naming a file under where that keeps all of it.
func cut(text, where, name string) (string, error) {
	runes := []rune(text)
	if len(runes) <= outCap {
		return text, nil
	}
	line, err := kept(strings.NewReader(text), where, name)
	return line + string(runes[len(runes)-outCap:]), err
}
