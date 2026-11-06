package handin

import (
	"errors"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// concede is a reviewer's concession of a dispute handed to its turn, with why it is right, Python's
// checked for `concede`.
func (t *turn) concede(args []string) (*run.Object, error) {
	if !strings.HasPrefix(t.role, "reviewer") {
		return nil, errors.New("concede is only for review turns")
	}
	if len(args) != 3 || blank(args[2]) {
		return nil, errors.New(`use concede with path:line and one nonempty "why"`)
	}
	disputes, err := t.disputed()
	if err != nil {
		return nil, err
	}
	dispute := named(disputes, args[1])
	if dispute == nil {
		return nil, errors.New("concede must name a dispute handed to this turn")
	}
	return run.Fields("kind", "concede", "path", dispute.Get("path"), "line", dispute.Get("line"),
		"why", strings.TrimFunc(args[2], config.Space)), nil
}

// answered refuses a review's done while a dispute handed to it has no answer, Python's
// check_disputes.
func (t *turn) answered() error {
	disputes, err := t.disputed()
	if err != nil {
		return err
	}
	answers := Answers(disputes, t.records)
	var unanswered []string
	for _, dispute := range disputes {
		if at := site(dispute); answers[at] == nil && !slices.Contains(unanswered, at) {
			unanswered = append(unanswered, at)
		}
	}
	if len(unanswered) == 0 {
		return nil
	}
	return errors.New("done refused: unanswered disputes:\n" + strings.Join(unanswered, "\n") +
		"\nUphold with `ak hand-in finding path:line \"what\" \"why it matters\" --run COMMAND`" +
		"\nor concede with `ak hand-in concede path:line \"why\"`.")
}

// disputed is the disputes handed to the turn, read only as the loop writes them: each at a site
// with the lines the fix left it at.
func (t *turn) disputed() ([]*run.Object, error) {
	list, ok := t.disputes.([]any)
	if !ok {
		return nil, ErrPython
	}
	disputes := make([]*run.Object, len(list))
	for i, item := range list {
		dispute, _ := item.(*run.Object)
		if dispute == nil || !sited(dispute) || dispute.List("lines") == nil {
			return nil, ErrPython
		}
		disputes[i] = dispute
	}
	return disputes, nil
}

// Answers is each disputed site's answer by its path:line, Python's dispute_answers: a finding
// handed in again with a command at a line the fix left it at upholds it, else the reviewer's
// concession of it answers, else nothing does.
func Answers(disputes, records []*run.Object) map[string]*run.Object {
	answers := map[string]*run.Object{}
	for _, row := range records {
		if row.Str("kind") == "concede" {
			answers[site(row)] = row
		}
	}
	for _, dispute := range disputes {
		for _, row := range records {
			evidence := row.Dict("evidence")
			if row.Str("kind") == "finding" && evidence != nil && evidence.Has("run") && row.Str("path") == dispute.Str("path") &&
				slices.ContainsFunc(dispute.List("lines"), func(line any) bool { return run.Equal(line, row.Get("line")) }) {
				answers[site(dispute)] = row
				break
			}
		}
	}
	return answers
}
