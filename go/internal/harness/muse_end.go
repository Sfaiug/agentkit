package harness

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/config"
	"agentkit/internal/sqlite"
)

// museEnd takes the session's row in session-index.db, then the views cached of it, then its
// folder: a pass cut short finds the folder again, and nothing of it is left once that goes
// (muse.py `end_conversation`).
func museEnd(folder string) End {
	return func(ends func(...string) bool, _ func(string) bool) error {
		views, ended, err := museUnindexed(folder, ends)
		if err != nil {
			return fmt.Errorf("Muse's session index: %w", err)
		}
		if !ended {
			return nil
		}
		for _, part := range append(views, folder) {
			if err := os.RemoveAll(part); err != nil {
				return err
			}
		}
		return nil
	}
}

// museUnindexed takes the session's row out of session-index.db only where ends(the views cached
// of it) holds once Muse's writers wait on the index, as a session resumed meanwhile has written
// or cached: those views, and whether it went.
func museUnindexed(folder string, ends func(...string) bool) ([]string, bool, error) {
	sessions := filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(folder))))
	conn, err := sqlite.Open(filepath.Join(filepath.Dir(sessions), "session-index.db"), sqlite3.OPEN_READWRITE)
	if err != nil {
		return nil, false, err
	}
	defer conn.Close() // what is not committed rolls back
	if err := conn.BusyTimeout(30 * time.Second); err != nil {
		return nil, false, err
	}
	transaction, err := conn.BeginImmediate()
	if err != nil {
		return nil, false, err
	}
	var views []string
	for _, cached := range config.Glob(sessions, ".msp-view-*") {
		if view := filepath.Join(cached, filepath.Base(folder)); exists(view) {
			views = append(views, view)
		}
	}
	if !ends(views...) {
		return nil, false, nil
	}
	stmt, _, err := conn.Prepare("DELETE FROM sessions WHERE session_dir = ?")
	if err != nil {
		return nil, false, err
	}
	defer stmt.Close()
	if err := stmt.BindText(1, folder); err != nil {
		return nil, false, err
	}
	if err := stmt.Exec(); err != nil {
		return nil, false, err
	}
	return views, true, transaction.Commit()
}
