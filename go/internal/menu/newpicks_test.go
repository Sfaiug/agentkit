package menu

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"agentkit/internal/terminal"
)

func TestDraftReopeningPickerReplacesOrchestrator(t *testing.T) {
	for _, choices := range [][2]string{{"2", "1"}, {"beta", "alpha"}} {
		d := draftOf()
		for at, choice := range choices {
			d.Key(terminal.Key{Name: "tab"})
			for _, char := range choice {
				d.Key(terminal.Key{Name: "char", Char: string(char)})
			}
			d.Key(terminal.Key{Name: "esc"})
			want := []string{"beta", "alpha"}[at]
			if d.Orchestrator != want {
				t.Errorf("%v, choice %q: got %q, want %q", choices, choice, d.Orchestrator, want)
			}
		}
		if !reflect.DeepEqual(d.Workers, []string{"alpha", "beta"}) || !reflect.DeepEqual(d.Reviewers, d.Workers) {
			t.Fatalf("reopening changed the crew: %+v", d)
		}
	}
}

func TestDraftFallbackGroupsCanBeEditedIndependently(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	path := filepath.Join(home, ".agentkit", "config.toml")
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	text := `[defaults]
orchestrator = "alpha"
workers = ["removed"]
reviewers = ["removed"]
[models.alpha]
harness = "claude"
model = "default"
effort = "high"
provider = "test"
[providers.test]
mode = "subscription"
`
	if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
		t.Fatal(err)
	}
	d, err := NewDraft("rex", nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"tab", "right", "right", "space", "esc"} { // past the effort beside its orchestrator mark
		d.Key(terminal.Key{Name: key})
	}
	if len(d.Workers) != 0 || !reflect.DeepEqual(d.Reviewers, []string{"alpha"}) {
		t.Fatalf("unmarking builders changed reviewers: workers %v, reviewers %q", d.Workers, d.Reviewers)
	}
}
