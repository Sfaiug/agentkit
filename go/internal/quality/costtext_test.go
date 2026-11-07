package quality

import "testing"

func TestAWhySaysACostInItsRolesUnit(t *testing.T) {
	rows := []Row{row("bolt", "low", true, intel, 50.0, "aa.frontierCode20", .6, "aa.terminalBench40", .6, taskCost, 0.3)}
	for unit, want := range map[string]string{"share": "0.30% a task", "money": "$0.30 a task"} {
		found := Answer(rows, nil, func(string, []Row, []*Rating) string { return unit })["execute"]
		if why := Explain(found, "execute", found.Pick); why.Cost != want {
			t.Errorf("%s: %q", unit, why.Cost)
		}
	}
}
