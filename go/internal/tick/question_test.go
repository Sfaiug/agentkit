//go:build unix

package tick

import (
	"io"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestAnOpenGenerationDoesNotStopTheTick(t *testing.T) {
	ak, _ := idleHome(t, answers)
	put(t, filepath.Join(ak, "state", "watch.json"), `{"seen_at":{"acme":100}}`)
	if !Carry(io.Discard, io.Discard) {
		t.Fatal("an open's generation was treated as work for Python")
	}
	if state, err := run.ReadJSON(filepath.Join(ak, "state", "watch.json")); err != nil || !run.Equal(state.Dict("seen_at"), run.Fields("acme", 100)) {
		t.Fatalf("the tick changed the generation: %v, %v", state, err)
	}
}

func TestCardWorkHandsOverAtItsOwnRow(t *testing.T) {
	ak, _ := idleHome(t, answers)
	tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
	var cards pass
	for _, row := range table(tick) {
		if row.name == "card transitions" {
			cards = row
		}
	}
	if cards.idle == nil || !cards.idle() || cards.step == nil {
		t.Fatal("an empty home did not reach the card row")
	}
	path, text := filepath.Join(ak, "state", "card-acme.json"), `{"word":"needs you"}`
	after := false
	if tick.through([]pass{
		{"before", false, nil, func() error { put(t, path, text); return nil }}, cards,
		{"after", false, nil, func() error { after = true; return nil }},
	}) || after || read(t, path) != text {
		t.Fatal("the card row did not hand over the newly orphaned card unchanged")
	}
}
