package history

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"agentkit/internal/run"
)

// turn is a turn of the run id, in round 1's folder name, as Go's worker leaves it: its harness
// receipt, none for "", written as it began, and its events as it ended.
func turn(t *testing.T, id, name, harness, events string, began, ended int64) string {
	t.Helper()
	out := filepath.Join(run.Runs(), id, "round-1", name)
	if err := os.MkdirAll(out, 0o700); err != nil {
		t.Fatal(err)
	}
	for file, text := range map[string]string{"harness": harness, "account": "default", "events.jsonl": events} {
		if file == "harness" && harness == "" {
			continue
		}
		at := time.Unix(began, 0)
		if file == "events.jsonl" {
			at = time.Unix(ended, 0)
		}
		if os.WriteFile(filepath.Join(out, file), []byte(text), 0o600) != nil || os.Chtimes(filepath.Join(out, file), at, at) != nil {
			t.Fatal(file)
		}
	}
	return out
}

// spent is the run's tokens by role.
func spent(t *testing.T, id string) [2]any {
	t.Helper()
	got := row(t, id, "executor_tokens", "reviewer_tokens")
	return [2]any{got["executor_tokens"], got["reviewer_tokens"]}
}

// Each turn counts once, for its role, by what its harness says it spent: a turn cut off counts the
// calls it finished, the ending counts the turn whose own end never came, a resumed Codex thread its
// share, and nothing read later changes a turn counted.
func TestEachTurnCountsOnceForItsRole(t *testing.T) {
	home(t)
	log, lines := said()
	id := "20261106-1200-fix-api"
	going := record(t, `{"run_id": "`+id+`", "state": "running"}`)
	Start(going, log)
	executor := turn(t, id, "executor-opus", "claude",
		`{"type": "message", "message": {"id": "1", "usage": {"input_tokens": 100, "output_tokens": 20}}}`+"\n"+
			`{"type": "message", "message": {"id": "2", "usage": {"input_tokens": 200, "output_tokens": 30}}}`+"\n"+`{"type":`, 1000, 1001)
	Spent(going, "claude", executor, log)
	Spent(going, "claude", executor, log)
	Spent(going, "codex", turn(t, id, "reviewer-astra-retry1", "", "", 1001, 1001), log)
	if got := spent(t, id); got != [2]any{int64(350), nil} {
		t.Fatalf("by its turns' ends: %v", got)
	}
	thread := `{"type": "thread.started", "thread_id": "thread-acme"}` + "\n"
	turn(t, id, "reviewer-astra", "codex", thread+`{"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 10}}`, 1002, 1003)
	turn(t, id, "reviewer-astra-attempt2", "codex", thread+`{"type": "turn.completed", "usage": {"input_tokens": 90, "output_tokens": 10}}`, 1004, 1005)
	ended := going.Copy()
	run.SetAll(ended, "state", "stopped", "finished_at", 1100.0)
	Finish(ended, log)
	if got := spent(t, id); got != [2]any{int64(350), int64(100)} {
		t.Fatalf("by its ending: %v", got)
	}
	matches, _ := filepath.Glob(filepath.Join(run.Runs(), id, "round-1", "*", "events.jsonl"))
	for _, events := range matches {
		os.WriteFile(events, []byte(`{"type": "result", "usage": {"tokens": 999}}`), 0o600)
	}
	Finish(ended, log)
	if got := spent(t, id); got != [2]any{int64(350), int64(100)} || len(*lines) > 0 {
		t.Fatalf("ended again: %v, said %q", got, *lines)
	}
}

