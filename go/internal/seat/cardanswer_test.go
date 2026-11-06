package seat

import (
	"errors"
	"os"
	"testing"
	"time"

	"agentkit/internal/history"
	"agentkit/internal/run"
)

// The owner's answer on a card is Python's, with nothing written, while a notice stands, while a
// question it leaves waits to be asked of a turn since ended, or while history cannot take its
// rows or the seat's file its questions' leaving; otherwise each question it answers is the
// owner's time, once, and leaves what the seat keeps back, which keeps the rest.
func TestACardsAnswerIsTheOwnersTimeOrPythons(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	for _, text := range []string{"Which port?", "Which branch?", "Which port?"} {
		if err := Keep("acme", text); err != nil {
			t.Fatal(err)
		}
	}
	at := seconds(time.Now()) + 1
	replies := [][]string{{"Which port?", "8080", "9090"}}
	kept := contents(t, seatFile("acme"))
	owned := func() []history.Row {
		t.Helper()
		db, err := history.Open()
		if err != nil || db == nil {
			return nil
		}
		defer db.Close()
		rows, _ := db.Owner(0, at+1)
		return rows
	}
	pythons := func(why string) {
		t.Helper()
		if err := answerCard("acme", at, replies); !errors.Is(err, errPython) {
			t.Fatalf("%s: %v", why, err)
		}
		if contents(t, seatFile("acme")) != kept || len(owned()) > 0 {
			t.Fatalf("%s: written", why)
		}
	}
	write(t, stateFile(home, "notify-acme.json"), `{"session": "acme", "kind": "needs", "text": "Older?", "time": 1}`)
	pythons("a notice")
	os.Remove(stateFile(home, "notify-acme.json"))
	if err := TurnEnded("acme"); err != nil {
		t.Fatal(err)
	}
	open := kept
	kept = contents(t, seatFile("acme"))
	pythons("a turn ended") // which asks the copy of the words it leaves
	kept = open
	write(t, seatFile("acme"), kept)
	write(t, history.Path(), "not a database")
	pythons("history")
	os.Remove(history.Path())
	state := stateFile(home, "")
	t.Cleanup(func() { os.Chmod(state, 0o700) })
	os.Chmod(state, 0o500)
	pythons("a seat file")
	os.Chmod(state, 0o700)

	if err := answerCard("acme", at, replies); err != nil {
		t.Fatal(err)
	}
	file, _ := run.ReadJSON(seatFile("acme"))
	if left := questionsKept(file.Dict("unasked"), nil); len(left) != 1 || left[0].Str("text") != "Which branch?" {
		t.Fatal(run.Line(file))
	}
	rows := owned()
	if len(rows) != 2 || rows[0]["kind"] != "asked" || rows[1]["kind"] != "answered" || rows[0]["waited"] != nil {
		t.Fatal(rows)
	}
	if asked, waited := rows[0]["at"].(float64), rows[1]["waited"].(float64); asked >= at || waited != at-asked {
		t.Fatal(rows)
	}
}
