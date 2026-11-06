//go:build linux

package loop

import (
	"context"
	"errors"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// Green, red and flaky pieces share one piecesCap: 40 loud pieces, half red or each red then green
// on its re-run, hand on their 256 KB with the pieces' headers and record lines, under 300 KB.
func TestPiecesShareOneBound(t *testing.T) {
	loud := `head -c 30000 /dev/zero | tr '\0' X | fold -w 1500`
	cases := []struct {
		name, command string
		pass          bool
	}{
		{"half red", loud + `; test "${AK_SHARD%/*}" -le 20 # AK_SHARD`, false},
		{"all flaky", `p="ran-${AK_SHARD%/*}"; test -e "$p" && { ` + loud + `; exit 0; }; : >"$p"; ` + loud + ` | tr X Y; exit 1 # AK_SHARD`, true},
	}
	for _, each := range cases {
		t.Run(each.name, func(t *testing.T) {
			l := rig(t, 30*time.Second)
			t.Setenv("AK_HOST_READINGS", `{"cpus":64,"free_mb":16400,"mem_total_mb":65536}`)
			ok, text := l.checked(t, each.command)
			if ok != each.pass || len(text) < piecesCap/2 || len(text) > 300*1024 {
				t.Fatalf("passed %v, handed on %d bytes", ok, len(text))
			}
		})
	}
}

// A suite interrupted keeps in history what its pieces that ended named, as Python's run_suite
// does: one piece names a flake and ends, its siblings hang, and the driver is stopped.
func TestAnInterruptedSuiteKeepsWhatItsEndedPiecesNamed(t *testing.T) {
	l := rig(t, time.Minute)
	t.Setenv("AK_HOST_READINGS", `{"cpus":2,"free_mb":16400,"mem_total_mb":65536}`)
	l.id = filepath.Base(l.dir)
	history.Start(run.Fields("run_id", l.id, "state", "running"), nil)
	db, err := sqlite3.Open(history.Path())
	if err == nil {
		err = db.BusyTimeout(2 * time.Second) // as the binding waits on a writer
	}
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	read := func(statement string) (rows [][2]any) {
		stmt, _, err := db.Prepare(statement)
		if err != nil {
			t.Error(err)
			return nil
		}
		defer stmt.Close()
		for stmt.Step() {
			rows = append(rows, [2]any{stmt.ColumnText(0), stmt.ColumnInt(1)})
		}
		return rows
	}
	ctx, cancel := context.WithCancelCause(context.Background())
	l.ctx = ctx
	interrupted := errors.New("the driver got SIGINT")
	polled := make(chan struct{})
	go func() {
		defer close(polled)
		// once the first piece's row has ended
		for ctx.Err() == nil && len(read("SELECT command, exit FROM checks WHERE command LIKE 'AK_SHARD=1/%' AND exit IS NOT NULL")) == 0 {
			time.Sleep(50 * time.Millisecond)
		}
		cancel(interrupted)
	}()
	suite := `case $AK_SHARD in 1/*) echo tests/test_web.py >"$AK_FLAKY" ;; *) sleep 60 ;; esac`
	_, _, err = l.checks([]string{suite}, filepath.Join(l.roundDir(), "donewhen.log"))
	cancel(nil)
	<-polled
	if !errors.Is(err, interrupted) {
		t.Fatalf("the suite ended with %v, its pieces' rows %v", err, read("SELECT command, exit FROM checks"))
	}
	if got := read("SELECT test, flaky FROM test_reds"); !reflect.DeepEqual(got, [][2]any{{"tests/test_web.py", 1}}) {
		t.Fatalf("test_reds: %v", got)
	}
}
