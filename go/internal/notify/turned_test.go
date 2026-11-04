package notify

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func TestTurnedCardsANewWordFromWhenItBegan(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	if err := os.MkdirAll(state(), 0o700); err != nil {
		t.Fatal(err)
	}
	said := func(word string, since any) func(string) (string, any) {
		return func(string) (string, any) { return word, since }
	}
	card := func() *run.Object {
		read, err := run.ReadJSON(filepath.Join(state(), "card-acme.json"))
		if err != nil {
			t.Fatal(err)
		}
		return read
	}
	turned := func(word string, since any) error {
		carried, err := Turned("acme", said(word, since))
		if !carried && err == nil {
			t.Fatalf("%s was left", word)
		}
		return err
	}
	if err := turned("idle", run.Number("1000")); err != nil {
		t.Fatal(err)
	}
	first := card()
	if first.Get("word") != "idle" || first.Get("since") != run.Number("1000") || first.Get("began") != run.Number("1000") ||
		first.Get("sent") != false || len(first.Str("episode")) != 32 {
		t.Fatalf("a first card: %s", run.Line(first))
	}
	if err := turned("idle", run.Number("2000")); err != nil || card().Str("episode") != first.Str("episode") {
		t.Fatalf("the same word keeps its episode: %v, %s", err, run.Line(card()))
	}
	if err := turned("working", run.Number("3000")); err != nil || card().Get("since") != run.Number("3000") {
		t.Fatalf("a word begun after the card is carded from then: %v, %s", err, run.Line(card()))
	}
	// the seat file's word began before the card's: the card is the newer, and its word is over now
	if err := turned("idle", run.Number("2500")); err != nil {
		t.Fatal(err)
	}
	if since, _ := card().Num("since"); card().Get("word") != "idle" || since < 3000 {
		t.Fatalf("a word read older than the card begins now: %s", run.Line(card()))
	}
	before := run.Line(card())
	for _, word := range []string{"needs you", "done", ""} {
		if carried, err := Turned("acme", said(word, run.Number("4000"))); carried || err != nil || run.Line(card()) != before {
			t.Fatalf("%q, a word a card goes out for or none, is left: %v %v, %s", word, carried, err, run.Line(card()))
		}
	}
	// a card that went out for a word is closed by Python's transition, whatever the word now
	if err := os.WriteFile(filepath.Join(state(), "card-acme.json"), []byte(`{"word": "needs you"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if carried, err := Turned("acme", said("idle", run.Number("4000"))); carried || err != nil {
		t.Fatalf("a needs card was carried: %v %v", carried, err)
	}
}
