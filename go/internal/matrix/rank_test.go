package matrix

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"agentkit/internal/pick"
)

// budgets is a read where every model has room and the budget given.
type budgets map[string]float64

func (budgets) Spent(string) string                    { return "" }
func (b budgets) Budget(name string) (float64, string) { return b[name], "" }
func (budgets) OnCredits(string) bool                  { return false }
func (budgets) Pace(string) (float64, bool)            { return 0, true }

// lineupHome is a fresh home whose stored lineup holds rows, each release run by echo as
// echo-<name> at high effort and scored by scores (Values beside its index), and whose config
// offers names, so run, in that order on a subscription.
func lineupHome(t *testing.T, rows map[string]string, names ...string) {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	var lineup []string
	config := "companies = ['Acme']\n[providers.p]\nmode = 'subscription'\n"
	for _, name := range names {
		config += "[models." + name + "]\nharness = 'echo'\nmodel = 'echo-" + name + "'\neffort = 'high'\nprovider = 'p'\n"
		if scores, ok := rows[name]; ok {
			lineup = append(lineup, `{"release": "acme-`+name+`", "maker": "Acme", "effort": "high", "values": {"aa.intelligenceIndex": 50, `+
				scores+`}, "yours": [{"harness": "echo", "model": "echo-`+name+`"}]}`)
		}
	}
	for path, text := range map[string]string{
		filepath.Join("state", "matrix.json"): `{"matrix": {"lineup": [` + strings.Join(lineup, ", ") + `]}}`,
		"config.toml":                         config,
	} {
		path = filepath.Join(home, ".agentkit", path)
		if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
}

// Execute's pick of two rows is the cheaper, the better one only on the line between them, so it
// ranks first though it has the least budget left; a model no row is ranks last whatever its budget.
func TestAPickRanksByTheStoredLineup(t *testing.T) {
	lineupHome(t, map[string]string{
		"max": `"aa.frontierCode20": 0.6, "arena.agent": 0.6, "aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask": 2`,
		"mid": `"aa.frontierCode20": 0.4, "arena.agent": 0.4, "aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask": 1`,
	}, "max", "mid", "other")
	rules, ok := pick.Within([]string{"other", "max", "mid"}, nil)
	if !ok {
		t.Fatal("the pick is handed over")
	}
	want := []string{"mid", "max", "other"}
	if got := rules.Order(budgets{"other": 3, "max": 2, "mid": 1}, false, nil); !slices.Equal(got, want) {
		t.Fatalf("picked in the order %v, want %v", got, want)
	}
}

// one and two are twins at quality 100 and cost 2 but for their errors, 0.421 and 2.859 to review;
// cheap reviews at 98.4, error 0.421, cost 1, and has no execute row, wanting an arena score.  In
// config.toml's order one is each role's pick: execute's of the twins, review's as cheap is told
// apart from it.  Ranked with two first, as its budget would put it, two would be execute's pick,
// and cheap review's, as two's error cannot tell cheap from the best.  Budget orders only models
// ranked alike, so it changes neither.
func TestBudgetNeverChangesTheRolesPick(t *testing.T) {
	scores := func(code, ends, arena, cost string) string {
		return `"aa.frontierCode20": ` + code + `, ` + ends + arena + `"aa.omniscience": 50, "aa.omniscience.lower95ci": 49, ` +
			`"aa.omniscience.upper95ci": 51, "aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask": ` + cost
	}
	arena := `"arena.agent": 0.6, `
	lineupHome(t, map[string]string{
		"one":   scores("0.6", `"aa.frontierCode20.lower95ci": 0.59, "aa.frontierCode20.upper95ci": 0.61, `, arena, "2"),
		"two":   scores("0.6", `"aa.frontierCode20.lower95ci": 0.53, "aa.frontierCode20.upper95ci": 0.67, `, arena, "2"),
		"cheap": scores("0.58", `"aa.frontierCode20.lower95ci": 0.57, "aa.frontierCode20.upper95ci": 0.59, `, "", "1"),
	}, "one", "two", "cheap")
	rules, ok := pick.Within([]string{"one", "two", "cheap"}, nil)
	if !ok {
		t.Fatal("the pick is handed over")
	}
	want := []string{"one", "two", "cheap"}
	for _, review := range []bool{false, true} {
		for _, room := range []budgets{{"one": 1, "two": 1, "cheap": 1}, {"one": 1, "two": 3, "cheap": 2}} {
			if got := rules.Order(room, review, nil); !slices.Equal(got, want) {
				t.Errorf("review %v with budgets %v picked in the order %v, want %v", review, room, got, want)
			}
		}
	}
}
