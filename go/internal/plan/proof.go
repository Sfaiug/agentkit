package plan

import (
	"context"
	"fmt"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/features"
	record "agentkit/internal/run"
)

// unproven refuses the check Python's retirement writes for a proven switch while the project's
// switch list dates that proof in the future, as Python's retire.vet_check does: ak plans that
// line itself once the switch is proven, so a seat never holds work only time can finish.
// ErrUnread where Go does not read that list as Python surely does.
func unproven(ctx context.Context, checkout, check string) error {
	words, ok := commandhelp.ShellSplit(check)
	if !ok || len(words) < 2 || words[len(words)-1] != "proven" {
		return nil
	}
	id := words[len(words)-2]
	if check != features.Check(id, true) {
		return nil
	}
	rows, err := features.List(ctx, checkout)
	if err != nil {
		return ErrUnread
	}
	for _, row := range rows {
		// when it last went on for everyone, as Python's retire.since reads it: each Z +00:00
		since, _ := row.Get("everyone_since").(string)
		at, dated := fromISO(strings.ReplaceAll(since, "Z", "+00:00"))
		if record.Text(row.Get("id")) == id && row.Get("everyone") == true && dated && time.Since(at) < features.Proven {
			return fmt.Errorf("%s's switch %s is not yet proven; ak plans this line itself into a seat at work once it "+
				"is proven on %s; the seat holds no line for it before then",
				filepath.Base(checkout), id, at.Add(features.Proven).UTC().Format(time.DateOnly))
		}
	}
	return nil
}
