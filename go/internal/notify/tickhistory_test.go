//go:build unix

package notify

import (
	"io"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestRetryDropsHistoryBeforeReadingTheSeatOrDestination(t *testing.T) {
	_, write := questionHome(t)
	write(filepath.Join(state(), "installed-at"), "200\n")
	// No readable seat or webhook is needed to retire a page from an older install.
	write(seatFile("seat", "acme", "json"), "[]")
	t.Setenv(sinkEnv, "not a URL")
	event := run.Fields("id", "old", "session", "acme", "kind", "done", "status", "pending",
		"created_at", 100, "attempts", 1, "next_attempt", 0)
	write(filepath.Join(outbox(), "old.json"), run.Line(event))
	if carried, err := RetryPending(func(string) (string, any) {
		t.Fatal("history read a seat's word")
		return "", nil
	}, false, nil, io.Discard); !carried || err != nil {
		t.Fatal(carried, err)
	}
	event, err := readEvent("old")
	if err != nil || event.Str("status") != "disabled" || event.Str("error") != "queued before the agentkit running now was installed" ||
		number(event, "attempts") != 1 || event.Get("next_attempt") != nil {
		t.Fatal(event, err)
	}
}
