package quality

import "testing"

func TestExplanationUsesTheBestEvenWhenUnpricedAndNotCompared(t *testing.T) {
	rows := []Row{
		row("acme", "max", false, intel, 70.0, "aa.frontierCode20", .8, "aa.terminalBench40", .8),
		row("bolt", "low", true, intel, 50.0, "aa.frontierCode20", .6, "aa.terminalBench40", .6, taskCost, 1.0),
	}
	found := Answer(rows, map[string]bool{"bolt": true})["execute"]
	why := Explain(found, "execute", found.Pick)
	if *found.Best != 80 || why.Best.Release != "acme" || why.Behind != "20.0 behind the best," {
		t.Fatalf("compared best %v, explanation %+v", *found.Best, why)
	}
	if why.Cost != "$1.00 a FrontierCode 2.0 task" {
		t.Fatal(why.Cost)
	}
	// No row has Arena Agent: it has no points, rather than being counted as missing.
	if one := why.Measures[1]; one.Name != "Arena Agent" || one.Points != "" || one.How != "no score" {
		t.Fatalf("unscored measure %+v", one)
	}
	best := Explain(found, "execute", found.Top)
	if best.Behind != "the best" || best.Best != nil || best.Cost != "no cost" {
		t.Fatalf("best %+v", best)
	}
}
