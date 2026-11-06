// Package doctor is `ak doctor`, as Python's watch.doctor: where the agents run, whether the tick
// is alive, what each machine ak may use is, any model set to an effort it does not take, and
// what ak rents. It changes nothing.
package doctor

import (
	"fmt"
	"io"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/listing"
	"agentkit/internal/machines"
	"agentkit/internal/tick"
)

// Report says all of it and is the exit: 2 for a config Python's config.load refuses, after what
// it reads without one, 1 where the tick reads as hung or a dead run has outlasted two ticks.
// False, with nothing said, where a read is one Go cannot make. The first lines come out before
// the efforts, which ask each harness.
func Report(out, errOut io.Writer) (int, bool) {
	health, stuck, read := tick.Health()
	if !read {
		return 0, false
	}
	harnesses, refused := config.OfferedHarnesses()
	if refused == nil && (config.MayRent() || !askable(harnesses)) {
		return 0, false
	}
	runs, dead, read := census(tick.Grace())
	if !read {
		return 0, false
	}
	fmt.Fprintln(out, host.SliceLine())
	fmt.Fprintln(out, "tick  "+health)
	fmt.Fprintln(out, "runs  "+runs)
	var wrong []string
	if refused == nil {
		for _, machine := range machines.Known() {
			fmt.Fprintln(out, "machine  "+machine.String())
		}
		wrong, refused = config.WrongEfforts(listings{}.efforts)
	}
	if refused != nil {
		fmt.Fprintf(errOut, "ak doctor: %s\n", refused)
		return 2, true
	}
	if len(wrong) == 0 {
		wrong = []string{"effort  every model takes the effort it is set to"}
	}
	fmt.Fprintln(out, strings.Join(wrong, "\n"))
	fmt.Fprintln(out, "rented machines: "+rented())
	if stuck || dead {
		return 1, true
	}
	return 0, true
}

// askable is whether each harness has an adapter to ask for its models.
func askable(harnesses []string) bool {
	return !slices.ContainsFunc(harnesses, func(harness string) bool {
		_, can := config.Lister(harness)
		return !can
	})
}

// listings keeps what each harness's logins listed, asked once a run.
type listings map[string][][]string

// efforts is what the harness's listing says that model takes, as config.catalog_held merges it:
// the first login to list the model says it, none where it leaves them unsaid.
func (l listings) efforts(harness, model string) []string {
	rows, asked := l[harness]
	if !asked {
		rows = listing.Ask(harness)
		l[harness] = rows
	}
	for _, row := range rows {
		if row[0] == model {
			return strings.FieldsFunc(row[1], config.Space)
		}
	}
	return nil
}
