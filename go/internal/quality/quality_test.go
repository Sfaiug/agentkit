package quality

import (
	"fmt"
	"slices"
	"testing"

	"agentkit/internal/run"
)

// row is one release at one effort; numbers are pairs of a column and its value.
func row(release, effort string, yours bool, numbers ...any) Row {
	values := run.NewObject()
	for i := 0; i < len(numbers); i += 2 {
		values.Set(numbers[i].(string), numbers[i+1])
	}
	return Row{Release: release, Name: release, Effort: effort, Values: values, Yours: yours}
}

const taskCost = "aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask"

func shown(rows []*Rating) []string {
	var names []string
	for _, each := range rows {
		names = append(names, fmt.Sprintf("%s/%s %.3f", each.Release, each.Effort, each.Quality))
	}
	return names
}

// The role rule picks over all rows and over yours; dominated rows leave the front.
func TestAnswerPicksAboveTheLine(t *testing.T) {
	share := func(release, effort string, yours bool, value, cost float64) Row {
		return row(release, effort, yours, intel, 60.0, "aa.frontierCode20", value, "arena.agent", value,
			"aa.terminalBench40", value, taskCost, cost, "aa.omniscience", 50.0)
	}
	rows := []Row{share("top", "max", false, 0.9, 30), share("near", "high", false, 0.87, 10),
		share("mine", "high", true, 0.86, 12), share("worse", "low", true, 0.5, 20), share("low", "low", false, 0.5, 1)}
	said := Answer(rows, nil, nil)["execute"]
	if *said.Best != 100 || said.Pick.Release != "near" || said.Take.Release != "mine" {
		t.Fatalf("best %v pick %s take %s", *said.Best, said.Pick.Release, said.Take.Release)
	}
	got := fmt.Sprint(shown(said.Front))
	// `worse` is no better than `mine`, cheaper and yours; `near` stays though `mine`, costing more,
	// is yours: one no harness of yours runs is no reason to leave a row of yours out
	if want := "[top/max 100.000 near/high 97.000 mine/high 96.000 low/low 60.000]"; got != want {
		t.Fatalf("front %s, want %s", got, want)
	}
	if compared := Answer(rows, map[string]bool{"worse": true}, nil)["execute"]; compared.Pick.Release != "worse" || *compared.Best != 60 {
		t.Fatalf("compared %v", shown(compared.Front))
	}
	if none := Answer(rows, map[string]bool{"nothing": true}, nil)["execute"]; none.Best != nil || none.Pick != nil || len(none.Front) != 0 {
		t.Fatalf("none compared %+v", none)
	}
}

func TestRoleChoicesStayVisible(t *testing.T) {
	var rows []Row
	names := []string{"acme-cheap", "acme-noisy", "acme-best", "acme-higher"}
	for n, p := range [][4]float64{{1, .93, 93, 0}, {2, .92, 92, 10}, {10, .99, 99, 0}, {20, 1, 100, 5}} {
		rows = append(rows, row(names[n], "high", n < 3, intel, 50.0, taskCost, p[0],
			"aa.frontierCode20", p[1], "aa.frontierCode20.lower95ci", p[1]-3.92*p[3]/80,
			"aa.frontierCode20.upper95ci", p[1], "aa.omniscience", p[2],
			"aa.omniscience.lower95ci", p[2], "aa.omniscience.upper95ci", p[2]))
	}
	for n, want := range []string{"acme-noisy", "acme-best"} {
		said := Answer(rows[:3+n], nil, nil)["review"]
		if said.Pick.Release != want || said.Take.Release != "acme-noisy" {
			t.Fatalf("pick %s, take %s", said.Pick.Release, said.Take.Release)
		}
		for _, chosen := range []*Rating{said.Pick, said.Take} {
			if !slices.Contains(said.Front, chosen) {
				t.Errorf("selected %s is absent from Front", chosen.Release)
			}
		}
	}
}

func TestEqualPositiveLineDistancesChooseCheaper(t *testing.T) {
	var rows []*Rating
	for _, pair := range [][2]float64{{0, 91}, {.125, 92}, {.75, 96.5}, {1.25, 100}} {
		cost := pair[0]
		rows = append(rows, &Rating{Cost: &cost, Quality: pair[1], SE: 4})
	}
	for _, role := range Roles {
		if pick(rows, role) != rows[1] {
			t.Errorf("%s did not choose the cheaper row on a tie", role)
		}
	}
	rows[2].Quality += 1e-10
	for _, role := range Roles {
		if pick(rows, role) != rows[2] {
			t.Errorf("%s did not choose the row further above the line", role)
		}
	}
}

// The best row lies on its own line, exactly as Python reckons it, however the products round.
func TestTheBestRowTiesTheCheapest(t *testing.T) {
	var rows []*Rating
	for _, pair := range [][2]float64{{8.175, 90}, {31.065000000000005, 99}, {32.7, 100}} {
		cost := pair[0]
		rows = append(rows, &Rating{Cost: &cost, Quality: pair[1], SE: 1})
	}
	if pick(rows, "execute") != rows[0] {
		t.Error("the best row did not tie the cheapest")
	}
}

