//go:build linux

package harness

import (
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"agentkit/internal/run"
)

// TestCodexServerGoesWithItsDescendants: what Codex's server leaves running past its SIGTERM is
// killed with its group once the seat ends, as npm's shim parents the real server.
func TestCodexServerGoesWithItsDescendants(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("AGENTKIT_HOME", "")
	state := filepath.Join(home, ".agentkit", "state")
	os.MkdirAll(state, 0o700)
	program := filepath.Join(home, "codex")
	os.WriteFile(program, []byte(`#!/bin/sh
sh -c 'trap "" TERM; echo $$ > "$HOME/child.tmp"; mv "$HOME/child.tmp" "$HOME/child"; exec sleep 600' &
while [ ! -e "$HOME/child" ]; do sleep 0.01; done
for word; do [ -n "$listen" ] && touch "${word#unix://}"; listen=; [ "$word" = --listen ] && listen=1; done
exec sleep 600
`), 0o700)
	receipt := filepath.Join(state, "receipt.json")
	os.WriteFile(receipt, []byte(run.Encode(run.Fields("launch", strings.Repeat("a", 32), "remote", strings.Repeat("b", 32)))), 0o600)
	child := 0
	t.Cleanup(func() {
		if child > 0 {
			syscall.Kill(child, syscall.SIGKILL)
		}
	})
	terminal := func(_, _ []string) int {
		data, _ := os.ReadFile(filepath.Join(home, "child"))
		child, _ = strconv.Atoi(strings.TrimSpace(string(data)))
		return 0
	}
	if code := codexOnServer([]string{program}, nil, receipt, os.Environ(), io.Discard, terminal, func() {}); code != 0 || child == 0 {
		t.Fatalf("exit %d, child %d", code, child)
	}
	for deadline := time.Now().Add(3 * time.Second); ; time.Sleep(10 * time.Millisecond) {
		data, err := os.ReadFile(filepath.Join("/proc", strconv.Itoa(child), "stat"))
		if _, after, _ := strings.Cut(string(data), ") "); err != nil || strings.HasPrefix(after, "Z ") {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("Codex's descendant %d outlived the seat", child)
		}
	}
}
