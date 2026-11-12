package harness

import (
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"

	"agentkit/internal/hookfact"
	"agentkit/internal/run"
)

// museLogs writes that session's log as Muse 1.4.12 does: one line per entry, each event a run's,
// recorded a microsecond apart from 1 unless an entry dates itself.
func museLogs(t *testing.T, session string, entries ...*run.Object) {
	t.Helper()
	dir := filepath.Join(os.Getenv("XDG_DATA_HOME"), "muse", "sessions", "2026", "10", "26", session)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	var lines []string
	for at, entry := range entries {
		if !entry.Has("recorded_at") {
			entry.Set("recorded_at", (at+1)*1_000_000)
		}
		lines = append(lines, run.Line(entry))
	}
	if err := os.WriteFile(filepath.Join(dir, "session.jsonl"), []byte(strings.Join(lines, "\n")+"\n"), 0o600); err != nil {
		t.Fatal(err)
	}
}

func museEvent(fields ...any) *run.Object {
	return run.Fields("payload", run.Fields("kind", "run", "run_id", "acme-run", "event", run.Fields(fields...)))
}

func museRunOf(id string, event *run.Object) *run.Object {
	event.Dict("payload").Set("run_id", id)
	return event
}

func museCardEvent(prompt, kind string, fields ...any) *run.Object {
	return museEvent(append([]any{"kind", "user_input_prompt_" + kind, "prompt_id", prompt, "tool_call_id", prompt + "-call"}, fields...)...)
}

var museAsked = []any{"questions", []any{run.Fields("id", "shape", "question", "Which shape should acme use?")}}

func TestMuseCardIsItsNewestCardUntilThatCardSettles(t *testing.T) {
	t.Setenv("XDG_DATA_HOME", t.TempDir())
	asked := hookfact.Fact{Event: "Notification", Kind: "question_prompt", Text: "Which shape should acme use?"}
	for _, each := range []struct {
		why     string
		entries []*run.Object
		want    hookfact.Fact
		up      bool
	}{
		{"no card", []*run.Object{museEvent("kind", "started", "prompt", "Shape the acme logo.")}, hookfact.Fact{}, false},
		{"a card quoted in a message is none", []*run.Object{museEvent("kind", "assistant_message_committed",
			"text", run.Line(museCardEvent("quoted", "requested", museAsked...)))}, hookfact.Fact{}, false},
		{"up", []*run.Object{museCardEvent("acme", "requested", museAsked...)}, with(asked, 1), true},
		{"answered", []*run.Object{museCardEvent("acme", "requested", museAsked...), museCardEvent("acme", "settled", "outcome", "answered")},
			hookfact.Fact{Event: "PostToolBatch", Kind: "request_user_input", At: 2}, true},
		{"an older card's settling leaves the newer up", []*run.Object{museCardEvent("old", "requested", museAsked...),
			museCardEvent("acme", "requested", museAsked...), museCardEvent("old", "settled", "outcome", "answered")}, with(asked, 2), true},
		{"Esc rests it", []*run.Object{museCardEvent("acme", "requested", museAsked...), museCardEvent("acme", "settled", "outcome", "interrupted")},
			hookfact.Fact{Event: "Interrupt", At: 2}, true},
		{"until its next prompt", []*run.Object{museCardEvent("acme", "requested", museAsked...), museCardEvent("acme", "settled", "outcome", "interrupted"),
			museEvent("kind", "started", "prompt", "Make it round.")}, hookfact.Fact{Event: "Stop", At: 2}, true},
		{"a time that is no whole number dates nothing", []*run.Object{
			run.Fields("payload", museCardEvent("acme", "requested", museAsked...).Get("payload"), "recorded_at", 1.5)}, hookfact.Fact{}, false},
	} {
		museLogs(t, "acme", each.entries...)
		if got, up := museCard("acme"); !reflect.DeepEqual(got, each.want) || up != each.up {
			t.Errorf("%s: %+v %v, want %+v %v", each.why, got, up, each.want, each.up)
		}
	}
	if _, up := museCard("other"); up {
		t.Error("a session with no log has a card")
	}
}

func with(fact hookfact.Fact, at float64) hookfact.Fact {
	fact.At = at
	return fact
}

func TestMuseSaidShowsARunsFirstFinalToItsPromptOrSteer(t *testing.T) {
	t.Setenv("XDG_DATA_HOME", t.TempDir())
	steer := museEvent("kind", "inbox_item_drained", "delivery_snapshot", run.Fields("source", run.Fields("source", "user_steer"), "body", "Make it green."))
	notice := museEvent("kind", "inbox_item_drained", "delivery_snapshot", run.Fields("source", run.Fields("source", "background"), "body", "A task ended."))
	museLogs(t, "acme",
		museEvent("kind", "started", "prompt", "Build the acme preview."),
		museEvent("kind", "assistant_message_committed", "phase", "commentary", "text", "Sending the notification."),
		museEvent("kind", "assistant_message_committed", "message_id", "first", "text", "Ready"),
		museEvent("kind", "reminder_reconciler_outcome", "outcome", "accepted"),
		museEvent("kind", "assistant_message_committed", "message_id", "later", "text", "Which colour?"),
		notice, steer,
		museEvent("kind", "assistant_message_committed", "text", "Green it is."),
		museRunOf("next-run", museEvent("kind", "assistant_message_committed", "text", "Another run's final.")),
		run.Fields("recorded_at", 1.5, "payload", museEvent("kind", "started", "prompt", "Undated.").Get("payload")))
	want := []Turn{{"user", "Build the acme preview."}, {"model", "Sending the notification."}, {"model", "Ready"},
		{"user", "Make it green."}, {"model", "Green it is."}, {"model", "Another run's final."}, {"user", "Undated."}}
	if got := museSaid("acme"); !slices.Equal(got, want) {
		t.Errorf("said %+v\nwant %+v", got, want)
	}
	typed := []Prompt{{1, "Build the acme preview."}, {7, "Make it green."}}
	if got, _ := museTyping("acme"); !slices.Equal(got, typed) {
		t.Errorf("typed %+v, want %+v (an undated line is nobody's answer)", got, typed)
	}
	if got := museSaid("other"); got != nil {
		t.Errorf("a session with no log says %+v", got)
	}
}
