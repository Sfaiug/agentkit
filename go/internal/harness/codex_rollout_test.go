package harness

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
)

// codexSeat is a home whose Codex launch receipt vouches for thread t1 in its rollout, the
// receipt's token, and how that rollout is written past its first line.
func codexSeat(t *testing.T) (token string, write func(lines string)) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	token, cwd := strings.Repeat("a", 32), filepath.Join(home, "acme")
	rollout := filepath.Join(home, "rollout.jsonl")
	receipt := `{"launch": "` + token + `", "cwd": "` + cwd + `", "event": {"hook_event_name": "SessionStart",
		"source": "startup", "session_id": "t1", "cwd": "` + cwd + `", "transcript_path": "` + rollout + `"}}`
	put := func(path, text string) {
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil || os.WriteFile(path, []byte(text), 0o600) != nil {
			t.Fatal(path)
		}
	}
	put(filepath.Join(home, ".agentkit", "state", "codex-launch-"+token+".json"), receipt)
	meta := `{"type": "session_meta", "payload": {"id": "t1", "cwd": "` + cwd + `"}}` + "\n"
	return token, func(lines string) { put(rollout, meta+lines) }
}

// TestCodexErrorIsTheLastTurnsEndInTheThreadItsLaunchReported: what a seat's rollout says, once its
// receipt vouches for it, as codex.py `error` reads it.
func TestCodexErrorIsTheLastTurnsEndInTheThreadItsLaunchReported(t *testing.T) {
	token, write := codexSeat(t)
	failed := `{"type": "event_msg", "payload": {"type": "task_complete", "error": {"message": " stream disconnected \n"}}}` + "\n"
	record := func(pairs ...string) *run.Object {
		made := run.NewObject()
		for at := 0; at < len(pairs); at += 2 {
			made.Set(pairs[at], pairs[at+1])
		}
		return made
	}
	for _, each := range []struct {
		name, rollout string
		record        *run.Object
		said          string
		recorded      bool
	}{
		{"a failed turn", failed, record("codex_launch", token), "stream disconnected", true},
		{"a prompt after it", failed + `{"type": "event_msg", "payload": {"type": "task_started"}}` + "\n", record("codex_launch", token), "", true},
		{"an item after it", failed + `{"type": "response_item", "payload": {}}` + "\n", record("codex_launch", token), "", true},
		{"no receipt", failed, record(), "", false},
		{"another launch's receipt", failed, record("codex_launch", strings.Repeat("b", 32)), "", false},
		{"a thread the record replaced", failed, record("codex_launch", token, "id_source", "codex-session-start", "conversation", "t2"), "", false},
	} {
		write(each.rollout)
		if said, recorded := For("codex").RecordedError(each.record); said != each.said || recorded != each.recorded {
			t.Errorf("%s: %q, %v", each.name, said, recorded)
		}
	}
}

// TestCodexAnswerIsTheTurnContextOfTheLatestAnswer: the model and effort the turn holding the latest
// answer started on, and that answer's time, as codex.py `running` reads them.
func TestCodexAnswerIsTheTurnContextOfTheLatestAnswer(t *testing.T) {
	token, write := codexSeat(t)
	record := run.NewObject()
	record.Set("codex_launch", token)
	turn := func(model string) string {
		return `{"type": "turn_context", "payload": {"model": "` + model + `", "effort": "high"}}` + "\n"
	}
	answer := `{"type": "event_msg", "timestamp": "2026-11-03T10:00:00Z", "payload": {"type": "item_completed", ` +
		`"item": {"type": "AgentMessage", "content": [{"type": "Text", "text": "done"}]}}}` + "\n"
	write(turn("gpt-a") + answer + turn("gpt-b"))
	if model, effort, at, found := For("codex").LastAnswer(record); model != "gpt-a" || effort != "high" || at != "2026-11-03T10:00:00Z" || !found {
		t.Errorf("%v %v %v %v", model, effort, at, found)
	}
	write(turn("gpt-a"))
	if _, _, _, found := For("codex").LastAnswer(record); found {
		t.Error("a turn that never answered shows a model")
	}
}

