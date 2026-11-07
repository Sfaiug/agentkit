package quality

import "fmt"

const Behind = "behind the best"

var measureNames = map[string]string{
	"aa.automationBenchPartialScore":    "AutomationBench",
	"arena.agent":                       "Arena Agent",
	"aa.omniscience":                    "AA-Omniscience",
	"aa.briefcaseBreakdown.overall.elo": "AA-Briefcase",
	"aa.frontierCode20":                 "FrontierCode 2.0",
	"aa.terminalBench40":                "Terminal-Bench 4.0",
}

var costMeasures = map[string]string{
	Costs["orchestrate"]: "aa.briefcaseBreakdown.overall.elo",
	Costs["execute"]:     "aa.frontierCode20",
}

// Explanation is a rating in plain words, leaving the screen only its layout.
type Explanation struct {
	Does, Quality, Cost, Behind string
	Best                        *Rating
	Measures                    []MeasureWhy
}

type MeasureWhy struct{ Name, Points, How string }

// Explain uses the role's original measure order and the best of every rated row,
// even when that row is not compared or has no price.
func Explain(found *Said, role string, row *Rating) Explanation {
	why := Explanation{
		Does:    map[string]string{"orchestrate": "orchestrates", "execute": "builds", "review": "reviews"}[role],
		Quality: fmt.Sprintf("quality %.1f ± %.1f", row.Quality, row.SE),
		Cost:    "no cost",
		Behind:  "the best",
	}
	if row.Cost != nil {
		// board dollars are a task of the board's evaluation; a share or plan dollars, one of ak's
		why.Cost = found.CostText(row) + " a task"
		if found.CostUnit == "board_dollars" {
			why.Cost = found.CostText(row) + " a " + measureNames[costMeasures[Costs[role]]] + " task"
		}
	}
	if top := found.Top; top != nil && row != top {
		why.Behind = fmt.Sprintf("%.1f %s,", top.Quality-row.Quality, Behind)
		why.Best = top
	}
	scored := map[string]*Measure{}
	for _, one := range row.Measures {
		scored[one.Column] = one
	}
	for _, each := range measures[role] {
		one := MeasureWhy{Name: measureNames[each.column], How: "no score"}
		if score := scored[each.column]; score != nil {
			one.Points = fmt.Sprintf("%.1f", score.Points)
			switch score.How {
			case "carried":
				one.How = "carried from " + score.From
			case "missing":
				one.How = "no score, counted as its worst"
			case "measured":
				value, _ := row.Values.Num(each.column)
				one.How = fmt.Sprintf("measured, %.6g", value)
				if each.kind == "share" {
					one.How = fmt.Sprintf("measured, %.1f%%", 100*value)
				}
			}
		}
		why.Measures = append(why.Measures, one)
	}
	return why
}
