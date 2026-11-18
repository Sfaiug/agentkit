package history

import (
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"testing"

	"agentkit/internal/run"
)

// A turn its run's ending counts after the session's later totals were kept gives back the share
// the earliest of them took, so the session's rows sum to its total in whatever order they are
// counted.
func TestATurnCountedAfterItsSessionsNextTotalGivesItsShareBack(t *testing.T) {
	home(t)
	log, lines := said()
	id := "20261106-1200-fix-api"
	going := record(t, `{"run_id": "`+id+`", "state": "running"}`)
	Start(going, log)
	total := func(opus, haiku string) string {
		return `{"type": "result", "session_id": "session-acme", "usage": {"input_tokens": 1}, "modelUsage": {` +
			`"claude-opus-5": ` + opus + `, "claude-haiku-5": ` + haiku + `}}`
	}
	// the first turn's own end never came; the second and third were counted at theirs
	turn(t, id, "executor-opus", "claude", total(`{"inputTokens": 10, "cacheCreationInputTokens": 1000, "cacheReadInputTokens": 5000, "outputTokens": 200}`,
		`{"inputTokens": 3, "cacheCreationInputTokens": 300, "outputTokens": 40}`), 1000, 1005)
	Spent(going, "claude", turn(t, id, "fixer-opus", "claude", total(`{"inputTokens": 15, "cacheCreationInputTokens": 1500, "cacheReadInputTokens": 9000, "outputTokens": 260}`,
		`{"inputTokens": 5, "cacheCreationInputTokens": 350, "cacheReadInputTokens": 100, "outputTokens": 50}`), 1010, 1015), log)
	Spent(going, "claude", turn(t, id, "final-fixer-opus", "claude", total(`{"inputTokens": 20, "cacheCreationInputTokens": 2000, "cacheReadInputTokens": 12000, "outputTokens": 300}`,
		`{"inputTokens": 5, "cacheCreationInputTokens": 350, "cacheReadInputTokens": 100, "outputTokens": 50}`), 1020, 1025), log)
	ended := going.Copy()
	run.SetAll(ended, "state", "stopped", "finished_at", 1100.0)
	Finish(ended, log)
	db, err := Open()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var got [][]any
	for _, kept := range query(t, db, "SELECT * FROM turn_usage ORDER BY began, model") {
		got = append(got, []any{filepath.Base(kept.Text("turn")), kept["model"], kept["input"], kept["cache_write"], kept["cache_read"], kept["output"]})
	}
	want := [][]any{
		{"executor-opus", "claude-haiku-5", int64(3), int64(300), int64(0), int64(40)},
		{"executor-opus", "claude-opus-5", int64(10), int64(1000), int64(5000), int64(200)},
		{"fixer-opus", "claude-haiku-5", int64(2), int64(50), int64(100), int64(10)},
		{"fixer-opus", "claude-opus-5", int64(5), int64(500), int64(4000), int64(60)},
		{"final-fixer-opus", "claude-haiku-5", int64(0), int64(0), int64(0), int64(0)},
		{"final-fixer-opus", "claude-opus-5", int64(5), int64(500), int64(3000), int64(40)},
	}
	if !reflect.DeepEqual(got, want) || len(*lines) > 0 {
		t.Fatalf("kept\n%v\nwant\n%v\nsaid %q", got, want, *lines)
	}
}

// Each row a turn writes keeps what its counts cost at the boards' prices then, and a turn giving
// its share back from a later total prices that total's row of a model whose counts change anew,
// leaving one whose counts stay with the dollars it kept and one with a count unknown unpriced.
func TestASharedTotalsRowKeepsItsDollarsOnlyWhileItsCountsStay(t *testing.T) {
	home(t)
	board := `{"model": "Claude %[1]s 5", "slug": "claude-%[2]s-5", "release": {"slug": "claude-%[2]s-5", "name": "Claude %[1]s 5"}, ` +
		`"values": {"aa.price1mInputTokens": %[3]d, "aa.price1mOutputTokens": 1}}`
	if os.MkdirAll(filepath.Join(filepath.Dir(Path()), "state"), 0o700) != nil || os.WriteFile(filepath.Join(filepath.Dir(Path()), "state", "boards.json"),
		[]byte(`{"artificialanalysis.ai": {"rows": [`+fmt.Sprintf(board, "Opus", "opus", 300000)+`, `+fmt.Sprintf(board, "Haiku", "haiku", 100000)+`, `+
			fmt.Sprintf(board, "Sonnet", "sonnet", 200000)+`]}}`), 0o600) != nil {
		t.Fatal("boards")
	}
	log, lines := said()
	id := "20261106-1200-fix-api"
	going := record(t, `{"run_id": "`+id+`", "state": "running"}`)
	Start(going, log)
	total := func(opus, haiku, sonnet int) string {
		return `{"type": "result", "session_id": "session-acme", "usage": {"input_tokens": 1}, "modelUsage": {` +
			`"claude-opus-5": {"inputTokens": ` + strconv.Itoa(opus) + `}, "claude-haiku-5": {"inputTokens": ` + strconv.Itoa(haiku) + `}, ` +
			`"claude-sonnet-5": {"inputTokens": ` + strconv.Itoa(sonnet) + `}}}`
	}
	turn(t, id, "executor-opus", "claude", total(10, 0, 4), 1000, 1005)
	Spent(going, "claude", turn(t, id, "fixer-opus", "claude", total(15, 5, 6), 1010, 1015), log)
	db, err := Open()
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	if err := db.exec("UPDATE turn_usage SET listed_usd = 1, cache_read = IIF(model = 'claude-sonnet-5', NULL, cache_read)"); err != nil {
		t.Fatal(err)
	}
	ended := going.Copy()
	run.SetAll(ended, "state", "stopped", "finished_at", 1100.0)
	Finish(ended, log)
	var got [][]any
	for _, kept := range query(t, db, "SELECT * FROM turn_usage ORDER BY began, model") {
		got = append(got, []any{filepath.Base(kept.Text("turn")), kept["model"], kept["input"], kept["cache_read"], kept["listed_usd"]})
	}
	want := [][]any{
		{"executor-opus", "claude-haiku-5", int64(0), int64(0), 0.0},
		{"executor-opus", "claude-opus-5", int64(10), int64(0), 3.0},
		{"executor-opus", "claude-sonnet-5", int64(4), int64(0), 0.8},
		{"fixer-opus", "claude-haiku-5", int64(5), int64(0), 1.0},
		{"fixer-opus", "claude-opus-5", int64(5), int64(0), 1.5},
		{"fixer-opus", "claude-sonnet-5", int64(2), nil, nil},
	}
	if !reflect.DeepEqual(got, want) || len(*lines) > 0 {
		t.Fatalf("kept\n%v\nwant\n%v\nsaid %q", got, want, *lines)
	}
}
