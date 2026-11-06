package loop

import (
	"os"
	"path/filepath"
	"testing"
)

func saidIn(t *testing.T, files map[string]string) string {
	t.Helper()
	out := t.TempDir()
	for name, text := range files {
		if err := os.WriteFile(filepath.Join(out, name), []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	return out
}

func TestWhatTheHarnessSaidLeavesTheWorksOutputOut(t *testing.T) {
	out := saidIn(t, map[string]string{
		"stderr.log":   "API Error: 500\n",
		"session_id":   "API Error: bookkeeping\n",
		"events.jsonl": `{"type":"item","output":"grep says rate limit"}` + "\n" + `{"type":"turn.failed","message":"over capacity"}` + "\n" + `{"type":"result","text":"short"}` + "\nnot json\n",
	})
	want := "answer\n" + `{"type": "turn.failed", "message": "over capacity"}` + "\n" + `{"type": "result", "text": "short"}` + "\nAPI Error: 500"
	if said := harnessSaid(out, "answer", "result", false); said != want {
		t.Fatalf("said %q", said)
	}
}

func TestACleanExitOnlyHearsATerminalRefusal(t *testing.T) {
	warned := `{"type":"warning","error":"retrying"}` + "\n"
	out := saidIn(t, map[string]string{"stderr.log": "API Error: 500\n", "events.jsonl": warned + `{"type":"result","text":"## Done"}` + "\n"})
	if said := harnessSaid(out, "## Done\n", "result", true); said != "" {
		t.Fatalf("an answered turn said %q", said)
	}
	out = saidIn(t, map[string]string{"stderr.log": "API Error: 500\n", "events.jsonl": warned + `{"type":"result","is_error":true,"text":"at capacity"}` + "\n"})
	if said := harnessSaid(out, "", "result", true); said != `{"type": "result", "is_error": true, "text": "at capacity"}` {
		t.Fatalf("a refused turn said %q", said)
	}
}

func TestAPromptQuotedBackIsNoRefusal(t *testing.T) {
	echo := "You are the executor of a task that names API Error: 500 in its first line."
	out := saidIn(t, map[string]string{"prompt.md": echo + "\nmore\n", "stderr.log": "started: " + echo + "\nfine\n"})
	if said := harnessSaid(out, "", "", false); said != "fine" {
		t.Fatalf("said %q", said)
	}
}
