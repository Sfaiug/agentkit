package menu

import (
	"reflect"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/matrix"
	"agentkit/internal/quality"
	"agentkit/internal/run"
)

// Acme Max at high is best, Bolt's one row names no effort, Dull runs only at its release's
// default and Crux is on no row: each one harness `h` runs as its id.
func TestEachRoleSaysTheRowItUses(t *testing.T) {
	t.Setenv("HOME", t.TempDir()) // harness `h` has no catalog: a model is named off its id
	var rows []quality.Row
	for _, one := range []struct {
		release, effort string
		value           float64
	}{{"acme", "high", .9}, {"acme", "low", .6}, {"bolt", "", .8}, {"dull", "medium", .7}} {
		row := modelRow(one.release, one.effort, true, one.value)
		row.Runners = [][2]string{{"h", one.release}}
		rows = append(rows, row)
	}
	answer := quality.Answer(rows, nil, nil)
	models := map[string]config.Model{
		"acme": {Harness: "h", ID: "acme", Efforts: map[string]string{"effort": "low", "exec_effort": "high"}},
		"bolt": {Harness: "h", ID: "bolt", Efforts: map[string]string{"effort": "high"}},
		"dull": {Harness: "h", ID: "dull", Efforts: map[string]string{"effort": "none"}},
		"crux": {Harness: "h", ID: "vendor/crux-9", Efforts: map[string]string{"effort": "high"}},
	}
	record := func(orchestrator string, workers, reviewers []any, efforts map[string]map[string]string) *run.Object {
		selected := run.NewObject()
		selected.Set("orchestrator", orchestrator)
		selected.Set("workers", workers)
		selected.Set("reviewers", reviewers)
		held := run.NewObject()
		for name, keys := range efforts {
			entry := run.NewObject()
			for key, effort := range keys {
				entry.Set(key, effort)
			}
			held.Set(name, entry)
		}
		selected.Set("efforts", held)
		return selected
	}
	// the role lines as drawn, one space between words, `▸` on the role at
	said := func(columns string, selected *run.Object, at int) []string {
		c := &matrix.Configuration{Models: models, Selected: selected}
		var lines []string
		for _, row := range roleLines(screenAt(t, columns), ModelsView{Answer: answer, Uses: c.Uses(answer), Models: models}, at) {
			lines = append(lines, strings.Join(strings.Fields(row.line), " "))
		}
		return lines
	}
	// New seats: Crux orchestrates, Bolt, the pick of the two, builds before Acme at high, and Acme
	// reviews at its effort, low.  Costs are the boards', measured by no run.
	newSeats := record("crux", []any{"acme", "bolt"}, []any{"acme"}, nil)
	want := []string{"▸ orchestrator Crux 9 high not on the boards", "quality a task",
		"executor bolt 90.0 ≈$80.00", "reviewer acme low 76.0 ≈$60.00"}
	if got := said("100", newSeats, 0); !reflect.DeepEqual(got, want) {
		t.Errorf("new seats:\n%q\nwant\n%q", got, want)
	}
	// A seat running Dull at none, its one row, and Acme at high but low to build; Acme at high
	// reviews before Bolt, no match for it there.
	seat := record("dull", []any{"acme"}, []any{"bolt", "acme"},
		map[string]map[string]string{"acme": {"effort": "high", "exec_effort": "low"}})
	want = []string{"quality a task", "▸ orchestrator dull medium 92.9 ≈$70.00",
		"executor acme low 70.0 ≈$60.00", "reviewer acme high 100.0 ≈$90.00"}
	if got := said("100", seat, 0); !reflect.DeepEqual(got, want) {
		t.Errorf("a seat:\n%q\nwant\n%q", got, want)
	}
	// ↑↓ move `▸` from role to role, held at the first and the last
	at := 0
	for _, step := range []struct{ by, on int }{{-1, 0}, {1, 1}, {1, 2}, {1, 2}, {-1, 1}} {
		at = RoleStep(at, step.by)
		lines := said("100", seat, at)
		if marked := lines[step.on+1]; !strings.HasPrefix(marked, "▸ ") || strings.Count(strings.Join(lines, "\n"), "▸") != 1 {
			t.Errorf("after %+d `▸` is not on role %d alone: %q", step.by, step.on, lines)
		}
	}
	// too narrow beside its word, each row goes under it, named in full with its effort, wrapped at
	// its words where it is wider still, what follows it staying on the word's line
	for columns, want := range map[string][]string{
		"24": {"▸ orchestrator not on the boards", "Crux 9 high", "quality a task",
			"executor 90.0 ≈$80.00", "bolt", "reviewer 76.0 ≈$60.00", "acme low"},
		"14": {"▸ orchestrator not on the boards", "Crux 9", "high", "quality a task",
			"executor 90.0 ≈$80.00", "bolt", "reviewer 76.0 ≈$60.00", "acme low"},
	} {
		if got := said(columns, newSeats, 0); !reflect.DeepEqual(got, want) {
			t.Errorf("on %s cells:\n%q\nwant\n%q", columns, got, want)
		}
	}
}

// A model too wide for its lines wraps at its spaces, then after a hyphen, then after a dot,
// never cut, a part with none of these left whole: Python's menu.columned.
func TestAModelWrapsAtItsWordsNeverCut(t *testing.T) {
	for _, one := range []struct {
		text string
		room int
		want []string
	}{
		{"Acme gpt-6.1-sol high", 8, []string{"Acme", "gpt-6.1-", "sol", "high"}},
		{"gpt-6.1-sol", 5, []string{"gpt-", "6.1-", "sol"}},
		{"gpt-6.10-sol", 3, []string{"gpt-", "6.", "10-", "sol"}},
		{"Acme Mid 5 high", 20, []string{"Acme Mid 5 high"}},
	} {
		if got := columned(one.text, one.room, " -."); !reflect.DeepEqual(got, one.want) {
			t.Errorf("%q in %d cells: %q, want %q", one.text, one.room, got, one.want)
		}
	}
}
