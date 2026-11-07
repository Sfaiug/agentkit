package tick

import (
	"cmp"
	"encoding/json"
	"os"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/history"
	"agentkit/internal/run"
)

// seatTokens is Python's seat_tokens.read where no seat has spent anything it could count yet:
// history.db keeps each seat's sources, to be read from their start, where a seat or a source
// kept stands.  errLeft, having written nothing, where a seat's harness keeps its tokens where Go
// does not look, or a source holds lines, which Python counts.  A home without a history keeps
// none: Go's tick makes none (mergeRows).
func seatTokens() error {
	if run.Historyless() {
		return nil
	}
	var sources []history.Source
	seats := 0
	for _, file := range config.SeatFiles() {
		data, err := os.ReadFile(file)
		var record map[string]any
		if err != nil || json.Unmarshal(data, &record) != nil || record == nil {
			continue // no record Python's session_records reads
		}
		if _, renamed := record[config.Renamed]; renamed {
			continue
		}
		seats++
		orchestrator, _ := record["orchestrator"].(string)
		model, _ := config.ModelNamed(orchestrator) // a model the config does not name runs on no harness Go reads
		found, known := harness.TokenSources(model.Harness, record)
		if !known {
			return errLeft
		}
		repo, _ := record["repo"].(string)
		account, _ := record["account"].(string)
		for _, path := range found {
			sources = append(sources, history.Source{Path: config.Resolve(path), Harness: model.Harness, Repo: repo,
				Account: cmp.Or(account, config.DefaultAccount)})
		}
	}
	if seats == 0 && !history.KeepsSeats() {
		return nil // renames' pointers alone: Python reads no seat, and makes no table for none
	}
	if !history.Sources(sources) {
		return errLeft
	}
	return nil
}
