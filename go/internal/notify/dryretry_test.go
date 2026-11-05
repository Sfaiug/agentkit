//go:build unix

package notify

import (
	"io"
	"io/fs"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"sync/atomic"
	"testing"

	"agentkit/internal/run"
)

// A dry retry decides as the real one and acts on nothing: it says it would retry a completion
// card the real one sends and a page from before the install the real one drops, and the webhook
// hears nothing and no file under HOME, lock files included, changes.
func TestDryRetryLeavesCompletionCardsAndHistoryUntouched(t *testing.T) {
	home, write := questionHome(t)
	var hits atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		io.WriteString(w, `{"id":"1001"}`)
	}))
	defer server.Close()
	t.Setenv(sinkEnv, server.URL)
	write(filepath.Join(state(), "installed-at"), "200\n")
	write(filepath.Join(outbox(), "done.json"), run.Line(run.Fields("id", "done", "source", "card:done-1", "episode", "done-1",
		"session", "acme", "kind", "done", "created_at", run.Float(clock()), "sink", true, "status", "pending",
		"attempts", 1, "next_attempt", 0, "webhook", digest(server.URL), "payload", run.Fields("content", "✅ Done · acme"))))
	write(filepath.Join(outbox(), "old.json"), run.Line(run.Fields("id", "old", "session", "acme", "kind", "done",
		"status", "pending", "created_at", 100, "attempts", 1, "next_attempt", 0)))
	said := func(string) (string, any) { return "done", nil }
	before := tree(t, home)
	var lines []string
	if carried, err := RetryPending(said, true, func(line string) { lines = append(lines, line) }, io.Discard); !carried || err != nil {
		t.Fatal(carried, err)
	}
	if want := []string{"would retry notification done (pending)", "would retry notification old (pending)"}; !reflect.DeepEqual(lines, want) {
		t.Fatalf("said %q", lines)
	}
	if after := tree(t, home); hits.Load() != 0 || !reflect.DeepEqual(after, before) {
		t.Fatalf("requests=%d; HOME changed: %v", hits.Load(), after)
	}
	if carried, err := RetryPending(said, false, nil, io.Discard); !carried || err != nil {
		t.Fatal(carried, err)
	}
	done, _ := readEvent("done")
	old, _ := readEvent("old")
	if hits.Load() != 1 || done.Str("status") != "delivered" || old.Str("status") != "disabled" {
		t.Fatalf("requests=%d; the real retry left %s and %s", hits.Load(), run.Line(done), run.Line(old))
	}
}

// tree is every path under root with what it holds.
func tree(t *testing.T, root string) map[string]string {
	t.Helper()
	found := map[string]string{}
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			found[path] = ""
			return err
		}
		data, err := os.ReadFile(path)
		found[path] = string(data)
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	return found
}
