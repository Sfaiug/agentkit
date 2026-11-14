package loop

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/pick"
	"agentkit/internal/run"
	"agentkit/internal/usage"
)

// handoverNote opens a turn taking over a round another model began, Python's prompts.HANDOVER.
const handoverNote = "## Another model started this round\n%s began this round and its provider's window ran out mid-way, so the work is yours from here. The checkout is the same one it was working in and may carry uncommitted edits of its own: read them, keep what is right, and finish the task below as if it were round one."

// refusing is a read with the providers that refused this piece of work out of it: handing the work
// back to one of those is how a handover becomes a circle.
type refusing struct {
	pick.Room
	models map[string]config.Model
	dry    map[string]bool
}

func (r refusing) Spent(name string) string {
	if r.dry[r.models[name].Provider] {
		return "it refused this work"
	}
	return r.Room.Spent(name)
}

// unmetered is a read nobody could take: meters nobody could read withhold no reviewer, and
// report no pace, which keeps a payg one out.
type unmetered struct{}

func (unmetered) Spent(string) string             { return "" }
func (unmetered) Budget(string) (float64, string) { return 0, "unknown: unread" }
func (unmetered) OnCredits(string) bool           { return false }
func (unmetered) Pace(string) (float64, bool)     { return 0, false }

// handExecutor gives this round's work to a model on a provider that refused nothing yet, Python's
// hand_executor: the same worktree, branch, round and budget, only the model changes, and the record
// says so.  dry grows here for the rest of the round.  It is the new executor, "" where none can
// take it, when the same worker carries on and nothing is recorded.  Only a flake settles for no
// self-review: it usually answers after a wait.
func (l *loop) handExecutor(why, detail string, dry map[string]bool) (string, error) {
	before := l.executor
	if model, err := config.ModelNamed(before); err == nil {
		dry[model.Provider] = true
	}
	rules, ok := l.rules()
	readings, err := usage.Read()
	models, known := config.Models()
	if !ok || err != nil || known != nil {
		return "", nil
	}
	next, reviewer, found := rules.Pair(refusing{ready{readings, unable()}, models, dry})
	if !found || why == "transient" && rules.Same(next, reviewer) {
		return "", nil
	}
	previous := l.reviewer
	l.executor, l.execSession = next, ""
	if reviewer != previous {
		l.reviewer, l.reviewSession = reviewer, ""
	}
	if err := l.save(func(record *run.Object) {
		noteHandover(record, before, next, why, l.rnd)
		run.SetAll(record, "executor", next, "reviewer", none(reviewer), "exec_session", nil, "review_session", none(l.reviewSession))
	}); err != nil {
		return "", err
	}
	l.say(fmt.Sprintf("handing executor to %s: %s %s", next, before, detail))
	if reviewer != previous {
		l.say(fmt.Sprintf("reviewer re-picked for executor %s: %s -> %s", next, previous, reviewer))
	}
	return next, nil
}

// noteHandover is which model held which rounds and why the work changed hands, Python's
// note_handover: two models that shared a round both held it, so the outgoing model's rounds start
// at the round it took over in.
func noteHandover(record *run.Object, before, next, why string, round int) {
	history := record.List("executor_history")
	from := 1
	if len(history) > 0 {
		from = round
		if last, _ := history[len(history)-1].(*run.Object); last != nil {
			if held := last.List("rounds"); len(held) > 0 {
				if number, ok := run.Num(held[len(held)-1]); ok {
					from = int(number)
				}
			}
		}
	}
	rounds := []any{}
	for each := from; each <= round; each++ {
		rounds = append(rounds, run.Number(strconv.Itoa(each)))
	}
	record.Set("executor_history", append(slices.Clone(history), run.Fields("from", before, "to", next, "reason", "dry",
		"model", before, "rounds", rounds, "why", why)))
}

// headWriters is every model that wrote part of the head a review judges, Python's head_writers: a
// seat's own PR's orchestrator among them.
func headWriters(record *run.Object) []string {
	writers := []string{record.Str("executor")}
	if record.Truthy("own_pr") {
		writers = append(writers, record.Str("own_orchestrator"))
	}
	for _, each := range record.List("executor_history") {
		if entry, _ := each.(*run.Object); entry != nil {
			writers = append(writers, entry.Str("from"), entry.Str("to"))
		}
	}
	return writers
}

