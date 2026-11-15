package harness

import (
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strconv"
	"testing"
)

// agyCardStep is an `ask_question` card's step (step_type, metadata, step_payload) as
// tests/test_key_card_answers_antigravity.py writes one: answered at `at` with the id of the
// choice `picked`, the words `written`, or neither (0, ""), as Esc leaves it.  A choice labelled ""
// has no label.
func agyCardStep(question string, labels []string, at float64, picked int, written string) [3]any {
	shown := agyNested(1, []byte(question))
	for n, label := range labels {
		choice := agyNested(1, []byte(strconv.Itoa(n+1)))
		if label != "" {
			choice = append(choice, agyNested(2, []byte(label))...)
		}
		shown = append(shown, agyNested(2, choice)...)
	}
	answered := shown
	if picked != 0 {
		answered = append(slices.Clone(answered), agyNested(4, []byte(strconv.Itoa(picked)))...)
	}
	if written != "" {
		answered = append(slices.Clone(answered), agyNested(5, []byte(written))...)
	}
	payload := slices.Concat(agyVarintOf(1<<3), agyVarintOf(132),
		agyNested(147, slices.Concat(agyNested(1, agyNested(22, agyNested(1, shown))), agyNested(2, agyNested(22, agyNested(1, answered))))))
	return [3]any{132, slices.Concat(agyStamp(1, at-60), agyStamp(8, at)), payload}
}

func TestAntigravityOwnerWordsAreReadStrictly(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	path := filepath.Join(home, ".gemini", "antigravity-cli", "conversations", "conv-acme.db")
	user := func(text string) []byte { return agyNested(19, agyNested(2, []byte(text))) }
	model := func(text string) []byte { return agyNested(20, agyNested(1, []byte(text))) }
	colours := []string{"Red", "Blue"}
	agySteps(t, path, [][3]any{
		{14, agyStamp(1, 1_800_000_000), user("Build the acme banner.")},
		{15, agyStamp(1, 1_800_000_001), model("Which colour?")},
		agyCardStep("Which colour should the acme banner be?", colours, 1_800_000_060.25, 2, ""),
		agyCardStep("Which font should it use?", nil, 1_800_000_120.25, 0, "Sans, bold"),
		agyCardStep("Which size should it be?", colours, 1_800_000_180, 0, ""),         // skipped
		agyCardStep("Which border should it have?", colours, 1_800_000_240, 3, "Thin"), // a pick of no choice
		agyCardStep("Which shadow should it cast?", colours, 1_800_000_300, 1, "soft"),
		agyCardStep("Which margin should it keep?", colours, 1_800_000_360, 0, " \t"),           // blank
		agyCardStep("Which corner should it round?", []string{"Top", ""}, 1_800_000_420, 1, ""), // a choice with no label
	})
	choices := []Choice{{"Red", ""}, {"Blue", ""}}
	want := []Card{{1_800_000_060.25, "Which colour should the acme banner be?", "Blue", choices},
		{1_800_000_120.25, "Which font should it use?", "Sans, bold", nil},
		{1_800_000_240, "Which border should it have?", "Thin", choices},
		{1_800_000_300, "Which shadow should it cast?", "Red\nsoft", choices}}
	// the launcher's conversation, one its agy took a prompt in after /clear, beside what its launch
	// learned before, or one the seat left
	followed := map[string]any{"conversation": "conv-acme", "id_source": "antigravity-hook",
		"antigravity_launch": "token", "antigravity_open": map[string]any{"launch": "token", "conversation": "conv-old"}}
	for _, record := range []map[string]any{{"conversation": "conv-acme", "id_source": "launcher"}, followed,
		{"harness": "antigravity", "conversation": "conv-acme"}} {
		said, cards, err := Answered("antigravity", record)
		if err != nil || !slices.Equal(said, []Turn{{"user", "Build the acme banner."}, {"model", "Which colour?"}}) || !reflect.DeepEqual(cards, want) {
			t.Fatalf("read %v %#v %v", said, cards, err)
		}
	}
	if conversation, typed, _, err := Typed("antigravity", followed, ""); conversation != "conv-acme" || len(typed) != 1 || err != nil {
		t.Fatalf("typed %q %v %v", conversation, typed, err)
	}
	if !Reads("antigravity", true) {
		t.Fatal("Go reads an Antigravity seat's owner words otherwise than Python's done check")
	}
	// a store that is there and cannot be read is an error, never an owner who said nothing
	for name, write := range map[string]func() error{
		"not SQLite":     func() error { return os.WriteFile(path, []byte("not a SQLite database"), 0o600) },
		"no steps table": func() error { return os.WriteFile(path, nil, 0o600) },
	} {
		if err := os.Remove(path); err != nil {
			t.Fatal(err)
		}
		if err := write(); err != nil {
			t.Fatal(err)
		}
		if _, _, err := Answered("antigravity", map[string]any{"conversation": "conv-acme", "id_source": "launcher"}); err == nil {
			t.Fatalf("%s: read", name)
		}
		if _, _, known, err := Typed("antigravity", map[string]any{"conversation": "conv-acme", "id_source": "launcher"}, ""); !known || err == nil {
			t.Fatalf("%s: typed %v %v", name, known, err)
		}
	}
	// one that is gone holds none
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if said, cards, err := Answered("antigravity", map[string]any{"conversation": "conv-acme", "id_source": "launcher"}); said != nil || cards != nil || err != nil {
		t.Fatalf("read a store that is gone: %v %v %v", said, cards, err)
	}
	// a launch whose conversation is learned under a lock that cannot be taken: a folder in its
	// place, or a link to itself
	claim := filepath.Join(home, ".agentkit", "state", "antigravity-claim.lock")
	unclaimed := func(why string) {
		t.Helper()
		if _, _, err := Answered("antigravity", map[string]any{"antigravity_launch": "token"}); err == nil {
			t.Fatalf("%s: read", why)
		}
		if _, _, known, err := Typed("antigravity", map[string]any{"antigravity_launch": "token"}, ""); !known || err == nil {
			t.Fatalf("%s: typed %v %v", why, known, err)
		}
	}
	if err := os.MkdirAll(claim, 0o700); err != nil {
		t.Fatal(err)
	}
	unclaimed("a folder")
	if err := os.Remove(claim); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("antigravity-claim.lock", claim); err != nil {
		t.Skip(err)
	}
	unclaimed("a link to itself")
}
