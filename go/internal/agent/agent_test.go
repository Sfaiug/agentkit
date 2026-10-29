package agent

import (
	"os"
	"strings"
	"testing"
)

func TestProgramReadsEachInterpretersGrammar(t *testing.T) {
	for words, want := range map[string]string{
		"bash -e /opt/bin/claude":                         "claude",
		"bash -o pipefail --rcfile rc -- /opt/bin/claude": "claude",
		"node --require=hook /usr/lib/codex/bin/codex":    "codex",
		"bash -c claude || sleep 600":                     "bash",
		"python3 -m claude":                               "python3",
		"ssh claude sleep 600":                            "ssh",
	} {
		if got := program(strings.Fields(words)); got != want {
			t.Errorf("program(%q) = %q, want %q", words, got, want)
		}
	}
}

func TestGlobsReadStarsAndQuestionMarksAndNoBracket(t *testing.T) {
	harness, _ := globs([]string{"muse-bin-*", "a?c", `c\d`, `e\*`})
	for name, want := range map[string]bool{"muse-bin-7": true, "muse-bin": false, "abc": true,
		"ac": false, `c\d`: true, "cd": false, `e\x`: true, "e*": false} {
		if harness.MatchString(name) != want {
			t.Errorf("%q matches: %v, want %v", name, !want, want)
		}
	}
	if _, err := globs([]string{"acme-bin-[0-9]"}); err == nil {
		t.Error("a pattern holding `[` was read")
	}
}

func TestOnlyAHarnessNoWorkerRunsMakesASeat(t *testing.T) {
	// 41 is a worker's harness: nothing under it makes a seat, though 42's environment is
	// unreadable, which proves no worker. 20 says it is a worker but is no harness.
	read := environ
	t.Cleanup(func() { environ = read })
	environ = func(pid int) ([]byte, error) {
		if pid == 20 || pid == 41 {
			return []byte("HOME=/home/acme\x00AK_RUN_ROLE=worker\x00"), nil
		}
		return nil, os.ErrPermission
	}
	commands, children := parse(`   10     1 sh
   11    10 bash -e /opt/bin/claude
   20     1 sh
   21    20 claude
   30     1 sleep 600
   40     1 sh
   41    40 claude
   42    41 codex
`)
	harness, _ := globs([]string{"claude", "codex"})
	for pane, want := range map[int]bool{10: true, 20: true, 30: false, 40: false, 99: false} {
		if got := runsAgent([]int{pane}, commands, children, harness); got != want {
			t.Errorf("pane %d runs an agent: %v, want %v", pane, got, want)
		}
	}
}
