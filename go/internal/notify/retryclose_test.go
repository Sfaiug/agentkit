//go:build unix

package notify

import (
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"sync/atomic"
	"testing"

	"agentkit/internal/run"
)

func TestRetryRetiresAPageClosedAfterTheCardRow(t *testing.T) {
	_, write := questionHome(t)
	var hits atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		io.WriteString(w, `{"id":"1001"}`)
	}))
	defer server.Close()
	t.Setenv(sinkEnv, server.URL)
	write(seatFile("notify", "acme", "json"), `{"kind":"needs","text":"Which database?","time":100}`)
	// The close takes the typing lock, while the health row's published word still stands.
	write(seatFile("seat", "acme", "json"), `{"word":"needs you","closed_by_owner":true}`)
	key := cardKey("question")
	event := run.Fields("id", key, "source", "card:question", "episode", "question", "session", "acme",
		"kind", "needs", "text", "Which database?", "created_at", run.Float(clock()), "sink", true,
		"status", "pending", "attempts", 1, "next_attempt", 0, "webhook", digest(server.URL),
		"payload", run.Fields("content", "🙋 Needs you · acme"), "message", "Needs you · acme: Which database?")
	write(filepath.Join(outbox(), key+".json"), run.Line(event))
	if carried, err := RetryPending(func(string) (string, any) { return "needs you", nil }, false, nil, io.Discard); !carried || err != nil {
		t.Fatal(carried, err)
	}
	event, err := readEvent(key)
	if err != nil || event == nil {
		t.Fatal(event, err)
	}
	if attempts, _ := event.Int("attempts"); hits.Load() != 0 || attempts != 1 || event.Str("status") != "disabled" ||
		event.Str("error") != "its seat was closed by the owner" || event.Get("next_attempt") != nil {
		t.Fatalf("requests=%d, page=%s", hits.Load(), run.Line(event))
	}
}
