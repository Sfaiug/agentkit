package harness

import (
	"errors"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/run"
	"agentkit/internal/sqlite"
)

// opencodeDatabase is opencode.db, which keeps every session, as OpenCode resolves it (opencode.py
// `database`): $OPENCODE_DB, a name under OpenCode's data folder or a path of its own.
func opencodeDatabase() string {
	name, set := os.LookupEnv("OPENCODE_DB")
	if !set {
		name = "opencode.db"
	}
	if filepath.IsAbs(name) {
		return name
	}
	return filepath.Join(share(), "opencode", name)
}

// An opencodeTurn is what opencode.db says of a session: the error its last turn ended on, "" for
// none (opencode.py `error`), and the model and effort of its last answer and when it was made
// (`running`); `ended` and `answered` are false where the database holds no row of either.
type opencodeTurn struct {
	said              string
	ended             bool
	model, effort, at any
	answered          bool
}

// opencodeRead is what opencode.db says of that session now, read once; false where Go cannot read
// it as Python's sqlite3 does.  Each answer reads the session's row of its kinds with the highest
// `seq`.
func opencodeRead(session string) (opencodeTurn, bool) {
	var ended, answer latest
	numbered := true
	err := sqlite.Rows(opencodeDatabase(), "session_message", []string{"session_id", "type", "seq", "time_created", "data"}, func(row []any) {
		seq, isNumber := sqlNumber(row[2])
		switch {
		case row[0] != session:
		case row[1] == "user" || row[1] == "idle":
			numbered = numbered && isNumber
			ended.take(row, seq)
		case row[1] == "assistant":
			numbered = numbered && isNumber
			answer.take(row, seq)
		}
	})
	if errors.Is(err, fs.ErrNotExist) {
		return opencodeTurn{}, true
	}
	if err != nil || !numbered { // SQLite orders a seq that is no number among the numbers its own way
		return opencodeTurn{}, false
	}
	turn, known := opencodeTurn{ended: ended.row != nil}, true
	if turn.ended {
		turn.said, known = opencodeError(ended.row)
	}
	if answer.row != nil {
		data, readable := opencodeData(answer.row[4])
		known = known && readable
		turn.model, turn.effort, turn.at, turn.answered = opencodeAnswer(data, answer.row[3])
	}
	return turn, known
}

// A latest is the row of the highest seq taken so far.
type latest struct {
	row []any
	seq float64
}

func (last *latest) take(row []any, seq float64) {
	if last.row == nil || seq > last.seq {
		*last = latest{row, seq}
	}
}

// opencodeError is the error a turn's ending row holds, "" where it holds none: a failed turn's
// `idle` row holds its own -- the `provider.*` type, the status and the message the seat shows
// behind `Error: ` -- and one that names its wait (`retryAfterMs`, from the row's own stamp)
// says when, as `turns.try_again_at` reads it.
func opencodeError(row []any) (string, bool) {
	data, known := opencodeData(row[4])
	if data == nil || row[1] != "idle" || data.Dict("error") == nil {
		return "", known
	}
	failed := data.Dict("error")
	var parts []string
	for _, key := range []string{"type", "status", "message"} {
		if value := failed.Get(key); value != nil {
			parts = append(parts, run.Text(value))
		}
	}
	said := "Error: " + strings.Join(parts, " ")
	wait, waits := run.Num(failed.Get("retryAfterMs"))
	created, dated := sqlNumber(row[3])
	if !waits || !dated {
		return said, known
	}
	// Python's datetime: its microseconds rounded half to even, written to the millisecond
	at := (created + wait) / 1000
	if !(at > -62135596800 && at < 253402300800) { // past the years it holds, it raises
		return "", false
	}
	whole := math.Floor(at)
	reset := time.Unix(int64(whole), int64(math.RoundToEven((at-whole)*1e6))*1000).UTC()
	return said + " try again at " + reset.Format("2006-01-02T15:04:05.000+00:00"), known
}

// opencodeAnswer is the model, effort and time an answer's row records: OpenCode records them on
// each (`model`, its `variant` the effort, `default` where none was set).
func opencodeAnswer(data *run.Object, created any) (model, effort, at any, answered bool) {
	if data == nil {
		return nil, nil, nil, false
	}
	ran := data.Dict("model")
	when, dated := sqlNumber(created)
	if ran == nil || !ran.Has("providerID") || !ran.Has("id") || !dated {
		return nil, nil, nil, false
	}
	if effort = ran.Get("variant"); effort == "default" {
		effort = nil
	}
	return run.Text(ran.Get("providerID")) + "/" + run.Text(ran.Get("id")), effort, run.Float(when / 1000), true
}

// opencodeData is a row's `data` as Python's json.loads reads it, nil where it is no object or
// raises; false where Python reads what Go does not: bytes, or a lone surrogate.
func opencodeData(value any) (*run.Object, bool) {
	if _, isBytes := value.([]byte); isBytes {
		return nil, false
	}
	text, isText := value.(string)
	decoded, err := run.Decode([]byte(text))
	if errors.Is(err, run.ErrLoneSurrogate) {
		return nil, false
	}
	data, _ := decoded.(*run.Object)
	if !isText || err != nil {
		return nil, true
	}
	return data, true
}

// sqlNumber is a value SQLite keeps as a number, as Python reads it: an int or a float.
func sqlNumber(value any) (float64, bool) {
	switch number := value.(type) {
	case int64:
		return float64(number), true
	case float64:
		return number, true
	}
	return 0, false
}