func TestCodexReadsTheThreadOnlyOnceAReconcileBindsItsReceipt(t *testing.T) {
	token, write := codexSeat(t)
	write("")
	record := run.NewObject()
	record.Set("codex_launch", token)
	if owned, known := Owns("codex", record, "t1"); !owned || !known {
		t.Error("its proven thread is not its own")
	}
	if owned, _ := Owns("codex", record, "t2"); owned {
		t.Error("another thread is its own")
	}
	for _, each := range []struct {
		conversation, source string
		resumable            any
		ready                bool
		bound                string // the conversation reconciling leaves, resumable where it is t1
	}{
		{"", "", false, false, "t1"},
		{"old", "launcher", true, false, "t1"},
		{"t1", "launcher", true, false, "t1"},
		{"t1", "codex-session-start", false, false, "t1"},
		{"t1", "codex-session-start", nil, false, "t1"},
		{"t1", "codex-session-start", true, true, "t1"},
		{"newer", "codex-session-start", true, true, "newer"}, // no reconcile binds an older receipt over this
	} {
		record.Set("conversation", each.conversation)
		record.Set("id_source", each.source)
		record.Set("resumable", each.resumable)
		before := run.Encode(record)
		if _, ready := For("codex").Reconciled("acme", record); ready != each.ready || run.Encode(record) != before {
			t.Errorf("record changed or readiness differs: %+v", each)
		}
		// as the tick's reconcile leaves it, and read then
		fields := Reconcile("codex", record)
		for _, key := range fields.Keys() {
			record.Set(key, fields.Get(key))
		}
		if _, ready := For("codex").Reconciled("acme", record); !ready || record.Get("conversation") != each.bound ||
			record.Get("id_source") != "codex-session-start" || record.Get("resumable") != (each.bound == "t1") {
			t.Errorf("reconciled %+v into %s", each, run.Encode(record))
		}
	}
	record.Set("codex_launch", strings.Repeat("b", 32))
	if _, ready := For("codex").Reconciled("acme", record); !ready || !RecordReadOnly("codex") {
		t.Error("a record with no proven thread cannot be read without reconciling it")
	}
	for entry, kept := range map[string]bool{"codex-launch-" + token + ".json": true, "codex-remote-" + token: true,
		"codex-remote-" + token + ".forgotten": true, "codex-launch-x.json": false, "session-acme.json": false} {
		if KeptInState(entry) != kept {
			t.Errorf("%s kept: %v", entry, !kept)
		}
	}
}

func TestCodexListingKeepsItsReceiptButReadsTheRolloutOn(t *testing.T) {
	token, write := codexSeat(t)
	write("")
	record := run.NewObject()
	for key, value := range map[string]any{"codex_launch": token, "conversation": "t1",
		"id_source": "codex-session-start", "resumable": true} {
		record.Set(key, value)
	}
	reader, ready := For("codex").Reconciled("acme", record)
	if !ready {
		t.Fatal("the bound receipt needs no reconciliation")
	}
	if err := os.Remove(filepath.Join(os.Getenv("HOME"), ".agentkit", "state", "codex-launch-"+token+".json")); err != nil {
		t.Fatal(err)
	}
	write(`{"type":"turn_context","payload":{"model":"gpt-a","effort":"high"}}` + "\n" +
		`{"type":"event_msg","payload":{"type":"item_completed","item":{"type":"AgentMessage","content":[{"type":"Text","text":"done"}]}}}` + "\n" +
		`{"type":"event_msg","payload":{"type":"task_complete","error":{"message":"stream disconnected"}}}` + "\n")
	if owned, _ := reader.Owns(record, "t1"); !owned {
		t.Fatal("this listing lost the receipt it read")
	}
	if said, recorded := reader.RecordedError(record); said != "stream disconnected" || !recorded {
		t.Fatalf("the rollout's newer error: %q, %v", said, recorded)
	}
	if model, _, _, found := reader.LastAnswer(record); model != "gpt-a" || !found {
		t.Fatalf("the rollout's newer answer: %v, %v", model, found)
	}
	if owned, _ := Owns("codex", record, "t1"); owned {
		t.Fatal("the next reading kept the removed receipt")
	}
}
