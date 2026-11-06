//go:build unix

package notify

import (
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"

	"agentkit/internal/run"
)

func TestRetryDefersQuestionRetirementAfterTheCardRow(t *testing.T) {
	_, write := questionHome(t)
	var hits atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		io.WriteString(w, `{"id":"1001"}`)
	}))
	defer server.Close()
	t.Setenv(sinkEnv, server.URL)
	write(seatFile("notify", "acme", "json"), `{"kind":"needs","text":"Which database?","time":100}`)
	write(seatFile("seat", "acme", "json"), `{"word":"needs you","reason":"Which database?","state":"at_prompt"}`)
	card := run.Fields("word", "needs you", "since", 100, "began", 100, "episode", "question", "sent", true)
	write(seatFile("card", "acme", "json"), run.Line(card))
	said := func(string) (string, any) { return "needs you", run.Float(100) }
	if carried, err := TurnedQuestion("acme", said, io.Discard); !carried || err != nil {
		t.Fatal("card row did not carry the standing question", carried, err)
	}
	// A later look shows a chooser while a hook withdraws the queued question.
	write(seatFile("seat", "acme", "json"), `{"word":"needs you","state":"asking","reason":"Pick one","word_since":100}`)
	key := cardKey("question")
	event := run.Fields("id", key, "source", "card:question", "episode", "question", "session", "acme",
		"kind", "needs", "text", "Which database?", "created_at", run.Float(clock()), "sink", true,
		"status", "pending", "attempts", 1, "next_attempt", 0, "webhook", digest(server.URL),
		"payload", run.Fields("content", "🙋 Needs you · acme"), "message", "Which database?")
	path, before := filepath.Join(outbox(), key+".json"), run.Line(event)
	write(path, before)
	write(filepath.Join(outbox(), "late.clear"), `{"session":"acme","prefix":"Which database?"}`)
	for _, recorded := range []bool{true, false} {
		if !recorded {
			if err := os.Remove(seatFile("notify", "acme", "json")); err != nil {
				t.Fatal(err)
			}
		}
		if carried, err := RetryPending(said, false, nil, io.Discard); carried || err != nil {
			t.Fatal("a queued retirement was not left to Python", carried, err)
		}
		if after, err := os.ReadFile(path); err != nil || string(after) != before || hits.Load() != 0 {
			t.Fatalf("withdrawn question changed: requests=%d, event=%s, error=%v", hits.Load(), after, err)
		}
	}
}
