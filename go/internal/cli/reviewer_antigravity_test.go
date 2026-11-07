package cli

import (
	"bytes"
	"context"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"
	"time"

	"agentkit/internal/harness"
	"agentkit/internal/lock"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

type reviewerClaimWriter func([]byte) (int, error)

func (f reviewerClaimWriter) Write(p []byte) (int, error) { return f(p) }

func TestReviewerClaimRechecksOtherOwnersAfterWaitingForSeatLock(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("requires Linux's open-file records")
	}
	home := sandbox(t)
	t.Setenv("AGENTKIT_SESSION", "acme")
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.gemini]\nharness='antigravity'\nmodel='gemini-3'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	fields, env := harness.LaunchExtras("antigravity")
	path := filepath.Join(state, "session-acme.json")
	write(t, path, run.Encode(run.SetAll(fields, "orchestrator", "gemini", "cwd", home))+"\n")
	write(t, filepath.Join(state, "plan-acme.md"), "- [x] Merge the parser\n")
	store := filepath.Join(home, ".gemini", "antigravity-cli", "conversations", "c-acme.db")
	write(t, store, "")
	file, err := os.Open(store)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	agy := exec.Command("sleep", "60")
	agy.Env, agy.ExtraFiles = append(os.Environ(), env...), []*os.File{file}
	if err := agy.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { agy.Process.Kill(); agy.Wait() })

	// Stop the final write at the record lock, after the reader has learned the conversation.
	ready := make(chan struct{})
	finished := make(chan int, 1)
	var seatLock *os.File
	var before []byte
	errOut := reviewerClaimWriter(func(p []byte) (int, error) {
		if seatLock == nil {
			seatLock, err = lock.Wait(context.Background(), filepath.Join(state, ".session-acme.lock"))
			if err != nil {
				return 0, err
			}
			before, err = os.ReadFile(path)
			close(ready)
		}
		return len(p), err
	})
	go func() { finished <- Main([]string{"notify", "needs", "Merge it?"}, io.Discard, errOut) }()
	select {
	case <-ready:
	case <-time.After(10 * time.Second):
		t.Fatal("command did not reach its final output")
	}
	defer seatLock.Close()
	code, ended := 0, false
	deadline := time.Now().Add(10 * time.Second)
	waitingOnRecordLock := func() bool {
		fds, _ := os.ReadDir("/proc/self/fd")
		count := 0
		for _, fd := range fds {
			path, _ := os.Readlink(filepath.Join("/proc/self/fd", fd.Name()))
			if path == filepath.Join(state, ".session-acme.lock") {
				count++
			}
		}
		return count >= 2
	}
	for !waitingOnRecordLock() && !ended {
		select {
		case code = <-finished:
			ended = true
		case <-time.After(time.Millisecond):
			if time.Now().After(deadline) {
				t.Fatal("command neither finished nor reached the claim lock")
			}
		}
	}
	// A launcher resumes this conversation in beta while acme's record lock is held.
	// Launch record writers use the record lock, not antigravity-claim.lock.
	betaLock, err := lock.Wait(context.Background(), filepath.Join(state, ".session-beta.lock"))
	if err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(state, "session-beta.json"), `{"orchestrator":"gemini","id_source":"launcher","conversation":"c-acme"}`+"\n")
	betaLock.Close()
	seatLock.Close()
	if !ended {
		select {
		case code = <-finished:
		case <-time.After(10 * time.Second):
			t.Fatal("command did not finish after releasing the record lock")
		}
	}
	if code != 2 {
		t.Fatalf("unexpected command exit: %d", code)
	}
	after, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(before, after) {
		t.Fatalf("a new claim was written after beta already owned c-acme:\nbefore: %s\nafter: %s", before, after)
	}
}

func TestReviewerAnAntigravityHistoryEntryKeepsItsOwnConversation(t *testing.T) {
	home := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.gemini]\nharness='antigravity'\nmodel='gemini-3'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	write(t, filepath.Join(state, "session-acme.json"), `{"orchestrator":"gemini","antigravity_launch":"token-now","antigravity_open":{"launch":"token-now","conversation":"c-now"},"left":[{"harness":"antigravity","conversation":"c-before"}]}`+"\n")
	had, err := notify.Conversations("acme")
	if err != nil {
		t.Fatal(err)
	}
	if len(had) != 2 || had[0].Name != "c-before" || had[1].Name != "c-now" {
		t.Fatalf("history must keep c-before, then c-now: %#v", had)
	}
}
