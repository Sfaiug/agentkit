package launch

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

// A seat may have as many runs waiting for a slot as holding one, and always one, for every task a
// launch starts, counted from run records as Python's gate.seat_full reads them: under the name the
// seat goes by now, a run holding only while its loop lives, and none below another run.
func TestASeatQueuesNoMoreThanItRuns(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	// what `ak orch rename` leaves under the name a seat was started with
	if err := os.MkdirAll(filepath.Join(home, ".agentkit", "state"), 0o777); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "state", "session-old.json"), []byte(`{"renamed": "acme"}`), 0o666); err != nil {
		t.Fatal(err)
	}
	alive := []any{"pid", os.Getpid()}
	if born, ok := host.ReadIdentity(os.Getpid()); ok {
		alive = append(alive, "process_identity", run.Fields("boot", born.Boot, "ticks", int(born.Ticks), "started_at", born.StartedAt))
	}
	holds := func(seat string, at float64) []any {
		return append([]any{"launched_session", seat, "state", "running", "slot_started_at", at}, alive...)
	}
	waits := func(seat string, at float64) []any {
		return []any{"launched_session", seat, "state", "queued", "slot_waiting", true, "queued_at", at}
	}
	for id, fields := range map[string][]any{
		// acme: two holding, the first under its old name and earlier than its directory says, and two waiting
		"1-acme-holds-later": holds("acme", 20),
		"2-acme-holds-first": holds("old", 10),
		"3-acme-waits":       waits("acme", 5),
		"4-acme-waits-too":   waits("acme", 6),
		// what holds no slot of acme's: a loop with no process, a run below another, an ending, nobody's
		"5-acme-dead":   {"launched_session", "acme", "state", "running"},
		"6-acme-below":  append(waits("acme", 1), "run_depth", 1),
		"7-acme-passed": {"launched_session", "acme", "state", "pass"},
		"8-nobody":      waits("", 1),
		// bravo: two holding, one waiting
		"a-bravo-one":   holds("bravo", 1),
		"b-bravo-two":   holds("bravo", 2),
		"c-bravo-waits": waits("bravo", 3),
		// charlie: one waiting, none holding
		"d-charlie-waits": waits("charlie", 9),
	} {
		dir := filepath.Join(run.Runs(), id)
		if err := os.MkdirAll(dir, 0o777); err != nil {
			t.Fatal(err)
		}
		if err := run.Create(dir, run.Fields(append([]any{"run_id", id}, fields...)...)); err != nil {
			t.Fatal(err)
		}
	}
	for asked, want := range map[struct {
		seat     string
		launches int
	}]string{
		{"acme", 1}:    "acme may have as many runs waiting for a slot as holding one, and always one: it has 2 waiting and 2 holding, so room for 0 more, not 1; `ak wait 2-acme-holds-first`, then launch again",
		{"bravo", 1}:   "",
		{"bravo", 2}:   "bravo may have as many runs waiting for a slot as holding one, and always one: it has 1 waiting and 2 holding, so room for 1 more, not 2; `ak wait a-bravo-one`, then launch again",
		{"charlie", 1}: "charlie may have as many runs waiting for a slot as holding one, and always one: it has 1 waiting and 0 holding, so room for 0 more, not 1; `ak wait d-charlie-waits`, then launch again",
		{"delta", 1}:   "",
		{"delta", 2}:   "delta may have as many runs waiting for a slot as holding one, and always one: it has 0 waiting and 0 holding, so room for 1 more, not 2; launch one at a time",
	} {
		if got := seatFull(asked.seat, asked.launches); got != want {
			t.Errorf("%v:\n got %q\nwant %q", asked, got, want)
		}
	}
}
