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

// A reminder's card names only what it is about, its outbox the whole sentence; one still waiting
// from before this install is dropped unsent, where a page owed still would go.
func TestAReminderFromAnEarlierInstallIsDroppedUnsent(t *testing.T) {
	_, write := questionHome(t)
	var hits atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		io.WriteString(w, `{"id":"1001"}`)
	}))
	defer server.Close()
	t.Setenv(sinkEnv, server.URL)
	write(filepath.Join(state(), "installed-at"), "200\n")
	write(filepath.Join(outbox(), pageKey("login:old")+".json"), run.Line(run.Fields("id", pageKey("login:old"),
		"session", nil, "kind", "needs", "status", "pending", "sink", true, "created_at", 100, "attempts", 1, "next_attempt", 0)))
	var said []string
	if err := Remind("login:old", "Claude II login", "Claude II login ended.", func(line string) { said = append(said, line) }, io.Discard); err != nil {
		t.Fatal(err)
	}
	event, err := readEvent(pageKey("login:old"))
	if err != nil || event.Str("status") != "disabled" || hits.Load() != 0 || len(said) != 1 {
		t.Fatal(event, err, hits.Load(), said)
	}
	if err := Remind("login:new", "Claude II login", "Claude II login ended.", nil, io.Discard); err != nil {
		t.Fatal(err)
	}
	event, err = readEvent(pageKey("login:new"))
	if err != nil || event.Str("status") != "delivered" || event.Str("text") != "Claude II login ended." ||
		event.Dict("payload").Str("content") != "🙋 Needs you · Claude II login" {
		t.Fatal(event, err)
	}
}
