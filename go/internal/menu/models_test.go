package menu

import (
	"bytes"
	"strings"
	"testing"

	"agentkit/internal/quality"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
)

func screenAt(t *testing.T, columns string) terminal.Screen {
	t.Helper()
	t.Setenv("COLUMNS", columns)
	t.Setenv("LC_ALL", "C.UTF-8")
	return terminal.For(&bytes.Buffer{})
}

func modelRow(release, effort string, yours bool, value float64) quality.Row {
	values := run.NewObject()
	for _, column := range []string{"aa.frontierCode20", "arena.agent", "aa.terminalBench40"} {
		values.Set(column, value)
	}
	values.Set("aa.intelligenceIndex", 60.0)
	values.Set("aa.omniscience", 50.0)
	values.Set("aa.automationBenchPartialScore", 0.5)
	values.Set("aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask", 100*value)
	values.Set("aa.intelligenceIndexEvaluations.aa-briefcase.costPerTask", 100*value)
	return quality.Row{Release: release, Name: release, Effort: effort, Values: values, Yours: yours}
}

func TestEveryWidthSaysHowManyModelsAreCompared(t *testing.T) {
	rows := []quality.Row{modelRow("acme", "max", false, 0.9), modelRow("acme", "high", true, 0.8), modelRow("bolt", "", true, 0.7)}
	for _, columns := range []string{"1", "2", "13", "24", "30", "40", "60", "100", "200"} {
		view := ModelsView{Answer: quality.Answer(rows, nil, nil, nil), Compared: map[string]bool{"acme": true, "bolt": true}, Total: 2}
		joined := strings.Join(ModelsLines(screenAt(t, columns), view), "\n")
		// said at every width, going on at its words where its line is too narrow
		if !strings.Contains(strings.Join(strings.Fields(joined), ""), "comparingall2models") {
			t.Errorf("at %s columns: %s", columns, joined)
		}
		if strings.Contains(joined, "boards read") {
			t.Errorf("at %s columns boards never read were said read", columns)
		}
	}
}

func TestLiveLinesWrapWhereTheyDoNotFit(t *testing.T) {
	screen := screenAt(t, "12")
	lines := LiveLines(screen, [][]string{{"a-long-model-name", "-", "-", "-"}})
	if lines[len(lines)-1] != "name - - -" && !strings.HasSuffix(strings.Join(lines, " "), "- - -") {
		t.Fatalf("%q", lines)
	}
	screen = screenAt(t, "100")
	lines = LiveLines(screen, [][]string{{"mid", "-", "-", "-"}, {"bolt", "-", "-", "-"}})
	if got := strings.Join(lines[len(lines)-3:], "|"); got != "model orch exec review|mid   -    -    -|bolt  -    -    -" {
		t.Fatal(got)
	}
}
