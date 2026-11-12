package cli

import (
	"fmt"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
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

// What a seat spent on ak's own checkout counts in the week's tokens, as from seats, and in ak's
// share of them, though no run ended, as Python's board counts it.
func TestTheBoardCountsWhatTheSeatsSpent(t *testing.T) {
	home := sandbox(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "[models.opus]\nharness='claude'\nmodel='claude-opus'\n"+
		"effort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	record := map[string]any{"conversation": "conv-acme", "cwd": "/code/acme"}
	path, _ := harness.Conversation("claude", record)
	write(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"),
		fmt.Sprintf(`{"orchestrator":"opus","conversation":"conv-acme","cwd":"/code/acme","repo":%q}`, config.Repo()))
	write(t, path, `{"type":"assistant","timestamp":"2026-11-05T09:00:05Z","message":{"id":"msg_acme",`+
		`"usage":{"input_tokens":1200,"output_tokens":300}}}`+"\n")
	db, uncounted, err := boardHistory()
	defer db.Close()
	if err != nil || len(uncounted) > 0 {
		t.Fatalf("read with %q uncounted: %v", uncounted, err)
	}
	board := readScoreboard(db, time.Date(2026, 11, 6, 0, 0, 0, 0, time.UTC))
	cells := board.cells(board.now)
	if !slices.Equal(cells[:3], []string{"no runs ended", "no runs ended; 100% of all recorded tokens",
		"1,500 tokens; 1,500 from seats"}) {
		t.Fatalf("the week reads %q", cells[:3])
	}
	if cell := board.cells(board.now - week)[2]; cell != "no tokens recorded" {
		t.Fatalf("the week before reads %q", cell)
	}
}
