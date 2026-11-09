package cli

import (
	"fmt"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"agentkit/internal/history"
)

// The board names the seats it counts nothing of, as Python's does, each with its harness: one
// whose conversation is not written yet, its file kept in history.db to be read from its start,
// and one holding a conversation its harness names no file for; a seat with neither goes unnamed.
func TestTheBoardNamesTheSeatsItCountsNothingOf(t *testing.T) {
	home := sandbox(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.opus]\nharness='claude'\nmodel='claude-opus'\n"+
		"effort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	for name, record := range map[string]string{
		"elm": fmt.Sprintf(`{"orchestrator":"opus","conversation":"conv-elm","cwd":%q}`, t.TempDir()),
		"ash": `{"orchestrator":"opus","conversation":"conv-ash"}`,
		"fir": `{"orchestrator":"opus"}`,
	} {
		write(t, filepath.Join(home, ".agentkit", "state", "session-"+name+".json"), record)
	}
	db, uncounted, err := boardHistory()
	db.Close()
	if err != nil || !slices.Equal(uncounted, []string{"ash (claude)", "elm (claude)"}) {
		t.Fatalf("named %q: %v", uncounted, err)
	}
	board := readScoreboard(nil, time.Now())
	board.uncounted = uncounted
	if cell := board.cells(board.now)[2]; cell != "no tokens recorded; not counted: ash (claude), elm (claude)" {
		t.Fatalf("the tokens row says %q", cell)
	}
	look := history.Look()
	defer look.Close()
	if kept := look.Select("SELECT path FROM seat_sources"); len(kept) != 1 || filepath.Base(kept[0].Text("path")) != "conv-elm.jsonl" {
		t.Fatalf("kept %v", kept)
	}
}
