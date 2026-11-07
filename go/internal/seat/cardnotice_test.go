package seat

import (
	"testing"
	"time"

	"agentkit/internal/history"
	"agentkit/internal/notify"
)

// A card answering the question the seat's notice asks, which the seat kept back again mid-turn,
// answers both, and the owner's time it took is the notice's alone: one answered row, from when the
// notice asked it.
func TestACardAnsweringTheNoticesQuestionCountsTheNoticesWait(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	write(t, stateFile(home, "notify-acme.json"), `{"session": "acme", "kind": "needs", "text": "Which port?", "time": 10,
		"asked_at": {"which port?": 10}, "question_times": {"which port?": 10}, "question_ids": {"which port?": null}}`)
	if err := Keep("acme", "Which port?"); err != nil {
		t.Fatal(err)
	}
	at := seconds(time.Now()) + 1
	if whole, err := answerCard("acme", at, [][]string{{"Which port?", "8080", "9090"}}); !whole || err != nil {
		t.Fatal(whole, err)
	}
	if Kept("acme") || notify.Last("acme") != nil {
		t.Fatal("the question stands")
	}
	db, err := history.Open()
	if err != nil || db == nil {
		t.Fatal(err)
	}
	defer db.Close()
	if rows, _ := db.Owner(0, at+1); len(rows) != 1 || rows[0]["kind"] != "answered" || rows[0]["waited"] != at-10 {
		t.Fatal(rows)
	}
}
