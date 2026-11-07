package harness

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"agentkit/internal/run"
)

func TestMuseAnswersAreTheOwnersPicksOnCardsThatSettledAnswered(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("XDG_DATA_HOME", filepath.Join(home, "share"))
	token := strings.Repeat("a", 32)
	receipt := filepath.Join(home, ".agentkit", "state", "muse-launch-"+token)
	if err := os.MkdirAll(receipt, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(receipt, "session"), []byte("acme"), 0o600); err != nil {
		t.Fatal(err)
	}
	record := map[string]any{"muse_launch": token}
	layout := run.Fields("id", "layout", "question", "Which layout?", "options", []any{
		run.Fields("label", "Compact"), run.Fields("label", "Tabbed", "description", "One tab each.")})
	ask := func(prompt string, questions ...any) *run.Object {
		return museCardEvent(prompt, "requested", "tool_name", "request_user_input", "questions", questions)
	}
	pick := func(prompt string, answers ...any) *run.Object {
		return museCardEvent(prompt, "settled", "outcome", "answered", "answers", answers)
	}
	picked := func(id, label any) *run.Object { return run.Fields("id", id, "selected_label", label) }
	card := func(at float64, answer string) Card {
		return Card{at, "Which layout?", answer, []Choice{{"Compact", ""}, {"Tabbed", "One tab each."}}}
	}
	for _, each := range []struct {
		why     string
		entries []*run.Object
		want    []Card
	}{
		{"answered", []*run.Object{ask("acme", layout), pick("acme", picked("layout", "Tabbed"))}, []Card{card(2, "Tabbed")}},
		{"Esc's settling answers nothing", []*run.Object{ask("acme", layout),
			museCardEvent("acme", "settled", "outcome", "interrupted", "answers", []any{picked("layout", "Tabbed")})}, nil},
		{"a settling of another card answers nothing", []*run.Object{ask("acme", layout), pick("other", picked("layout", "Tabbed"))}, nil},
		{"another tool's card asks nothing", []*run.Object{
			museCardEvent("acme", "requested", "tool_name", "other", "questions", []any{layout}), pick("acme", picked("layout", "Tabbed"))}, nil},
		{"a settling dated otherwise answers nothing", []*run.Object{ask("acme", layout),
			run.Fields("payload", pick("acme", picked("layout", "Tabbed")).Get("payload"), "recorded_at", 1.5)}, nil},
		{"an answer to a question not asked voids its card's", []*run.Object{
			ask("acme", layout), pick("acme", picked("layout", "Tabbed"), picked("colour", "Blue"))}, nil},
		{"a question with no text id is passed over", []*run.Object{
			ask("acme", run.Fields("id", 1, "question", "Which colour?"), layout), pick("acme", picked("layout", "Compact"))}, []Card{card(2, "Compact")}},
		{"a question with a text id and no options asks nothing", []*run.Object{
			ask("acme", run.Fields("id", "colour", "question", "Which colour?"), layout), pick("acme", picked("layout", "Compact"))}, nil},
		{"a pick that is no text or blank is no answer, and leaves the card's others", []*run.Object{
			ask("acme", layout, run.Fields("id", "size", "question", "Which layout?", "options", layout.Get("options")),
				run.Fields("id", "font", "question", "Which layout?", "options", layout.Get("options"))),
			pick("acme", picked("size", 2), picked("font", " "), picked("layout", "Tabbed"))}, []Card{card(2, "Tabbed")}},
		{"a choice that is not all text leaves its answer out", []*run.Object{
			ask("acme", run.Fields("id", "layout", "question", "Which layout?", "options", []any{run.Fields("label", "Compact", "description", nil)})),
			pick("acme", picked("layout", "Compact"))}, nil},
	} {
		museLogs(t, "acme", append(each.entries, museEvent("kind", "started", "prompt", "Lay out acme."))...)
		said, cards, known, err := Answered("muse", record)
		if !known || err != nil || !reflect.DeepEqual(cards, each.want) || !reflect.DeepEqual(said, []Turn{{"user", "Lay out acme."}}) {
			t.Errorf("%s: %v %v %+v %+v, want %+v", each.why, known, err, said, cards, each.want)
		}
	}
	// a file among the folders hides no log; a log, or a folder that may hold it, that cannot be
	// read is the done check's error, never an owner who said nothing
	sessions := filepath.Join(home, "share", "muse", "sessions")
	log := filepath.Join(sessions, "2026", "10", "26", "acme", "session.jsonl")
	for _, stray := range []string{filepath.Join(sessions, ".DS_Store"), filepath.Join(sessions, "2026", "10", "26", "notes")} {
		if err := os.WriteFile(stray, nil, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	if said, _, _, err := Answered("muse", record); err != nil || len(said) != 1 {
		t.Errorf("a stray file: %+v %v", said, err)
	}
	for _, hidden := range []string{log, filepath.Dir(log), filepath.Dir(filepath.Dir(log)), sessions} {
		if err := os.Chmod(hidden, 0); err != nil {
			t.Fatal(err)
		}
		_, readable := os.ReadFile(log)
		_, _, _, err := Answered("muse", record)
		if err := os.Chmod(hidden, 0o700); err != nil {
			t.Fatal(err)
		}
		if readable != nil && err == nil { // where permissions hide nothing, there is nothing to test
			t.Errorf("%s unreadable: no error", hidden)
		}
	}
	if err := os.Remove(log); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(log, 0o700); err != nil {
		t.Fatal(err)
	}
	if _, _, _, err := Answered("muse", record); err == nil {
		t.Error("a log that cannot be read holds nothing")
	}
}
