package plan

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAPlanOwesItsOpenLinesAndIsDoneOnlyWithDoneWork(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("USERPROFILE", os.Getenv("HOME"))
	state := filepath.Join(os.Getenv("HOME"), ".agentkit", "state")
	if err := os.MkdirAll(state, 0o700); err != nil {
		t.Fatal(err)
	}
	where := " · ~/code/acme#0123456789ab · written 2026-10-20 09:00"
	for text, want := range map[string]string{
		"": "nothing",
		"Notes, and [docs](https://acme.example)\n- [docs](https://acme.example)\n": "nothing",
		"- [x] Merge the parser\n": "done",
		"- [x] z · check: `true`" + where + " · done 0123456789ab init\n- [ ] z · your eye" + where + "\n": "done",
		"- [x] Merge the parser\n- [ ] Ship it\n":                                                          "owed",
		"- [x] z · check: `true`" + where + "\n":                                                           "owed", // ticked by hand, nothing proved it
		"- [x] z · written by hand\n":                                                                      "owed",
		"* [x] Merge the parser · check: x\n":                                                              "owed",
		"- [ ] z · check: `true`" + where + " · deferred · written x\n":                                    "owed",
	} {
		if err := os.WriteFile(filepath.Join(state, "plan-acme.md"), []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
		done, err := DoneAt("acme")
		owes, _ := Owes("acme")
		if got := map[bool]string{true: "owed", false: map[bool]string{true: "nothing", false: "done"}[done.IsZero()]}[owes]; got != want {
			t.Errorf("%q: %s, want %s", text, got, want)
		}
		if err != nil && !strings.Contains(text, "deferred") {
			t.Errorf("%q: %v", text, err)
		}
	}
	os.Remove(filepath.Join(state, "plan-acme.md"))
	if done, err := DoneAt("acme"); !done.IsZero() || err != nil {
		t.Error("no plan holds nothing done")
	}
	if owes, err := Owes("acme"); owes || err != nil {
		t.Error("no plan owes nothing")
	}
}
