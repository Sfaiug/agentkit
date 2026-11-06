package loop

import (
	"fmt"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/handin"
	"agentkit/internal/run"
)

// A judging is what one review holds from its start to its verdict.
type judging struct {
	earlier   []*run.Object   // the blocking findings the last review handed in, as weighed then
	from      string          // the commit the last review judged
	since     string          // that commit where this review reads what changed since, else ""
	sites     map[string]bool // where an earlier finding can stand on this commit, once since is set
	disputes  []*run.Object   // what the round's fixer disputed
	replayed  []replay        // ak's own proof of the earlier findings on this commit
	standing  []any           // the earlier findings where they stand on this commit, for the reviewer
	answering []*run.Object   // the disputes handed to the reviewer, each with the lines the fix left it at
	listed    string          // the file of earlier findings and disputes handed to the reviewer, "" for none
	whole     string          // the whole change, for a conversation that starts fresh; "" where the section is that

	uncounted bool   // a landing re-review, which spends no round
	passed    string // the head the task's checks last passed on as it began
}

// A replay is an earlier finding proven again on this commit, at the line the fix left it.
type replay struct {
	row     *run.Object
	now     *run.Object
	failing bool
	touched bool
	lines   []int // every line it may stand at
}

func siteKey(path string, line int) string { return fmt.Sprintf("%s:%d", path, line) }

// lineOf is a sited row's line.
func lineOf(row *run.Object) int {
	line, _ := row.Int("line")
	return line
}

// judgingFrom is what a review starts from on the record as it stands.
func judgingFrom(record *run.Object) *judging {
	j := &judging{from: record.Str("delta_from")}
	for _, each := range record.List("review_records") {
		if row, _ := each.(*run.Object); row != nil && row.Str("kind") == "finding" {
			j.earlier = append(j.earlier, row)
		}
	}
	for _, file := range record.List("dispute_files") {
		submitted, _ := handin.Read(run.Text(file))
		if submitted == nil {
			continue
		}
		for _, row := range submitted.Of("dispute") {
			if !slices.ContainsFunc(j.disputes, func(kept *run.Object) bool { return run.Equal(kept, row) }) {
				j.disputes = append(j.disputes, row)
			}
		}
	}
	return j
}

// earlierList is the earlier findings as a record holds them.
func (j *judging) earlierList() []any {
	rows := []any{}
	for _, row := range j.earlier {
		rows = append(rows, row)
	}
	return rows
}

// disputed is whether the fixer disputed the finding's site.
func (j *judging) disputed(row *run.Object) bool {
	return slices.ContainsFunc(j.disputes, func(each *run.Object) bool {
		return each.Str("path") == row.Str("path") && lineOf(each) == lineOf(row)
	})
}

// keepDisputes puts the turn's disputes on the record, as Python's record_disputes, so the next
// review reads what its fixer handed in.
func (l *loop) keepDisputes(out string) error {
	path := filepath.Join(out, handin.File)
	submitted, _ := handin.Read(path)
	if submitted == nil || len(submitted.Of("dispute")) == 0 {
		return nil
	}
	return l.save(func(record *run.Object) {
		files := record.List("dispute_files")
		if !slices.Contains(files, any(path)) {
			record.Set("dispute_files", append(files, path))
		}
	})
}

// reviewDisputes is each dispute with ak's own run of its proof on the reviewed work beside it,
// Python's review_disputes, its finding as the fixer received it.
func (l *loop) reviewDisputes(j *judging) (*handin.Review, error) {
	rows := []*run.Object{}
	for index, row := range j.disputes {
		kept := row.Copy()
		if evidence := row.Dict("evidence"); evidence.Has("run") {
			proof, err := l.place.prove(l, evidence.Str("run"), filepath.Join(l.roundDir(), fmt.Sprintf("dispute-%d.log", index+1)))
			if err != nil {
				return nil, err
			}
			kept.Set("evidence", proof)
		}
		rows = append(rows, kept)
	}
	return &handin.Review{Records: rows}, nil
}

