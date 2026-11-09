//go:build linux

package launch

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// A launch told --bg, which nothing in its process follows, waits queued on the count outside a
// suite's home, where a followed one is handed over; its driver's poll then leaves that wait, which
// Python counts in history.db, to Python, writing nothing of it.
func TestADetachedLaunchWaitsAndItsDriverLeavesTheWait(t *testing.T) {
	gatedHome(t, "")
	held(t, "held")
	admitted, err := admit("waits", false, "", 0, false)
	if err != nil || admitted.in || admitted.kind != "count" {
		admitted.release()
		t.Fatalf("not held on the count: %+v %v", admitted, err)
	}
	waits := filepath.Join(run.Runs(), "waits")
	os.Mkdir(waits, 0o777)
	if err := admitted.claim(waits, run.Capture(waits, "", nil, nil, config.Binding{}, "")); err != nil {
		t.Fatal(err)
	}
	if record, _ := run.Read(waits); record.Str("state") != "queued" || !record.Truthy("slot_waiting") {
		t.Fatalf("not waiting: %s", run.Line(record))
	}
	// what a poll writes: the run's record and the line
	written := func() string {
		record, _ := os.ReadFile(filepath.Join(waits, "run.json"))
		line, _ := os.ReadFile(filepath.Join(run.Runs(), ".slots.queue"))
		return string(record) + string(line)
	}
	before := written()
	// a driver that went on would wait for the count: the deadline ends it
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	if err := waitSlot(ctx, waits); !errors.Is(err, loop.ErrLeft) {
		t.Fatalf("the driver went on with a wait Python counts: %v", err)
	}
	if written() != before {
		t.Fatal("the driver wrote its poll")
	}
}
