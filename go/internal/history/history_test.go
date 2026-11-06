package history

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/lock"
)

func home(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("XDG_CACHE_HOME", "")
	if err := os.MkdirAll(filepath.Dir(Path()), 0o700); err != nil {
		t.Fatal(err)
	}
	return home
}

// older writes a database as an older ak left it: the runs columns the first ak to keep a
// history made, and one an ak since made and dropped.
func older(t *testing.T, statements ...string) {
	t.Helper()
	write(t, append([]string{"CREATE TABLE runs (run_id TEXT PRIMARY KEY, repo TEXT, executor TEXT, " +
		"reviewer TEXT, rounds_used INTEGER, final_state TEXT, verdict TEXT, started_at REAL, finished_at REAL, " +
		"executor_seconds REAL, done_when_seconds REAL, reviewer_seconds REAL, merge_seconds REAL, " +
		"total_seconds REAL, executor_tokens INTEGER, reviewer_tokens INTEGER, peak_rss_mb REAL, session TEXT, " +
		"suite_repo TEXT)",
		"INSERT INTO runs (run_id, repo, final_state, executor_tokens, reviewer_tokens, finished_at, suite_repo) " +
			"VALUES ('20261001-1200-fix-api', 'acme', 'pass', 12000, 3000, 1.5, 'acme')"}, statements...)...)
}

// write runs statements on history.db as another program would.
func write(t *testing.T, statements ...string) {
	t.Helper()
	conn, err := sqlite3.Open(Path())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	for _, statement := range statements {
		if err := conn.Exec(statement); err != nil {
			t.Fatal(err)
		}
	}
}

func query(t *testing.T, db *DB, statement string) []Row {
	t.Helper()
	rows, err := db.rows(statement)
	if err != nil {
		t.Fatal(err)
	}
	return rows
}

// An older ak's database is brought up to today's tables in place: its rows as they were, the
// columns nothing reads gone, dones kept from that moment on, a writer's WAL; and once it is,
// opening it again writes nothing.
func TestAnOlderDatabaseIsBroughtUpToTodaysTables(t *testing.T) {
	home(t)
	older(t)
	before := float64(time.Now().UnixNano()) / 1e9
	db, err := Open()
	if err != nil {
		t.Fatal(err)
	}
	var tables []string
	for _, row := range query(t, db, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") {
		tables = append(tables, row.Text("name"))
	}
	if want := []string{"checks", "conflicts", "done_runs", "dones", "findings", "kept", "meter_readings",
		"owner", "phases", "reviews", "runs", "test_reds"}; !slices.Equal(tables, want) {
		t.Fatalf("tables %v, want %v", tables, want)
	}
	columns, _ := db.columns("runs")
	if !columns["no_review"] || !columns["landing_flakes"] || columns["suite_repo"] {
		t.Fatalf("runs columns %v", columns)
	}
	if rows := query(t, db, "SELECT run_id, repo, executor_tokens, reviewer_tokens, finished_at, kind FROM runs"); len(rows) != 1 ||
		rows[0]["run_id"] != "20261001-1200-fix-api" || rows[0]["repo"] != "acme" || rows[0]["executor_tokens"] != int64(12000) ||
		rows[0]["reviewer_tokens"] != int64(3000) || rows[0]["finished_at"] != 1.5 || rows[0]["kind"] != nil {
		t.Fatalf("rows %v", rows)
	}
	if kept := query(t, db, "SELECT since FROM kept"); len(kept) != 1 || kept[0]["since"].(float64) < before {
		t.Fatalf("kept %v, before %v", kept, before)
	}
	if mode := query(t, db, "PRAGMA journal_mode"); mode[0]["journal_mode"] != "wal" {
		t.Fatalf("journal mode %v", mode)
	}
	if version := query(t, db, "PRAGMA user_version"); version[0]["user_version"] != int64(2) {
		t.Fatalf("user version %v", version)
	}
	db.Close()
	written := map[string][]byte{}
	for _, suffix := range []string{"", "-wal"} {
		written[suffix], _ = os.ReadFile(Path() + suffix)
	}
	if db, err = Open(); err != nil {
		t.Fatal(err)
	}
	db.Close()
	for suffix, data := range written {
		if now, _ := os.ReadFile(Path() + suffix); !bytes.Equal(now, data) {
			t.Fatalf("history.db%s changed on a second open", suffix)
		}
	}
}

// Where no history.db stands, opening it makes none: only a run's row does.
func TestNoDatabaseIsMade(t *testing.T) {
	home(t)
	if db, err := Open(); db != nil || err != nil {
		t.Fatalf("got (%v, %v)", db, err)
	}
	if _, err := os.Lstat(Path()); err == nil {
		t.Fatal("history.db was made")
	}
}

