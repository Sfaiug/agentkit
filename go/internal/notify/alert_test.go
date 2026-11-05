package notify

import (
	"io"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestAnAlertPagesOnceAndKeepsAlreadyCompletedWork(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("AK_NOTIFY_SINK", "dry-run")
	t.Setenv("AK_NOTIFY_SINK_LOG", filepath.Join(t.TempDir(), "pages"))
	t.Setenv("AGENTKIT_DISCORD_USER_ID", "")
	if err := os.MkdirAll(state(), 0o700); err != nil {
		t.Fatal(err)
	}
	completed := run.Fields("previous", "work")
	if err := writeCard("acme", run.Fields("word", "working", "completed", completed)); err != nil {
		t.Fatal(err)
	}
	for range 2 {
		if err := Alert("acme", "the seat could not reopen", "revive:acme:r-build:1000", io.Discard); err != nil {
			t.Fatal(err)
		}
	}
	card, err := readObject(seatFile("card", "acme", "json"))
	events, _ := filepath.Glob(filepath.Join(outbox(), "*.json"))
	if err != nil || !run.Equal(card.Get("completed"), completed) || len(events) != 1 || !sentAlert("acme", "needs you", card) {
		t.Fatalf("card=%s, events=%v, err=%v", run.Line(card), events, err)
	}
}
