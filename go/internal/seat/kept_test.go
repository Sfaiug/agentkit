package seat

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestAStopMarksTheQuestionsKeptBackForItsTurnEnded(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("USERPROFILE", os.Getenv("HOME"))
	state := filepath.Join(os.Getenv("HOME"), ".agentkit", "state")
	path := filepath.Join(state, "seat-acme.json")
	put := func(text string) {
		if err := os.MkdirAll(state, 0o700); err != nil || os.WriteFile(path, []byte(text), 0o600) != nil {
			t.Fatal(path)
		}
	}
	put(`{"word": "working"}`)
	if Kept("acme") || TurnEnded("acme") != nil {
		t.Fatal("a seat keeping nothing back is left as it is")
	}
	if data, _ := os.ReadFile(path); string(data) != `{"word": "working"}` {
		t.Fatalf("it wrote %s", data)
	}
	put(`{"word": "working", "unasked": {"text": "A? Also: B?", "questions": [{"text": "A?", "at": 5, "id": null}, ` +
		`{"text": "B?", "id": "toolu_1", "at": 6, "ended": 7}, {"at": 8}]}}`)
	if !Kept("acme") || TurnEnded("acme") != nil {
		t.Fatal("two questions kept back")
	}
	data, _ := run.ReadJSON(path)
	questions := data.Dict("unasked").List("questions")
	first, _ := questions[0].(*run.Object)
	second, _ := questions[1].(*run.Object)
	if ended, _ := first.Num("ended"); len(questions) != 2 || ended < 8 || !run.Equal(second.Get("ended"), run.Number("7")) ||
		data.Str("session") != "acme" || data.Dict("unasked").Str("text") != "A? Also: B?" {
		t.Fatalf("the turn's end is on each question once: %s", run.Line(data))
	}
	// an older install kept its one question as the whole record
	put(`{"unasked": {"text": "C?", "at": 3}}`)
	TurnEnded("acme")
	data, _ = run.ReadJSON(path)
	if questions := data.Dict("unasked").List("questions"); len(questions) != 1 || questions[0].(*run.Object).Str("text") != "C?" {
		t.Fatalf("its one question is kept: %s", run.Line(data))
	}
}