// A Claude turn keeps what each model spent by kind, with the login it ran on, as its last result
// says: counts that total its session are their growth over the session's turn before it, and a
// result naming no model is the turn's own.
func TestAClaudeTurnKeepsEachModelsGrowthOverItsSession(t *testing.T) {
	home(t)
	log, lines := said()
	id := "20261106-1200-fix-api"
	going := record(t, `{"run_id": "`+id+`", "state": "running"}`)
	Start(going, log)
	session := `{"type": "result", "session_id": "session-acme", "usage": {"input_tokens": 1}, "modelUsage": `
	for _, each := range []struct {
		name, events string
		at           int64
	}{
		{"executor-opus", session + `{"claude-opus-5": {"inputTokens": 10, "cacheCreationInputTokens": 1000, "cacheReadInputTokens": 5000, "outputTokens": 200}, "claude-haiku-5": {"inputTokens": 3, "cacheCreationInputTokens": 300, "outputTokens": 40}}}`, 1000},
		{"fixer-opus", session + `{"claude-opus-5": {"inputTokens": 15, "cacheCreationInputTokens": 1500, "cacheReadInputTokens": 9000, "outputTokens": 260}, "claude-haiku-5": {"inputTokens": 5, "cacheCreationInputTokens": 350, "cacheReadInputTokens": 100, "outputTokens": 50.0}}}`, 1010},
		{"final-fixer-opus", `{"type": "result", "session_id": "session-acme", "usage": {"input_tokens": 7, "cache_creation_input_tokens": 70, "cache_read_input_tokens": 700, "output_tokens": 17}}`, 1020},
	} {
		Spent(going, "claude", turn(t, id, each.name, "claude", each.events, each.at, each.at+5), log)
	}
	db, err := Open()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var got [][]any
	for _, kept := range query(t, db, "SELECT * FROM turn_usage ORDER BY began, model") {
		got = append(got, []any{filepath.Base(kept.Text("turn")), kept["run_id"], kept["role"], kept["account"], kept["model"],
			kept["began"], kept["at"], kept["input"], kept["cache_write"], kept["cache_read"], kept["output"]})
	}
	want := [][]any{
		{"executor-opus", id, "executor", "default", "claude-haiku-5", 1000.0, 1005.0, int64(3), int64(300), int64(0), int64(40)},
		{"executor-opus", id, "executor", "default", "claude-opus-5", 1000.0, 1005.0, int64(10), int64(1000), int64(5000), int64(200)},
		{"fixer-opus", id, "executor", "default", "claude-haiku-5", 1010.0, 1015.0, int64(2), int64(50), int64(100), int64(0)},
		{"fixer-opus", id, "executor", "default", "claude-opus-5", 1010.0, 1015.0, int64(5), int64(500), int64(4000), int64(60)},
		{"final-fixer-opus", id, "executor", "default", nil, 1020.0, 1025.0, int64(7), int64(70), int64(700), int64(17)},
	}
	if !reflect.DeepEqual(got, want) || len(*lines) > 0 {
		t.Fatalf("kept\n%v\nwant\n%v\nsaid %q", got, want, *lines)
	}
}

// The tick ends a row whose run ended without it as the run's own ending would, every turn its
// receipts name counted.
func TestTheTickCountsTheTurnsOfARowItEnds(t *testing.T) {
	home(t)
	log, lines := said()
	id := "20261106-1200-fix-api"
	Start(record(t, `{"run_id": "`+id+`", "state": "running"}`), log)
	put(t, filepath.Join(run.Runs(), id, "run.json"), `{"state": "fail", "started_at": 1000.0, "finished_at": 1100.0}`)
	turn(t, id, "executor-astra", "codex", `{"type": "thread.started", "thread_id": "thread-acme"}`+"\n"+
		`{"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 10}}`, 1000, 1001)
	if !Agree(log) || len(*lines) > 0 {
		t.Fatalf("left to Python, said %q", *lines)
	}
	if got := row(t, id, "final_state", "executor_tokens"); got["final_state"] != "fail" || got["executor_tokens"] != int64(60) {
		t.Fatalf("row %v", got)
	}
}

func put(t *testing.T, path, text string) {
	t.Helper()
	if os.MkdirAll(filepath.Dir(path), 0o700) != nil || os.WriteFile(path, []byte(text), 0o600) != nil {
		t.Fatal(path)
	}
}
