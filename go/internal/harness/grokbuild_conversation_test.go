package harness

import (
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"testing"
)

// grokSeat is a Grok Build seat's record on a checkout whose name holds a space, its session's
// updates.jsonl testdata/grok-updates.jsonl under GROK_HOME's sessions, or ~/.grok's where it is
// "".  The session folder is the record's.
func grokSeat(t *testing.T, grokHome string) (record map[string]any, updates string) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("GROK_HOME", grokHome)
	data, err := os.ReadFile(filepath.Join("testdata", "grok-updates.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	updates = filepath.Join(home, ".grok", "sessions", "%2Fcode%2Facme%20banner", "conv-acme", "updates.jsonl")
	if grokHome != "" {
		updates = filepath.Join(grokHome, "sessions", "%2Fcode%2Facme%20banner", "conv-acme", "updates.jsonl")
	}
	if os.MkdirAll(filepath.Dir(updates), 0o700) != nil || os.WriteFile(updates, data, 0o600) != nil {
		t.Fatal(updates)
	}
	return map[string]any{"conversation": "conv-acme", "cwd": "/code/acme banner", "id_source": "grokbuild-hook"}, updates
}

// The conversation a Grok Build seat's record names, whatever vouched for it, reads as
// grokbuild.py reads it from its session's updates.jsonl: what each case of the testdata gives
// here is what Python's `messages` and `answers` gave for that very file, kept as Harness.answers
// keeps them.  A prompt's chunks join, past a shell command, a chunk with no time or words and
// a picture; any other line ends a message, and each interjection is one of its own.  A card is
// read only with what it offered, "Other" alone is no answer, a description that is not text
// drops its question and a label that is not text its card, and only a dated `completed` update
// settles a card.
func TestAGrokConversationReadsAsGrokbuildPyReadsIt(t *testing.T) {
	for _, grokHome := range []string{"", filepath.Join(t.TempDir(), "grok-acme")} {
		record, _ := grokSeat(t, grokHome)
		conversation, typed, known, err := Typed("grokbuild", record, "")
		if want := []Prompt{{100, "Build the acme banner."}, {104, "Red, please."}, {107, "Stop."}, {108, "Wait."}, {111, "Go "}, {113, "on."}}; conversation != "conv-acme" ||
			!slices.Equal(typed, want) || !known || err != nil {
			t.Fatalf("typed %q %v %v %v", conversation, typed, known, err)
		}
		turns, cards, err := Answered("grokbuild", record)
		if want := []Turn{{"user", "Build the acme banner."}, {"model", "Which colour?"}, {"user", "Red, please."}, {"user", "Stop."},
			{"user", "Wait."}, {"user", "Go "}, {"user", "on."}}; !slices.Equal(turns, want) || err != nil {
			t.Fatalf("said %q %v", turns, err)
		}
		offered := func(labels ...string) (choices []Choice) {
			for _, label := range labels {
				choices = append(choices, Choice{label, label + " for acme"})
			}
			return choices
		}
		want := []Card{{201, "Q1", "typed beside Other", offered("Other", "B")}, {201, "Q2", "X\nn", offered("X")}, {201, "Q3", "only typed", nil},
			{211, "Q1", "X\nn, \"Q2\"=\"Z\"", offered("X")}, {231, "Q1", "X", offered("X")}, {231, "Q2", "Y", []Choice{{"Y", ""}}},
			{241, "Q1", "X", offered("X")}, {261, "Q1", "A, B, A\ntwo\nlines", offered("A, B", "A", "B")}, {283, "Q1", "X", offered("X")}}
		if !reflect.DeepEqual(cards, want) {
			t.Fatalf("answered %+v", cards)
		}
		if !Reads("grokbuild", true) {
			t.Fatal("Go reads a Grok Build seat's owner words less strictly than its done check")
		}
	}
}

// A Grok Build session whose updates.jsonl is there and cannot be read is an error to the done
// check's reads, never an owner who said nothing; one that is gone holds nothing.
func TestAnUnreadableGrokSessionIsAnError(t *testing.T) {
	record, updates := grokSeat(t, "")
	if os.Remove(updates) != nil || os.Mkdir(updates, 0o700) != nil {
		t.Fatal(updates)
	}
	if _, _, _, err := Typed("grokbuild", record, ""); err == nil {
		t.Error("an unreadable session's messages read as none")
	}
	if _, _, err := Answered("grokbuild", record); err == nil {
		t.Error("an unreadable session's answers read as none")
	}
	if os.Remove(updates) != nil {
		t.Fatal(updates)
	}
	if _, typed, known, err := Typed("grokbuild", record, ""); typed != nil || !known || err != nil {
		t.Errorf("a gone session typed %v %v %v", typed, known, err)
	}
	if turns, cards, err := Answered("grokbuild", record); turns != nil || cards != nil || err != nil {
		t.Errorf("a gone session said %v %v %v", turns, cards, err)
	}
}
