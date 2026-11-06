package history

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"time"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/config"
	"agentkit/internal/pick"
	"agentkit/internal/run"
)

// A run's row, written where Python's transitions writes it, from the run's record: made, or
// brought back to running, as the run is launched and as it starts (Start); kept as its loop goes
// (Keep), its turns' tokens counted as each ends (Spent); and closed in history_ending's terms as it
// ends (Finish).  The steps, checks and waits Python records beside it are not Go's yet.

// Start is Python's transitions.history_start: the row of a run as its launch or its start finds
// it, made running.  A suite's repository has none, and the row a launch wrote before its
// repository was known goes.
func Start(record *run.Object, log func(string)) {
	if unrecorded(record) {
		return
	}
	id := record.Get("run_id")
	if sandbox(record.Str("repo")) {
		apply(log, func(db *DB) error {
			if err := db.exec("DELETE FROM runs WHERE run_id=?", id); err != nil {
				return err
			}
			return db.exec("DELETE FROM phases WHERE run_id=?", id)
		})
		return
	}
	started := record.Get("started_at")
	if started == nil {
		started = now()
	}
	var repo, orchestrator any
	if record.Truthy("repo") {
		repo = name(record.Get("repo"))
	}
	session := seat(record)
	if session != nil {
		if _, held, err := config.ResolveSession(session.(string)); err == nil && len(held) > 0 {
			orchestrator = held["orchestrator"]
		}
	}
	noReview := 0
	if policy := record.Dict("policy"); policy != nil && run.Equal(policy.Get("review_rounds"), run.Number("0")) {
		noReview = 1
	}
	// a new row is followed for breaks and landing flakes, none yet; the orchestrator and the plan
	// line stay as the first write found them
	values := []any{id, repo, record.Get("executor"), record.Get("reviewer"),
		len(record.List("round_summaries")), "running", nil, started, nil, 0.0, 0.0, 0.0, 0.0, nil, nil, nil, nil,
		session, record.Get("task_words"), record.Get("task_points"), record.Get("task_checks"), nil,
		orchestrator, 0.0, 0.0, 0.0, 0.0, run.ChangeName(record), 0, "", kind(record), 0, record.Get("plan_line"), noReview}
	apply(log, func(db *DB) error {
		return db.exec("INSERT INTO runs (run_id, repo, executor, reviewer, rounds_used, final_state, verdict, "+
			"started_at, finished_at, executor_seconds, done_when_seconds, reviewer_seconds, "+
			"merge_seconds, total_seconds, executor_tokens, reviewer_tokens, peak_rss_mb, session, "+
			"task_words, task_points, task_checks, task_files, orchestrator, "+
			"slot_wait_seconds, suite_wait_seconds, merge_wait_seconds, lander_wait_seconds, change, "+
			"landing_breaks, broke_after_merge, kind, landing_flakes, plan_line, no_review) "+
			"VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "+
			"ON CONFLICT(run_id) DO UPDATE SET repo=COALESCE(excluded.repo,runs.repo), "+
			"executor=COALESCE(excluded.executor,runs.executor), reviewer=COALESCE(excluded.reviewer,runs.reviewer), "+
			"rounds_used=excluded.rounds_used, final_state='running', verdict=NULL, "+
			"finished_at=NULL, total_seconds=NULL, "+
			"session=COALESCE(excluded.session,runs.session), "+
			"task_words=COALESCE(excluded.task_words,runs.task_words), "+
			"task_points=COALESCE(excluded.task_points,runs.task_points), "+
			"task_checks=COALESCE(excluded.task_checks,runs.task_checks), "+
			"task_files=COALESCE(excluded.task_files,runs.task_files), "+
			"orchestrator=COALESCE(runs.orchestrator,excluded.orchestrator), "+
			"change=COALESCE(excluded.change,runs.change), "+
			"kind=COALESCE(excluded.kind,runs.kind), "+
			"no_review=COALESCE(excluded.no_review,runs.no_review)", values...)
	})
}

