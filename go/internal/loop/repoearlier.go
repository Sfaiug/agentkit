package loop

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"

	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/run"
)

// A hunk is one of git's, no context: its old start and count, its new start and count.
type hunk struct{ old, oldCount, now, nowCount int }

// hunks is those of path from since to head, as git reads a conflict: two commits' trees, not their
// merge base's.
func (r *repoPlace) hunks(path, since, head string) ([]hunk, error) {
	diff, err := r.git().Must("diff", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames", "--unified=0", since, head, "--", ":(literal)"+path)
	if err != nil {
		return nil, err
	}
	number := func(text string) int {
		if text == "" {
			return 1
		}
		parsed, _ := strconv.Atoi(text)
		return parsed
	}
	var found []hunk
	for _, each := range hunkHeader.FindAllStringSubmatch(diff, -1) {
		found = append(found, hunk{number(each[1]), number(each[2]), number(each[3]), number(each[4])})
	}
	return found, nil
}

// moved is Python's moved_lines: the lines on the checkout's commit where a line of path at since
// can sit, and whether the diff between them touched it.  One line where a fix above it moved a
// line it never touched; those the fix put in its place where it rewrote it; the removal's anchor
// where it deleted it; the line itself with no delta.
func (r *repoPlace) moved(path string, line int, since string) ([]int, bool, error) {
	if since == "" {
		return []int{line}, false, nil
	}
	head, _, err := r.identity()
	if err != nil {
		return nil, false, err
	}
	found, err := r.hunks(path, since, head)
	if err != nil {
		return nil, false, err
	}
	shift := 0
	for _, each := range found {
		start := each.old
		if each.oldCount == 0 {
			start++ // lines were added after it: what follows it moves
		}
		if line < start {
			break
		}
		if line < start+each.oldCount {
			if each.nowCount == 0 {
				return []int{max(each.now, 1)}, true, nil
			}
			lines := make([]int, each.nowCount)
			for i := range lines {
				lines[i] = each.now + i
			}
			return lines, true, nil
		}
		shift += each.nowCount - each.oldCount
	}
	return []int{line + shift}, false, nil
}

// placed is where an earlier finding stands on the commit, Python's placed: a line the fix rewrote
// stands at the line it put in its place that reads most like it, a tie going to the first.
func (r *repoPlace) placed(row *run.Object, since string) (int, bool, []int, error) {
	lines, touched, err := r.moved(row.Str("path"), lineOf(row), since)
	if err != nil {
		return 0, false, nil, err
	}
	if len(lines) == 1 {
		return lines[0], touched, lines, nil
	}
	shown := func(commit string) ([]string, error) {
		text, err := r.git().Try("show", commit+":"+row.Str("path"))
		return config.SplitLines(text), err
	}
	then, err := shown(since)
	if err != nil {
		return 0, false, nil, err
	}
	now, err := shown("HEAD")
	if err != nil {
		return 0, false, nil, err
	}
	was := ""
	if at := lineOf(row); at > 0 && at <= len(then) {
		was = then[at-1]
	}
	best, score := lines[0], -1.0
	for _, at := range lines {
		text := ""
		if at <= len(now) {
			text = now[at-1]
		}
		if ratio := similarity(was, text); ratio > score {
			best, score = at, ratio
		}
	}
	return best, touched, lines, nil
}

// prove replays a command on the commit under review, its evidence as a record holds it.
func (r *repoPlace) prove(l *loop, command, path string) (*run.Object, error) {
	head, _, err := r.identity()
	if err != nil {
		return nil, err
	}
	proof, err := r.proofOn(l, command, path, head, "")
	if err != nil {
		return nil, err
	}
	return merged(run.Fields("run", command, "commit", head), proof), nil
}

// earlierWork is what a later round's review adds to the whole change: ak's proof of the last
// review's findings on this commit, which the reviewer is handed where the fix left them, and with
// a new commit the delta since that review, which is what the review reads.  A landing re-review
// reads the whole change alone, and one whose base moved since that review (no `delta_from`) reads
// it with that proof.
func (r *repoPlace) earlierWork(l *loop, j *judging, whole, head string) (string, error) {
	if j.uncounted || len(j.earlier) == 0 {
		return whole, nil
	}
	if j.from != "" && j.from != head {
		j.since = j.from
	}
	var left []*run.Object
	listed := []any{}
	j.sites = map[string]bool{}
	index := 0
	for _, row := range j.earlier {
		line, touched, lines, err := r.placed(row, j.since)
		if err != nil {
			return "", err
		}
		for _, at := range lines {
			j.sites[siteKey(row.Str("path"), at)] = true
		}
		standing := row.Copy()
		standing.Set("line", line)
		listed = append(listed, standing)
		switch {
		case j.disputed(row):
			left = append(left, standing)
		case row.Dict("evidence").Has("run"):
			// one at a site the fixer disputed is the reviewer's to weigh: listed, not replayed
			index++
			now, err := r.prove(l, row.Dict("evidence").Str("run"), filepath.Join(l.roundDir(), fmt.Sprintf("replay-%d.log", index)))
			if err != nil {
				return "", err
			}
			j.replayed = append(j.replayed, replay{standing, now, handin.ProofFailed(now), touched, lines})
		}
	}
	j.listed = filepath.Join(l.roundDir(), "earlier.json")
	if err := os.WriteFile(j.listed, []byte(run.Line(listed)), 0o666); err != nil {
		return "", err
	}
	section := replaySection(j.replayed, left, j.since)
	if j.since == "" {
		return whole + "\n\n" + section, nil
	}
	changed, err := r.git().Try("diff", j.since, head)
	if err != nil {
		return "", err
	}
	j.whole = whole
	return fmt.Sprintf("## Fix delta (%s...HEAD in %s; what changed since the last review)\n```diff\n%s\n```\n\n%s", j.since[:min(len(j.since), 12)], r.wt, r.capped(changed), section), nil
}
