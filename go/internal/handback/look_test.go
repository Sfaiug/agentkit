package handback

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

func TestALookLeavesAConcurrentDeliveryItsNoticeAndRecord(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	dir := t.TempDir()
	reason := strings.Repeat("The parser keeps the last row. ", 100)
	record := run.Fields("state", "not_needed", "not_needed", reason,
		"handback_pending", true, "finished_at", now())
	if err := run.Create(dir, record); err != nil {
		t.Fatal(err)
	}
	held, err := lock.Try(filepath.Join(dir, "delivery.lock"))
	if err != nil {
		t.Fatal(err)
	}
	defer held.Close()
	before, _ := os.ReadFile(filepath.Join(dir, "run.json"))
	line, printed := LookLine(dir, record)
	after, _ := os.ReadFile(filepath.Join(dir, "run.json"))
	if line == "" || printed != nil || string(before) != string(after) {
		t.Fatal("a concurrent delivery lost its line or record")
	}
	if _, err := os.Stat(filepath.Join(dir, "result.md")); !os.IsNotExist(err) {
		t.Fatal("the look saved a notice without its lock", err)
	}
	held.Close()
	got, printed := LookLine(dir, record)
	if got != line || printed == nil {
		t.Fatalf("the same ending changed: %q != %q", got, line)
	}
	notice, _ := os.ReadFile(filepath.Join(dir, "result.md"))
	if !strings.Contains(string(notice), strings.TrimSpace(reason)) {
		t.Fatal("the look lost its compact line's full notice")
	}
	printed()
	said, _ := run.Read(dir)
	if Waiting(said) || !handedBack(said) || !said.Truthy("reported") {
		t.Fatal("the printed ending was not handed back", run.Line(said))
	}
}

func TestAChangedAttemptOrTypedLineCannotBeRecordedByAnEarlierLook(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	for _, changed := range []*run.Object{
		run.Fields("pid", 2), run.Fields("finished_at", run.Float(200)),
		run.Fields("interrupted_at", run.Float(200)), run.Fields("handback_typed", true),
		run.Fields("handed_back", run.Float(101)),
	} {
		dir := t.TempDir()
		snapshot := run.Fields("pid", 1, "state", "fail", "finished_at", run.Float(100), "handback_pending", true)
		if err := run.Create(dir, snapshot); err != nil {
			t.Fatal(err)
		}
		_, printed := LookLine(dir, snapshot)
		if printed == nil {
			t.Fatal("the uncontended ending has no recording action")
		}
		if err := run.Change(dir, func(record *run.Object) error {
			for _, key := range changed.Keys() {
				record.Set(key, changed.Get(key))
			}
			return nil
		}); err != nil {
			t.Fatal(err)
		}
		before, _ := os.ReadFile(filepath.Join(dir, "run.json"))
		printed()
		after, _ := os.ReadFile(filepath.Join(dir, "run.json"))
		if string(before) != string(after) {
			t.Fatal("an earlier look changed the record", run.Line(changed))
		}
	}
}

func TestALookAtAMergeGoneLiveSaysAndSettlesItUnlessHealthMovedSince(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	for _, moved := range []bool{false, true} {
		dir := filepath.Join(t.TempDir(), "fix-api")
		if err := os.Mkdir(dir, 0o755); err != nil {
			t.Fatal(err)
		}
		record := run.Fields("state", "pass", "verdict", "PASS", "merged", true, "pr", "https://github.com/acme/api/pull/1",
			"finished_at", now(), "live_at", run.Float(100), "handback_pending", true)
		if err := run.Create(dir, record); err != nil {
			t.Fatal(err)
		}
		line, printed := LookLine(dir, record)
		if !strings.Contains(line, "run fix-api is live: https://github.com/acme/api/pull/1.") || printed == nil {
			t.Fatalf("the look left out its live sentence: %q", line)
		}
		if moved {
			if err := run.Change(dir, func(current *run.Object) error {
				current.Set("live_at", run.Float(200))
				return nil
			}); err != nil {
				t.Fatal(err)
			}
		}
		printed()
		said, _ := run.Read(dir)
		if !handedBack(said) || said.Truthy("live_notified") == moved || !moved && said.Str("live_note") != looked {
			t.Fatal("the live notice the look printed was not settled as such", moved, run.Line(said))
		}
	}
}