// Keep is the history.update_run of Python's LoopState.save, made where a change of the record
// moved what it keeps: the run's repository, workers, executor's effort, rounds and seat.
func Keep(before, after *run.Object, log func(string)) {
	if unrecorded(after) {
		return
	}
	kept := func(record *run.Object, session any) []any {
		return []any{"repo", record.Get("repo"), "executor", record.Get("executor"), "reviewer", record.Get("reviewer"),
			"executor_effort", record.Get("executor_effort"), "rounds_used", len(record.List("round_summaries")),
			"session", session}
	}
	// the seat as the record names it: resolving a rename on every save would read its files
	if reflect.DeepEqual(kept(before, named(before)), kept(after, named(after))) {
		return
	}
	pairs := kept(after, seat(after))
	apply(log, func(db *DB) error { return db.update(after.Get("run_id"), pairs...) })
}

// Classified is the history.update_run of Python's preflight, once a review knows whose pull
// request it reads: the row's kind as the record now has it.
func Classified(record *run.Object, log func(string)) {
	if unrecorded(record) {
		return
	}
	apply(log, func(db *DB) error { return db.update(record.Get("run_id"), "kind", kind(record)) })
}

// Finish is Python's transitions.history_finish: the row ended as the record ends the run, in
// history_ending's terms and with what git measures of it, what neither says left as the row has it.
func Finish(record *run.Object, log func(string)) {
	if unrecorded(record) {
		return
	}
	files, lines, rules := measured(record)
	apply(log, ending(record.Get("run_id"), record, "task_files", files, "changed_lines", lines, "rules_bytes", rules))
}

// ending is Python's finish_run of history_ending's terms: the row of that id ended as the record
// ends its run, with the measures given as column, value pairs, in one commit with the run time it
// closes and every turn the run's receipts name counted, one killed with its run included.
func ending(id any, record *run.Object, measures ...any) func(*DB) error {
	finished := record.Get("finished_at")
	if !record.Truthy("finished_at") {
		finished = now()
	}
	var rounds any
	if summaries, isList := record.Get("round_summaries").([]any); isList {
		rounds = len(summaries)
	}
	var pairs []any
	given := append([]any{"repo", record.Get("repo"), "executor", record.Get("executor"),
		"reviewer", record.Get("reviewer"), "rounds_used", rounds, "final_state", record.Get("state"),
		"verdict", record.Get("verdict"), "finished_at", finished, "session", seat(record),
		"own_orchestrator", record.Get("own_orchestrator"), "own_orchestrator_effort", record.Get("own_orchestrator_effort")},
		measures...)
	for i := 0; i < len(given); i += 2 {
		if given[i+1] != nil {
			pairs = append(pairs, given[i], given[i+1])
		}
	}
	peak, started, pair := record.Get("peak_rss_mb"), record.Get("started_at"), reviewPair(record)
	return func(db *DB) error {
		// a merge republished keeps the pair it ended with, a resume's ending records it anew
		err := db.exec("UPDATE runs SET review_pair=? WHERE run_id=? AND finished_at IS NOT ?", pair, id, finished)
		if err == nil {
			err = db.update(id, pairs...)
		}
		if err == nil && peak != nil {
			err = db.exec("UPDATE runs SET peak_rss_mb=MAX(COALESCE(peak_rss_mb,0), ?) WHERE run_id=?", peak, id)
		}
		// the earliest start stays: the wait for a slot is run time too
		if err == nil && started != nil {
			err = db.exec("UPDATE runs SET started_at=COALESCE(MIN(started_at, ?), ?) WHERE run_id=?", started, started, id)
		}
		if err == nil {
			err = db.exec("UPDATE runs SET total_seconds=CASE WHEN started_at IS NULL THEN total_seconds "+
				"ELSE MAX(0, ?-started_at) END WHERE run_id=?", finished, id)
		}
		if err == nil {
			err = db.spendAll(id)
		}
		return err
	}
}

