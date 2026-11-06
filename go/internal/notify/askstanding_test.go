//go:build unix

package notify

import (
	"io"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
)

func TestASavedGoneSeatCanAskBeforeAndAfterAQuietTick(t *testing.T) {
	for _, each := range []struct {
		name, watch string
		known       bool
	}{
		{"before a tick", "", true},
		{"after a quiet tick", `{"tick":{"ended_at":1},"seen_at":{"acme":1},"boot_id":"boot"}`, true},
		{"outstanding recovery", `{"stalls":{"acme":{"at":1}}}`, false},
		{"unreadable watch", `[]`, false},
	} {
		t.Run(each.name, func(t *testing.T) {
			_, write := questionHome(t)
			write(filepath.Join(os.Getenv("PATH"), "tmux"), "#!/bin/sh\nexit 1\n")
			if each.watch != "" {
				write(filepath.Join(state(), "watch.json"), each.watch)
			}
			_, record, err := config.ResolveSession("acme")
			if err != nil {
				t.Fatal(err)
			}
			code, known := Ask("acme", record, "Which database?", nil, io.Discard, io.Discard) // no seat file: its word is the question
			if code != 0 || known != each.known {
				t.Fatal(code, known)
			}
			notice := Last("acme")
			if each.known != (notice != nil) {
				t.Fatal("question admission and its notice disagree", notice)
			}
			pages, err := filepath.Glob(filepath.Join(outbox(), "*.json"))
			want := 0
			if each.known {
				want = 1
			}
			if err != nil || len(pages) != want {
				t.Fatal("question admission and its page disagree", pages, err)
			}
		})
	}
}
