package loop

import (
	"os"
	"path/filepath"
	"strconv"

	"agentkit/internal/handin"
	"agentkit/internal/run"
)

// handDisputes hands each dispute to the reviewer's turn after the earlier findings, with every
// line where the fix left its site, Python's handed_disputes: the review's done waits for an
// answer to each, a finding handed in again at one of those lines or a concession of its site
// (handin.Answers).
func (l *loop) handDisputes(j *judging, disputes *handin.Review) error {
	for _, row := range disputes.Records {
		lines, _, err := l.place.moved(row.Str("path"), lineOf(row), j.since)
		if err != nil {
			return err
		}
		at := []any{}
		for _, line := range lines {
			at = append(at, run.Number(strconv.Itoa(line)))
		}
		j.answering = append(j.answering, run.Fields("kind", "dispute", "path", row.Get("path"), "line", row.Get("line"), "lines", at))
	}
	if len(j.standing) == 0 && len(j.answering) == 0 {
		return nil
	}
	listed := j.standing
	if len(listed) == 0 {
		listed = j.earlierList()
	}
	for _, dispute := range j.answering {
		listed = append(listed, dispute)
	}
	if err := os.MkdirAll(l.roundDir(), 0o777); err != nil {
		return err
	}
	j.listed = filepath.Join(l.roundDir(), "earlier.json")
	return os.WriteFile(j.listed, []byte(run.Line(listed)), 0o666)
}

// answer puts how each dispute ended on its row: conceded, with the reviewer's why, where the
// reviewer conceded its site, else upheld.  What the reviewer handed in answers, as handed in:
// weighing may turn an uphold into a note, never into a concession.
func answer(j *judging, disputes, submitted *handin.Review) {
	answers := handin.Answers(j.answering, submitted.Records)
	for _, row := range disputes.Records {
		given := answers[siteKey(row.Str("path"), lineOf(row))]
		if given == nil || given.Str("kind") != "concede" {
			row.Set("outcome", "upheld")
			continue
		}
		row.Set("outcome", "conceded")
		row.Set("conceded", given.Str("why"))
	}
}
