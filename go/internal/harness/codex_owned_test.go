package harness

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// TestCodexSettingsAppliedSinceTheAnswerComeFirst: `/model` or effort set in the seat shows before
// another turn answers, as codex.py `running` reads it; settings with no model are passed over,
// and settings before the latest answer's turn give way to that turn.
func TestCodexSettingsAppliedSinceTheAnswerComeFirst(t *testing.T) {
	token, write := codexSeat(t)
	record := run.Fields("codex_launch", token)
	turn := `{"type": "turn_context", "payload": {"model": "gpt-a", "effort": "high"}}` + "\n"
	answer := `{"type": "event_msg", "timestamp": "2026-11-03T10:00:00Z", "payload": {"type": "item_completed", ` +
		`"item": {"type": "AgentMessage", "content": [{"type": "Text", "text": "done"}]}}}` + "\n"
	applied := func(settings string) string {
		return `{"type": "event_msg", "timestamp": "2026-11-03T11:00:00Z", "payload": ` +
			`{"type": "thread_settings_applied", "thread_settings": ` + settings + `}}` + "\n"
	}
	write(turn + answer + applied(`{"model": "gpt-b", "reasoning_effort": "low"}`) + applied(`{"model": null}`))
	if model, effort, at, found := For("codex").LastAnswer(record); model != "gpt-b" || effort != "low" || at != "2026-11-03T11:00:00Z" || !found {
		t.Errorf("%v %v %v %v", model, effort, at, found)
	}
	write(applied(`{"model": "gpt-b"}`) + turn + answer)
	if model, _, _, _ := For("codex").LastAnswer(record); model != "gpt-a" {
		t.Errorf("settings before the answer's turn: %v", model)
	}
}

// TestCodexReopensOnItsReceipt: a launch resuming the thread its receipt proves carries that
// receipt's evidence and remote home on and binds the thread, as codex.py `prepare` does; a
// SessionStart's binding writes what codex.py `reconcile` would, once.
func TestCodexReopensOnItsReceipt(t *testing.T) {
	token, write := codexSeat(t)
	write("")
	state := filepath.Join(os.Getenv("HOME"), ".agentkit", "state")
	path := filepath.Join(state, "codex-launch-"+token+".json")
	data, _ := os.ReadFile(path)
	read, _ := run.Decode(data)
	previous := read.(*run.Object)
	previous.Set("remote", "0123456789abcdef0123456789abcdef")
	previous.Set("home", "/acme/codex")
	os.WriteFile(path, []byte(run.Encode(previous)), 0o600)

	record := run.Fields("codex_launch", token, "codex_history", []any{"earlier"})
	if !codexReconciled(record) || record.Get("conversation") != "t1" || record.Get("id_source") != codexSource ||
		record.Get("resumable") != true || codexReconciled(record) {
		t.Fatalf("bound: %s", run.Encode(record))
	}
	if _, _, err := codexLaunched("acme", t.TempDir(), "t2", record); err == nil {
		t.Error("a thread the receipt does not prove was resumed")
	}
	fields, env, err := codexLaunched("acme", t.TempDir(), "t1", record)
	if err != nil {
		t.Fatal(err)
	}
	if fields.Get("conversation") != "t1" || fields.Get("id_source") != codexSource || fields.Get("resumable") != true ||
		!run.Equal(fields.Get("codex_history"), []any{"earlier"}) {
		t.Errorf("record: %s", run.Encode(fields))
	}
	data, _ = os.ReadFile(filepath.Join(state, "codex-launch-"+fields.Str("codex_launch")+".json"))
	read, _ = run.Decode(data)
	receipt := read.(*run.Object)
	for _, key := range []string{"cwd", "remote", "event", "home"} {
		if !run.Equal(receipt.Get(key), previous.Get(key)) {
			t.Errorf("%s: %v", key, receipt.Get(key))
		}
	}
	if receipt.Get("expected") != "t1" || len(env) != 1 {
		t.Errorf("receipt: %s, %v", run.Encode(receipt), env)
	}
}
