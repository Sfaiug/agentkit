package loop

import (
	"fmt"
	"io"

	"agentkit/internal/run"
)

// dropTold is what follows an ending its seat was told, Python's worktrees._drop_told: the seat
// reads result.md, never the checkout, so a blocked run's goes unless kept on purpose, its branch
// staying, the only copy of work never pushed. An unmerged PASS keeps its checkout for
// `ak run merge`, and a FAIL or an ERROR for a resume that
// may take it, which gc judges.
func dropTold(dir string, said io.Writer) {
	record, _ := run.Read(dir)
	if record != nil && record.Str("state") == "blocked" && !record.Truthy("checkout_kept") {
		stopCheckout(dir, record, func(line string) { fmt.Fprintln(said, line) }, true)
	}
}
