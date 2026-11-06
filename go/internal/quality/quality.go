// Package quality is how good a model at one effort is for each role, from board numbers that
// cover some efforts and models and not others, and the owner's role rule on models over that.
// Every row is rated, none left out for a missing score, and a missing score never helps it: a measure
// another effort of its release has is carried from there, never credited upward, and one no
// effort has counts as far behind as the row's furthest-behind measure, with that one's error.
// Every score carries its standard error, each error counted once however many scores take it,
// used by the role rules in Python's quality.pick. It reads no board, config or clock.
package quality

import (
	"cmp"
	"math"
	"slices"
	"strings"

	"agentkit/internal/run"
)

const intel = "aa.intelligenceIndex"

// evaluation is where the Intelligence Index's evaluations sit, each `<slug>`'s score at
// evaluation + slug + `.score`: what an effort's change in them says of its error.
const evaluation = "aa.intelligenceIndexEvaluations."

type measure struct {
	column, kind string
	weight       float64
}

// Roles are the roles answered, in the order a screen says them.
var Roles = []string{"orchestrate", "execute", "review"}

// measures is what each role is rated on, as Python's quality.ROLES: pinned there, with why each
// weighs what it does, by tests/test_matrix_measures.py.
var measures = map[string][]measure{
	"orchestrate": {{"aa.automationBenchPartialScore", "share", 0.35}, {"arena.agent", "share", 0.3},
		{"aa.omniscience", "percent", 0.2}, {"aa.briefcaseBreakdown.overall.elo", "rating", 0.15}},
	"execute": {{"aa.frontierCode20", "share", 0.4}, {"arena.agent", "share", 0.4},
		{"aa.terminalBench40", "share", 0.2}},
	"review": {{"aa.frontierCode20", "share", 0.8}, {"aa.omniscience", "percent", 0.2}},
}

// Costs is the column holding what a task of each role costs a row, in dollars: the evaluation
// nearest the role's work.
var Costs = map[string]string{
	"orchestrate": "aa.intelligenceIndexEvaluations.aa-briefcase.costPerTask",
	"execute":     "aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask",
	"review":      "aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask",
}

// intervals is a measure's 95% interval where it is not `<column>.lower95ci` and `.upper95ci`.
var intervals = map[string][2]string{"aa.briefcaseBreakdown.overall.elo": {
	"aa.briefcaseBreakdown.overall.lower95ci", "aa.briefcaseBreakdown.overall.upper95ci"}}

// tasks is how many tasks a share without an interval is of, as Artificial Analysis's methodology
// pages say.
var tasks = map[string]float64{"aa.automationBenchPartialScore": 657, "aa.frontierCode20": 132, "aa.terminalBench40": 66}

// Omniscience's index and the columns its error comes from, over its questions, each +1 right,
// -1 wrong and 0 declined.
const (
	omniscience          = "aa.omniscience"
	omniscienceAccuracy  = "aa.omniscienceAccuracy"
	omniscienceRate      = "aa.omniscienceHallucinationRate"
	omniscienceQuestions = 3000
)

