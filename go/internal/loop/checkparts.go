package loop

// Check selections hide the runner's named-test files and piece reports. A selection pins one
// piece or its tests; its report keeps the first failed command, from exits and names the box
// returned, so landing can narrow a failure without reading failure words from output, and what
// the check saw of each test for the line's flakes (flakes.go).

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

// A testReport is what a run named of its tests: failed (AK_FAILED), and of those run alone the
// ones that failed again (confirmed); the tests that failed, then passed (flaky: AK_FLAKY, or
// failed tests that passed run again); and every test its red repeated (reds), Python's confirmed
// by share: each red piece's confirmed, or a whole command's failed when it failed twice.
type testReport struct {
	piece                          string
	failed, confirmed, flaky, reds []string
}

// A checkSelection is what a landing check is asked to run, and what it saw: the tests that
// failed, then passed, every command's repeated reds (as `.flakes` keeps them, but for tree, time
// and log), and each command that passed with the tests it ran, nil for all.
type checkSelection struct {
	shard   string
	tests   []string
	red     *run.Object
	handoff bool
	flaky   []string
	reds    []*run.Object
	passed  map[string][]string
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

func (s *checkSelection) observe(command string, result ran) {
	if s == nil {
		return
	}
	s.flaky = append(s.flaky, result.flaky...)
	if len(result.reds) > 0 {
		s.reds = append(s.reds, run.Fields("command", command, "tests", toList(result.reds)))
	}
	if result.code == 0 && result.stopped == "" {
		// a pinned piece passing ran just its tests, and without them none it names
		if s.tests != nil || s.shard == "" {
			if s.passed == nil {
				s.passed = map[string][]string{}
			}
			s.passed[command] = s.tests
		}
		return
	}
	if s.red != nil {
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

// testNames is the tests a report file names, one per line, read only where the check left a file
// of its own: read outside the box, a link could reach a file the box masked, a credential.
func testNames(path string) (names []string) {
	if info, err := os.Lstat(path); err != nil || !info.Mode().IsRegular() {
		return nil
	}
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
	result.flaky = testNames(filepath.Join(out, "AK_FLAKY"))
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
// host's red (starved.go). An inconclusive retry needs the piece again; tests passing alone
// failed, then passed, whatever the piece does next.  Each go keeps the names the goes before it
// had (pieces.go's attempt).
func retryTests(at *piece, attempt func(*piece, string, []string) error) error {
	if tests := at.ended.failed; len(tests) > 0 {
		if err := attempt(at, "its failed tests alone", tests); err != nil {
			return err
		}
		if at.ended.code == 0 {
			at.ended.flaky = append(at.ended.flaky, tests...)
		}
		if at.ended.stopped != "" || at.ended.starved || len(at.ended.confirmed) > 0 {
			return nil
		}
	}
	return attempt(at, pieceRetry, nil)
}