// readyReviewers is the run's marked reviewers with room as the meters read now, in pick order
// beside everyone who wrote part of the head, Python's ready_reviewers, and those of them that wrote
// none of it: a reviewer passed over while its meter was spent is picked once it refilled.
func (l *loop) readyReviewers(failed []any) (all, independent []string, err error) {
	record, err := run.Read(l.dir)
	if record == nil {
		return nil, nil, err
	}
	rules, ok := l.rules()
	if !ok {
		return nil, nil, nil
	}
	var room pick.Room = unmetered{}
	if readings, err := usage.Read(); err != nil {
		l.say("WARN could not read the meters: " + err.Error())
	} else {
		room = ready{readings, unable()}
	}
	writers := headWriters(record)
	for _, name := range rules.Beside(room, writers, nil) {
		if slices.Contains(failed, any(name)) {
			continue
		}
		all = append(all, name)
		if !rules.Wrote(name, writers) {
			independent = append(independent, name)
		}
	}
	return all, independent, nil
}

// fallBack is the road a dry, twice-silent or twice-transient reviewer takes, Python's fall_back:
// the name of the next one's directory, or an exhausted run.  Only those that failed this round stay
// out, and only a reviewer that cannot come back settles for the executor's own model.
func (l *loop) fallBack(reason, out string, allowSelf, window bool) (string, error) {
	var failed []any
	if err := l.save(func(record *run.Object) {
		pending := record.Dict("review_pending")
		failed = pending.List("failed")
		if !slices.Contains(failed, any(l.reviewer)) {
			failed = append(slices.Clone(failed), any(l.reviewer))
		}
		pending.Set("failed", failed)
	}); err != nil {
		return "", err
	}
	all, independent, err := l.readyReviewers(failed)
	if err != nil {
		return "", err
	}
	offered := all
	if !allowSelf {
		offered = independent
	}
	if len(offered) == 0 {
		return "", &exhausted{fmt.Sprintf("reviewer %s %s and no eligible reviewer is left to review; waiting for review. See %s*/stderr.log", l.reviewer, reason, out), window}
	}
	l.reviewer, l.reviewSession = offered[0], ""
	if err := l.save(func(record *run.Object) { run.SetAll(record, "reviewer", l.reviewer, "review_session", nil) }); err != nil {
		return "", err
	}
	l.say("WARN reviewer fell back to " + l.reviewer)
	return "reviewer-" + l.reviewer, nil
}

// reviewerHandover is what a reviewer's second transient failure in a row tries: "" where nobody
// else may review, and it waits on.
func (l *loop) reviewerHandover(out string) func(string) (string, error) {
	return func(detail string) (string, error) {
		name, err := l.fallBack(detail, out, false, false)
		if tired := (*exhausted)(nil); errors.As(err, &tired) {
			return "", nil
		}
		return name, err
	}
}

// keepFindings writes what a reviewer said beside its turn and is what the record keeps of it, the
// two always together: a `findings_file` left pointing at another answer would hand the next fixer
// the wrong review, Python's record_findings.
func (l *loop) keepFindings(dir string, submitted *handin.Review) ([]any, error) {
	text := submitted.Text()
	report := filepath.Join(dir, "review.md")
	if err := os.WriteFile(report, []byte(text), 0o666); err != nil {
		return nil, err
	}
	findings, records := make([]any, 0), make([]any, 0, len(submitted.Records))
	for _, row := range submitted.Of("finding") {
		findings = append(findings, row)
	}
	if err := os.WriteFile(filepath.Join(dir, "findings.json"), []byte(run.Line(findings)), 0o666); err != nil {
		return nil, err
	}
	for _, row := range submitted.Records {
		records = append(records, row)
	}
	l.findings, l.findingsFile = text, report
	tail := []rune(strings.TrimFunc(text, config.Space))
	return []any{"findings", string(tail[max(0, len(tail)-8000):]), "findings_file", report, "review_records", records}, nil
}
