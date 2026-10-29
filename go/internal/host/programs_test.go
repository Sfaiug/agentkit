package host

import (
	"strings"
	"testing"
)

// What a pane runs, as Python ak's `orch.program` reads the same command lines.
func TestProgramReadsAnInterpretersScript(t *testing.T) {
	for line, want := range map[string]string{
		"/usr/bin/claude --x": "claude", "bash -e /opt/bin/claude": "claude", "bash -c claude": "bash",
		"python3 -O /opt/bin/claude": "claude", "python3 -W ignore x/codex.py": "codex.py",
		"node --require a /n/bin/codex": "codex", "node --eval x": "node", "sh -- /x/grok": "grok",
		"sh -": "sh", "sh -o pipefail /x/agy": "agy", "sleep 600": "sleep",
	} {
		if got := Program(strings.Fields(line)); got != want {
			t.Errorf("Program(%q) = %q, want %q", line, got, want)
		}
	}
	if got := Program([]string{"sh", "", "/x/claude"}); got != "claude" {
		t.Errorf("an empty word is no script: %q", got)
	}
}
