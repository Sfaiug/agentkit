package loop

import (
	"bytes"
	"cmp"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

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
// waiting on the target.  With recheck the branch is checked and reviewed again on tip, a red or a
// failed review there being Python's; without, the round under way checks and reviews it next.  A
// conflict beside its lander's red is Python's whole.
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
	text, err := r.retest(l, upstream, how)
	if err != nil {
		return false, err
	}
	if passed, err := l.review(summary, true, text, again); err != nil || passed {
		return passed, err
	}
	return false, notYet("the review after "+what+" failed", "a fixer round on its findings")
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