// A measure another effort has is carried, a higher effort's plus what the index loses and a lower
// one's as it is; one no effort has counts as the row's furthest behind; one measure alone rates
// nothing.
func TestAMissingScoreNeverHelps(t *testing.T) {
	rows := []Row{
		row("acme", "max", false, intel, 70.0, "aa.frontierCode20", 0.8, "aa.terminalBench40", 0.8, "arena.agent", 0.8),
		row("acme", "high", false, intel, 65.0, "aa.frontierCode20", 0.6, "aa.terminalBench40", 0.7),
		row("acme", "low", false, "aa.frontierCode20", 0.5, "aa.terminalBench40", 0.5),
		row("lone", "high", false, intel, 50.0, "aa.frontierCode20", 0.9),
		row("gap", "high", false, intel, 50.0, "aa.frontierCode20", 0.7, "aa.terminalBench40", 0.6),
		row("base", "low", false, intel, 40.0, "aa.frontierCode20", 0.4, "arena.agent", 0.7),
		row("base", "high", false, intel, 45.0, "aa.frontierCode20", 0.5, "aa.terminalBench40", 0.6),
	}
	found := map[string]*Measure{}
	for _, each := range Rated(rows, "execute") {
		if each.Release == "lone" {
			t.Fatal("a row of one measure was rated")
		}
		for _, one := range each.Measures {
			if one.Column == "arena.agent" {
				found[each.Release+"/"+each.Effort] = one
			}
		}
	}
	high, base, gap := found["acme/high"], found["base/high"], found["gap/high"]
	if high.How != "carried" || high.From != "max" || high.Points != 5 {
		t.Fatalf("high: %+v", high)
	}
	if base.How != "carried" || base.From != "low" || base.Points < 9.99 || base.Points > 10.01 {
		t.Fatalf("base: %+v", base)
	}
	if gap.How != "missing" || gap.Points < 19.99 || gap.Points > 20.01 {
		t.Fatalf("gap: %+v", gap)
	}
}

// Each number here is Python's quality.rated to the last digit: --json prints them whole.
func TestARowsNumbersAreToTheLastDigitPythons(t *testing.T) {
	const briefcase = "aa.briefcaseBreakdown.overall"
	evaluations := func(one, two, three float64) []any {
		return []any{evaluation + "aa-briefcase.score", one, evaluation + "omniscience.score", two, evaluation + "frontiercode-2-0.score", three}
	}
	numbers := func(index, elo, low, high, omni, right, wrong, bench, arena float64, more ...any) []any {
		return append([]any{intel, index, briefcase + ".elo", elo, briefcase + ".lower95ci", low, briefcase + ".upper95ci", high,
			"aa.omniscience", omni, "aa.omniscienceAccuracy", right, "aa.omniscienceHallucinationRate", wrong,
			"aa.automationBenchPartialScore", bench, "arena.agent", arena, "arena.agent.lower95ci", arena - 0.031, "arena.agent.upper95ci", arena + 0.027}, more...)
	}
	rows := []Row{
		row("acme", "max", true, numbers(70.3, 1512.5, 1490.25, 1533.75, 41.7, 0.61, 0.33, 0.713, 0.82, evaluations(1490.5, 40.25, 0.77)...)...),
		row("acme", "high", true, append([]any{intel, 66.1, "aa.automationBenchPartialScore", 0.655, "arena.agent", 0.79}, evaluations(1402.25, 36.5, 0.71)...)...),
		row("bolt", "high", false, numbers(61.9, 1377.0, 1350.0, 1401.5, 33.3, 0.5, 0.41, 0.59, 0.66)...),
	}
	want := map[string]string{
		"acme/max":  "100.0 0.8387838927779436",
		"acme/high": "95.60000000000001 1.0800511227018421",
		"bolt/high": "86.42979602712228 0.8889491531754309",
	}
	for _, each := range Rated(rows, "orchestrate") {
		got := fmt.Sprint(run.Float(each.Quality), " ", run.Float(each.SE))
		if name := each.Release + "/" + each.Effort; got != want[name] {
			t.Errorf("%s: %s, want %s", name, got, want[name])
		}
	}
}

func TestExactMathIsPythons(t *testing.T) {
	// each right side is what Python 3.13 answers
	if got := pow10(0.123456789); got != 1.3287913397912978 {
		t.Errorf("pow10 %v", run.Float(got))
	}
	if got := Sum([]float64{0.1, 0.2, 0.3, 1e16, -1e16}); got != 0.6 {
		t.Errorf("sum %v", run.Float(got))
	}
	if got := stdev([]float64{0.1, 0.25, 0.7}); got != 0.31224989991991986 {
		t.Errorf("stdev %v", run.Float(got))
	}
	if got := Median([]float64{3, 1, 2, 4}); got != 2.5 {
		t.Errorf("median %v", got)
	}
}

func TestEverythingReadIsNeeded(t *testing.T) {
	needed := map[string]bool{}
	for _, column := range Needed() {
		needed[column] = true
	}
	for _, column := range []string{intel, taskCost, "aa.omniscienceHallucinationRate", "arena.agent.upper95ci", "aa.briefcaseBreakdown.overall.lower95ci"} {
		if !needed[column] {
			t.Errorf("%s is read and not needed", column)
		}
	}
	// no interval exists for these: naming one would read the board again at every new build
	if needed["aa.frontierCode20.lower95ci"] || needed["aa.omniscience.lower95ci"] {
		t.Error("an interval no board publishes is needed")
	}
}
