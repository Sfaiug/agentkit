//go:build unix

package tick

import (
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// tokenHome is an idle home holding claude's worker token, written that many days before now,
// whose adapter says says and exits code, writing each call's words to the file asked.
func tokenHome(t *testing.T, days int, says string, code int) (ak, asked string) {
	t.Helper()
	ak, _ = idleHome(t, answers)
	adapters := t.TempDir()
	asked = filepath.Join(adapters, "asked")
	put(t, filepath.Join(adapters, "claude.sh"), "#!/bin/sh\necho \"$*\" >> "+asked+"\necho '"+says+"'\nexit "+strconv.Itoa(code)+"\n")
	if err := os.Chmod(filepath.Join(adapters, "claude.sh"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	token := filepath.Join(ak, "secrets", "claude_oauth_token")
	put(t, token, "acme-token\n")
	written := time.Now().Add(-time.Duration(days) * 24 * time.Hour)
	if err := os.Chtimes(token, written, written); err != nil {
		t.Fatal(err)
	}
	return ak, asked
}

// The verb is asked once a day, and at once of a file with a new date; its answer is kept.
func TestAWorkerTokenIsAskedOnceADay(t *testing.T) {
	ak, asked := tokenHome(t, 300, "claude: long-lived worker token (expires in 65 days)", 0)
	asks := func() int {
		data, _ := os.ReadFile(asked)
		return strings.Count("\n"+string(data), "\nauth\n")
	}
	for range 2 {
		if !carries(io.Discard, io.Discard) {
			t.Fatal("left the tick to Python")
		}
	}
	kept, _ := watched(t, ak)["worker_tokens"].(map[string]any)
	claude, _ := kept["claude"].(map[string]any)
	if asks() != 1 || claude["days"] != 65.0 || claude["expired"] != false {
		t.Fatalf("asked %d times, keeping %v", asks(), kept)
	}
	now := time.Now()
	if err := os.Chtimes(filepath.Join(ak, "secrets", "claude_oauth_token"), now, now); err != nil {
		t.Fatal(err)
	}
	if !carries(io.Discard, io.Discard) || asks() != 2 {
		t.Fatalf("a new file asked %d times in all", asks())
	}
}

// A dead token is every seat's word, which Python's tick words: Go's ends there, keeping no answer.
func TestADeadWorkerTokenEndsTheTickThere(t *testing.T) {
	ak, _ := tokenHome(t, 400, "claude: worker token expired; run `claude setup-token`", 1)
	endedThere(t, ak, "")
	if got := read(t, filepath.Join(ak, "state", "watch.json")); strings.Contains(got, "worker_tokens") {
		t.Errorf("watch.json holds %s", got)
	}
}
