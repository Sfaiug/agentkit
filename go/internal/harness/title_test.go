package harness

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"agentkit/internal/run"
)

func TestTitleReadsOnFromWhereTheLastReadingStopped(t *testing.T) {
	if runtime.GOOS != "linux" && runtime.GOOS != "darwin" {
		t.Skip("no file stamp Python's stat would match is read here")
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	record := run.Fields("conversation", "conv-acme", "cwd", "/home/acme/code/fix-api")
	cache := filepath.Join(home, "title-acme.json")
	if title, kept := SessionTitle("claude", record, cache); title != nil || kept != nil {
		t.Fatalf("no conversation yet: %v, %v", title, kept)
	}
	path := claudeConversation(map[string]any{"conversation": "conv-acme", "cwd": "/home/acme/code/fix-api"})
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	write := func(text string) {
		file, err := os.OpenFile(path, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o600)
		if err == nil {
			_, err = file.WriteString(text)
			file.Close()
		}
		if err != nil {
			t.Fatal(err)
		}
	}
	read := func() (any, *run.Object) {
		title, kept := SessionTitle("claude", record, cache)
		if kept != nil {
			if err := KeepTitle(cache, kept); err != nil {
				t.Fatal(err)
			}
		}
		return title, kept
	}
	write(`{"type":"user"}` + "\n" + `{"type":"custom-title","sessionId":"conv-other","customTitle":"elsewhere"}` + "\n")
	if title, kept := read(); title != "" || kept == nil || kept.Get("readable") != true {
		t.Fatalf("a conversation never titled: %v, %v", title, kept)
	}
	write(`{"type":"custom-title","sessionId":"conv-acme","customTitle":"billing"}` + "\n")
	if title, _ := read(); title != "billing" {
		t.Fatalf("its own title: %v", title)
	}
	if title, kept := read(); title != "billing" || kept != nil {
		t.Fatalf("nothing new is no reading to keep: %v, %v", title, kept)
	}
	write(`{"type":"custom-title","sessionId":"conv-acme","customTitle":"caf` + "\xc3")
	title, kept := read()
	if size, _ := wholeNumber(kept.Get("offset")); title != "billing" || kept.Get("readable") != true || size >= mustSize(t, path) {
		t.Fatalf("a line cut inside a character waits for its end: %v, %v", title, kept)
	}
	write("\xa9\"}\n" + "\xff\n")
	if title, kept := read(); title != nil || kept.Get("readable") != false {
		t.Fatalf("a broken character is no title to read: %v, %v", title, kept)
	}
	if title, kept := read(); title != nil || kept != nil {
		t.Fatalf("unreadable it stays, read once: %v, %v", title, kept)
	}
}

func mustSize(t *testing.T, path string) int64 {
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	return info.Size()
}
