package harness

import (
	"cmp"
	"errors"
	"io/fs"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/ncruces/go-sqlite3"

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

// opencodeRead is what opencode.db says of that session now, read through SQLite over a read-only
// connection with Python's queries (opencode.py `error`, `running`), the write-ahead log OpenCode
// keeps while it runs included; false where Go reads it otherwise than Python does.
func opencodeRead(session string) (opencodeTurn, bool) {
	path := opencodeDatabase()
	if info, err := os.Stat(path); errors.Is(err, fs.ErrNotExist) {
		return opencodeTurn{}, true
	} else if err != nil || !info.Mode().IsRegular() { // Python's sqlite3 fails on it (`unread`); a pipe would hang the open
		return opencodeTurn{}, false
	}
	conn, err := sqlite.Open(path, sqlite3.OPEN_READONLY)
	if err != nil {
		return opencodeTurn{}, false
	}
	defer conn.Close()
	ended, err := opencodeRow(conn, "SELECT type, time_created, data FROM session_message"+
		" WHERE session_id = ? AND type IN ('user', 'idle') ORDER BY seq DESC LIMIT 1", session)
	answer, failed := opencodeRow(conn, "SELECT time_created, data FROM session_message"+
		" WHERE session_id = ? AND type = 'assistant' ORDER BY seq DESC LIMIT 1", session)
	if err != nil || failed != nil {
		return opencodeTurn{}, false
	}
	turn, known := opencodeTurn{ended: ended != nil}, true
	if turn.ended {
		turn.said, known = opencodeError(ended)
	}
	if answer != nil {
		data, readable := opencodeData(answer[1])
		known = known && readable
		turn.model, turn.effort, turn.at, turn.answered = opencodeAnswer(data, answer[0])
	}
	return turn, known
}

// opencodeRow is the first row the query answers for that session, each value as Python's sqlite3
// reads it; nil where it answers none.
func opencodeRow(conn *sqlite3.Conn, query, session string) ([]any, error) {
	stmt, _, err := conn.Prepare(query)
	if errors.Is(err, sqlite3.ERROR) { // no such table: Python's sqlite3.Error reads none
		return nil, nil
	} else if err != nil {
		return nil, err
	}
	defer stmt.Close()
	if err := stmt.BindText(1, session); err != nil || !stmt.Step() {
		return nil, cmp.Or(err, stmt.Err())
	}
	row := make([]any, stmt.ColumnCount())
	return row, stmt.Columns(row...)
}

// opencodeError is the error a turn's ending row holds, "" where it holds none: a failed turn's
// `idle` row holds its own -- the `provider.*` type, the status and the message the seat shows
// behind `Error: ` -- and one that names its wait (`retryAfterMs`, from the row's own stamp)
// says when, as `turns.try_again_at` reads it.
func opencodeError(row []any) (string, bool) {
	data, known := opencodeData(row[2])
	if data == nil || row[0] != "idle" || data.Dict("error") == nil {
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
	created, dated := sqlNumber(row[1])
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
