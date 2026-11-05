//go:build unix

package tick

import (
	"bytes"
	"io"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestAGoneQuestionReachesItsRetryRow(t *testing.T) {
	ak, path := goneHome(t)
	record, _ := run.ReadJSON(path)
	record.Delete("id_source")
	put(t, path, run.Line(record))
	asked := run.Float(epoch(time.Now()) - 300)
	put(t, filepath.Join(ak, "state", "notify-acme.json"), run.Line(run.Fields(
		"session", "acme", "kind", "needs", "text", "Which database?", "time", asked)))
	put(t, filepath.Join(ak, "state", "card-acme.json"), run.Line(run.Fields(
		"word", "needs you", "since", asked, "began", asked, "episode", "question", "sent", false)))
	state, known := loadState()
	if !known {
		t.Fatal("watch state unreadable")
	}
	var out, errOut bytes.Buffer
	tick := &ticking{state: state, log: newLog(&out, &errOut), clock: time.Now}
	for _, row := range table(tick) {
		if !tick.through([]pass{row}) {
			t.Fatalf("handed over at %s: %s %s", row.name, &out, &errOut)
		}
	}
	paths, _ := filepath.Glob(filepath.Join(ak, "state", "notification-outbox", "*.json"))
	if len(paths) != 1 {
		t.Fatalf("queued %d pages", len(paths))
	}
	event, _ := run.ReadJSON(paths[0])
	if attempts, _ := event.Int("attempts"); event.Str("status") != "disabled" || attempts != 1 || errOut.Len() == 0 {
		t.Fatalf("page=%s; stderr=%s", run.Line(event), &errOut)
	}
}

func TestRetryWorkIsReadAtItsOwnRow(t *testing.T) {
	ak, _ := idleHome(t, answers)
	tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
	var retry pass
	for _, row := range table(tick) {
		if row.name == "notification retry" {
			retry = row
		}
	}
	if retry.step == nil {
		t.Fatal("the retry row carries out nothing")
	}
	path := filepath.Join(ak, "state", "notification-outbox", "done.json")
	text := `{"kind":"done","status":"pending"}`
	after := false
	if tick.through([]pass{
		{"before", false, nil, func() error { put(t, path, text); return nil }}, retry,
		{"after", false, nil, func() error { after = true; return nil }},
	}) || after || read(t, path) != text {
		t.Fatal("the retry row did not hand over the newly queued done unchanged")
	}
}
