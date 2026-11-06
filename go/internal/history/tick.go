package history

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/run"
)

// The tick's history rows: seat tokens' read (KeepsSeats), history sync (Agree) and history
// checkpoint (Checkpoint).

// KeepsSeats is whether history.db keeps seats' tokens, which Python ak alone reads on: true where
// SQLite cannot say.
func KeepsSeats() bool {
	db, err := connect(Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		return true
	}
	defer db.Close()
	seats, err := db.keepsSeats()
	return err != nil || seats
}

func (db *DB) keepsSeats() (bool, error) {
	seats, err := db.rows("SELECT 1 FROM sqlite_master WHERE name = 'seat_sources'")
	return len(seats) > 0, err
}

// Agree is Python's transitions.history_agree: each row history.db still holds as running brought
// to the end its run reached, as a row's own ending can be lost (a write that failed, a process
// killed before it).  A run whose record has ended gives its row that ending, as Finish writes it
// but for what git measures; one whose directory is gone ends as unknown; one still going, or
// started again before the write, ends its row itself.  False, having written nothing, where the
// sync is Python ak's: a history SQLite cannot read, or whose tokens wait for Python's one-time
// repair, running rows or none; or an ending Python writes more of, a record Go cannot read as
// Python does, or a merge's landing breaks.
func Agree(log func(string)) bool {
	ids, read := running()
	if !read {
		return false
	}
	type due struct {
		id             string
		saved, endedAs *run.Object
	}
	var dues []due
	for _, id := range ids {
		dir := filepath.Join(run.Runs(), id)
		record, err := run.Read(dir)
		if errors.Is(err, run.ErrLoneSurrogate) || errors.Is(err, run.ErrLimit) {
			return false
		}
		if record != nil && run.Ended(record) {
			if record.Truthy("merged") && record.Truthy("landing_red_patches") {
				return false
			}
			dues = append(dues, due{id, record, record})
		} else if _, err := os.Stat(dir); errors.Is(err, fs.ErrNotExist) {
			dues = append(dues, due{id, run.NewObject(), run.Fields("state", "unknown")})
		}
	}
	for _, each := range dues {
		agree(each.id, each.saved, each.endedAs, log)
	}
	return true
}

// running is the ids of the rows still running, as Python's history.running reads them, and
// whether Go read them as they stand: not where SQLite cannot answer (a journal to roll back,
// tables to make), nor while the tokens wait for Python's one-time repair, which Python's
// connect brings about first.
func running() ([]string, bool) {
	if _, err := os.Stat(Path()); err != nil {
		return nil, true
	}
	db, err := connect(Path(), sqlite3.OPEN_READONLY)
	if err != nil {
		return nil, false
	}
	defer db.Close()
	rows, err := db.rows("SELECT run_id FROM runs WHERE final_state='running'")
	if err != nil {
		return nil, false
	}
	var ids []string
	for _, row := range rows {
		ids = append(ids, row.Text("run_id"))
	}
	_, err = db.recounted()
	return ids, err == nil
}

// agree writes the run's ending to its row, Python's finish_run with `saved`: only to a row still
// running whose run's record still reads its state and end as saved, a gone run's as none, under
// the run's recovery lock while its directory stands, so a stop the tick read has stopped writing.
func agree(id string, saved, endedAs *run.Object, log func(string)) {
	dir := filepath.Join(run.Runs(), id)
	if info, err := os.Stat(dir); err == nil && info.IsDir() {
		release, err := run.Hold(dir)
		if err != nil {
			return
		}
		defer release()
	}
	write := ending(id, endedAs)
	apply(log, func(db *DB) error {
		now, _ := run.Read(dir)
		if now == nil {
			now = run.NewObject()
		}
		still, err := db.rows("SELECT 1 FROM runs WHERE run_id=? AND final_state='running'", id)
		if err != nil || len(still) == 0 || !run.Equal(now.Get("state"), saved.Get("state")) ||
			!run.Equal(now.Get("finished_at"), saved.Get("finished_at")) {
			return err
		}
		return write(db)
	})
}

// Checkpoint is Python's waiter.checkpoint: history.db's WAL moved into the database once it holds
// more than walMax.  Passive, it waits on no reader or writer and holds no lock of ak's, so no
// writer waits on its syncs; one it cannot finish waits for the next tick.
func Checkpoint() {
	path := Path()
	if info, err := os.Stat(path + "-wal"); err != nil || info.Size() <= walMax {
		return
	}
	db, err := connect(path, sqlite3.OPEN_READWRITE)
	if err != nil {
		return
	}
	defer db.Close()
	if db.writer() == nil {
		db.exec("PRAGMA wal_checkpoint(PASSIVE)")
	}
}
