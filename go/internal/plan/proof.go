package plan

import (
	"context"
	"fmt"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/features"
)

// proven is how long a switch is on for everyone before it is proven: Python's retire.PROVEN.
const proven = 14 * 24 * time.Hour

// unproven refuses the check Python's retirement writes for a proven switch while the project's
// switch list dates that proof in the future, as Python's retire.vet_check does: ak plans that
// line itself once the switch is proven, so a seat never holds work only time can finish.
func unproven(ctx context.Context, checkout, check string) error {
	words, ok := commandhelp.ShellSplit(check)
	if !ok || len(words) < 2 || words[len(words)-1] != "proven" {
		return nil
	}
	id := words[len(words)-2]
	if check != `python3 -c "import sys; sys.path.insert(0, `+commandhelp.Quote(config.Repo())+
		`); from agentkit import retire; retire.check_main()" `+commandhelp.ShellJoin([]string{id})+" proven" {
		return nil
	}
	rows, _ := features.List(ctx, checkout)
	for _, row := range rows {
		// when it last went on for everyone, as Python's retire.since reads it: each Z +00:00
		at, dated := fromISO(strings.ReplaceAll(row.Since, "Z", "+00:00"))
		if row.ID == id && row.Everyone && dated && time.Since(at) < proven {
			return fmt.Errorf("%s's switch %s is not yet proven; ak plans this line itself into a seat at work once it "+
				"is proven on %s; the seat holds no line for it before then",
				filepath.Base(checkout), id, at.Add(proven).UTC().Format(time.DateOnly))
		}
	}
	return nil
}