// update is Python's history._update: the row's columns set to the values given after them, a
// repository by its name.
func (db *DB) update(id any, pairs ...any) error {
	var columns []string
	var values []any
	for i := 0; i < len(pairs); i += 2 {
		value := pairs[i+1]
		if pairs[i] == "repo" {
			value = name(value)
		}
		columns, values = append(columns, pairs[i].(string)+"=?"), append(values, value)
	}
	if len(columns) == 0 {
		return nil
	}
	return db.exec("UPDATE runs SET "+strings.Join(columns, ", ")+" WHERE run_id=?", append(values, id)...)
}

// Carried is whether history.db holds a step of the run, or of any run for "", which Python
// records and Go does not yet: a run Python carried, whose going on is Python's, or a history of
// runs Python kept, which a launch would join.  Where none stands it holds none; where SQLite cannot
// say, it may.
func Carried(id string) bool {
	path := Path()
	if _, err := os.Stat(path); err != nil {
		return false
	}
	db, err := connect(path, sqlite3.OPEN_READONLY)
	if err != nil {
		return true
	}
	defer db.Close()
	steps, err := db.rows("SELECT 1 FROM phases WHERE ? IN ('', run_id) LIMIT 1", id)
	return err != nil || len(steps) > 0
}

// unrecorded is whether the run has no row: a suite's, under its notify sink.  Go makes no
// database for one, where Python's writes that find no row still make one: only a suite's home
// holds such a run, and nothing of it is worth measuring.
func unrecorded(record *run.Object) bool {
	return record.Truthy("notify_sink")
}

// apply is Python's history._write: change made on history.db, made where none stands and brought
// up to today's tables, in one commit under Python's writers' lock.  History never makes a run
// fail: what goes wrong is said on log, else in history.log.
func apply(log func(string), change func(*DB) error) {
	err := commit(change)
	if err == nil {
		return
	}
	line := "WARN history: " + err.Error()
	if log != nil {
		log(line)
		return
	}
	if file, err := os.OpenFile(filepath.Join(config.Home(), "history.log"), os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666); err == nil {
		file.WriteString(line + "\n")
		file.Close()
	}
}

// reviewPair is how far the recorded review's reviewer stands from its executor, Python's
// history_ending reads it: none without a review, or where the config does not know both.  A seat's
// own PR has no executor, so its writer, the seat's orchestrator, counts as one.
func reviewPair(record *run.Object) any {
	review := record.Dict("review")
	if review == nil || !review.Truthy("reviewer") {
		return nil
	}
	executor := review.Get("executor")
	if executor == nil {
		executor = record.Get("executor")
		if record.Truthy("own_pr") {
			executor = record.Get("own_orchestrator")
		}
	}
	models, err := config.Models()
	pair := [2]string{}
	for i, worker := range []any{executor, review.Get("reviewer")} {
		known, _ := worker.(string)
		if _, ok := models[known]; !ok || err != nil {
			return nil
		}
		pair[i] = known
	}
	return []string{"other provider", "same provider", "self"}[pick.Tier(models, pair[0], pair[1])]
}

// kind is the launch a row keeps after its run's record is collected, Python's run_kind.
func kind(record *run.Object) string {
	for _, origin := range [][2]string{{"repair", "repair"}, {"split_suite", "split"}, {"followup", "follow-up"}, {"night", "night"}} {
		if record.Truthy(origin[0]) {
			return origin[1]
		}
	}
	switch {
	case record.Truthy("review_pr") && record.Truthy("own_pr"):
		return "seat PR"
	case record.Truthy("review_pr"):
		return "PR"
	}
	return "task"
}

// seat is the seat the run was launched from, by its name now, nil for none.
func seat(record *run.Object) any {
	if name := run.Seat(record); name != "" {
		return name
	}
	return nil
}

// named is the seat the run was launched from as its record names it.
func named(record *run.Object) any {
	if record.Truthy("launched_session") {
		return record.Get("launched_session")
	}
	return record.Get("session")
}

// name is a repository by the last part of its path, as Python's Path.name reads it; anything
// that is no path as it was.
func name(repo any) any {
	path, isText := repo.(string)
	if !isText || path == "" {
		return repo
	}
	if base := filepath.Base(path); base != "." && base != string(filepath.Separator) {
		return base
	}
	return ""
}

func now() float64 { return float64(time.Now().UnixNano()) / 1e9 }
