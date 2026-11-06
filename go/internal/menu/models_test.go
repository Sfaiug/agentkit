package menu

import (
	"bytes"
	"strings"
	"testing"

	"agentkit/internal/quality"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
)

func answerOf(rows []quality.Row) map[string]*quality.Said {
	return quality.Answer(rows, nil, nil)
}

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

func TestEveryWidthDrawsWithinItsRoomOrFolds(t *testing.T) {
	rows := []quality.Row{modelRow("acme", "max", false, 0.9), modelRow("acme", "high", true, 0.8), modelRow("bolt", "", true, 0.7)}
	for _, columns := range []string{"1", "2", "13", "24", "30", "40", "60", "100", "200"} {
		screen := screenAt(t, columns)
		lines := ModelsBody(screen, ModelsSaid(screen, answerOf(rows), rows), nil, 2, 0)
		if joined := strings.Join(lines, "\n"); !strings.Contains(joined, "comparing all 2 models") {
			t.Errorf("at %s columns: %s", columns, joined)
		}
		if strings.Contains(strings.Join(lines, "\n"), "boards read") {
			t.Errorf("at %s columns boards never read were said read", columns)
		}
	}
}

func TestNothingYoursRunsThePickSaysSo(t *testing.T) {
	rows := []quality.Row{modelRow("acme", "max", false, 0.9)}
	screen := screenAt(t, "100")
	joined := strings.Join(ModelsBody(screen, ModelsSaid(screen, answerOf(rows), rows), nil, 1, 0), "\n")
	if !strings.Contains(joined, "no harness of yours runs a model this good") || strings.Contains(joined, "r takes") {
		t.Fatal(joined)
	}
}

func TestARoleWithNoRowIsSaidNone(t *testing.T) {
	screen := screenAt(t, "100")
	joined := strings.Join(ModelsBody(screen, ModelsSaid(screen, answerOf(nil), nil), map[string]bool{"x": true}, 3, 0), "\n")
	for _, want := range []string{"  orch · none", "  builds · none", "  reviews · none", "comparing 1 of 3 models"} {
		if !strings.Contains(joined, want) {
			t.Errorf("%q not in\n%s", want, joined)
		}
	}
}

func TestAnUnpricedBestIsSaidInTheHead(t *testing.T) {
	best := modelRow("best", "max", false, 0.9)
	best.Values.Delete("aa.intelligenceIndexEvaluations.frontiercode-2-0.costPerTask")
	best.Values.Delete("aa.intelligenceIndexEvaluations.aa-briefcase.costPerTask")
	rows := []quality.Row{best, modelRow("far", "low", true, 0.2)}
	screen := screenAt(t, "100")
	joined := strings.Join(ModelsBody(screen, ModelsSaid(screen, answerOf(rows), rows), nil, 2, 0), "\n")
	for _, want := range []string{"builds · best 100.0", "★ pick"} {
		if !strings.Contains(joined, want) {
			t.Errorf("%q not in\n%s", want, joined)
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
