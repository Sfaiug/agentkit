package history

import (
	"cmp"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
)

// An Unknown is a worker turn whose tokens ak does not know: the harness and login its receipts
// name, and when it ran, from its harness receipt to its last event.
type Unknown struct {
	Harness, Account string
	Began, End       float64
}

// Unknowns are the worker turns whose tokens ak does not know, of the runs not ended or ended at
// or after since, Python's spend._unknown: each no turn_usage row of those runs names, either one
// its run's counted_turns names or one of a run not ended.  Its login is the one its account
// receipt names, the usual one where it names none; it ended at its start where it kept no
// event, and one with no harness receipt is none.  Only these turns' directories are read:
// listing every run's took the owner 12.7 s cold.
func (db *DB) Unknowns(since float64) []Unknown {
	counted, kept, running := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, row := range db.Select("SELECT run_id, finished_at, counted_turns, turn FROM runs "+
		"LEFT JOIN turn_usage USING (run_id) WHERE finished_at IS NULL OR finished_at >= ?", since) {
		var turns []string
		json.Unmarshal([]byte(cmp.Or(row.Text("counted_turns"), "[]")), &turns)
		for _, turn := range turns {
			counted[turn] = true
		}
		kept[row.Text("turn")] = true
		if row["finished_at"] == nil {
			running[row.Text("run_id")] = true
		}
	}
	for id := range running {
		for _, path := range receipts(id) {
			counted[resolved(filepath.Dir(path))] = true
		}
	}
	var found []Unknown
	for turn := range counted {
		if kept[turn] {
			continue
		}
		began, dated := moment(filepath.Join(turn, "harness"))
		if !dated {
			continue
		}
		end, ended := moment(filepath.Join(turn, "events.jsonl"))
		if !ended {
			end = began
		}
		found = append(found, Unknown{receipt(turn, "harness"), cmp.Or(receipt(turn, "account"), config.DefaultAccount), began, end})
	}
	return found
}

// receipt is the turn directory's receipt name as the worker wrote it, "" once it is gone.
func receipt(turn, name string) string {
	text, _ := os.ReadFile(filepath.Join(turn, name))
	return strings.TrimSpace(string(text))
}
