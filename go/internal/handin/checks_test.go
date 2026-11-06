package handin

import (
	"os"
	"os/exec"
	"strconv"
	"strings"
	"testing"
)

func TestTaskChecksHoldABuildersDone(t *testing.T) {
	for _, name := range []string{"bash", "timeout"} {
		if _, err := exec.LookPath(name); err != nil {
			t.Skip("checks run in bash under timeout")
		}
	}
	if _, err := os.Stat("/proc/self/cmdline"); err != nil {
		t.Skip("a check reads its parent from /proc")
	}
	ws, record := checkout(t)
	// the bound the worker's watch reads, so a turn waiting on its checks is no silent one
	declared := `tr '\0' ' ' </proc/$PPID/cmdline | grep -Eq '(^|/)timeout -s KILL [0-9.]+ bash -c '`
	for _, each := range []struct{ checks, refusal string }{
		{`"commands": [` + strconv.Quote(declared) + `, "exit 3"]`, "done refused: task checks still fail:\n$ exit 3 [exit 3]\n\nFix the cause"},
		// stopped at the list's deadline, or at the run's silence, a check shows nothing
		{`"commands": ["sleep 5; exit 7"], "limit": 0.2`, ""},
		{`"commands": ["sleep 5; exit 7"], "silence": 1`, ""},
	} {
		row, err := handIn(t, record, opened(ws, `, "role": "executor", "checks": {`+each.checks+`}`), "done")
		if each.refusal == "" && (err != nil || row != `{"kind": "done"}`+"\n") {
			t.Fatalf("%s: appended %q: %v", each.checks, row, err)
		}
		if each.refusal != "" && (err == nil || !strings.HasPrefix(err.Error(), each.refusal) || row != "") {
			t.Fatalf("%s: appended %q: %v", each.checks, row, err)
		}
	}
}
