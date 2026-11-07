//go:build unix

package notify

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// A card answers only the questions of the seat's notice it names, each said before its answer and
// on no card of its own, unless kept back since under one naming none: the rest stand, the notice
// rewritten without the answered, each of those the owner's time once; heard again it answers
// nothing more, and once it names all that is left the notice is answered whole.
func TestACardAnswersOnlyTheNoticesQuestionsItNames(t *testing.T) {
	_, write := questionHome(t)
	port, branch, scope := "Which port? Options: 8080, 9090.", "Which branch?", "Which scope?"
	asked := []string{port, branch, scope}
	dates := run.Fields(questionKey(port), 10, questionKey(branch), 20, questionKey(scope), 30)
	write(seatFile("notify", "acme", "json"), run.Line(run.Fields("session", "acme", "kind", "needs",
		"text", strings.Join(asked, also), "time", 30, "questions", []any{port, branch, scope},
		"asked_at", dates, "question_times", dates, "question_ids", run.Fields(questionKey(scope), "toolu_scope"))))
	names := func(named ...string) func(string) bool {
		return func(question string) bool { return slices.Contains(named, question) }
	}
	answer := func(at float64, renewed map[string]any, named ...string) bool {
		t.Helper()
		whole, err := CardAnswered("acme", at, renewed, names(named...), "claude:conv-acme")
		if err != nil {
			t.Fatal(err)
		}
		return whole
	}
	waits := func() (waited []float64) {
		t.Helper()
		db, err := history.Open()
		if err != nil || db == nil {
			return nil
		}
		defer db.Close()
		rows, _ := db.Owner(0, 100)
		for _, row := range rows {
			waited = append(waited, row["waited"].(float64))
		}
		return waited
	}

	// the port, heard again, and the branch at a moment before it was asked
	if answer(40, nil, port, scope) || answer(40, nil, port, scope) || answer(15, nil, branch) {
		t.Fatal("answered whole")
	}
	notice := Last("acme")
	if notice == nil || !slices.Equal(questions(notice), []string{branch, scope}) || notice.Str("text") != branch+also+scope ||
		notice.Dict("asked_at").Has(questionKey(port)) || notice.Dict("question_times").Has(questionKey(port)) {
		t.Fatal(run.Line(notice))
	}
	if got := waits(); !slices.Equal(got, []float64{30}) {
		t.Fatal(got)
	}
	if !answer(50, map[string]any{questionKey(scope): nil}, branch, scope) || Last("acme") != nil {
		t.Fatal("the notice stands")
	}
	if got := waits(); !slices.Equal(got, []float64{30, 30, 20}) {
		t.Fatal(got)
	}
}

// A card's answer is Go's only where Go reads as Python does all it goes on to read: none of a
// question's retirements waits for Python's notice lock to carry it out, and neither the notice nor
// the page its needs you card put out holds what Go cannot keep.
func TestACardIsAnsweredOnlyWhereGoReadsAllItGoesOnToRead(t *testing.T) {
	_, write := questionHome(t)
	notice, page := seatFile("notify", "acme", "json"), filepath.Join(outbox(), cardKey("acme-episode")+".json")
	write(notice, `{"session":"acme","kind":"needs","text":"Which port?","time":10}`)
	write(seatFile("card", "acme", "json"), `{"word":"needs you","since":10,"episode":"acme-episode"}`)
	write(page, `{"status":"pending"}`)
	if !CardAnswerable("acme") {
		t.Fatal("refused what Go reads")
	}
	for _, unkept := range [][2]string{
		{notice, `{"session":"acme","kind":"needs","text":"Which path /tmp/caf\udcff?","time":10}`},
		{page, `{"status":"pending","payload":"/tmp/caf\udcff"}`},
		{filepath.Join(outbox(), "stuck.clear"), `{"session":"acme","prefix":"Which"}`},
	} {
		kept, err := os.ReadFile(unkept[0])
		write(unkept[0], unkept[1])
		if CardAnswerable("acme") {
			t.Errorf("answered over %s", filepath.Base(unkept[0]))
		}
		if err == nil {
			write(unkept[0], string(kept))
		}
	}
}
