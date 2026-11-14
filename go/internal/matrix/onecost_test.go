package matrix

import (
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/ncruces/go-sqlite3"

	"agentkit/internal/pick"
)

// Pa and Qb rate alike, each run on a provider of its own, whose $100 week its seat's spend at $1 a
// million tokens fits.  One run of each built at high, Pa's taking 0.2 points of its week for its
// row's $2 a task on the boards and Qb's 2 points for $1.  No run reviewed, yet a review costs Pa
// 0.2 points and Qb 2 off those builds, so Pa is review's pick, though the boards price Qb's review
// at half Pa's and Qb has the more budget left.
func TestAPickOverAMeasuredLineupRanksInOneUnit(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	ak := filepath.Join(home, ".agentkit")
	number := func(value float64) string { return strconv.FormatFloat(value, 'f', -1, 64) }
	now, day := float64(time.Now().Unix()), 86400.0
	config := ""
	var lineup, board, meters []string
	history := "CREATE TABLE runs (run_id, executor, executor_effort, reviewer, kind, finished_at, counted_turns);" +
		"CREATE TABLE reviews (run_id, review_id, effort);" +
		"CREATE TABLE turn_usage (turn, run_id, role, account, model, began, at, input, cache_write, cache_read, output);" +
		"CREATE TABLE seat_usage (event, at, tokens, account, model, input, cache_write, cache_read, output);" +
		"CREATE TABLE meter_readings (provider, account, meter, used, resets_at, window_secs, at, source, plan);"
	for _, one := range []struct {
		name, provider string
		dollars, built float64 // its row's board dollars a task, and the tokens its build took
	}{{"pa", "p", 2, 0.2e6}, {"qb", "q", 1, 2e6}} {
		model, harness, turn := one.name+"-1", "h"+one.provider, "runs/fix-"+one.name+"/round-1/executor"
		config += "[providers." + one.provider + "]\nmode = 'subscription'\n[models." + one.name + "]\nharness = '" + harness +
			"'\nmodel = '" + model + "'\neffort = 'high'\nprovider = '" + one.provider + "'\n"
		lineup = append(lineup, `{"release": "`+model+`", "maker": "Acme", "effort": "high", "values": {"aa.intelligenceIndex": 50, `+
			`"aa.frontierCode20": 0.6, "arena.agent": 0.6, "aa.omniscience": 50, `+
			`"aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask": `+number(one.dollars)+`}, `+
			`"yours": [{"harness": "`+harness+`", "model": "`+model+`"}]}`)
		board = append(board, `{"model": "`+model+`", "effort": "high", "slug": "`+model+`", "maker": "Acme", "deprecated": false, `+
			`"values": {"aa.intelligenceIndex": 50, "aa.price1mInputTokens": 1, "aa.price1mOutputTokens": 1}, `+
			`"release": {"slug": "`+model+`", "name": "`+model+`", "deprecatedTo": null}}`)
		meters = append(meters, `"`+one.provider+`": {"meters": [{"name": "weekly", "used": 40, "window_secs": 604800, "resets_at": `+
			number(now+day)+`}]}`)
		// the week rose 50 points as its seat spent $50, and the build took one.built tokens a day ago
		for _, reading := range [][2]float64{{10, 3 * day}, {60, 2 * day}} {
			history += "INSERT INTO meter_readings VALUES ('" + one.provider + "', 'default', 'weekly', " + number(reading[0]) + ", " +
				number(now+3*day) + ", 604800, " + number(now-reading[1]) + ", 'probe', NULL);"
		}
		history += "INSERT INTO seat_usage VALUES ('" + harness + ":seat', " + number(now-2.5*day) + ", 50000000, 'default', '" +
			model + "', 50000000, 0, 0, 0);" +
			"INSERT INTO runs VALUES ('fix-" + one.name + "', '" + one.name + "', 'high', NULL, 'task', " + number(now-day) +
			`, '["` + turn + `"]');` +
			"INSERT INTO turn_usage VALUES ('" + turn + "', 'fix-" + one.name + "', 'executor', 'default', '" + model + "', " +
			number(now-day) + ", " + number(now-day) + ", " + number(one.built) + ", 0, 0, 0);"
	}
	for path, text := range map[string]string{
		"config.toml":                         config,
		filepath.Join("state", "matrix.json"): `{"matrix": {"lineup": [` + strings.Join(lineup, ", ") + `]}}`,
		filepath.Join("state", "boards.json"): `{"artificialanalysis.ai": {"rows": [` + strings.Join(board, ", ") + `]}}`,
		filepath.Join("state", "usage.json"):  `{"providers": {` + strings.Join(meters, ", ") + `}}`,
	} {
		path = filepath.Join(ak, path)
		if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
	}
	db, err := sqlite3.Open(filepath.Join(ak, "history.db"))
	if err != nil {
		t.Fatal(err)
	}
	err = db.Exec(history)
	db.Close()
	if err != nil {
		t.Fatal(err)
	}
	rules, ok := pick.Within([]string{"pa", "qb"}, nil)
	if !ok {
		t.Fatal("the pick is handed over")
	}
	if got := rules.Order(budgets{"pa": 1, "qb": 2}, true, nil); !slices.Equal(got, []string{"pa", "qb"}) {
		t.Fatalf("reviewers picked in the order %v, want [pa qb]", got)
	}
}
