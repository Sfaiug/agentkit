package harness

import (
	"errors"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"testing"
)

// A Claude conversation is read by Claude's own transcript, then by ak's link to it once Claude's
// cleanup deleted its own, by whichever is there as it is opened; only Claude's own is one Claude
// resumes (claude.py `opened`).
func TestAClaudeConversationIsReadByAksLinkButResumedOnlyByItsOwn(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	record := map[string]any{"conversation": "conv-acme", "cwd": "/code/acme"}
	own, kept := claudeConversation(record), filepath.Join(home, ".agentkit", "state", "conversations", "claude-conv-acme.jsonl")
	if names, known := ReadBy("claude", record); !known || !slices.Equal(names, []string{own, kept}) {
		t.Fatalf("read by %q, %v", names, known)
	}
	if os.MkdirAll(filepath.Dir(own), 0o700) != nil || os.WriteFile(own, []byte("Add a retry button.\n"), 0o600) != nil ||
		os.MkdirAll(filepath.Dir(kept), 0o700) != nil || os.Link(own, kept) != nil || os.Remove(own) != nil {
		t.Fatal(own)
	}
	if opened, known := Opened("claude", record); opened || !known {
		t.Errorf("a transcript only ak's link keeps reads as one to resume: %v %v", opened, known)
	}
	file, err := Open(own, kept)
	if err != nil {
		t.Fatal(err)
	}
	read, _ := io.ReadAll(file)
	file.Close()
	if string(read) != "Add a retry button.\n" {
		t.Errorf("read %q", read)
	}
	if os.Remove(kept) != nil {
		t.Fatal(kept)
	}
	if _, err := Open(own, kept); !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("neither there: %v", err)
	}
}
