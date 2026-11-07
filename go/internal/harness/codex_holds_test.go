package harness

import (
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A seat's server that never answers, like one nobody can reach, leaves its last Stop standing.
func TestCodexHoldsLeaveTheStopToAServerThatCannotSay(t *testing.T) {
	token, write := codexSeat(t)
	write("")
	state := filepath.Join(os.Getenv("HOME"), ".agentkit", "state")
	receipt, _ := run.ReadJSON(filepath.Join(state, "codex-launch-"+token+".json"))
	remote := strings.Repeat("c", 32)
	receipt.Set("remote", remote)
	os.WriteFile(filepath.Join(state, "codex-launch-"+token+".json"), []byte(run.Encode(receipt)), 0o600)
	home := filepath.Join(state, "codex-remote-"+remote)
	os.MkdirAll(home, 0o700)
	record := run.Fields("codex_launch", token)
	if _, ok := codexHolds(record); ok {
		t.Fatal("a seat with no connection said what it holds")
	}
	socket := filepath.Join(t.TempDir(), "s")
	listener, err := net.Listen("unix", socket)
	if err != nil {
		t.Skip("no Unix socket here:", err)
	}
	defer listener.Close()
	go func() { // accepts, and answers nothing
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			defer conn.Close()
		}
	}()
	os.WriteFile(filepath.Join(home, "connection.json"), []byte(run.Line(run.Fields("socket", socket))), 0o600)
	if held, ok := codexHolds(record); ok {
		t.Fatalf("a silent server said it holds %q", held)
	}
}

// A tick's conversation with a seat's server ends by its own end, sooner than each step's 15 seconds.
func TestCodexClientEndsByItsConversationsEnd(t *testing.T) {
	by := time.Now().Add(time.Second)
	if at := (&codexClient{by: by}).deadline(); !at.Equal(by) {
		t.Errorf("a step outlasts the conversation: %v, not %v", at, by)
	}
	if at := (&codexClient{by: time.Now().Add(time.Hour)}).deadline(); at.After(time.Now().Add(time.Minute)) {
		t.Errorf("a step waits past its own 15 seconds: %v", at)
	}
}
