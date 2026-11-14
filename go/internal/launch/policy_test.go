package launch

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func TestALaunchReadsItsNumbersFirstRefusingATaskWhileExecutorsAreOff(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(filepath.Join(home, ".agentkit"), 0o777); err != nil {
		t.Fatal(err)
	}
	const off = "executor_lines = 0: Executors are off; the orchestrator builds every change itself."
	for _, example := range []struct {
		config       string
		task, review string // what each launch is told: "" goes ahead, "python" is Python's
	}{
		{"", "", ""},
		{"executor_lines=0\n", off, ""},
		{"executor_lines=0\nreview_rounds=0\n", off, "python"},
		{"review_rounds=0\n", "", "python"},
		{"executor_lines='no limit'\norchestrator_lines='no limit'\n", "", ""},
		{"review_rounds=-1\n", "(got -1)", "(got -1)"},
		{"rounds=2\n", "use review_rounds instead of rounds", "use review_rounds instead of rounds"},
	} {
		if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(example.config), 0o600); err != nil {
			t.Fatal(err)
		}
		for review, want := range map[bool]string{false: example.task, true: example.review} {
			_, err := numbers("", review)
			switch {
			case want == "" && err != nil,
				want == "python" && !errors.Is(err, ErrPython),
				want != "" && want != "python" && (err == nil || errors.Is(err, ErrPython) || !strings.HasSuffix(err.Error(), want)):
				t.Errorf("%q, review %v: %v, want %q", example.config, review, err, want)
			}
		}
	}
}

// A scratch run keeps the numbers it launched under, as every run does.
func TestAScratchRunRecordsTheNumbersItLaunchedUnder(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	record, stop := run.Fields(), errors.New("stopped after the first write")
	launched := config.Numbers{Rounds: 1, ReviewLines: config.AtMost(120), SeatLines: config.AtMost(20)}
	_, err := drive("", nil, place{numbers: launched}, "", nil, "",
		func(change func(*run.Object)) error { change(record); return stop }, nil, io.Discard, io.Discard)
	if kept, _ := run.Policy(record); !errors.Is(err, stop) || kept != launched || !record.Truthy("scratch") {
		t.Fatalf("%v: %s", err, run.Line(record))
	}
}
