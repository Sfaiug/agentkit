//go:build unix

package seat

import (
	"errors"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// The tick's news of a login is no card Go sends: over a question on the seat's screen the seat is
// announced `needs you` for the login, and its card word is none, so no card path writes for it.
func TestALoginsWordIsNoCardOfGos(t *testing.T) {
	home := sandbox(t)
	framed(t, home, "acme")
	record(t, home, "acme", nil)
	t.Setenv("AK_RUN_ROLE", "") // a worker's transitions card nothing
	write(t, stateFile(home, "watch.json"), `{"gh_out": {"at": 100}}`)
	write(t, filepath.Join(home, "screen-acme"), asked)
	seats, known := Looking(time.Now())
	if !known {
		t.Fatal("Go does not read the home")
	}
	if err := seats.Announce(time.Now()); err != nil {
		t.Fatal(err)
	}
	file, _ := run.ReadJSON(stateFile(home, "seat-acme.json"))
	if file.Str("word") != "needs you" || file.Str("reason") != "GitHub is logged out: run `gh auth login -p https -w`" {
		t.Fatalf("announced %s", run.Line(file))
	}
	if word, since := CardWord("acme"); word != "" || since != nil {
		t.Errorf("the login's card word is %q since %v", word, since)
	}
	carried, err := notify.TurnedQuestion("acme", CardWord, io.Discard)
	if _, missing := os.Stat(stateFile(home, "card-acme.json")); carried || err != nil || !errors.Is(missing, fs.ErrNotExist) {
		t.Errorf("a question's card took the login's: carried %v, %v, card %v", carried, err, missing)
	}
}
