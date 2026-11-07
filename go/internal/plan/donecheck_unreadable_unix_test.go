//go:build linux || darwin

package plan

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

// A transcript that cannot be read as the owner's messages are read keeps a finished plan's done
// check owed, as Python's does (harness.unread in harness.strictly), though it reads again for
// its turns and cards straight after.  The first read fails because the transcript is a folder.
// The seat's typing receipts are a pipe that the reader opens only once that read is over. Until
// then it holds the test's writer, which puts the transcript back before the receipts end, so
// every later read finds it whole.
func TestAnUnreadableOwnerMessageKeepsTheCheckOwed(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	write := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil || os.WriteFile(path, []byte(text), 0o600) != nil {
			t.Fatal(path)
		}
	}
	state := filepath.Join(home, ".agentkit", "state")
	chat := filepath.Join(home, ".claude", "projects", "-code-acme", "conv-1.jsonl")
	write(filepath.Join(state, "session-acme.json"), `{"orchestrator": "opus", "cwd": "/code/acme", "conversation": "conv-1"}`)
	write(filepath.Join(state, "plan-acme.md"), "- [x] Merge the parser\n")
	receipts := filepath.Join(state, "input-acme.jsonl")
	readOnceUnread := func(read func()) {
		t.Helper()
		if err := os.MkdirAll(chat, 0o700); err != nil || syscall.Mkfifo(receipts, 0o600) != nil {
			t.Fatal(chat, err)
		}
		mended := make(chan struct{})
		go func() {
			defer close(mended)
			// open once the reader opens the receipts, after its first read of the transcript
			writer, err := os.OpenFile(receipts, os.O_WRONLY, 0)
			if err != nil {
				t.Error(err)
				return
			}
			defer writer.Close()
			if os.Remove(receipts) != nil || os.Remove(chat) != nil || os.WriteFile(chat, []byte(
				`{"type": "user", "timestamp": "2026-10-31T05:00:01Z", "message": {"role": "user", "content": "Add a retry button."}}`+"\n"), 0o600) != nil {
				t.Error("could not put the transcript back")
			}
		}()
		read()
		// a reader that ends before the receipts lets the writer in, as they are opened
		if reader, err := os.OpenFile(receipts, os.O_RDONLY|syscall.O_NONBLOCK, 0); err == nil {
			defer reader.Close()
		} else if !errors.Is(err, fs.ErrNotExist) {
			t.Fatal(err)
		}
		<-mended
		os.Remove(chat)
	}
	readOnceUnread(func() {
		if finished, err := Finished("acme"); finished || err != nil {
			t.Errorf("a plan whose owner's messages could not be read reads done: %v, %v", finished, err)
		}
	})
	readOnceUnread(func() {
		if line, owed, err := OwedLine("acme"); !owed || line != owedCheck || err != nil {
			t.Errorf("its check reads as not owed: %q, %v, %v", line, owed, err)
		}
	})
}
