package history

import (
	"errors"
	"io/fs"
	"os"

	"github.com/ncruces/go-sqlite3"
)

// SlotGates is the gate each reason a run waits for a slot names, Python's history.SLOT_GATES.
var SlotGates = map[string]string{"count": "admission", "load": "admission", "memory": "memory", "unit memory": "memory"}

// GateHolds is Python's history.gate_holds: when each gate last held a run, the end of the last
// wait counted for it, kept after the run's record is collected; none where no history.db stands.
// Read through a connection that cannot write, as Python reads it; false where SQLite
// cannot answer.
func GateHolds() (map[string]float64, bool) {
	last := map[string]float64{}
	if _, err := os.Stat(Path()); errors.Is(err, fs.ErrNotExist) {
		return last, true
	}
	db, err := connect(Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		return nil, false
	}
	defer db.Close()
	have, err := db.columns("phases")
	if err != nil {
		return nil, false
	}
	// a history from before slot waits kept their reason holds none
	kind := "NULL"
	if have["wait_kind"] {
		kind = "wait_kind"
	}
	rows, err := db.rows("SELECT phase, " + kind + " AS kind, MAX(ended_at) AS at FROM phases " +
		"WHERE phase IN ('slot wait', 'suite wait', 'lander wait') AND ended_at > started_at GROUP BY phase, " + kind)
	if err != nil {
		return nil, false
	}
	for _, row := range rows {
		name := "suite turns"
		if row.Text("phase") == "slot wait" {
			name = SlotGates[row.Text("kind")]
		}
		if at, ok := row.Num("at"); ok && name != "" {
			last[name] = max(last[name], at)
		}
	}
	return last, true
}