// What Go leaves to Python ak, it leaves having written nothing: a file SQLite cannot open,
// a crashed writer's journal, which SQLite would roll back into it, seats' tokens, which Python
// alone reads on, and the tokens Python recounts once.
func TestOpenLeavesToPythonWhatItCannotKeep(t *testing.T) {
	for name, setup := range map[string]func(t *testing.T){
		"not a database": func(t *testing.T) {
			if err := os.WriteFile(Path(), bytes.Repeat([]byte("acme "), 2000), 0o600); err != nil {
				t.Fatal(err)
			}
		},
		"a crashed writer's journal": func(t *testing.T) {
			writer := filepath.Join(t.TempDir(), "history.db")
			conn, err := sqlite3.Open(writer)
			if err != nil {
				t.Fatal(err)
			}
			defer conn.Close()
			if err := conn.Exec("CREATE TABLE runs (run_id TEXT PRIMARY KEY, executor_tokens INTEGER); " +
				"WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 2000) " +
				"INSERT INTO runs SELECT 'fix-api-' || i, 1 FROM n; PRAGMA cache_size=1; BEGIN IMMEDIATE; " +
				"UPDATE runs SET executor_tokens=999999"); err != nil {
				t.Fatal(err)
			}
			// mid-transaction, its files stand as a writer that died now leaves them
			for _, suffix := range []string{"", "-journal"} {
				data, err := os.ReadFile(writer + suffix)
				if err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(Path()+suffix, data, 0o600); err != nil {
					t.Fatal(err)
				}
			}
		},
		"seats' tokens": func(t *testing.T) {
			older(t, "CREATE TABLE seat_sources (path TEXT PRIMARY KEY, harness TEXT, repo TEXT, cursor TEXT)",
				"PRAGMA user_version=2")
		},
		"tokens to recount": func(t *testing.T) {
			older(t)
			events := filepath.Join(filepath.Dir(Path()), "runs", "20261001-1200-fix-api", "round-1", "executor", "events.jsonl")
			if err := os.MkdirAll(filepath.Dir(events), 0o700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(events, []byte("{}\n"), 0o600); err != nil {
				t.Fatal(err)
			}
		},
	} {
		t.Run(name, func(t *testing.T) {
			home(t)
			setup(t)
			data, journal := read(Path()), read(Path()+"-journal")
			if db, err := Open(); db != nil || err == nil {
				t.Fatalf("got (%v, %v)", db, err)
			}
			if !bytes.Equal(read(Path()), data) || !bytes.Equal(read(Path()+"-journal"), journal) {
				t.Fatal("history.db changed")
			}
		})
	}
}

func read(path string) []byte {
	data, _ := os.ReadFile(path)
	return data
}

// Seats' tokens Python's writers keep while Go waits for their lock leave the database Python's:
// Go decides on what it reads once the lock is its own.
func TestWhatPythonWritesWhileGoWaitsDecides(t *testing.T) {
	home(t)
	older(t, "PRAGMA user_version=2")
	held, err := lock.Wait(context.Background(), strings.TrimSuffix(Path(), ".db")+".lock")
	if err != nil {
		t.Fatal(err)
	}
	opened := make(chan error)
	go func() {
		db, err := Open()
		db.Close()
		opened <- err
	}()
	// time for Open to reach the lock; it waits there however long this takes
	time.Sleep(200 * time.Millisecond)
	write(t, "CREATE TABLE seat_sources (path TEXT PRIMARY KEY, harness TEXT, repo TEXT, cursor TEXT)")
	held.Close()
	if err := <-opened; err == nil {
		t.Fatal("Go opened a database keeping seats' tokens")
	}
}

// A suite's runs count in no statistic: a row naming a suite's repository, or whose run's record
// names one.
func TestASuitesRunIsNoWork(t *testing.T) {
	home := home(t)
	record := filepath.Join(home, ".agentkit", "runs", "20261001-1300-add-beta", "run.json")
	if err := os.MkdirAll(filepath.Dir(record), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(record, []byte(`{"repo": "`+filepath.Join(home, ".agentkit", "tmp", "widgets")+`"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	older(t, "INSERT INTO runs (run_id, repo, final_state, finished_at) VALUES ('20261001-1300-add-beta', 'widgets', 'pass', 1.5)",
		"INSERT INTO runs (run_id, repo, final_state, finished_at) VALUES ('20261001-1400-smoke', 'agentkit-smoke', 'pass', 1.5)")
	db, err := Open()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if rows, ok := db.EndedRuns(0, 2); !ok || len(rows) != 1 || rows[0]["run_id"] != "20261001-1200-fix-api" {
		t.Fatalf("got (%v, %v)", rows, ok)
	}
}
