package harness

import (
	"math"
	"os"
	"time"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/sqlite"
)

// opencodeTyped is what the user side typed in that session, as opencode.py's `user_messages`
// reads opencode.db: each user row's `text`, dated when OpenCode wrote it, in milliseconds; none
// where the database holds none or cannot be read.
func opencodeTyped(session string) []Prompt {
	path := opencodeDatabase()
	if info, err := os.Stat(path); err != nil || !info.Mode().IsRegular() { // a pipe would hang the open
		return nil
	}
	conn, err := sqlite.Open(path, sqlite3.OPEN_READONLY)
	if err != nil {
		return nil
	}
	defer conn.Close()
	conn.BusyTimeout(5 * time.Second) // sqlite3.connect's own
	stmt, _, err := conn.Prepare("SELECT time_created, data FROM session_message WHERE session_id = ? AND type = 'user' ORDER BY seq")
	if err != nil {
		return nil
	}
	defer stmt.Close()
	if stmt.BindText(1, session) != nil {
		return nil
	}
	var typed []Prompt
	for stmt.Step() {
		row := make([]any, 2)
		if stmt.Columns(row...) != nil {
			return nil
		}
		created, dated := sqlNumber(row[0])
		data, _ := opencodeData(row[1])
		if at := created / 1000; data != nil && dated && !math.IsInf(at, 0) {
			if text, _ := data.Get("text").(string); text != "" {
				typed = append(typed, Prompt{at, text})
			}
		}
	}
	if stmt.Err() != nil {
		return nil
	}
	return typed
}
