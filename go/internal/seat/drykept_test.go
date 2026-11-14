//go:build unix

package seat

import (
	"encoding/json"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/run"
)

// A dry look at a Muse seat at its prompt holding a question it kept back, whose chat showed
// neither that one nor the question standing, says the reminder of both the real look would type
// once it asked the kept one, and asks, answers, types and keeps nothing, the owner's reply since
// left unread. Where the look found the seat otherwise than its saved file says, or with no
// question of the seat's standing, which that ask would open, the seat is Python's dry tick's.
func TestDryHealthSaysTheReminderOfAQuestionKeptBack(t *testing.T) {
	home := sandbox(t)
	t.Setenv("XDG_DATA_HOME", "")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig+
		"[models.spark]\nharness='muse'\nmodel='spark'\neffort='high'\nprovider='test'\n")
	token := strings.Repeat("a", 32)
	record(t, home, "acme", map[string]any{"orchestrator": "spark", "workers": []string{"spark"},
		"muse_launch": token, "id_source": nil})
	receipt := stateFile(home, "muse-launch-"+token)
	write(t, filepath.Join(receipt, "session"), "session_1")
	now := time.Now()
	var log []string
	for at, event := range []map[string]any{{"kind": "started", "prompt": "Build the acme parser."},
		{"kind": "assistant_message_committed", "text": "Ready"}, {"kind": "started", "prompt": "Blue."}} {
		data, err := json.Marshal(map[string]any{"schema_version": 1, "record_type": "event",
			"stream":      map[string]any{"kind": "session", "id": "session_1"},
			"recorded_at": now.Add(time.Duration(at-3) * time.Minute).UnixMicro(), "payload": map[string]any{"kind": "run", "run_id": "r1", "event": event}})
		if err != nil {
			t.Fatal(err)
		}
		log = append(log, string(data)+"\n")
	}
	write(t, filepath.Join(home, ".local", "share", "muse", "sessions", "2026", "10", "24", "session_1", "session.jsonl"), strings.Join(log, ""))
	pane, err := os.ReadFile(filepath.Join("..", "..", "..", "tests", "fixtures", "muse-prompt-pane.txt"))
	if err != nil {
		t.Fatal(err)
	}
	drawn(t, home, "acme", "Ready\n"+string(pane))
	asked, kept := "Which colour should the acme preview use?", "Which schema should the acme parser write?"
	ago := run.Float(seconds(now.Add(-150 * time.Second)))
	notice := run.Line(run.Fields("session", "acme", "kind", "needs", "text", asked, "time", ago, "source", nil, "watcher", false))
	write(t, stateFile(home, "notify-acme.json"), notice)
	prompt := run.Line(run.Fields("state", "at_prompt", "stop_said", "Ready", "stop_said_at", ago, "unasked", run.Fields("text", kept, "ended", ago)))
	write(t, stateFile(home, "seat-acme.json"), prompt)
	dry := func() (bool, []string) {
		t.Helper()
		var said []string
		before := tree(t, home)
		carried, err := Health("acme", func(Live) bool { return true }, func(line string) { said = append(said, line) }, true)
		if err != nil {
			t.Fatal(err)
		}
		if after := tree(t, home); !maps.Equal(after, before) {
			t.Fatalf("the dry look changed HOME: %v", after)
		}
		return carried, said
	}
	reminder := "would resume acme, left its question out of the chat, with " + commandhelp.Quote(Reminder("Ready", []string{asked, kept}))
	if carried, said := dry(); !carried || !slices.Equal(said, []string{reminder}) {
		t.Fatalf("carried %v, said %q", carried, said)
	}
	// Python's dry tick, which takes no look, reads the seat file as saved: saved working,
	// interrupted, or with no stop on record, the look's reminder is not its to say
	for _, saved := range []*run.Object{
		run.Fields("state", "working", "stop_said", "Ready", "stop_said_at", ago, "unasked", run.Fields("text", kept, "ended", ago)),
		run.Fields("state", "at_prompt", "interrupted", true, "stop_said", "Ready", "stop_said_at", ago, "unasked", run.Fields("text", kept, "ended", ago)),
		run.Fields("state", "at_prompt", "unasked", run.Fields("text", kept, "ended", ago)),
	} {
		write(t, stateFile(home, "seat-acme.json"), run.Line(saved))
		if carried, said := dry(); carried || len(said) > 0 {
			t.Fatalf("saved %s: carried %v, said %q", run.Line(saved), carried, said)
		}
	}
	write(t, stateFile(home, "seat-acme.json"), prompt)
	if err := os.Remove(stateFile(home, "notify-acme.json")); err != nil {
		t.Fatal(err)
	}
	if carried, said := dry(); carried || len(said) > 0 {
		t.Fatalf("with no question standing: carried %v, said %q", carried, said)
	}
}
