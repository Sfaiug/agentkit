package seat

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPastAdmissionKeepsStopAndHarnessBoundaries(t *testing.T) {
	for _, test := range []struct {
		name, file, data string
		fields           map[string]any
		known            bool
	}{
		{name: "plain", known: true},
		{name: "old rulebook", file: "state/rulebook-acme.md", data: "the old rules", known: true},
		{name: "seen notice", file: "state/notify-acme.json", data: `{"kind":"needs","text":"Which branch?","seen":true}`},
		{name: "unread notice", file: "state/notify-acme.json", data: `{"kind":"needs","text":"Which branch?"}`},
		{name: "retained checkout", file: "runs/api/run.json", data: `{"state":"pass","launched_session":"acme","worktree":"/wt/api"}`},
		{name: "owned tab", file: "state/browser-tabs.json", data: `{"T1":{"opener":{"session":"acme"}}}`},
		{name: "sent card", file: "state/card-acme.json", data: `{"sent":true}`},
		{name: "unopened harness", file: "config.toml", data: testConfig + gemini, fields: map[string]any{"orchestrator": "gemini", "workers": []string{"gemini"}}},
		{name: "account login", fields: map[string]any{"account": "work"}},
		{name: "unowned conversation", fields: map[string]any{"id_source": "guess"}},
	} {
		t.Run(test.name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", test.fields)
			if err := os.MkdirAll(filepath.Join(home, "work", "acme"), 0o700); err != nil {
				t.Fatal(err)
			}
			state := filepath.Join(home, ".agentkit", "state")
			write(t, filepath.Join(state, "seat-acme.json"), `{"stopped_at":1799999999,"closed_by_owner":true}`)
			if test.file != "" {
				write(t, filepath.Join(home, ".agentkit", test.file), test.data)
			}
			before, mark := contents(t, filepath.Join(state, "session-acme.json")), contents(t, filepath.Join(state, "seat-acme.json"))
			closed, _, known := (Seat{Name: "acme"}).PastReady(moment)
			if known != test.known || known && closed != 1799999999 {
				t.Fatalf("closed=%v known=%v", closed, known)
			}
			if contents(t, filepath.Join(state, "session-acme.json")) != before || contents(t, filepath.Join(state, "seat-acme.json")) != mark {
				t.Fatal("admission changed the seat")
			}
			if test.known {
				if _, known := Menu(moment); !known {
					t.Fatal("the menu could not carry the admitted past seat")
				}
			}
		})
	}
}
