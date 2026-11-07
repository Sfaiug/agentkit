//go:build linux

package launch

import (
	"context"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// gatedHome is a home whose launches the gate decides on calm injected readings, one run at a
// time, under the notify sink given.
func gatedHome(t *testing.T, sink string) string {
	home := t.TempDir()
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "XDG_CACHE_HOME": "",
		"AK_NOTIFY_SINK": sink, "AK_RUN_DEPTH": "", "AGENTKIT_RUN_DIR": "", "AK_PARENT_RUN": "", "AK_MAX_RUNS": "1",
		"AK_HOST_READINGS": `{"free_mb": 64000, "mem_total_mb": 128000, "cpus": 8, "load": 0.1}`} {
		t.Setenv(key, value)
	}
	for _, key := range []string{"AK_SLOT_POLL", "AK_MIN_FREE_MB", "AK_MAX_LOAD"} {
		t.Setenv(key, "")
		os.Unsetenv(key)
	}
	return home
}

// held is a run of this process holding its slot.
func held(t *testing.T, id string) {
	dir := filepath.Join(run.Runs(), id)
	if err := os.MkdirAll(dir, 0o777); err != nil {
		t.Fatal(err)
	}
	if err := run.Create(dir, run.Capture(dir, "", nil, nil, config.Binding{}, "")); err != nil {
		t.Fatal(err)
	}
}

// A launch the count holds is handed over where its wait would count in history.db, which Go
// writes none of, leaving runs/ as it found it but for the slots lock; under a suite's sink the same
// launch waits queued on the count, and one told --first goes in past it, the waiter still in line.
func TestALaunchWaitsInLineOnlyWhereHistoryCountsNoWait(t *testing.T) {
	home := gatedHome(t, "")
	held(t, "held")
	before := files(t, home)
	if admitted, err := admit("waits", false, ""); !errors.Is(err, ErrPython) {
		admitted.release()
		t.Fatalf("waits beside a history that counts waits: %v", err)
	}
	after := files(t, home)
	delete(after, filepath.Join(run.Runs(), ".slots.lock"))
	for path, is := range after {
		if was, found := before[path]; !found || was != is {
			t.Fatalf("the hand-over changed %s", path)
		}
	}

	t.Setenv("AK_NOTIFY_SINK", "dry-run")
	waits := filepath.Join(run.Runs(), "waits")
	admitted, err := admit("waits", false, "")
	if err != nil || admitted.in || admitted.kind != "count" {
		t.Fatalf("not held on the count: %+v %v", admitted, err)
	}
	os.Mkdir(waits, 0o777)
	if err := admitted.claim(waits, run.Capture(waits, "", nil, nil, config.Binding{}, "")); err != nil {
		t.Fatal(err)
	}
	record, _ := run.Read(waits)
	if record.Str("state") != "queued" || !record.Truthy("slot_waiting") || record.Has("slot_started_at") ||
		record.Str("slot_wait_reason") != "waiting for a slot · limit full (1 running) · 0 ahead" {
		t.Fatal(run.Line(record))
	}
	admitted, err = admit("first", true, "")
	if err != nil || !admitted.in {
		t.Fatalf("--first held: %+v %v", admitted, err)
	}
	first := filepath.Join(run.Runs(), "first")
	os.Mkdir(first, 0o777)
	if err := admitted.claim(first, run.Capture(first, "", nil, nil, config.Binding{}, "")); err != nil {
		t.Fatal(err)
	}
	line, _ := queued()
	if len(line.queue) != 1 || line.queue[0] != "waits" || line.lastIn == 0 {
		t.Fatalf("the line after --first went in: %+v", line)
	}
}

// A run's driver finds its queued receipt and, with no gate to ask, holds its slot at its first
// poll, writing no line.
func TestAnUngatedWaiterHoldsItsSlotAtOnce(t *testing.T) {
	gatedHome(t, "dry-run")
	t.Setenv("AK_MAX_RUNS", "0")
	dir := filepath.Join(run.Runs(), "fix")
	os.MkdirAll(dir, 0o777)
	receipt := run.SetAll(run.Capture(dir, "", nil, nil, config.Binding{}, ""), "state", "queued", "slot_waiting", true)
	receipt.Delete("slot_started_at")
	if err := run.Create(dir, receipt); err != nil {
		t.Fatal(err)
	}
	if err := waitSlot(context.Background(), dir); err != nil {
		t.Fatal(err)
	}
	record, _ := run.Read(dir)
	if record.Str("state") != "running" || record.Truthy("slot_waiting") || !record.Truthy("slot_started_at") {
		t.Fatalf("never claimed its own slot: %s", run.Line(record))
	}
	if _, err := os.Stat(filepath.Join(run.Runs(), ".slots.queue")); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("an outright claim saved a line: %v", err)
	}
}

// files is each path under root with its contents, "" for a folder.
func files(t *testing.T, root string) map[string]string {
	found := map[string]string{}
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			found[path] = ""
			return err
		}
		data, err := os.ReadFile(path)
		found[path] = "file " + string(data)
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	return found
}
