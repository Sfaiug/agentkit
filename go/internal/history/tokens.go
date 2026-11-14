package history

import (
	"cmp"
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// Spent counts into the run's row what the turn in out, of the harness name, spent, Python's
// add_turn_tokens at a turn's end, however it ended: a refused, parked or killed turn spent too.
func Spent(record *run.Object, name, out string, log func(string)) {
	if unrecorded(record) {
		return
	}
	id := record.Get("run_id")
	apply(log, func(db *DB) error { return db.spend(id, name, out) })
}

// spendAll counts every turn of the run whose receipt names its harness, as Python's finish_run
// does at an ending: a turn whose own end never came, killed with its run, is counted here, and a
// launch from before receipts keeps the total it recorded.
func (db *DB) spendAll(id any) error {
	for _, receipt := range receipts(id) {
		name, err := os.ReadFile(receipt)
		if err != nil {
			continue
		}
		if err := db.spend(id, strings.TrimSpace(string(name)), filepath.Dir(receipt)); err != nil {
			return err
		}
	}
	return nil
}

// spend adds what the turn in out, of the harness name, spent to its role's total in the run's
// row, and its counts by model, unless the row counts that turn already, Python's _add_turn_tokens:
// the total, the turns it includes and their counts go in or roll back together.  A turn its
// harness says nothing of stays uncounted, for a later reading; one whose total it does not say,
// as a turn killed before its stream showed a usage whose session's transcripts hold its
// messages, totals its counts.
func (db *DB) spend(id any, name, out string) error {
	found, err := db.rows("SELECT counted_turns FROM runs WHERE run_id=?", id)
	if err != nil || len(found) == 0 {
		return err
	}
	var counted []string
	if err := json.Unmarshal([]byte(cmp.Or(found[0].Text("counted_turns"), "[]")), &counted); err != nil {
		return err
	}
	turn := resolved(out)
	if slices.Contains(counted, turn) {
		return nil
	}
	tokens, said := harness.Tokens(name, out)
	usage := turnUsage(id, name, out)
	if !said {
		if len(usage) == 0 {
			return nil
		}
		for _, row := range usage {
			for _, count := range row[4:] {
				tokens += float64(count.(int64))
			}
		}
	}
	role := "executor"
	if strings.HasPrefix(filepath.Base(out), "reviewer") {
		role = "reviewer"
	}
	counted = append(counted, turn)
	slices.Sort(counted)
	listed := []any{}
	for _, each := range counted {
		listed = append(listed, each)
	}
	column := role + "_tokens"
	if err := db.exec("UPDATE runs SET "+column+"=COALESCE("+column+",0)+?, counted_turns=? WHERE run_id=?",
		int64(tokens), run.Line(listed), id); err != nil {
		return err
	}
	for _, row := range usage {
		if err := db.exec("INSERT INTO turn_usage (turn, run_id, role, account, model, began, at, input, "+
			"cache_write, cache_read, output) VALUES (?,?,?,?,?,?,?,?,?,?,?)", append([]any{turn, id, role}, row...)...); err != nil {
			return err
		}
	}
	return nil
}

// turnUsage is the turn_usage columns past its role of each model the turn in out reported, Python's
// _turn_usage: the login it ran on, the model, when it began (its harness receipt) and ended (its
// last event), and its counts by kind, those totalling its session less what the session's
// latest earlier turn in the run had reached.
func turnUsage(id any, name, out string) [][]any {
	session, counts, reported := harness.TurnCounts(name, out)
	if !reported {
		return nil
	}
	began, dated := moment(filepath.Join(out, "harness"))
	if session != nil && dated {
		latest, before := 0.0, map[any][4]int64{}
		for _, receipt := range receipts(id) {
			when, dated := moment(receipt)
			if !dated || when >= began || len(before) > 0 && when <= latest {
				continue
			}
			if kept, earlier, ok := harness.TurnCounts(name, filepath.Dir(receipt)); ok && run.Equal(kept, session) {
				latest, before = when, map[any][4]int64{}
				for _, each := range earlier {
					before[each.Model] = each.Spent
				}
			}
		}
		for at, each := range counts {
			for kind, then := range before[each.Model] {
				counts[at].Spent[kind] = max(0, each.Spent[kind]-then)
			}
		}
	}
	var account any
	if text, err := os.ReadFile(filepath.Join(out, "account")); err == nil {
		account = string(text)
	}
	var rows [][]any
	for _, each := range counts {
		rows = append(rows, []any{account, each.Model, known(began, dated), known(moment(filepath.Join(out, "events.jsonl"))),
			each.Spent[0], each.Spent[1], each.Spent[2], each.Spent[3]})
	}
	return rows
}

// receipts are the harness receipts of the run id's turns, each in its turn's directory.
func receipts(id any) []string {
	dir, _ := id.(string)
	found, _ := filepath.Glob(filepath.Join(run.Runs(), dir, "round-*", "*", "harness"))
	return found
}

// moment is when the file at path was last written, in seconds, false where it cannot be read.
func moment(path string) (float64, bool) {
	info, err := os.Stat(path)
	if err != nil {
		return 0, false
	}
	return float64(info.ModTime().UnixNano()) / 1e9, true
}

// known is the value where it is, else nil.
func known(value float64, is bool) any {
	if !is {
		return nil
	}
	return value
}

// resolved is the turn's directory as Python's Path.resolve names it, which a row counts it by.
func resolved(out string) string {
	path, _ := filepath.Abs(out)
	if real, err := filepath.EvalSymlinks(path); err == nil {
		return real
	}
	return path
}
