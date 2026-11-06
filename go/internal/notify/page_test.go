//go:build unix

package notify

import (
	"io"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

// A page the webhook did not take waits for its caller to ask again: the retry row passes it by,
// and the next ask sends it.
func TestAPageWaitsForItsCallerToAskAgain(t *testing.T) {
	questionHome(t)
	var hits atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if hits.Add(1) == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		io.WriteString(w, `{"id":"1001"}`)
	}))
	defer server.Close()
	t.Setenv(sinkEnv, server.URL)
	if waiting, err := Page("down:acme", "acme is down", true, io.Discard); !waiting || err != nil {
		t.Fatal(waiting, err)
	}
	event, err := readEvent(pageKey("down:acme"))
	if err != nil || event == nil {
		t.Fatal(event, err)
	}
	event.Set("next_attempt", 0)
	if err := writeEvent(event); err != nil {
		t.Fatal(err)
	}
	if carried, err := RetryPending(func(string) (string, any) { return "", nil }, false, nil, io.Discard); !carried || err != nil || hits.Load() != 1 {
		t.Fatal(carried, err, hits.Load())
	}
	if waiting, err := Page("down:acme", "acme is down", true, io.Discard); waiting || err != nil || hits.Load() != 2 {
		t.Fatal(waiting, err, hits.Load())
	}
	if paged, err := Paged("down:acme"); !paged || err != nil {
		t.Fatal(paged, err)
	}
}
