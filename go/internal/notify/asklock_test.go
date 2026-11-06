//go:build unix

package notify_test

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/notify"
	"agentkit/internal/seat"
)

// A seat's record made while its ask waits for the notice lock is the record the ask decides from:
// a seat nothing is left of has its question as its word, and a new seat Go cannot read yet hands
// over with nothing written.
func TestAnAskDecidesFromWhatItsLockFinds(t *testing.T) {
	for _, made := range []bool{false, true} {
		t.Run(map[bool]string{false: "no record", true: "a record made while it waits"}[made], func(t *testing.T) {
			home, bin := t.TempDir(), t.TempDir()
			for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "PATH": bin,
				"AK_NOTIFY_SINK": "dry-run", "AK_RUN_ROLE": "", "AGENTKIT_ADAPTER_DIR": "", "AGENTKIT_DISCORD_USER_ID": ""} {
				t.Setenv(key, value)
			}
			state := filepath.Join(home, ".agentkit", "state")
			asked := filepath.Join(t.TempDir(), "asked")
			file := `{"unasked": {"text": "How should this seat go on?", "questions": [{"text": "How should this seat go on?", "at": 100, "ended": 101}]}}` + "\n"
			for path, text := range map[string]string{
				// tmux runs no server: the seat is in none, and its first call is the ask reading it
				filepath.Join(bin, "tmux"):                      "#!/bin/sh\n: >'" + asked + "'\necho 'no server running on /tmp/tmux-0/default' >&2\nexit 1\n",
				filepath.Join(home, ".agentkit", "config.toml"): "[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n",
				filepath.Join(state, "seat-acme.json"):          file,
			} {
				if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, []byte(text), 0o700); err != nil {
					t.Fatal(err)
				}
			}
			held, err := lock.Wait(context.Background(), filepath.Join(state, "notify-acme.lock"))
			if err != nil {
				t.Fatal(err)
			}
			type result struct {
				code    int
				decided bool
			}
			done := make(chan result)
			go func() {
				code, decided := notify.Ask("acme", nil, "Which schema should acme use?", seat.AskedWord, io.Discard, io.Discard)
				done <- result{code, decided}
			}()
			for deadline := time.Now().Add(30 * time.Second); ; time.Sleep(10 * time.Millisecond) {
				if _, err := os.Stat(asked); err == nil {
					break
				} else if time.Now().After(deadline) {
					t.Fatal("the ask never read the seat")
				}
			}
			if made {
				record := `{"orchestrator": "opus", "cwd": "/code/acme", "conversation": "conv-acme"}`
				if err := os.WriteFile(filepath.Join(state, "session-acme.json"), []byte(record), 0o600); err != nil {
					t.Fatal(err)
				}
			}
			held.Close()
			got := <-done
			notice := notify.Last("acme")
			if !made {
				if got != (result{0, true}) || notice == nil || notice.Str("text") != "Which schema should acme use?" {
					t.Fatalf("a seat nothing is left of was not asked: %v, %v", got, notice)
				}
				return
			}
			if got != (result{0, false}) {
				t.Fatalf("an ask for a seat Go cannot read was decided: %v", got)
			}
			after, err := os.ReadFile(filepath.Join(state, "seat-acme.json"))
			if err != nil || string(after) != file {
				t.Fatalf("its seat file changed: %s, %v", after, err)
			}
			for _, pattern := range []string{"notify-acme.json", "card-acme.json", filepath.Join("notification-outbox", "*")} {
				if written, _ := filepath.Glob(filepath.Join(state, pattern)); len(written) > 0 {
					t.Fatal("a handed-over ask wrote", written)
				}
			}
		})
	}
}
