//go:build unix

package plan

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

// An id is compared as Python's str() spells it, an integer's digits whole; a list whose ids or
// numbers Python may read otherwise is Python's, before anything is written.
func TestAProofGateSpellsIdsAsPythonOrHandsOver(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("USERPROFILE", os.Getenv("HOME"))
	state := filepath.Join(os.Getenv("HOME"), ".agentkit", "state")
	checkout, before := t.TempDir(), "- [x] the setup is done\n"
	if os.MkdirAll(state, 0o700) != nil || os.WriteFile(filepath.Join(state, "plan-acme.md"), []byte(before), 0o600) != nil ||
		os.WriteFile(filepath.Join(checkout, "AGENTS.md"), []byte("---\nfeatures: cat list.json; :\n---\n"), 0o644) != nil {
		t.Fatal("no checkout")
	}
	since := time.Now().UTC().AddDate(0, 0, -3).Format(time.RFC3339)
	row := func(id, more string) string {
		return `[{"id": ` + id + `, "everyone": true, "everyone_since": "` + since + `"` + more + `}]`
	}
	// each list, and the switch whose check it refuses; "" where it hands over
	for list, refused := range map[string]string{
		row("1000000", ""):                    "1000000",
		row("-0", ""):                         "0",
		row("1e6", ""):                        "",
		row("1000000.0", ""):                  "",
		row("true", ""):                       "",
		row("null", ""):                       "",
		row(`"\ud800"`, ""):                   "",
		row("1000000", `, "share": NaN`):      "",
		row("1000000", `, "share": Infinity`): "",
		row("1000000", `, "n": `+strings.Repeat("9", 641)): "",
	} {
		if os.WriteFile(filepath.Join(checkout, "list.json"), []byte(list), 0o644) != nil {
			t.Fatal("no list")
		}
		id := refused
		if refused == "" {
			id = "1000000"
		}
		check := `python3 -c "import sys; sys.path.insert(0, ` + commandhelp.Quote(config.Repo()) +
			`); from agentkit import retire; retire.check_main()" ` + commandhelp.ShellJoin([]string{id}) + " proven"
		line, err := Add(context.Background(), "acme", checkout, "acme's switch is out of the code", check)
		switch {
		case refused == "" && !errors.Is(err, ErrUnread):
			t.Errorf("%s: %q, %v, not handed over", list, line, err)
		case refused != "" && (err == nil || !strings.Contains(err.Error(), "switch "+refused+" is not yet proven")):
			t.Errorf("%s: %q, %v, not refused", list, line, err)
		}
		if data, _ := os.ReadFile(filepath.Join(state, "plan-acme.md")); string(data) != before {
			t.Errorf("%s: the plan is now %q", list, data)
		}
	}
}
