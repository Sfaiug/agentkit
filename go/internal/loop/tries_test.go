//go:build linux

package loop

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/box"
	"agentkit/internal/handin"
)

// killed is the report of a box whose command a SIGTERM ended.
const killed = `{"returncode": -15, "processes": []}`

func TestTheLatestTurnIsTheNewestTryOfTheLastAttempt(t *testing.T) {
	round, at := t.TempDir(), time.Now()
	written := func(name string, seconds int) {
		turnIn(t, round, name, nil)
		when := at.Add(time.Duration(seconds) * time.Second)
		if err := os.Chtimes(filepath.Join(round, name), when, when); err != nil {
			t.Fatal(err)
		}
	}
	written("executor", 0)
	written("executor-retry1", 9) // a try of the attempt before the last
	written("executor-attempt2", 1)
	written("executor-attempt2-retry1", 3)
	written("executor-attempt2-retry2", 3)
	if got := filepath.Base(latestTurn(round, "executor")); got != "executor-attempt2-retry2" {
		t.Fatalf("a tie goes to the later name: %s", got)
	}
	written("executor-attempt2-retry2", 2)
	if got := filepath.Base(latestTurn(round, "executor")); got != "executor-attempt2-retry1" {
		t.Fatalf("the newest try: %s", got)
	}
}

func TestATryKilledAfterItAnsweredStillOwesItsAnswer(t *testing.T) {
	round := t.TempDir()
	turnIn(t, round, "executor", map[string]string{"session_id": "sid-a"})
	turnIn(t, round, "executor-retry1", map[string]string{"final.md": "a\n", handin.File: closed, "session_id": "sid-b", box.Report: killed})
	if name, kind, session := openWorker(round); name != "executor" || kind != "resume" || session != "sid-b" {
		t.Fatalf("the killed try goes on: %q %q %q", name, kind, session)
	}
	turnIn(t, round, "executor-retry1", map[string]string{box.Report: `{"returncode": 1, "processes": []}`})
	if name, _, _ := openWorker(round); name != "" {
		t.Fatalf("a try that exited answered: %q", name)
	}
}
