package cli

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/seat"
)

// A seat renamed while its card's answer waits for the notice lock has the hook's fact under its
// new name, and none under the one the answer began waiting under.
func TestACardAnswerFactFollowsARenameItWaitedOut(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("this tmux is a shell script")
	}
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	record := `{"orchestrator": "opus", "conversation": "conv-acme", "id_source": "launcher"}`
	write(t, filepath.Join(state, "session-acme.json"), record)
	if err := seat.Keep("acme", "Which port?"); err != nil {
		t.Fatal(err)
	}
	// tmux says this hook runs in acme's own pane, and leaves word that it was asked
	bin, asked := t.TempDir(), filepath.Join(home, "asked")
	write(t, filepath.Join(bin, "tmux"), "#!/bin/sh\n: >\"$HOME/asked\"\nprintf '/tmp/ak-none\\tacme\\n'\n")
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("TMUX", "/tmp/ak-none,1,0")
	t.Setenv("TMUX_PANE", "%1")
	t.Setenv("AGENTKIT_SESSION", "acme")
	held, err := lock.Wait(context.Background(), filepath.Join(state, "notify-acme.lock"))
	if err != nil {
		t.Fatal(err)
	}
	answer := []byte(`{"hook_event_name": "PostToolUse", "tool_name": "AskUserQuestion", ` +
		`"tool_response": {"answers": {"Which port?": "8080"}}}`)
	exit := make(chan int)
	go func() { exit <- seatState(answer, new(bytes.Buffer)) }()
	for deadline := time.Now().Add(10 * time.Second); ; time.Sleep(10 * time.Millisecond) {
		if _, err := os.Stat(asked); err == nil {
			break
		} else if time.Now().After(deadline) {
			t.Fatal("the answer never looked at its pane")
		}
	}
	// renamed to beta under the lock the answer waits for, as a rename holds it
	write(t, filepath.Join(state, "session-beta.json"), record)
	write(t, filepath.Join(state, "session-acme.json"), `{"renamed": "beta"}`)
	if err := os.Rename(filepath.Join(state, "seat-acme.json"), filepath.Join(state, "seat-beta.json")); err != nil {
		t.Fatal(err)
	}
	held.Close()
	if code := <-exit; code != 0 {
		t.Fatalf("exit %d", code)
	}
	if seat.Kept("beta") {
		t.Fatal("its question was not answered")
	}
	if _, err := os.Stat(filepath.Join(state, "hook-beta.json")); err != nil {
		t.Fatal("its fact is not under its new name")
	}
	if _, err := os.Stat(filepath.Join(state, "hook-acme.json")); err == nil {
		t.Fatal("its fact is under its old name")
	}
}