// efforts are the words ak knows an effort by, the highest last.
var efforts = []string{"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}

// EffortRank is where an effort stands among the words ak knows; a word it does not know, or no
// effort, stands below them all.
func EffortRank(effort string) int {
	return slices.Index(efforts, effort)
}

func interval(column string) [2]string {
	if found, ok := intervals[column]; ok {
		return found
	}
	return [2]string{column + ".lower95ci", column + ".upper95ci"}
}

// Columns are the columns of every role's measures, each once.
func Columns() []string {
	var columns []string
	for _, role := range Roles {
		for _, each := range measures[role] {
			if !slices.Contains(columns, each.column) {
				columns = append(columns, each.column)
			}
		}
	}
	return columns
}

// Needed is every column this reads: each measure, what its error cannot be had without, the
// index and each role's cost.  A measure's error reads its interval, but none for a share of
// `tasks` and Omniscience's accuracy and hallucination rate for it, as Artificial Analysis
// publishes no interval for these: naming one would read the board again at every new build.
func Needed() []string {
	needed := []string{intel}
	for _, role := range Roles {
		needed = append(needed, Costs[role])
	}
	for _, column := range Columns() {
		needed = append(needed, column)
		switch _, shared := tasks[column]; {
		case shared:
		case column == omniscience:
			needed = append(needed, omniscienceAccuracy, omniscienceRate)
		default:
			ends := interval(column)
			needed = append(needed, ends[0], ends[1])
		}
	}
	return needed
}

// behind is how far a value is behind its board's best, in points out of 100: a percent in
// percentage points, a share from 0 to 1 in hundredths, and a rating as how far under half its
// wins against the best would be (35 behind is 45% of wins, 5 points).
func behind(kind string, best, value float64) float64 {
	switch kind {
	case "percent":
		return best - value
	case "share":
		return 100 * (best - value)
	}
	return 100 * (0.5 - 1/(1+pow10((best-value)/400)))
}

// ln10 is a variable so the sum below it is rounded as Python's is, not folded exactly as a Go
// constant.
var ln10 = math.Ln10

// worth is the points one unit of value is worth there.
func worth(kind string, best, value float64) float64 {
	switch kind {
	case "percent":
		return 1
	case "share":
		return 100
	}
	t := pow10((best - value) / 400)
	return 100 * ln10 / 400 * t / float64((1+t)*(1+t))
}

// A Row is one release at one effort: Effort "" where it names none, Values its numbers by column.
type Row struct {
	Release, Name, Effort, Maker string
	Values                       *run.Object
	Yours                        bool
	Runners                      [][2]string // harness and model pairs the lineup found for this row
}

// A Measure is how a row got its score on one column: How "measured", "carried" (from the effort
// From, its own part the shift's error) or "missing" (as its furthest-behind measure).
type Measure struct {
	Column, How, From string
	Points            float64
	parts             []part
}

// A part is one score's error, by the score it comes from.
type part struct {
	source source
	error  float64
}

type source struct{ release, effort, column string }

// A Rating is a row rated for one role.
type Rating struct {
	Row
	Measures []*Measure
	// Cost is what a task of the role costs it in its Said's CostUnit, nil where nothing says;
	// BoardCost its Costs at its own effort, nil where it has none; CostRule how Cost was had:
	// "measured", "provider", "global" or "board" (a Pricer's words).
	Cost, BoardCost *float64
	CostRule        string
	Quality, SE     float64
}

// Missing is how many of its measures no effort of its release has.
func (r *Rating) Missing() int {
	missing := 0
	for _, one := range r.Measures {
		if one.How == "missing" {
			missing++
		}
	}
	return missing
}

// Rated is each of rows that has at least two of the role's measures measured or carried, its
// quality 100 less its weighted mean points behind the best over the measures a row of the index
// has, its SE the root of squares of its error's parts by the score each comes from.
func Rated(rows []Row, role string) []*Rating {
	type scale struct {
		kind string
		top  float64
	}
	evaluations := map[string]scale{}
	for _, row := range rows {
		for _, column := range row.Values.Keys() {
			if !strings.HasPrefix(column, evaluation) || !strings.HasSuffix(column, ".score") {
				continue
			}
			value, _ := row.Values.Num(column)
			if held, seen := evaluations[column]; seen {
				evaluations[column] = scale{held.kind, max(held.top, value)}
				continue
			}
			kind := "share"
			switch strings.TrimSuffix(column[len(evaluation):], ".score") {
			case "aa-briefcase":
				kind = "rating"
			case "omniscience":
				kind = "percent"
			}
			evaluations[column] = scale{kind, value}
		}
	}
	best := map[string]float64{}
	for _, each := range measures[role] {
		for _, row := range rows {
			if !row.Values.Has(intel) || !row.Values.Has(each.column) {
				continue
			}
			value, _ := row.Values.Num(each.column)
			if top, seen := best[each.column]; !seen || value > top {
				best[each.column] = value
			}
		}
	}
	// a row's points and errors per measure it is scored on, by its place in rows
	points := make([]map[string]float64, len(rows))
	errors := make([]map[string]*float64, len(rows))
	for i, row := range rows {
		points[i], errors[i] = map[string]float64{}, map[string]*float64{}
		for _, each := range measures[role] {
			top, topped := best[each.column]
			if value, ok := row.Values.Num(each.column); ok && topped {
				points[i][each.column] = behind(each.kind, top, value)
				errors[i][each.column] = measuredError(row.Values, each, top)
			}
		}
	}
	typical := map[string]float64{}
	for _, each := range measures[role] {
		var found []float64
		for i := range rows {
			if held := errors[i][each.column]; held != nil {
				found = append(found, *held)
			}
		}
		if len(found) > 0 {
			typical[each.column] = Median(found)
		}
	}
	errorOf := func(i int, column string) float64 {
		if held := errors[i][column]; held != nil {
			return *held
		}
		return typical[column]
	}
	// how far a measure's change between two efforts can be off, from how unevenly the index's
	// evaluations changed between them
	shift := func(row, from Row, column string) float64 {
		var changes []float64
		for name, each := range evaluations {
			here, atRow := row.Values.Num(name)
			there, atFrom := from.Values.Num(name)
			if atRow && atFrom {
				changes = append(changes, behind(each.kind, each.top, here)-behind(each.kind, each.top, there))
			}
		}
		if len(changes) < 2 {
			return typical[column]
		}
		return stdev(changes) / math.Sqrt(float64(len(changes)))
	}
	// a higher effort's points plus what the index loses down to this one; else a lower effort's
	// as they are, as a lower effort is never better
	carried := func(i int, column string) *Measure {
		row := rows[i]
		rank := EffortRank(row.Effort)
		above, below := -1, -1
		for n, other := range rows {
			if n == i || other.Release != row.Release {
				continue
			}
			if _, scored := points[n][column]; !scored {
				continue
			}
			switch at := EffortRank(other.Effort); {
			case at > rank && (above < 0 || at < EffortRank(rows[above].Effort)):
				above = n
			case at < rank && (below < 0 || at > EffortRank(rows[below].Effort)):
				below = n
			}
		}
		nearest, value := above, 0.0
		top, topIndexed := 0.0, false
		if above >= 0 {
			top, topIndexed = rows[above].Values.Num(intel)
		}
		own, indexed := row.Values.Num(intel)
		if above >= 0 && topIndexed && indexed {
			value = points[above][column] + max(0, top-own)
		} else if nearest = below; nearest >= 0 {
			value = points[below][column]
		} else {
			return nil
		}
		from := rows[nearest]
		return &Measure{Column: column, How: "carried", From: from.Effort, Points: value, parts: []part{
			{source{from.Release, from.Effort, column}, errorOf(nearest, column)},
			{source{row.Release, row.Effort, column}, shift(row, from, column)}}}
	}
	weights := map[string]float64{}
	for _, each := range measures[role] {
		weights[each.column] = each.weight
	}
	var out []*Rating
	for i, row := range rows {
		var scored []*Measure
		for _, each := range measures[role] {
			if value, ok := points[i][each.column]; ok {
				scored = append(scored, &Measure{Column: each.column, How: "measured", Points: value, parts: []part{
					{source{row.Release, row.Effort, each.column}, errorOf(i, each.column)}}})
			}
		}
		for _, each := range measures[role] {
			if _, ok := points[i][each.column]; !ok {
				if found := carried(i, each.column); found != nil {
					scored = append(scored, found)
				}
			}
		}
		if len(scored) < 2 {
			continue
		}
		worst := scored[0]
		for _, one := range scored {
			if one.Points > worst.Points {
				worst = one
			}
		}
		for _, each := range measures[role] {
			_, topped := best[each.column]
			if topped && !slices.ContainsFunc(scored, func(one *Measure) bool { return one.Column == each.column }) {
				scored = append(scored, &Measure{Column: each.column, How: "missing", Points: worst.Points, parts: worst.parts})
			}
		}
		var shares, behinds []float64
		for _, one := range scored {
			shares = append(shares, weights[one.Column])
			behinds = append(behinds, float64(weights[one.Column]*one.Points))
		}
		total := Sum(shares)
		parts := map[source]float64{}
		for _, one := range scored {
			for _, each := range one.parts {
				parts[each.source] += weights[one.Column] * each.error / total
			}
		}
		rating := &Rating{Row: row, Measures: scored, CostRule: "board", Quality: 100 - Sum(behinds)/total}
		rating.SE = hypot(parts)
		if cost, ok := row.Values.Num(Costs[role]); ok {
			rating.Cost, rating.BoardCost = &cost, &cost
		}
		out = append(out, rating)
	}
	return out
}

// measuredError is a measured value's standard error in points, nil where its row lacks what it
// needs.
func measuredError(values *run.Object, each measure, best float64) *float64 {
	value, _ := values.Num(each.column)
	ends := interval(each.column)
	lower, hasLower := values.Num(ends[0])
	upper, hasUpper := values.Num(ends[1])
	if hasLower && hasUpper {
		found := (upper - lower) / 3.92 * worth(each.kind, best, value)
		return &found
	}
	if count, ok := tasks[each.column]; ok {
		found := 100 * math.Sqrt(value*(1-value)/count)
		return &found
	}
	right, hasRight := values.Num(omniscienceAccuracy)
	rate, hasRate := values.Num(omniscienceRate)
	if each.column == omniscience && hasRight && hasRate {
		wrong := rate * (1 - right)
		apart := right - wrong
		found := 100 * math.Sqrt((right+wrong-float64(apart*apart))/omniscienceQuestions)
		return &found
	}
	return nil
}

// Said is one role's answer over the rows compared: Best the best quality (nil with none), Pick
// the role's pick, Front those with a cost, best first, each better
// than every cheaper one, a row of yours than every cheaper one of yours, as one no harness of
// yours runs is no reason to leave it out, and Take what `r` takes: the same rule over yours.
// Pick and Take stay visible even if rows outside their eligible pool beat them.  CostUnit is
// what its rows' costs are in.
type Said struct {
	Front      []*Rating
	Best       *float64
	Pick, Take *Rating
	Top        *Rating // best over all rows, including those not compared or priced
	CostUnit   string
}

// A Pricer prices a role's rated rows of the lineup rows in place, each one's Cost and CostRule,
// and says their unit: "share", "money", or "board_dollars" for every row left at its board's.
type Pricer func(role string, rows []Row, rated []*Rating) string

// Answer is each role's Said, its rows priced by price (nil leaves them at their board's dollars);
// compared, the releases compared, nil for every one.  Every row is rated and priced whatever is
// compared, so a row's quality and cost never change with that.
func Answer(rows []Row, compared map[string]bool, price Pricer) map[string]*Said {
	out := map[string]*Said{}
	for _, role := range Roles {
		said := &Said{CostUnit: "board_dollars"}
		ratings := Rated(rows, role)
		if price != nil {
			said.CostUnit = price(role, rows, ratings)
		}
		var priced []*Rating
		for _, row := range ratings {
			if said.Top == nil || row.Quality > said.Top.Quality {
				said.Top = row
			}
			if compared != nil && !compared[row.Release] {
				continue
			}
			if said.Best == nil || row.Quality > *said.Best {
				said.Best = &row.Quality
			}
			if row.Cost != nil {
				priced = append(priced, row)
			}
		}
		// the cheaper first, the higher quality on an equal cost
		slices.SortStableFunc(priced, func(a, b *Rating) int {
			return cmp.Or(cmp.Compare(*a.Cost, *b.Cost), cmp.Compare(b.Quality, a.Quality))
		})
		var yours []*Rating
		for n, row := range priced {
			better := true
			for _, cheaper := range priced[:n] {
				if (cheaper.Yours || !row.Yours) && cheaper.Quality >= row.Quality {
					better = false
				}
			}
			if better {
				said.Front = append(said.Front, row)
			}
			if row.Yours {
				yours = append(yours, row)
			}
		}
		said.Pick, said.Take = pick(priced, role), pick(yours, role)
		for _, chosen := range []*Rating{said.Pick, said.Take} {
			if chosen != nil && !slices.Contains(said.Front, chosen) {
				said.Front = append(said.Front, chosen)
			}
		}
		slices.SortStableFunc(said.Front, func(a, b *Rating) int { return cmp.Compare(b.Quality, a.Quality) })
		out[role] = said
	}
	return out
}

// pick follows Python's quality.pick (owner, 3 Nov 2026) on priced rows sorted by cost,
// decreasing quality on ties: the frontier row farthest above its cheapest-to-best line,
// cheaper on a tie. Only execution may trade measured quality for cost; the other roles
// compare only rows indistinguishable from the best before building their frontier.
func pick(priced []*Rating, role string) *Rating {
	var best *Rating
	for _, row := range priced {
		if best == nil || row.Quality > best.Quality {
			best = row
		}
	}
	if best == nil {
		return nil
	}
	var front []*Rating
	for _, row := range priced {
		if role != "execute" && row != best && best.Quality-row.Quality >= 1.96*math.Hypot(best.SE, row.SE) {
			continue
		}
		if len(front) > 0 {
			last := front[len(front)-1]
			if *row.Cost == *last.Cost || row.Quality <= last.Quality {
				continue
			}
		}
		front = append(front, row)
	}
	cheapest := front[0]
	span := *best.Cost - *cheapest.Cost
	if span == 0 {
		return best
	}
	rise := best.Quality - cheapest.Quality
	chosen, largest := cheapest, 0.0
	// Scale every distance by the same span: division can round equal gaps apart.
	for _, row := range front[1:] {
		above := (row.Quality-cheapest.Quality)*span - rise*(*row.Cost-*cheapest.Cost)
		if above > largest {
			chosen, largest = row, above
		}
	}
	return chosen
}