// replayWord is how a replayed proof went, for the reviewer and the record.
func replayWord(now *run.Object, failing bool) string {
	code, _ := now.Int("returncode")
	switch {
	case now.Truthy("killed") || code < 0:
		return "did not finish; kept as a note"
	case code == 126 || code == 127:
		return fmt.Sprintf("could not run (exit %d); kept as a note", code)
	case failing:
		return fmt.Sprintf("still fails (exit %d)", code)
	}
	return "fixed (the proof passes now)"
}

// replaySection is what the reviewer is told of the earlier findings, Python's replay_section: ak's
// own replay of the proven ones and those left to it, never a question.
func replaySection(replayed []replay, left []*run.Object, since string) string {
	var lines, yours []string
	for _, each := range replayed {
		lines = append(lines, fmt.Sprintf("- %s:%d - %s - %s", each.row.Str("path"), lineOf(each.row), each.row.Str("what"), replayWord(each.now, each.failing)))
	}
	for _, row := range left {
		yours = append(yours, fmt.Sprintf("- %s:%d - %s - disputed by the fixer: hand it in again to uphold it", row.Str("path"), lineOf(row), row.Str("what")))
	}
	shown := "(none)"
	if len(lines) > 0 {
		shown = strings.Join(lines, "\n")
	}
	text := "## Earlier findings, re-proven by ak on this commit\n" + shown
	if len(yours) > 0 {
		text += "\n\n## Earlier findings left to you\n" + strings.Join(yours, "\n")
	}
	text += "\nA finding still failing blocks whatever you hand in; one you hand in again at its site with its proof is weighed as ak's replay is; one fixed needs no word. "
	if since != "" {
		return text + fmt.Sprintf("A new finding blocks only inside the fix delta since %s, or with a proof that passes on that commit: the fix broke it.", since[:min(len(since), 12)])
	}
	return text + "This is the commit the last review judged, again: a new finding blocks wherever it is in the change."
}

// withReplays is the weighed records with ak's replays among them, Python's weigh_review: one still
// failing blocks whether or not the reviewer handed it in again, one fixed or unable to run is a
// note.  The reviewer's own hand-in of its very proof at its site, weighed to block, is that
// finding upheld, and ak adds no copy.
func (l *loop) withReplays(records []*run.Object, j *judging) []*run.Object {
	var extra []*run.Object
	for _, each := range j.replayed {
		row := each.row.Copy()
		if !each.failing {
			row.Set("handed", row.Get("kind"))
			row.Set("kind", "note")
			row.Set("evidence", each.now)
			code, _ := each.now.Int("returncode")
			word := replayWord(each.now, false)
			if code == 0 && !each.now.Truthy("killed") {
				word = "fixed; its proof passes now"
			}
			row.Set("replayed", word)
			extra = append(extra, row)
			continue
		}
		if slices.ContainsFunc(records, func(other *run.Object) bool {
			evidence := other.Dict("evidence")
			return evidence != nil && evidence.Str("run") == each.now.Str("run") && other.Str("kind") == "finding" &&
				other.Str("path") == row.Str("path") && slices.Contains(each.lines, lineOf(other))
		}) {
			continue
		}
		word := "still failing; it blocks until its proof passes"
		if each.touched {
			word += "; the fix changed its line"
		}
		row.Set("kind", "finding")
		row.Set("evidence", each.now)
		row.Set("replayed", word)
		extra = append(extra, row)
		l.say(fmt.Sprintf("Earlier finding %s:%d still fails on this commit", row.Str("path"), lineOf(row)))
	}
	if len(extra) == 0 {
		return records
	}
	if last := len(records) - 1; last >= 0 && slices.Contains([]string{"done", "blocked", "not-needed"}, records[last].Str("kind")) {
		return append(append(slices.Clone(records[:last]), extra...), records[last])
	}
	return append(records, extra...)
}
