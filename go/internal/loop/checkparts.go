package loop

// Check selections hide the runner's named-test files and piece reports. A selection pins one
// piece or its tests; its report keeps the first failed command, from exits and names the box
// returned, so landing can narrow a failure without reading failure words from output.

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

type testReport struct {
	piece             string
	failed, confirmed []string
	flaky             bool
}

type checkSelection struct {
	shard   string
	tests   []string
	red     *run.Object
	handoff bool
}

func selectedCheck(selections []*checkSelection) *checkSelection {
	if len(selections) > 0 {
		return selections[0]
	}
	return nil
}

func (s *checkSelection) pinned() bool { return s != nil && (s.shard != "" || s.tests != nil) }

func (s *checkSelection) request() (string, []string) {
	if s != nil {
		return s.shard, s.tests
	}
	return "", nil
}

func (s *checkSelection) observe(command string, result ran, flaky bool) {
	if s == nil {
		return
	}
	s.handoff = s.handoff || flaky || result.flaky
	if s.red != nil || result.code == 0 && result.stopped == "" {
		return
	}
	if result.stopped != "" {
		// killed at the limit, its sibling pieces with it: no one piece is red, Python's red_part
		s.red = run.Fields("command", command, "piece", "")
		return
	}
	share := result.piece
	if s.pinned() {
		share = s.shard
	}
	s.red = run.Fields("command", command, "piece", share)
	if result.starved {
		s.red.Set("short", true)
	}
	if len(result.confirmed) > 0 {
		s.red.Set("tests", toList(result.confirmed))
	}
}

func nameTests(env map[string]string, out string, only [][]string) error {
	env["AK_RAN"], env["AK_FLAKY"] = filepath.Join(out, "AK_RAN"), filepath.Join(out, "AK_FLAKY")
	if len(only) == 0 || only[0] == nil {
		return nil
	}
	env["AK_ONLY"], env["AK_SHARD"] = filepath.Join(out, "AK_ONLY"), "1/1"
	return os.WriteFile(env["AK_ONLY"], []byte(strings.Join(only[0], "\n")+"\n"), 0o666)
}

func testNames(path string) (names []string) {
	data, _ := os.ReadFile(path)
	for _, line := range config.SplitLines(decoded(data)) {
		if line = strings.TrimSpace(line); line != "" && !slices.Contains(names, line) {
			names = append(names, line)
		}
	}
	return names
}

func reportedTests(result ran, out string, only [][]string, output io.Writer) ran {
	result.failed = testNames(filepath.Join(out, "AK_FAILED"))
	result.flaky = len(testNames(filepath.Join(out, "AK_FLAKY"))) > 0
	if len(only) == 0 || only[0] == nil {
		return result
	}
	seen := testNames(filepath.Join(out, "AK_RAN"))
	var missing []string
	for _, test := range only[0] {
		if !slices.Contains(seen, test) {
			missing = append(missing, test)
		} else if result.code > 0 && slices.Contains(result.failed, test) {
			result.confirmed = append(result.confirmed, test)
		}
	}
	if result.code == 0 && len(missing) > 0 {
		fmt.Fprintf(output, "[not named as run (AK_RAN): %s]\n", strings.Join(missing, " "))
		result.code = 1
	}
	return result
}

const pieceRetry = "command is not sent to the suite helper (piece retry)"

// A named retry confirms only tests both run and failed; one the kernel killed for memory is the
// host's red (starved.go). An inconclusive retry needs the piece again; passing alone is flaky
// even if the piece fails again, and landing leaves that to Python.
func retryTests(at *piece, attempt func(*piece, string, []string) error) error {
	flaky := at.ended.flaky
	if tests := at.ended.failed; len(tests) > 0 {
		if err := attempt(at, "its failed tests alone", tests); err != nil {
			return err
		}
		flaky = flaky || at.ended.flaky || at.ended.code == 0
		if at.ended.stopped != "" || at.ended.starved || len(at.ended.confirmed) > 0 {
			at.ended.flaky = flaky
			return nil
		}
	}
	if err := attempt(at, pieceRetry, nil); err != nil {
		return err
	}
	at.ended.flaky = at.ended.flaky || flaky || at.ended.code == 0
	return nil
}
