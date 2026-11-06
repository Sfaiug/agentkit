package seat

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

// A question about to be asked is climbed as the seat will stand once it is, nothing written: a Muse
// seat whose chat never showed it repeats it there, and one whose closing message holds it needs you.
func TestAQuestionAboutToBeAskedIsClimbedAsItWillStand(t *testing.T) {
	home := sandbox(t)
	t.Setenv("XDG_DATA_HOME", "")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig+
		"[models.spark]\nharness='muse'\nmodel='spark'\neffort='high'\nprovider='test'\n")
	token := strings.Repeat("a", 32)
	record(t, home, "acme", map[string]any{"orchestrator": "spark", "workers": []string{"spark"},
		"muse_launch": token, "id_source": nil})
	receipt := stateFile(home, "muse-launch-"+token)
	write(t, filepath.Join(receipt, "lineage"), `{"processes":[],"earlier":[]}`)
	write(t, filepath.Join(receipt, "session"), "session_1")
	log := filepath.Join(home, ".local", "share", "muse", "sessions", "2026", "10", "24", "session_1", "session.jsonl")
	said := func(event map[string]any) {
		t.Helper()
		data, err := json.Marshal(map[string]any{"schema_version": 1, "record_type": "event",
			"stream":      map[string]any{"kind": "session", "id": "session_1"},
			"recorded_at": time.Now().UnixMicro(), "payload": map[string]any{"kind": "run", "run_id": "r1", "event": event}})
		if err != nil {
			t.Fatal(err)
		}
		previous, _ := os.ReadFile(log)
		write(t, log, string(previous)+string(data)+"\n")
	}
	said(map[string]any{"kind": "started", "prompt": "Build the acme parser."})
	pane, err := os.ReadFile(filepath.Join("..", "..", "..", "tests", "fixtures", "muse-prompt-pane.txt"))
	if err != nil {
		t.Fatal(err)
	}
	drawn(t, home, "acme", string(pane))
	question := "Which schema should the acme parser write?"
	notice := run.Fields("session", "acme", "kind", "needs", "text", question, "time", run.Float(seconds(time.Now())))
	if word, _, asking := AskedWord("acme", notice, time.Now()); word != "working" || asking {
		t.Fatalf("a question its chat never showed: %q, %v", word, asking)
	}
	if _, err := os.Lstat(stateFile(home, "notify-acme.json")); err == nil {
		t.Fatal("climbing recorded the question")
	}
	said(map[string]any{"kind": "assistant_message_committed", "text": question})
	if word, _, asking := AskedWord("acme", notice, time.Now()); word != "needs you" || !asking {
		t.Fatalf("a question its chat shows: %q, %v", word, asking)
	}
}
