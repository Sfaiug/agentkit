package launch

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// A seat's waiters take turns in line as Python's gate.slot_counts gives them: acme, two turns
// served while it waited, keeps that count, bravo too; charlie's new batch and a run of no seat
// join level with acme, so each waits one turn behind bravo; a `--first` run goes ahead of all.
// The run let in counts a turn of its seat's.  Each line as Python's own saved it.
func TestASeatsWaitersTakeTurnsInLine(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	waits := func(id, seat string, at int, more ...any) *run.Object {
		dir := filepath.Join(run.Runs(), id)
		record := run.Fields(append([]any{"run_id", id, "state", "queued", "slot_waiting", true, "queued_at", at, "launched_session", seat}, more...)...)
		if seat == "" {
			record.Delete("launched_session")
		}
		if err := os.MkdirAll(dir, 0o777); err != nil || run.Create(dir, record) != nil {
			t.Fatal(dir, err)
		}
		return record
	}
	a1, polled := waits("a1", "acme", 1), waits("c2", "charlie", 5)
	waits("a2", "acme", 2)
	waits("b1", "bravo", 3)
	waits("c1", "charlie", 4)
	waits("n1", "", 6)
	waits("f1", "bravo", 7, "first", true)
	os.WriteFile(filepath.Join(run.Runs(), ".slots.queue"), []byte(`{"at": 1, "running": 1, "queue": ["a1", "a2", "b1"], "since": 1, "took": [], "last_in": 0, "turns": [[true, true, true, "acme", "", 2, ["a1", "a2"]], [true, true, true, "bravo", "", 0, ["b1"]]]}`), 0o666)
	saved, _ := queued()
	_, others, _ := places(polled)
	line, turns := inTurns(append([]*run.Object{polled}, others...), saved.turns)
	saves := func(waiting []*run.Object, let *run.Object, queue, kept string) {
		t.Helper()
		if err := saveLine(0, waiting, turns, let); err != nil {
			t.Fatal(err)
		}
		written, _ := run.ReadJSON(filepath.Join(run.Runs(), ".slots.queue"))
		if got := run.Line(written.Get("queue")); got != queue {
			t.Errorf("line\n got %s\nwant %s", got, queue)
		}
		if got := run.Line(written.Get("turns")); got != kept {
			t.Errorf("turns\n got %s\nwant %s", got, kept)
		}
	}
	saves(line, nil, `["f1", "b1", "a1", "c1", "n1", "a2", "c2"]`,
		`[[true, true, true, "acme", "", 2, ["a1", "a2"]], [true, true, true, "bravo", "", 0, ["b1"]], [true, true, true, "charlie", "", 2, ["c2", "c1"]], [false, true, true, "bravo", "", 0, ["f1"]], [true, true, true, "", "n1", 2, ["n1"]]]`)
	var rest []*run.Object
	for _, other := range line {
		if other.Str("run_id") != "a1" {
			rest = append(rest, other)
		}
	}
	saves(rest, a1, `["f1", "b1", "c1", "n1", "a2", "c2"]`,
		`[[true, true, true, "acme", "", 3, ["a2"]], [true, true, true, "bravo", "", 0, ["b1"]], [true, true, true, "charlie", "", 2, ["c2", "c1"]], [false, true, true, "bravo", "", 0, ["f1"]], [true, true, true, "", "n1", 2, ["n1"]]]`)
}
