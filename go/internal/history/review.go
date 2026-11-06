package history

import (
	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Reviewed is Python's history.record_review: one finished review's `reviews` row, the reviewer's
// harness, model and the effort it reviewed at, its own weighed counts (ak's replays are no
// reviewer's catch), its round and the round's verdict after ak's overrides; and a `findings` row
// for each of its records with a proof, the round's answered disputes after them: a closing or a
// concession holds none.  Its output directory names it, so recording it again counts nothing
// twice; only a run with a row gets either.
func Reviewed(record *run.Object, review string, reviewer config.Model, round int, verdict string, records []*run.Object, log func(string)) {
	if unrecorded(record) {
		return
	}
	id := record.Get("run_id")
	var blocking, followup, note int
	for _, row := range records {
		switch kind := row.Str("kind"); {
		case row.Truthy("replayed"):
		case kind == "finding":
			blocking++
		case kind == "follow-up" && row.Truthy("before"):
			followup++
		case kind == "note":
			note++
		}
	}
	apply(log, func(db *DB) error {
		err := db.exec("INSERT INTO reviews (run_id, review_id, harness, model, blocking, followup, note, "+
			"round, verdict, effort) SELECT run_id, ?,?,?,?,?,?,?,?,? FROM runs WHERE run_id=? "+
			"ON CONFLICT(run_id, review_id) DO NOTHING",
			review, reviewer.Harness, reviewer.ID, blocking, followup, note, round, verdict, reviewer.TurnEffort(true), id)
		if err != nil || db.conn.Changes() == 0 {
			return err
		}
		at := now()
		for _, row := range records {
			if row.Dict("evidence") == nil {
				continue
			}
			err := db.exec("INSERT INTO findings (run_id, review_id, round, path, line, handed, kind, proof, "+
				"commit_exit, base_exit, replayed, reason, outcome, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
				append(append([]any{id, review, round}, finding(row)...), at)...)
			if err != nil {
				return err
			}
		}
		return nil
	})
}

// finding is a record's `findings` columns from path to outcome, Python's _finding.  Its exit on
// base is its proof's base part, or the proof itself where ak ran it on base alone: a follow-up
// from before the task proven with no base part, never one on a reviewed commit that is base's
// own.  A record whose kind weighing left alone was handed in as that kind.
func finding(row *run.Object) []any {
	evidence := row.Dict("evidence")
	onBase := evidence.Dict("base")
	if !evidence.Truthy("base") && row.Has("before") && evidence.Has("commit") {
		onBase = evidence
	}
	proof, handed, reason := evidence.Get("quote"), row.Get("kind"), row.Get("dropped")
	if evidence.Has("run") {
		proof = evidence.Get("run")
	}
	if row.Has("handed") {
		handed = row.Get("handed")
	}
	for _, key := range []string{"outside", "conceded"} {
		if row.Truthy(key) {
			reason = row.Get(key)
		}
	}
	var commitExit, baseExit any
	if onBase != evidence {
		commitExit = evidence.Get("returncode")
	}
	if onBase != nil {
		baseExit = onBase.Get("returncode")
	}
	return []any{row.Get("path"), row.Get("line"), handed, row.Get("kind"), proof, commitExit, baseExit,
		row.Get("replayed"), reason, row.Get("outcome")}
}
