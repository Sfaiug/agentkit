package seat

import (
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

// login_refusals.owed of a run still going: the first login in the file's order holding two
// refusals or more with the run's name among them, every entry counted and only a string naming a
// run.  A file keeping nothing owes nothing, and what Go does not read hands over.
func TestALoginKeepsRefusingARunAsPythonCountsIt(t *testing.T) {
	home := sandbox(t)
	path, dir := stateFile(home, "login-refusals.json"), filepath.Join(home, ".agentkit", "runs", "r1")
	type owed struct {
		login string
		known bool
	}
	for text, want := range map[string]owed{
		`{"acme": ["r1", "r1"]}`: {"acme", true}, `{"acme": ["r1"]}`: {"", true},
		`{"acme": ["r2", "r3"], "shop": ["r1", 7]}`: {"shop", true}, `{"shop": ["r1", "r1"], "acme": ["r1", "r1"]}`: {"shop", true},
		`{"acme": [{"r1": 1}, ["r1"]]}`: {"", true}, `{"acme": ["r1", "r1"], "shop": "r1r1"}`: {"acme", true},
		`{"shop": "r1r1", "acme": ["r1", "r1"]}`: {"", false}, `{"acme": null}`: {"", false}, `{"\ud800": ["r1", "r1"]}`: {"", false},
		`[]`: {"", true}, `{`: {"", true},
	} {
		write(t, path, text)
		if login, known := Refusing(dir, run.Fields("state", "running")); (owed{login, known}) != want {
			t.Errorf("%s owes %q, %v", text, login, known)
		}
	}
	if login, known := Refusing("r1", run.Fields("state", "stopped")); login != "" || !known {
		t.Errorf("an ended run owes %q, %v", login, known)
	}
	os.Remove(path)
	if login, known := Refusing("r1", run.Fields("state", "running")); login != "" || !known {
		t.Errorf("no file owes %q, %v", login, known)
	}
}

// [1a] of a seat's runs a login keeps refusing, the oldest by its ending names the login and dates
// the word, one with none counting as 0 and the first winning a tie; a run that has ended owes none.
func TestTheOldestRunALoginKeepsRefusingNamesIt(t *testing.T) {
	home := sandbox(t)
	write(t, stateFile(home, "login-refusals.json"), `{"acme": ["r-new", "r-new"], "shop": ["r-old", "r-old"], "kit": ["r-tie", "r-tie", "r-done", "r-none"]}`)
	of := func(name string, fields ...any) ran {
		return ran{name: name, record: run.Fields(fields...), view: &runView{}}
	}
	done, newer := of("r-done", "state", "stopped", "finished_at", 1), of("r-new", "state", "running", "finished_at", 30)
	older, tie := of("r-old", "state", "waiting", "finished_at", 20), of("r-tie", "state", "waiting", "finished_at", 20)
	undated := of("r-none", "state", "running")
	for _, each := range []struct {
		mine   []ran
		reason string
		since  any
	}{
		{[]ran{done}, "", nil},
		{[]ran{done, newer, older, tie}, "shop login expired: open it and log in again", run.Number("20")},
		{[]ran{tie, older}, "kit login expired: open it and log in again", run.Number("20")},
		{[]ran{newer, undated}, "kit login expired: open it and log in again", nil},
	} {
		said, err := runOnALogin(climbing{mine: each.mine})
		switch {
		case err != nil:
			t.Fatal(err)
		case said == nil:
			if each.reason != "" {
				t.Errorf("%d runs say nothing", len(each.mine))
			}
		case said.word != "needs you" || said.reason != each.reason || said.since != each.since:
			t.Errorf("%d runs say %+v", len(each.mine), *said)
		}
	}
}
