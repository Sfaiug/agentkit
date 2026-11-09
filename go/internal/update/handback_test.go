package update

import (
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"agentkit/internal/run"
)

// Each red's line owed is told once, harnesses by name and then the fresh-install gate; a seat Go
// does not wake hands over at its record, unchanged, the records told before it staying told.
func TestEachOwedRedIsToldOnceAndASeatGoDoesNotWakeHandsOverAtItsRecord(t *testing.T) {
	home, _ := sandbox(t)
	state := filepath.Join(home, ".agentkit", "state")
	records := map[string]string{
		"harness-gates/beta":  `{"reds": 2, "line": "beta's line", "typed": null, "told": false}`,
		"harness-gates/alpha": `{"reds": 2, "line": "alpha's line", "typed": null, "told": false}`,
		"harness-gates/gamma": `{"reds": 1}`,
		"harness-gates/delta": `{"reds": 2, "line": "delta's line", "typed": null, "told": true}`,
		"fresh-gate-faults":   `{"sets": [["c"]], "typed": null, "told": false, "line": "fresh line"}`,
	}
	for dir, record := range records {
		if err := os.MkdirAll(filepath.Join(state, dir), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(state, dir, "handed"), []byte(record), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	read := func(dir string) string {
		data, _ := os.ReadFile(filepath.Join(state, dir, "handed"))
		return string(data)
	}
	var lines, said []string
	left := errors.New("left to Python")
	deliver := func(_, line string, typed *run.Object, receipt func(*run.Object) error) (string, error) {
		lines = append(lines, line)
		if line == "beta's line" {
			return "", left
		}
		return "acme", receipt(run.Fields("seat", 7, "line", line))
	}
	err := handBack(deliver, func(line string) { said = append(said, line) })
	if want := []string{"alpha's line", "beta's line"}; !errors.Is(err, left) || !reflect.DeepEqual(lines, want) ||
		read("harness-gates/alpha") != `{"reds": 2, "line": "alpha's line", "typed": {"seat": 7, "line": "alpha's line"}, "told": true}` ||
		read("harness-gates/beta") != records["harness-gates/beta"] ||
		!reflect.DeepEqual(said, []string{"handed alpha's failed harness upgrade back to fix"}) {
		t.Fatalf("gave %v, delivered %q, said %q, alpha %s, beta %s", err, lines, said, read("harness-gates/alpha"), read("harness-gates/beta"))
	}
	lines, said = nil, nil
	deliver = func(_, line string, typed *run.Object, receipt func(*run.Object) error) (string, error) {
		lines = append(lines, line)
		return "acme", nil
	}
	err = handBack(deliver, func(line string) { said = append(said, line) })
	if want := []string{"beta's line", "fresh line"}; err != nil || !reflect.DeepEqual(lines, want) ||
		!reflect.DeepEqual(said, []string{"handed beta's failed harness upgrade back to fix",
			"handed the fresh-install gate's standing faults back to fix"}) ||
		read("fresh-gate-faults") != `{"sets": [["c"]], "typed": null, "told": true, "line": "fresh line"}` {
		t.Fatalf("gave %v, delivered %q, said %q, fresh %s", err, lines, said, read("fresh-gate-faults"))
	}
}

// A mark that cannot be kept is an error, though the delivery answers it as a seat mid-turn.
func TestAMarkNotKeptIsAnError(t *testing.T) {
	home, _ := sandbox(t)
	check := filepath.Join(home, ".agentkit", "state", "fresh-gate-faults")
	if err := os.MkdirAll(filepath.Join(check, "handed.tmp"), 0o700); err != nil { // put writes through it
		t.Fatal(err)
	}
	record := `{"sets": [["c"]], "typed": null, "told": false, "line": "fresh line"}`
	if err := os.WriteFile(filepath.Join(check, "handed"), []byte(record), 0o600); err != nil {
		t.Fatal(err)
	}
	err := handBack(func(_, _ string, _ *run.Object, receipt func(*run.Object) error) (string, error) {
		receipt(run.Fields("seat", 7))
		return "", nil
	}, func(line string) { t.Errorf("said %q", line) })
	if data, _ := os.ReadFile(filepath.Join(check, "handed")); err == nil || string(data) != record {
		t.Fatalf("gave %v, left %s", err, data)
	}
}
