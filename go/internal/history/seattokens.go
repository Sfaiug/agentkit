package history

import (
	"cmp"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

// SeatSources is what Python's seat_tokens.read reads of the seats' records where none has spent
// anything it could count yet: the files each seat's harness keeps its tokens in, for seat_sources
// (Sources), how many records it read, and the seats it counts nothing of for want of a file, one
// whose harness names none though the seat holds a conversation, each named with that harness.
// False where a record holds text Go cannot read as Python does, a seat's harness keeps its tokens
// where Go does not look, or one of those files stands, whose lines Python counts.  It writes
// nothing.
func SeatSources() (sources []Source, seats int, uncounted []string, ok bool) {
	for _, file := range config.SeatFiles() {
		if _, err := run.ReadJSON(file); errors.Is(err, run.ErrLoneSurrogate) {
			return nil, 0, nil, false // which Python cannot write to history.db
		}
		data, err := os.ReadFile(file)
		var record map[string]any
		if err != nil || json.Unmarshal(data, &record) != nil || record == nil {
			continue // no record Python's session_records reads
		}
		if _, renamed := record[config.Renamed]; renamed {
			continue
		}
		seats++
		name := strings.TrimSuffix(strings.TrimPrefix(filepath.Base(file), "session-"), ".json")
		orchestrator, _ := record["orchestrator"].(string)
		model, _ := config.ModelNamed(orchestrator) // a model the config does not name runs on no harness Go reads
		found, known := harness.TokenSources(model.Harness, record)
		if !known {
			return nil, 0, nil, false
		}
		if conversation, _ := record["conversation"].(string); len(found) == 0 && conversation != "" {
			uncounted = append(uncounted, name+" ("+model.Harness+")")
		}
		repo, _ := record["repo"].(string)
		account, _ := record["account"].(string)
		for _, path := range found {
			path = config.Resolve(path)
			if _, err := os.Stat(path); !errors.Is(err, fs.ErrNotExist) {
				return nil, 0, nil, false // Python's reader opens whatever stands there
			}
			sources = append(sources, Source{Path: path, Harness: model.Harness, Repo: repo,
				Account: cmp.Or(account, config.DefaultAccount), Seat: name})
		}
	}
	return sources, seats, uncounted, true
}
