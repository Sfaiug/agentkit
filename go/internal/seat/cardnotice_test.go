package seat

import (
	"strings"
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

// A card answering one of the notice's questions while another names a file by a byte no UTF-8
// holds answers only its own: the other stands as Python wrote it, and the owner's time is still the
// notice's, from when it asked.
func TestACardAnswerLeavesTheNoticesFilenameQuestionAsWritten(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", nil)
	notice := stateFile(home, "notify-acme.json")
	write(t, notice, `{"session": "acme", "kind": "needs", "text": "Which port? Also: Which path /tmp/caf\udcff?", "time": 10,
		"questions": ["Which port?", "Which path /tmp/caf\udcff?"], "asked_at": {"which port?": 10}}`)
	if err := Keep("acme", "Which port?"); err != nil {
		t.Fatal(err)
	}
	at := seconds(time.Now()) + 1
	if whole, err := answerCard("acme", at, [][]string{{"Which port?", "8080", "9090"}}); whole || err != nil {
		t.Fatal(whole, err)
	}
	if said := contents(t, notice); Kept("acme") || !strings.Contains(said, `"text": "Which path /tmp/caf\udcff?"`) {
		t.Fatal(said)
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
